<!-- SpecChatPanel.vue — design-v4 U7: SPEC 设计 tab 内嵌对话面板.

  定位 (跟现有 ConfigAssistantPanel 浮窗区分):
  | | ConfigAssistant (浮窗) | SPEC Chat (本组件, 内嵌设计 tab) |
  |--|---------------------|--------------------------------|
  | 改对象 | apaas 真配置 | spec_sections 草稿 |
  | 立即生效 | 是 | 否, 等用户"确认并生成" |
  | 节奏 | 短链 / 单点 / 像素级 | 长链 / 批量 / 语义级 |
  | 心智 | 执行型 | 设计型 |

  布局 3 区:
    header  — 标题 ✨ + 当前章节 ctx chip
    body    — scroll list, 用户/AI 气泡, AI 气泡含 diff card + 接受/弃用
    input   — textarea + quick chips (按 chapter 切) + 发送 btn

  数据流:
    1. 用户输入 → POST /applications/{appId}/spec-chat-stream (SSE)
    2. backend stream:
       - started:     初始化
       - token:       逐字 stream 追加到当前 AI 气泡
       - spec_change: { section_type, section_key, before, after, summary, mcp_tool }
                      → 显 diff card + 接受/弃用 按钮
       - done:        结束
       - error:       报错
    3. 用户点接受 → emit('spec-updated', section_type, section_key) 给 SpecDesignPanel reload
       用户点弃用 → 标记 dismissed, MVP 不回滚 (backend 已写入草稿). P2 接 rollback.

  视觉 100% 跟 mockup `docs/internal/design-tab-mockup-2026-05-27.html` 视图 ① chat-pane 对齐.
  跟 ConfigAssistant 视觉区分: header 用 ✨ sparkle + brand-soft 底色提示"改 SPEC 不直接生效".

  ⚠️ MVP backend 是 rule-based mock LLM (含"字段/角色/字典/菜单/流程"关键词触发).
