<!-- frontend/src/components/v2/ConfigAssistantPanel.vue
     Right-column 360px panel for post-deploy `/chat?app_id=X` — users chat in
     natural language to adjust an already-deployed application.

     Self-contained: parent mounts with `:application-id` + (optional) `:app-name`.
     Backend route owned by parallel agent P:
       POST /api/applications/:id/config-chat
     ChangePlan apply/diff hooks are stubs for now (Plan D+1 will wire them to
     the existing incremental_update pipeline). -->
<script lang="ts">
/**
 * 2026-05-19 image #39: 改用 marked 做完整 GFM 渲染（表格 / 列表 / 代码块 / 标题），
 * 之前的 tiny renderer 只处理 bold/code/换行，AI 输出的表格全是 raw pipe 字符。
 */
import { marked } from 'marked'
marked.setOptions({ breaks: true, gfm: true })

export function renderMd(s: string): string {
  if (!s) return ''
  try {
    return marked.parse(s, { async: false }) as string
  } catch {
    // 极端 fallback：保留旧 tiny renderer 逻辑避免崩
    const escaped = s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    return escaped
      .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
      .replace(/`([^`]+)`/g, '<code>$1</code>')
      .replace(/\n/g, '<br/>')
  }
}
</script>

<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import {
  configChatApi,
  type ChangePlanPreview,
  type ConfigChatToolTrace,
} from '@/api/configChat'
import { applicationApi } from '@/api/application'

const props = defineProps<{
  applicationId: number
  appName?: string
}>()

const emit = defineEmits<{
  /** 2026-05-21 Phase 2: 完成态 hero CTA 触发父组件刷新 iframe */
  (e: 'refresh-iframe'): void
}>()

interface ChatMsg {
  id: number
  role: 'user' | 'assistant'
  content: string
  change_plan?: ChangePlanPreview | null
  actions_summary?: string[]
  tool_trace?: ConfigChatToolTrace[]
}

/** 2026-05-21 Phase 2: 修改类工具集 (Hero CTA 显示条件) */
const MODIFY_TOOL_PATTERN = /^(update_|create_|add_|delete_|disable_|set_)/

function isModifyTool(toolName: string): boolean {
  return MODIFY_TOOL_PATTERN.test(toolName)
}

function countModifyOps(msg: ChatMsg): number {
  return (msg.tool_trace || []).filter(t => t.ok && isModifyTool(t.tool_name)).length
}

/** 2026-05-21 Phase 2: 从 assistant content 解析"我的计划"块 (顶部独立卡片渲染)
 *
 * 匹配：开头是"我的计划"/"计划"/"执行计划" + ":" 或 "：" 后跟 markdown list。
 * 返 { planMd, rest } — planMd 渲染 plan card，rest 走普通 bubble。
 * 匹配不到返 { planMd: '', rest: content } 不影响渲染。
 */
function extractPlan(content: string): { planMd: string; rest: string } {
  if (!content) return { planMd: '', rest: '' }
  const trimmed = content.trimStart()
  // 匹配开头 "我的计划:" / "执行计划：" 然后接 list（1./2./3. 或 -/* 开头）
  const reHeader = /^(?:我的计划|执行计划|计划)\s*[：:]\s*\n+([\s\S]*?)(?:\n{2,}|$)/
  const m = trimmed.match(reHeader)
  if (!m) return { planMd: '', rest: content }
  const planBody = m[1].trim()
  // 必须真是 list (至少 2 行以 数字./-/* 开头)
  const listLines = planBody.split('\n').filter(l => /^\s*(?:\d+[.、）)]|[-*•])\s+/.test(l))
  if (listLines.length < 2) return { planMd: '', rest: content }
  const planMd = planBody
  const rest = content.substring(content.indexOf(m[0]) + m[0].length).trimStart()
  return { planMd, rest }
}

const messages = ref<ChatMsg[]>([])
const input = ref('')
const sending = ref(false)
const scrollerRef = ref<HTMLElement | null>(null)
let nextId = 1

function scrollToBottom() {
  nextTick(() => {
    if (scrollerRef.value) {
      scrollerRef.value.scrollTop = scrollerRef.value.scrollHeight
    }
  })
}

async function send() {
  const msg = input.value.trim()
  if (!msg || sending.value) return
  input.value = ''
  sending.value = true

  // Push user message
  messages.value.push({ id: nextId++, role: 'user', content: msg })
  scrollToBottom()

  // Build history for backend
  const history = messages.value
    .slice(-20)
    .slice(0, -1)
    .map((m) => ({ role: m.role, content: m.content }))

  // 2026-05-19 image #40 反馈：长 agent loop 撞 60s timeout。改成 SSE 流式，
  // 实时显示工具调用进度。
  // 先 push 一条占位 assistant，后续事件实时更新它。
  const placeholderId = nextId++
  const placeholder: ChatMsg = {
    id: placeholderId,
    role: 'assistant',
    content: '',
    tool_trace: [],
  }
  ;(placeholder as any).streaming = true
  ;(placeholder as any).progressLog = [] as string[]
  messages.value.push(placeholder)
  scrollToBottom()

  try {
    await configChatApi.chatStream(
      props.applicationId,
      { message: msg, history },
      (ev) => {
        const slot = messages.value.find((m) => m.id === placeholderId) as any
        if (!slot) return
        if (ev.type === 'started') {
          slot.progressLog.push(`📡 connected · ${ev.tools} tools · spec=${ev.spec_source}`)
        } else if (ev.type === 'turn_start') {
          slot.progressLog.push(`🔄 第 ${ev.turn}/${ev.of} 轮思考`)
        } else if (ev.type === 'tool_call') {
          slot.progressLog.push(`🔧 ${ev.tool_name}`)
        } else if (ev.type === 'tool_result') {
          slot.tool_trace.push({
            tool_name: ev.tool_name,
            args: ev.args,
            ok: ev.ok,
            summary: ev.summary,
          })
          slot.progressLog.push(`${ev.ok ? '✓' : '✗'} ${ev.tool_name}`)
        } else if (ev.type === 'assistant') {
          // 中间轮（有 tool_calls 时仍有思考文字）合并显示
          if (ev.content) {
            slot.content = slot.content
              ? `${slot.content}\n\n${ev.content}`
              : ev.content
          }
        } else if (ev.type === 'done') {
          slot.content = ev.reply
          slot.change_plan = ev.change_plan
          slot.actions_summary = ev.actions_summary
          slot.tool_trace = ev.tool_trace
          slot.streaming = false
          slot.progressLog = []
        } else if (ev.type === 'error') {
          slot.content = `❌ 出错了：${ev.message}`
          slot.streaming = false
          slot.progressLog = []
        }
        scrollToBottom()
      },
    )
  } catch (e: any) {
    const detail = e?.message || '调用失败'
    const slot = messages.value.find((m) => m.id === placeholderId) as any
    if (slot) {
      slot.content = `❌ 网络/解析失败：${detail}`
      slot.streaming = false
      slot.progressLog = []
    }
    scrollToBottom()
  } finally {
    sending.value = false
  }
}

// 2026-05-21 Task #13: onApplyChangePlan / onPreviewDiff stub 函数 + 对应按钮删了 —
// 半成品 UI 误导用户. ChangePlan 改纯信息卡片展示 summary. 真要执行配置改动 →
// agent 直接调真工具 (update_apaas_form_component 等已在白名单).

const emptyHint = computed(
  () => `配置「${props.appName ?? '应用'}」— 描述你想调整的字段、流程、权限...`
)

function pickExample(text: string) {
  input.value = text
}

// 截图大图查看 — 新 tab 打开 data URL
function openScreenshot(dataUrl: string) {
  try {
    const w = window.open()
    if (w) w.document.write(`<img src="${dataUrl}" style="max-width:100%;height:auto;" />`)
  } catch { /* popup blocked */ }
}

// 2026-05-19 image #36: 例子 chip 按当前应用真实 SPEC 动态生成，不再写死
// "人员档案" 这种跨应用无关的内容。失败/无 SPEC 时 fallback 到能力提示 chip。
type Example = { id: string; text: string }
const examples = ref<Example[]>([
  { id: 'cap-field',  text: '把 [模型].[字段] 改成必填' },
  { id: 'cap-role',   text: '加一个角色叫"XX管理员"' },
  { id: 'cap-dict',   text: '[字典名] 字典加一个"XX"选项' },
])

async function loadDynamicExamples() {
  if (!props.applicationId) return
  try {
    const app = await applicationApi.get(props.applicationId) as any
    const data = app?.config_preview?.data || app?.config_preview || {}
    const models: any[] = Array.isArray(data.models) ? data.models : []
    const dicts: any[]  = Array.isArray(data.dicts)  ? data.dicts  : []
    const next: Example[] = []
    // 改字段必填：用 first model 的 first field
    const m0 = models[0]
    const f0 = m0?.fields?.[0] || m0?.field_list?.[0]
    if (m0 && f0) {
      const mn = m0.label || m0.name || m0.code
      const fn = f0.label || f0.name || f0.code
      next.push({ id: 'ex-field', text: `把${mn}的${fn}改成必填` })
    }
    // 加角色：通用模板
    next.push({ id: 'ex-role', text: '加一个角色叫"运维管理员"' })
    // 改字典选项：用 first dict
    const d0 = dicts[0]
    if (d0) {
      const dn = d0.label || d0.name || d0.code
      next.push({ id: 'ex-dict', text: `${dn} 字典加一个"XX"选项` })
    }
    if (next.length > 0) examples.value = next
  } catch {
    // 保持 fallback chip
  }
}

onMounted(loadDynamicExamples)
watch(() => props.applicationId, loadDynamicExamples)

// 2026-05-19 image #39: 拖拽改宽度。localStorage 持久化。
const PANEL_WIDTH_KEY = 'apaas-config-assistant-width-v1'
const panelWidth = ref<number>(parseInt(localStorage.getItem(PANEL_WIDTH_KEY) || '420', 10) || 420)
const minWidth = 320
const maxWidth = 880
const isResizing = ref(false)

function onResizeStart(e: MouseEvent) {
  e.preventDefault()
  isResizing.value = true
  const startX = e.clientX
  const startWidth = panelWidth.value
  function onMove(ev: MouseEvent) {
    // 拖拽 handle 在左边界，向左拖拽（dx 为负）= 加宽
    const dx = ev.clientX - startX
    let next = startWidth - dx
    if (next < minWidth) next = minWidth
    if (next > maxWidth) next = maxWidth
    panelWidth.value = next
  }
  function onUp() {
    isResizing.value = false
    try { localStorage.setItem(PANEL_WIDTH_KEY, String(panelWidth.value)) } catch { /* private mode */ }
    window.removeEventListener('mousemove', onMove)
    window.removeEventListener('mouseup', onUp)
  }
  window.addEventListener('mousemove', onMove)
  window.addEventListener('mouseup', onUp)
}
</script>

<template>
  <aside
    class="config-assistant"
    data-design="v2"
    :class="{ 'is-resizing': isResizing }"
    :style="{ width: panelWidth + 'px' }"
  >
    <!-- 左边缘拖拽 handle -->
    <div class="ca-resize-handle" @mousedown="onResizeStart" title="拖拽调整宽度" />
    <header class="ca-head">
      <div class="ca-title">配置助手</div>
      <div class="ca-sub">
        {{ appName ? `调整「${appName}」` : '调整已部署应用' }}
      </div>
    </header>

    <div ref="scrollerRef" class="ca-scroll">
      <div v-if="messages.length === 0" class="ca-empty">
        <svg width="36" height="36" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round">
          <path d="M21 12a8 8 0 0 1-11.9 7L4 21l1.6-4.4A8 8 0 1 1 21 12z" />
        </svg>
        <div class="ca-empty-title">配置助手</div>
        <div class="ca-empty-hint">{{ emptyHint }}</div>
        <div class="ca-empty-examples">
          <button
            v-for="ex in examples"
            :key="ex.id"
            class="ca-example"
            @click="pickExample(ex.text)"
          >
            {{ ex.text }}
          </button>
        </div>
      </div>

      <div
        v-for="m in messages"
        :key="m.id"
        class="ca-msg"
        :class="`ca-msg-${m.role}`"
      >
        <div class="ca-bubble">
          <div
            v-if="m.role === 'assistant' && m.tool_trace && m.tool_trace.length"
            class="ca-tool-chips"
          >
            <span
              v-for="(t, i) in m.tool_trace"
              :key="i"
              class="ca-tool-chip"
              :class="t.ok ? 'ca-tool-chip-ok' : 'ca-tool-chip-err'"
              :title="t.summary"
            >
              {{ t.ok ? '✓' : '✗' }} {{ t.tool_name }}
            </span>
          </div>
          <!-- 浏览器截图直接渲染（Claude in Chrome 风格）-->
          <div
            v-if="m.role === 'assistant' && m.tool_trace && m.tool_trace.some(t => t.image_data_url)"
            class="ca-screenshots"
          >
            <figure
              v-for="(t, i) in m.tool_trace.filter(t => t.image_data_url)"
              :key="'shot-' + i"
              class="ca-screenshot"
            >
              <img :src="t.image_data_url" alt="browser screenshot" @click="openScreenshot(t.image_data_url!)" />
              <figcaption>📸 {{ t.tool_name }}</figcaption>
            </figure>
          </div>
          <!-- streaming progress log: SSE 期间显示工具调用实时进度 -->
          <div
            v-if="(m as any).streaming && (m as any).progressLog && (m as any).progressLog.length"
            class="ca-stream-log"
          >
            <div v-for="(l, i) in (m as any).progressLog" :key="i" class="ca-stream-line">{{ l }}</div>
          </div>
          <!-- 2026-05-21 Phase 2: plan 卡片 — agent 给出"我的计划:" 列表时单独渲染顶部 -->
          <template v-if="m.role === 'assistant' && m.content">
            <div
              v-if="extractPlan(m.content).planMd"
              class="ca-plan-card"
            >
              <div class="ca-plan-head">
                <span class="ca-plan-icon">📋</span>
                <span class="ca-plan-title">执行计划</span>
                <span v-if="(m as any).streaming" class="ca-plan-status">执行中…</span>
                <span v-else class="ca-plan-status ca-plan-status-done">已完成</span>
              </div>
              <div
                class="ca-plan-body"
                v-html="renderMd(extractPlan(m.content).planMd)"
              />
            </div>
            <div
              v-if="extractPlan(m.content).rest"
              class="ca-bubble-text"
              v-html="renderMd(extractPlan(m.content).rest)"
            />
          </template>
          <div
            v-else-if="m.content"
            class="ca-bubble-text"
            v-html="renderMd(m.content)"
          />
          <div v-else-if="(m as any).streaming" class="ca-bubble-typing">
            <span class="ca-dot" /><span class="ca-dot" /><span class="ca-dot" />
          </div>
          <!-- 2026-05-21 Phase 2: 完成态 hero CTA — 任务跑完且有修改类工具时显示 -->
          <div
            v-if="m.role === 'assistant' && !(m as any).streaming && countModifyOps(m) > 0"
            class="ca-hero-cta"
          >
            <div class="ca-hero-text">
              <span class="ca-hero-icon">✅</span>
              <span>已完成 <strong>{{ countModifyOps(m) }}</strong> 步调整</span>
            </div>
            <button
              type="button"
              class="ca-hero-btn"
              @click="emit('refresh-iframe')"
              title="刷新左侧 iframe 应用预览"
            >
              刷新预览 ↻
            </button>
          </div>
          <!-- 2026-05-21 Task #13 fix: 隐藏 stub "应用变更" / "预览 diff" 按钮.
               之前用户点了只 toast "Plan D+1 待接入" 不真做事 — 半成品 UI 误导.
               Change Plan 渲染成纯信息卡片 (summary + actions list) 让用户知道
               agent 给的设计方案, 不再有可点按钮. 真要执行配置改动 → agent 直接
               调 update_apaas_form_component / create_apaas_app_roles 等真工具
               (config-chat prompt 已写明). -->
          <div v-if="m.change_plan" class="ca-change-card ca-change-card-info">
            <div class="ca-change-title">📋 AI 给的方案分析</div>
            <ul
              v-if="m.actions_summary && m.actions_summary.length"
              class="ca-change-list"
            >
              <li v-for="(a, i) in m.actions_summary" :key="i">{{ a }}</li>
            </ul>
            <pre v-else class="ca-change-json">{{ JSON.stringify(m.change_plan, null, 2) }}</pre>
            <div class="ca-change-note">
              💡 仅展示 — 如要实际改配置，直接告诉 AI「把 XX 字段改成必填 / 加角色 / 加字典选项」让它调真工具。
            </div>
          </div>
        </div>
      </div>

      <div v-if="sending" class="ca-msg ca-msg-assistant">
        <div class="ca-bubble ca-thinking">
          <span class="ca-dot" /><span class="ca-dot" /><span class="ca-dot" />
        </div>
      </div>
    </div>

    <footer class="ca-input-area">
      <textarea
        v-model="input"
        class="ca-input"
        placeholder="描述你想调整的内容..."
        rows="2"
        :disabled="sending"
        @keydown.enter.exact.prevent="send"
        @keydown.enter.meta.prevent="send"
      />
      <button
        class="ca-send"
        :disabled="!input.trim() || sending"
        @click="send"
      >
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
          <path d="m22 2-7 20-4-9-9-4z" />
          <path d="M22 2 11 13" />
        </svg>
        发送
      </button>
    </footer>
  </aside>
</template>

<style scoped>
/* v3 redesign · 2026-05-20 — visual refresh only, template/script untouched.
   Preserved (don't change):
     - 360px → resizable width (panelWidth :style binding) / flex layout
     - All class names (template + :deep() references)
     - Resize handle position/z-index
     - SSE streaming/typing/thinking animation keyframes (just renamed colors)
   Refreshed:
     - All hex purples (#5b5bd6) + ai cyan (#1d89a8) gone — pure v3 token cascade
     - --border → --line / --ai-soft → --brand-soft (alias maps these too)
     - radii 8/10 → --r-2/--r-3/--r-4 token scale
     - Card shadows: surfaces lift via --sh-1 / --sh-2 on hover
     - Title 14 → 14.5 + letter-spacing -0.005em (matches v3 ShellTopBar)
     - Font weights 4 档: 600 (titles) / 500 (meta) / 400 (body)
     - Mono → var(--font-mono) (was --d-font-mono, undefined)
     - Transition uses var(--ease) 0.14s
     - Button focus-visible ring for a11y
*/
.config-assistant {
  /* width 由 :style 控制（可拖拽），fallback 360px */
  width: 360px;
  flex-shrink: 0;
  display: flex;
  flex-direction: column;
  height: 100%;
  background: var(--surface);
  border-left: 1px solid var(--line);
  position: relative;
}
.config-assistant.is-resizing {
  cursor: ew-resize;
  user-select: none;
}
.ca-resize-handle {
  position: absolute;
  left: -3px;
  top: 0;
  bottom: 0;
  width: 6px;
  cursor: ew-resize;
  z-index: 5;
  background: transparent;
  transition: background 0.14s var(--ease, cubic-bezier(0.2, 0.8, 0.2, 1));
}
.ca-resize-handle:hover,
.config-assistant.is-resizing .ca-resize-handle {
  background: var(--brand);
  opacity: 0.4;
}
.ca-head {
  padding: 14px 16px;
  border-bottom: 1px solid var(--line);
  background: var(--surface-2);
}
.ca-title {
  font-size: 14.5px;
  font-weight: var(--fw-semibold, 600);
  color: var(--text);
  letter-spacing: -0.005em;
}
.ca-sub {
  font-size: 12px;
  color: var(--text-3);
  margin-top: 4px;
}

.ca-scroll {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: 12px 14px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.ca-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  text-align: center;
  padding: 24px 12px;
  gap: 8px;
  color: var(--text-3);
}
.ca-empty svg {
  color: var(--brand);
  opacity: 0.55;
}
.ca-empty-title {
  font-size: 13px;
  font-weight: var(--fw-semibold, 600);
  color: var(--text);
  margin-top: 4px;
  letter-spacing: -0.005em;
}
.ca-empty-hint {
  font-size: 12px;
  line-height: 1.55;
  color: var(--text-3);
  max-width: 280px;
}
.ca-empty-examples {
  display: flex;
  flex-direction: column;
  gap: 6px;
  width: 100%;
  margin-top: 14px;
}
.ca-example {
  background: var(--surface);
  border: 1px solid var(--line);
  color: var(--text-2);
  font-size: 12px;
  padding: 8px 12px;
  border-radius: var(--r-3, 8px);
  cursor: pointer;
  text-align: left;
  font-family: inherit;
  transition: border-color 0.14s var(--ease, cubic-bezier(0.2, 0.8, 0.2, 1)),
              color 0.14s var(--ease, cubic-bezier(0.2, 0.8, 0.2, 1)),
              background 0.14s var(--ease, cubic-bezier(0.2, 0.8, 0.2, 1)),
              box-shadow 0.14s var(--ease, cubic-bezier(0.2, 0.8, 0.2, 1));
}
.ca-example:hover {
  border-color: var(--brand-ring);
  color: var(--brand);
  background: var(--brand-soft);
  box-shadow: var(--sh-1);
}
.ca-example:focus-visible {
  outline: 2px solid var(--line-focus, var(--brand-ring));
  outline-offset: 2px;
}

.ca-msg {
  display: flex;
}
.ca-msg-user {
  justify-content: flex-end;
}
.ca-msg-assistant {
  justify-content: flex-start;
}
.ca-bubble {
  max-width: 88%;
  padding: 10px 12px;
  border-radius: var(--r-3, 8px);
  font-size: 12.5px;
  line-height: 1.6;
  color: var(--text);
  word-break: break-word;
}
.ca-msg-user .ca-bubble {
  background: var(--brand);
  color: var(--text-inverse, #fff);
  box-shadow: var(--sh-brand);
}
.ca-msg-assistant .ca-bubble {
  background: var(--surface);
  border: 1px solid var(--line);
  box-shadow: var(--sh-1);
}
.ca-bubble-text :deep(strong) {
  font-weight: var(--fw-semibold, 600);
}
.ca-bubble-text :deep(code) {
  background: var(--surface-3);
  padding: 1px 5px;
  border-radius: var(--r-1, 4px);
  font-family: var(--font-mono, 'JetBrains Mono', monospace);
  font-size: 11.5px;
}
/* 2026-05-19 image #39 — marked GFM 输出的元素样式 */
.ca-bubble-text :deep(p) {
  margin: 0 0 8px;
}
.ca-bubble-text :deep(p:last-child) { margin-bottom: 0; }
.ca-bubble-text :deep(ul),
.ca-bubble-text :deep(ol) {
  margin: 4px 0 8px;
  padding-left: 20px;
}
.ca-bubble-text :deep(li) {
  margin: 2px 0;
}
.ca-bubble-text :deep(h1),
.ca-bubble-text :deep(h2),
.ca-bubble-text :deep(h3),
.ca-bubble-text :deep(h4) {
  margin: 10px 0 6px;
  font-weight: var(--fw-semibold, 600);
  line-height: 1.3;
  letter-spacing: -0.005em;
}
.ca-bubble-text :deep(h1) { font-size: 16px; }
.ca-bubble-text :deep(h2) { font-size: 14px; }
.ca-bubble-text :deep(h3) { font-size: 13px; }
.ca-bubble-text :deep(h4) { font-size: 12.5px; }
.ca-bubble-text :deep(pre) {
  background: var(--surface-3);
  padding: 8px 10px;
  border-radius: var(--r-2, 6px);
  overflow-x: auto;
  margin: 6px 0;
  font-size: 11.5px;
  line-height: 1.5;
  font-family: var(--font-mono, 'JetBrains Mono', monospace);
}
.ca-bubble-text :deep(pre code) {
  background: transparent;
  padding: 0;
  font-size: inherit;
}
.ca-bubble-text :deep(blockquote) {
  border-left: 3px solid var(--brand);
  padding: 2px 10px;
  margin: 6px 0;
  color: var(--text-2);
  background: var(--surface-3);
  border-radius: 0 var(--r-1, 4px) var(--r-1, 4px) 0;
}
.ca-bubble-text :deep(table) {
  border-collapse: collapse;
  margin: 8px 0;
  width: 100%;
  font-size: 11.5px;
  display: block;
  overflow-x: auto;
}
.ca-bubble-text :deep(thead) {
  background: var(--surface-3);
}
.ca-bubble-text :deep(th),
.ca-bubble-text :deep(td) {
  border: 1px solid var(--line);
  padding: 5px 8px;
  text-align: left;
  vertical-align: top;
  white-space: nowrap;
}
.ca-bubble-text :deep(th) {
  font-weight: var(--fw-semibold, 600);
}
.ca-bubble-text :deep(a) {
  color: var(--brand);
  text-decoration: none;
}
.ca-bubble-text :deep(a:hover) { text-decoration: underline; color: var(--brand-hover); }
.ca-bubble-text :deep(hr) {
  border: 0;
  border-top: 1px solid var(--line);
  margin: 10px 0;
}

/* SSE streaming progress log */
.ca-stream-log {
  display: flex;
  flex-direction: column;
  gap: 4px;
  margin-bottom: 8px;
  padding: 10px 12px;
  border-radius: var(--r-3, 8px);
  background: var(--surface-2);
  border: 1px dashed var(--line-strong);
  font-size: 12px;
  color: var(--text-2);
  font-family: var(--font-mono, 'JetBrains Mono', monospace);
  max-height: 360px;
  overflow-y: auto;
  line-height: 1.55;
}
.ca-stream-line {
  white-space: nowrap;
  overflow-x: auto;
  padding: 1px 0;
}
.ca-stream-line::-webkit-scrollbar {
  height: 4px;
}
.ca-bubble-typing {
  display: flex;
  gap: 4px;
  padding: 6px 0;
}
.ca-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--brand);
  animation: ca-bounce 1.2s infinite ease-in-out both;
}
.ca-dot:nth-child(2) { animation-delay: 0.16s; }
.ca-dot:nth-child(3) { animation-delay: 0.32s; }
@keyframes ca-bounce {
  0%, 80%, 100% { opacity: 0.3; transform: scale(0.85); }
  40% { opacity: 1; transform: scale(1); }
}

/* image #43 — 浏览器截图缩略图 */
.ca-screenshots {
  display: flex;
  flex-direction: column;
  gap: 6px;
  margin: 8px 0;
}
.ca-screenshot {
  margin: 0;
  padding: 4px;
  border-radius: var(--r-2, 6px);
  background: var(--surface-2);
  border: 1px solid var(--line);
}
.ca-screenshot img {
  width: 100%;
  height: auto;
  display: block;
  border-radius: var(--r-1, 4px);
  cursor: zoom-in;
  transition: opacity 0.14s var(--ease, cubic-bezier(0.2, 0.8, 0.2, 1));
}
.ca-screenshot img:hover {
  opacity: 0.92;
}
.ca-screenshot figcaption {
  font-size: 10.5px;
  color: var(--text-3);
  margin-top: 3px;
  text-align: right;
}

/* tool_trace chips — 让用户看见 AI 真调了哪些 MCP 工具 */
.ca-tool-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  margin-bottom: 6px;
}
.ca-tool-chip {
  display: inline-flex;
  align-items: center;
  padding: 1px 6px;
  border-radius: var(--r-1, 4px);
  font-family: var(--font-mono, 'JetBrains Mono', monospace);
  font-size: 10.5px;
  line-height: 1.6;
  border: 1px solid transparent;
  cursor: default;
}
.ca-tool-chip-ok {
  background: var(--brand-soft);
  color: var(--brand-text);
  border-color: var(--brand-ring);
}
.ca-tool-chip-err {
  background: var(--err-soft);
  color: var(--err);
  border-color: var(--err-soft);
}

/* 2026-05-21 Phase 2: plan 卡片 — 顶部独立卡片渲染"我的计划:" 列表 */
.ca-plan-card {
  margin-bottom: 10px;
  padding: 10px 12px;
  border-radius: var(--r-3, 8px);
  background: var(--brand-soft);
  border: 1px solid var(--brand-ring);
  box-shadow: var(--sh-1);
}
.ca-plan-head {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 6px;
  font-size: 12.5px;
  font-weight: var(--fw-semibold, 600);
  color: var(--brand-text);
  letter-spacing: -0.005em;
}
.ca-plan-icon { font-size: 14px; }
.ca-plan-title { flex: 1; }
.ca-plan-status {
  font-size: 10.5px;
  font-weight: 500;
  padding: 1px 6px;
  border-radius: var(--r-1, 4px);
  background: var(--surface);
  color: var(--text-3);
  border: 1px solid var(--line);
}
.ca-plan-status-done {
  color: var(--success, #15803d);
  background: var(--success-soft, #dcfce7);
  border-color: var(--success-soft, #bbf7d0);
}
.ca-plan-body {
  font-size: 12px;
  line-height: 1.6;
  color: var(--text-2);
}
.ca-plan-body :deep(ol),
.ca-plan-body :deep(ul) {
  margin: 0;
  padding-left: 18px;
}
.ca-plan-body :deep(li) {
  margin: 1px 0;
}

/* 2026-05-21 Phase 2: 完成态 hero CTA — 跑完 + 有修改类工具时让操作流闭环 */
.ca-hero-cta {
  margin-top: 10px;
  padding: 10px 12px;
  border-radius: var(--r-3, 8px);
  background: var(--success-soft, #dcfce7);
  border: 1px solid var(--success-ring, #86efac);
  display: flex;
  align-items: center;
  gap: 10px;
}
.ca-hero-text {
  flex: 1;
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12.5px;
  color: var(--success, #15803d);
}
.ca-hero-text strong {
  font-weight: var(--fw-semibold, 600);
}
.ca-hero-icon {
  font-size: 14px;
}
.ca-hero-btn {
  padding: 5px 12px;
  border-radius: var(--r-2, 6px);
  background: var(--success, #15803d);
  color: #fff;
  border: none;
  font-size: 12px;
  font-weight: 500;
  cursor: pointer;
  font-family: inherit;
  transition: opacity 0.14s var(--ease, cubic-bezier(0.2, 0.8, 0.2, 1));
}
.ca-hero-btn:hover { opacity: 0.88; }
.ca-hero-btn:focus-visible {
  outline: 2px solid var(--success, #15803d);
  outline-offset: 2px;
}

.ca-change-card {
  margin-top: 10px;
  padding: 10px 12px;
  background: var(--brand-soft);
  border: 1px solid var(--brand-ring);
  border-radius: var(--r-3, 8px);
}
/* 2026-05-21 Task #13: 纯信息卡片变体, 不带 stub 按钮 */
.ca-change-card-info {
  background: var(--surface-2);
  border-color: var(--line);
}
.ca-change-note {
  margin-top: 8px;
  padding: 6px 8px;
  font-size: 11px;
  line-height: 1.5;
  color: var(--text-3);
  background: var(--surface);
  border: 1px dashed var(--line);
  border-radius: var(--r-2, 6px);
}
.ca-change-title {
  font-size: 12px;
  font-weight: var(--fw-semibold, 600);
  color: var(--brand-text);
  margin-bottom: 6px;
  letter-spacing: -0.005em;
}
.ca-change-list {
  margin: 6px 0;
  padding-left: 18px;
  font-size: 11.5px;
  color: var(--text-2);
  line-height: 1.7;
}
.ca-change-json {
  background: var(--surface);
  border: 1px solid var(--line);
  padding: 8px;
  border-radius: var(--r-2, 6px);
  max-height: 200px;
  overflow: auto;
  font-family: var(--font-mono, 'JetBrains Mono', monospace);
  font-size: 10.5px;
  color: var(--text-2);
}
.ca-change-actions {
  display: flex;
  gap: 6px;
  margin-top: 8px;
}
.ca-btn-secondary,
.ca-btn-primary {
  padding: 5px 12px;
  border-radius: var(--r-2, 6px);
  font-size: 11.5px;
  font-weight: var(--fw-medium, 500);
  cursor: pointer;
  font-family: inherit;
  border: 1px solid var(--line);
  background: var(--surface);
  color: var(--text);
  transition: background 0.14s var(--ease, cubic-bezier(0.2, 0.8, 0.2, 1)),
              border-color 0.14s var(--ease, cubic-bezier(0.2, 0.8, 0.2, 1)),
              color 0.14s var(--ease, cubic-bezier(0.2, 0.8, 0.2, 1));
}
.ca-btn-secondary:hover {
  background: var(--brand-soft);
  border-color: var(--brand-ring);
  color: var(--brand);
}
.ca-btn-secondary:focus-visible,
.ca-btn-primary:focus-visible {
  outline: 2px solid var(--line-focus, var(--brand-ring));
  outline-offset: 2px;
}
.ca-btn-primary {
  background: var(--brand);
  color: var(--text-inverse, #fff);
  border-color: var(--brand);
  box-shadow: var(--sh-brand);
}
.ca-btn-primary:hover {
  background: var(--brand-hover);
  border-color: var(--brand-hover);
}

.ca-thinking {
  display: flex;
  gap: 4px;
  align-items: center;
  padding: 8px 12px;
}
.ca-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--text-3);
  animation: caBlink 1.4s infinite;
}
.ca-dot:nth-child(2) {
  animation-delay: 0.2s;
}
.ca-dot:nth-child(3) {
  animation-delay: 0.4s;
}
@keyframes caBlink {
  0%,
  60%,
  100% {
    opacity: 0.3;
  }
  30% {
    opacity: 1;
  }
}

.ca-input-area {
  display: flex;
  gap: 8px;
  padding: 10px 12px;
  border-top: 1px solid var(--line);
  background: var(--surface);
}
.ca-input {
  flex: 1;
  resize: none;
  padding: 8px 10px;
  border: 1px solid var(--line);
  border-radius: var(--r-3, 8px);
  background: var(--surface-2);
  color: var(--text);
  font-size: 12.5px;
  line-height: 1.5;
  font-family: inherit;
  outline: none;
  transition: border-color 0.14s var(--ease, cubic-bezier(0.2, 0.8, 0.2, 1)),
              box-shadow 0.14s var(--ease, cubic-bezier(0.2, 0.8, 0.2, 1)),
              background 0.14s var(--ease, cubic-bezier(0.2, 0.8, 0.2, 1));
}
.ca-input:focus {
  border-color: var(--brand);
  background: var(--surface);
  box-shadow: 0 0 0 3px var(--brand-ring);
}
.ca-input:disabled {
  opacity: 0.6;
}

.ca-send {
  align-self: flex-end;
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 7px 14px;
  border-radius: var(--r-3, 8px);
  background: var(--brand);
  color: var(--text-inverse, #fff);
  border: none;
  font-size: 12.5px;
  font-weight: var(--fw-medium, 500);
  cursor: pointer;
  font-family: inherit;
  box-shadow: var(--sh-brand);
  transition: background 0.14s var(--ease, cubic-bezier(0.2, 0.8, 0.2, 1));
}
.ca-send:disabled {
  opacity: 0.5;
  cursor: not-allowed;
  box-shadow: none;
}
.ca-send:not(:disabled):hover {
  background: var(--brand-hover);
}
.ca-send:focus-visible {
  outline: 2px solid var(--line-focus, var(--brand-ring));
  outline-offset: 2px;
}

/* Dark theme — most tokens cascade; explicit override only where needed
   to keep contrast on assistant bubbles + tool chips. */
html[data-theme="dark"] .ca-msg-assistant .ca-bubble {
  background: var(--surface-2);
}
html[data-theme="dark"] .ca-example {
  background: var(--surface-2);
}
html[data-theme="dark"] .ca-tool-chip-err {
  background: var(--err-soft);
  color: var(--err);
  border-color: var(--err);
}
</style>