-->
<template>
  <section class="spc-shell" aria-label="SPEC 对话助手">
    <!-- ── 1. header ─────────────────────────────────────────────────── -->
    <div class="spc-head">
      <div class="spc-title">
        <span class="spc-title-ic" aria-hidden="true">✨</span>
        <span>用对话改 SPEC</span>
      </div>
      <div class="spc-ctx">
        <span class="spc-ctx-label">当前章节</span>
        <span class="spc-ctx-chip">{{ props.chapterTitle || '—' }}</span>
      </div>
      <div class="spc-mode-hint">
        改 SPEC 不直接生效 — 写入草稿等"确认并生成"
      </div>
    </div>

    <!-- ── 2. body (msg list) ─────────────────────────────────────────── -->
    <div class="spc-body" ref="bodyEl">
      <!-- 空态 -->
      <div v-if="messages.length === 0" class="spc-empty">
        <div class="spc-empty-ic" aria-hidden="true">💬</div>
        <h4>用自然语言改这章</h4>
        <p>例如 "加字段 '备注'" / "加角色 '财务专员'" / "加字典选项 '已批准'".</p>
        <p class="spc-empty-hint">AI 把改动写入 SPEC 草稿; 你审核后点上方"确认并生成"才会真同步 apaas.</p>
      </div>

      <!-- 消息列表 -->
      <div
        v-for="(msg, idx) in messages"
        :key="msg.id"
        class="spc-msg"
        :class="msg.role"
      >
        <div class="spc-msg-meta">
          <span>{{ msg.role === 'user' ? '你' : 'AI' }}</span>
          <span class="spc-msg-time">{{ formatTime(msg.created_at) }}</span>
        </div>
        <div class="spc-bubble">
          <span class="spc-bubble-text">{{ msg.content || (msg.streaming ? '…' : '') }}</span>
          <span v-if="msg.streaming" class="spc-streaming-cursor" aria-hidden="true">▍</span>
        </div>

        <!-- AI 气泡的 diff card (来自 spec_change 事件) -->
        <div v-if="msg.role === 'ai' && msg.spec_change" class="spc-diff-card">
          <div class="spc-diff-card-head">
            <span aria-hidden="true">📌</span>
            <span>{{ describeSection(msg.spec_change.section_type, msg.spec_change.section_key) }}</span>
            <span v-if="msg.spec_change.mcp_tool" class="spc-mcp-chip">{{ msg.spec_change.mcp_tool }}</span>
          </div>
          <!-- diff content: 用 before/after key 集合算简单的 + - -->
          <div class="spc-diff-body">
            <div
              v-for="line in computeDiffLines(msg.spec_change.before, msg.spec_change.after)"
              :key="line.text"
              class="spc-diff-line"
              :class="line.kind"
            >{{ line.text }}</div>
          </div>
          <div v-if="!msg.spec_change.accepted && !msg.spec_change.dismissed" class="spc-accept-row">
            <button
              class="spc-btn-mini spc-btn-mini-primary"
              type="button"
              @click="onAcceptChange(idx)"
            >✓ 应用到草稿</button>
            <button
              class="spc-btn-mini"
              type="button"
              @click="onDismissChange(idx)"
            >✗ 弃用</button>
          </div>
          <div v-else-if="msg.spec_change.accepted" class="spc-accept-status accepted">
            <span aria-hidden="true">✓</span>
            已写入草稿 (draft +1)
          </div>
          <div v-else class="spc-accept-status dismissed">
            <span aria-hidden="true">✗</span>
            已弃用 — backend 已落库 (MVP), 真回滚 P2 接入
          </div>
        </div>
      </div>

      <!-- error 横幅 -->
      <div v-if="errorBanner" class="spc-error-banner">
        <span aria-hidden="true">⚠️</span>
        <span>{{ errorBanner }}</span>
        <button class="spc-error-close" type="button" @click="errorBanner = ''">×</button>
      </div>
    </div>

    <!-- ── 3. input area ─────────────────────────────────────────────── -->
    <div class="spc-input-area">
      <textarea
        v-model="inputText"
        ref="inputRef"
        class="spc-textarea"
        :placeholder="placeholderText"
        :disabled="sending"
        rows="2"
        @keydown.enter.exact.prevent="onSend"
      />
      <div class="spc-input-bar">
        <div class="spc-chips" role="group" aria-label="快捷指令">
          <button
            v-for="chip in quickChips"
            :key="chip"
            class="spc-chip"
            type="button"
            :disabled="sending"
            @click="onClickChip(chip)"
          >{{ chip }}</button>
        </div>
        <button
          class="spc-send-btn"
          type="button"
          :disabled="!inputText.trim() || sending"
          @click="onSend"
        >
          <span v-if="sending" class="spc-send-spinner" aria-hidden="true"></span>
          <span>{{ sending ? '发送中…' : '发送' }}</span>
        </button>
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { ref, computed, nextTick, watch } from 'vue'
import { API_PREFIX } from '@/utils/request'

// ── props / emits ───────────────────────────────────────────────────────
const props = defineProps<{
  appId: number
  apaasAppId?: string
  activeChapter: string   // e.g., 'data_model' — 当前 SpecDesignPanel 选中章节
  chapterTitle: string    // e.g., '数据模型' — header ctx chip 显示用
}>()

const emit = defineEmits<{
  (e: 'spec-updated', sectionType: string, sectionKey: string): void
}>()

// ── 消息类型 ──────────────────────────────────────────────────────────────
interface SpecChangeEvent {
  section_type: string
  section_key: string
  before: Record<string, any>
  after: Record<string, any>
  summary: string
  created?: boolean
  mcp_tool?: string
  // UI 状态 (前端补)
  accepted?: boolean
  dismissed?: boolean
}

interface ChatMsg {
  id: number
  role: 'user' | 'ai'
  content: string
  created_at: number  // ms epoch
  streaming?: boolean
  spec_change?: SpecChangeEvent
}

// ── reactive state ──────────────────────────────────────────────────────
const messages = ref<ChatMsg[]>([])
const inputText = ref('')
const sending = ref(false)
const errorBanner = ref('')
const bodyEl = ref<HTMLElement | null>(null)
const inputRef = ref<HTMLTextAreaElement | null>(null)
let _msgIdSeq = 1

// ── expose: focusInput — 父组件锚点联动用 ───────────────────────────────
// SpecDesignPanel 章节 hover "用对话改这段" 点击时调:
//   specChatRef.value?.focusInput?.()
// 行为: textarea focus + scroll 自身到视口可见区 (右栏滚动 + 桌面端整页滚动兜底).
function focusInput() {
  const el = inputRef.value
  if (!el) return
  try {
    el.focus({ preventScroll: false })
    el.scrollIntoView({ behavior: 'smooth', block: 'nearest' })
  } catch {
    // 老浏览器兜底
    try { el.focus() } catch { /* ignore */ }
  }
}
defineExpose({ focusInput })

// quick chips 按 chapter 切
const quickChips = computed(() => {
  switch (props.activeChapter) {
    case 'data_model':
      return ['+ 字段', '+ 模型', '+ 关系']
    case 'roles':
      return ['+ 角色', '+ 权限']
    case 'dict':
      return ['+ 字典', '+ 选项']
    case 'menus':
      return ['+ 菜单', '调整顺序']
    case 'form':
      return ['+ 字段', '改布局']
    case 'list':
      return ['+ 列', '改过滤器']
    case 'process':
      return ['+ 流程', '+ 节点']
    default:
      return ['改这段']
  }
})

const placeholderText = computed(() => {
  if (props.activeChapter === 'data_model') {
    return '例如: 加字段「备注」 / 加模型「图书」 / 借阅记录加 FK 关联 图书'
  }
  if (props.activeChapter === 'roles') {
    return '例如: 加角色「财务专员」 / 删除角色 X'
  }
  if (props.activeChapter === 'dict') {
    return '例如: 字典 borrow_status 加选项「已批准」'
  }
  return '描述你想怎么改这章 SPEC, AI 会写入草稿…'
})

// ── helpers ─────────────────────────────────────────────────────────────
function nextId(): number {
  return _msgIdSeq++
}

function formatTime(ms: number): string {
  const d = new Date(ms)
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${pad(d.getHours())}:${pad(d.getMinutes())}`
}

function scrollToBottom() {
  nextTick(() => {
    const el = bodyEl.value
    if (!el) return
    try {
      el.scrollTop = el.scrollHeight
    } catch {
      // ignore
    }
  })
}

function describeSection(sectionType: string, sectionKey: string): string {
  const typeName: Record<string, string> = {
    data_model: '数据模型',
    permission: '角色权限',
    page: '菜单/页面',
    form: '表单',
    list: '列表',
    process: '流程',
  }
  return `${typeName[sectionType] || sectionType} · ${sectionKey}`
}

interface DiffLine { text: string; kind: 'add' | 'del' | 'meta' }

/** 简单 diff: 比较 before/after 顶级 key 的值, 数组追加显 +, 删除显 -.
 *  MVP 用户体验: AI 一次只加东西, 所以主要走 add path; 删除分支留给 P2. */
function computeDiffLines(
  before: Record<string, any>,
  after: Record<string, any>,
): DiffLine[] {
  const lines: DiffLine[] = []
  if (!after || typeof after !== 'object') {
    return [{ text: '(no patch)', kind: 'meta' }]
  }
  const beforeKeys = new Set(Object.keys(before || {}))
  for (const [k, v] of Object.entries(after)) {
    const wasArray = Array.isArray((before || {})[k])
    if (Array.isArray(v) && wasArray) {
      const beforeArr = (before || {})[k] as any[]
      const addedCount = v.length - beforeArr.length
      if (addedCount > 0) {
        for (let i = beforeArr.length; i < v.length; i++) {
          const item = v[i]
          const desc = describeItem(item, k)
          lines.push({ text: desc, kind: 'add' })
        }
        continue
      }
    }
    if (Array.isArray(v) && !wasArray) {
      // 新建的 list
      for (const item of v) {
        const desc = describeItem(item, k)
        lines.push({ text: desc, kind: 'add' })
      }
      continue
    }
    if (!beforeKeys.has(k)) {
      lines.push({ text: `新增 ${k}: ${JSON.stringify(v).slice(0, 60)}`, kind: 'add' })
    }
  }
  if (lines.length === 0) {
    lines.push({ text: '(草稿无可视化差异 — 已 merge)', kind: 'meta' })
  }
  return lines
}

function describeItem(item: any, parentKey: string): string {
  if (!item || typeof item !== 'object') return String(item)
  const name = item.name || item.label || '(unnamed)'
  const code = item.code || item.value || ''
  const type = item.type || ''
  const kindLabel =
    parentKey.includes('field') ? '字段' :
    parentKey.includes('role') ? '角色' :
    parentKey.includes('dict') ? '字典项' :
    parentKey.includes('menu') ? '菜单' :
    parentKey.includes('process') ? '流程' :
    ''
  const suffix = type ? ` (${type})` : code ? ` [${code}]` : ''
  return `${kindLabel ? kindLabel + ': ' : ''}${name}${suffix}`
}

// ── SSE 连接 + 解析 ─────────────────────────────────────────────────────
async function streamChat(message: string): Promise<void> {
  // user msg 落到列表
  const userMsg: ChatMsg = {
    id: nextId(),
    role: 'user',
    content: message,
    created_at: Date.now(),
  }
  messages.value.push(userMsg)

  // ai 占位 (streaming=true)
  const aiMsg: ChatMsg = {
    id: nextId(),
    role: 'ai',
    content: '',
    created_at: Date.now(),
    streaming: true,
  }
  messages.value.push(aiMsg)
  scrollToBottom()

  const token = localStorage.getItem('token') || ''
  const url = `${API_PREFIX}/applications/${props.appId}/spec-chat-stream`
  const payload = {
    message,
    active_chapter: props.activeChapter,
    history: messages.value
      .slice(-20, -2)  // 排除刚 push 的 user/ai (最后两条)
      .map((m) => ({ role: m.role === 'user' ? 'user' : 'assistant', content: m.content })),
  }

  let resp: Response
  try {
    resp = await fetch(url, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Accept': 'text/event-stream',
        'Authorization': token ? `Bearer ${token}` : '',
      },
      body: JSON.stringify(payload),
    })
  } catch (e: any) {
    aiMsg.streaming = false
    aiMsg.content = '(连接失败)'
    errorBanner.value = `网络错误: ${e?.message || e}`
    return
  }

  if (!resp.ok || !resp.body) {
    aiMsg.streaming = false
    aiMsg.content = '(请求失败)'
    let detail = ''
    try { detail = await resp.text() } catch { /* ignore */ }
    errorBanner.value = `HTTP ${resp.status}: ${detail.slice(0, 200) || '无 body'}`
    return
  }

  const reader = resp.body.getReader()
  const decoder = new TextDecoder('utf-8')
  let buffer = ''
  let currentEvent = 'message'

  // SSE 解析: \n\n 分块
  while (true) {
    const { value, done } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true }).replace(/\r\n/g, '\n')
    let idx: number
    while ((idx = buffer.indexOf('\n\n')) !== -1) {
      const chunk = buffer.slice(0, idx)
      buffer = buffer.slice(idx + 2)
      for (const line of chunk.split('\n')) {
        if (line.startsWith(':')) continue   // SSE comment
        if (line.startsWith('event:')) {
          currentEvent = line.slice(6).trim()
        } else if (line.startsWith('data:')) {
          const raw = line.slice(5).trim()
          if (!raw) continue
          try {
            const parsed = JSON.parse(raw)
            handleEvent(currentEvent, parsed, aiMsg)
          } catch (e) {
            console.warn('[SpecChat] failed to parse SSE data', raw, e)
          }
        }
      }
      currentEvent = 'message'
    }
  }

  // stream 结束 — 关闭 streaming 状态 (兜底, done event 应该已经关了)
  aiMsg.streaming = false
  scrollToBottom()
}

function handleEvent(eventType: string, data: any, aiMsg: ChatMsg) {
  if (eventType === 'started') {
    // 不显, 只记日志
    return
  }
  if (eventType === 'token') {
    aiMsg.content += String(data.content || '')
    scrollToBottom()
    return
  }
  if (eventType === 'spec_change') {
    aiMsg.spec_change = {
      section_type: String(data.section_type || ''),
      section_key: String(data.section_key || ''),
      before: data.before || {},
      after: data.after || {},
      summary: String(data.summary || ''),
      created: Boolean(data.created),
      mcp_tool: data.mcp_tool ? String(data.mcp_tool) : undefined,
      accepted: false,
      dismissed: false,
    }
    scrollToBottom()
    return
  }
  if (eventType === 'done') {
    aiMsg.streaming = false
    // backend 已写入草稿. 这里前端 emit 让 SpecDesignPanel 知道有改动.
    // (P2 接入后改成"用户点'应用'再 emit", 现在为了 demo flow MVP 直接 emit.)
    // 实际 emit 在 onAcceptChange — done 时不动.
    return
  }
  if (eventType === 'error') {
    aiMsg.streaming = false
    errorBanner.value = String(data.message || '后端报错')
    return
  }
  // 其他 event 静默
}

// ── 用户操作 ─────────────────────────────────────────────────────────────
async function onSend() {
  const text = inputText.value.trim()
  if (!text || sending.value) return
  inputText.value = ''
  errorBanner.value = ''
  sending.value = true
  try {
    await streamChat(text)
  } finally {
    sending.value = false
  }
}

function onClickChip(chip: string) {
  // 把 chip 字面贴到 input, 让用户继续编辑
  const cleaned = chip.replace(/^\+\s*/, '加 ')
  if (inputText.value && !inputText.value.endsWith(' ')) inputText.value += ' '
  inputText.value += cleaned
}

function onAcceptChange(msgIdx: number) {
  const msg = messages.value[msgIdx]
  if (!msg || !msg.spec_change) return
  msg.spec_change.accepted = true
  // 通知父组件 reload 对应章节
  emit('spec-updated', msg.spec_change.section_type, msg.spec_change.section_key)
}

function onDismissChange(msgIdx: number) {
  const msg = messages.value[msgIdx]
  if (!msg || !msg.spec_change) return
  msg.spec_change.dismissed = true
  // MVP: 草稿已落库, 只 UI 标记弃用. P2 接 rollback (revert spec_json).
}

// ── 章节切换时清空 history (避免 cross-chapter 串台) ────────────────────
watch(
  () => props.activeChapter,
  (newCh, oldCh) => {
    if (newCh !== oldCh && oldCh !== undefined) {
      messages.value = []
      errorBanner.value = ''
    }
  },
)
</script>

<style scoped>
/* ── 整体 shell ─────────────────────────────────────────────────────────── */
.spc-shell {
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: 0;
  background: var(--surface);
  font-family: var(--font-sans);
  color: var(--text);
}

/* ── 1. header ─────────────────────────────────────────────────────────── */
.spc-head {
  padding: 14px 16px 12px;
  border-bottom: 1px solid var(--line);
  background: var(--brand-soft);
}
.spc-title {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 14px;
  font-weight: 600;
  color: var(--text);
  margin-bottom: 6px;
}
.spc-title-ic { font-size: 14px; color: var(--brand); }
.spc-ctx {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  color: var(--text-3);
}
.spc-ctx-label { color: var(--text-3); }
.spc-ctx-chip {
  display: inline-block;
  padding: 2px 10px;
  background: var(--surface);
  border: 1px solid var(--brand);
  color: var(--brand);
  border-radius: 12px;
  font-size: 11px;
  font-weight: 500;
}
.spc-mode-hint {
  margin-top: 6px;
  font-size: 11px;
  color: var(--text-3);
  font-style: italic;
}

/* ── 2. body ───────────────────────────────────────────────────────────── */
.spc-body {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: 16px;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

/* 空态 */
.spc-empty {
  margin: auto;
  text-align: center;
  max-width: 280px;
  color: var(--text-3);
  padding: 24px 8px;
}
.spc-empty-ic {
  font-size: 32px;
  opacity: 0.65;
  margin-bottom: 10px;
}
.spc-empty h4 {
  font-size: 13px;
  font-weight: 600;
  color: var(--text);
  margin: 0 0 6px;
}
.spc-empty p {
  font-size: 12.5px;
  line-height: 1.55;
  margin: 0 0 6px;
}
.spc-empty-hint {
  font-size: 11.5px;
  color: var(--text-4);
  margin-top: 10px;
}

/* ── 消息 ──────────────────────────────────────────────────────────────── */
.spc-msg {
  margin-bottom: 12px;
}
.spc-msg-meta {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 11px;
  color: var(--text-4);
  margin-bottom: 4px;
}
.spc-msg.user .spc-msg-meta { justify-content: flex-end; }
.spc-msg-time { color: var(--text-4); }

.spc-bubble {
  padding: 8px 12px;
  border-radius: 12px;
  font-size: 13px;
  line-height: 1.55;
  word-break: break-word;
  display: inline-block;
  max-width: 100%;
}
.spc-msg.user .spc-bubble {
  background: var(--brand);
  color: #fff;
  border-radius: 12px 12px 4px 12px;
  margin-left: 32px;
  display: block;
}
.spc-msg.ai .spc-bubble {
  background: var(--surface-2);
  color: var(--text);
  border-radius: 12px 12px 12px 4px;
  margin-right: 32px;
}
.spc-bubble-text { white-space: pre-wrap; }
.spc-streaming-cursor {
  display: inline-block;
  color: var(--brand);
  font-weight: 700;
  animation: spc-blink 1s infinite;
  margin-left: 2px;
}
@keyframes spc-blink {
  0%, 49% { opacity: 1; }
  50%, 100% { opacity: 0; }
}

/* ── diff card ────────────────────────────────────────────────────────── */
.spc-diff-card {
  margin-top: 8px;
  margin-right: 32px;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: var(--surface);
  overflow: hidden;
}
.spc-diff-card-head {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 10px;
  background: var(--surface-2);
  font-size: 11px;
  color: var(--text-3);
  border-bottom: 1px solid var(--line);
  font-weight: 500;
}
.spc-mcp-chip {
  margin-left: auto;
  font-family: var(--font-mono);
  font-size: 10px;
  color: var(--text-4);
  padding: 1px 6px;
  background: var(--surface-3);
  border-radius: 3px;
}
.spc-diff-body { padding: 4px 0; }
.spc-diff-line {
  padding: 3px 12px;
  font-family: var(--font-mono);
  font-size: 11px;
  line-height: 1.55;
  white-space: pre-wrap;
}
.spc-diff-line.add { background: var(--ok-soft, #ECFDF5); color: #065F46; }
.spc-diff-line.add::before { content: '+ '; font-weight: 700; }
.spc-diff-line.del { background: var(--err-soft, #FEF2F2); color: #991B1B; text-decoration: line-through; }
.spc-diff-line.del::before { content: '- '; font-weight: 700; }
.spc-diff-line.meta { color: var(--text-4); font-style: italic; }

/* ── accept / dismiss row ─────────────────────────────────────────────── */
.spc-accept-row {
  margin: 0 10px 8px;
  padding-top: 8px;
  display: flex;
  gap: 6px;
  border-top: 1px dashed var(--line);
}
.spc-btn-mini {
  padding: 4px 10px;
  border-radius: 6px;
  font-size: 11px;
  cursor: pointer;
  border: 1px solid var(--line);
  background: var(--surface);
  color: var(--text);
  font-family: inherit;
  transition: all 0.15s;
}
.spc-btn-mini:hover {
  background: var(--surface-2);
  border-color: var(--line-strong);
}
.spc-btn-mini-primary {
  background: var(--brand);
  border-color: var(--brand);
  color: #fff;
}
.spc-btn-mini-primary:hover {
  background: var(--brand-hover);
  border-color: var(--brand-hover);
  color: #fff;
}
.spc-accept-status {
  margin: 0 10px 8px;
  padding: 6px 10px;
  border-top: 1px dashed var(--line);
  font-size: 11px;
  display: flex;
  align-items: center;
  gap: 6px;
}
.spc-accept-status.accepted { color: var(--ok, #10B981); }
.spc-accept-status.dismissed { color: var(--text-3); }

/* ── error banner ────────────────────────────────────────────────────── */
.spc-error-banner {
  position: sticky;
  bottom: 0;
  margin: 8px 0 0;
  padding: 8px 12px;
  background: var(--err-soft, #FEE2E2);
  color: var(--err, #B91C1C);
  border: 1px solid var(--err, #EF4444);
  border-radius: 6px;
  font-size: 12px;
  display: flex;
  align-items: center;
  gap: 6px;
}
.spc-error-close {
  margin-left: auto;
  background: transparent;
  border: none;
  color: inherit;
  cursor: pointer;
  font-size: 16px;
  line-height: 1;
  padding: 0 4px;
}

/* ── 3. input area ─────────────────────────────────────────────────────── */
.spc-input-area {
  padding: 12px;
  border-top: 1px solid var(--line);
  background: var(--surface);
  flex-shrink: 0;
}
.spc-textarea {
  width: 100%;
  border: 1px solid var(--line);
  border-radius: 8px;
  padding: 10px 12px;
  resize: none;
  height: 56px;
  font-family: inherit;
  font-size: 13px;
  outline: none;
  color: var(--text);
  background: var(--surface);
  transition: border-color 0.15s;
  box-sizing: border-box;
}
.spc-textarea:focus { border-color: var(--brand); }
.spc-textarea:disabled {
  background: var(--surface-2);
  cursor: not-allowed;
}

.spc-input-bar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 8px;
  margin-top: 6px;
}
.spc-chips {
  display: flex;
  gap: 4px;
  flex-wrap: wrap;
  flex: 1;
  min-width: 0;
}
.spc-chip {
  padding: 3px 8px;
  background: var(--surface-2);
  border: 1px solid var(--line);
  border-radius: 12px;
  font-size: 11px;
  color: var(--text-2);
  cursor: pointer;
  font-family: inherit;
  white-space: nowrap;
  transition: all 0.15s;
}
.spc-chip:hover:not(:disabled) {
  background: var(--brand-soft);
  color: var(--brand);
  border-color: var(--brand);
}
.spc-chip:disabled {
  opacity: 0.55;
  cursor: not-allowed;
}

.spc-send-btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 6px 14px;
  background: var(--brand);
  color: #fff;
  border: none;
  border-radius: 6px;
  font-size: 12px;
  font-weight: 500;
  cursor: pointer;
  font-family: inherit;
  white-space: nowrap;
  transition: all 0.15s;
}
.spc-send-btn:hover:not(:disabled) { background: var(--brand-hover); }
.spc-send-btn:disabled {
  opacity: 0.55;
  cursor: not-allowed;
}
.spc-send-spinner {
  width: 11px;
  height: 11px;
  border: 1.5px solid rgba(255, 255, 255, 0.4);
  border-top-color: #fff;
  border-radius: 50%;
  animation: spc-spin 0.7s linear infinite;
}
@keyframes spc-spin { to { transform: rotate(360deg); } }
</style>
