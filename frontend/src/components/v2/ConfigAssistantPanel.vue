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
 * Tiny markdown renderer (inline-only, safe — no html passthrough).
 * Just supports **bold**, `code`, and newlines for assistant replies.
 * Defined in a normal <script> block so the template can call it directly.
 */
export function renderMd(s: string): string {
  if (!s) return ''
  const escaped = s
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
  return escaped
    .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
    .replace(/`([^`]+)`/g, '<code>$1</code>')
    .replace(/\n/g, '<br/>')
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

interface ChatMsg {
  id: number
  role: 'user' | 'assistant'
  content: string
  change_plan?: ChangePlanPreview | null
  actions_summary?: string[]
  tool_trace?: ConfigChatToolTrace[]
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

  // Build history for backend: last ~10 turns, excluding the just-pushed user msg
  const history = messages.value
    .slice(-20)
    .slice(0, -1)
    .map((m) => ({ role: m.role, content: m.content }))

  try {
    const resp = await configChatApi.chat(props.applicationId, {
      message: msg,
      history,
    })
    messages.value.push({
      id: nextId++,
      role: 'assistant',
      content: resp.reply,
      change_plan: resp.change_plan,
      actions_summary: resp.actions_summary,
      tool_trace: resp.tool_trace,
    })
    scrollToBottom()
  } catch (e: any) {
    const detail =
      e?.response?.data?.detail ||
      e?.response?.data?.message ||
      e?.message ||
      '调用失败'
    messages.value.push({
      id: nextId++,
      role: 'assistant',
      content: `❌ 出错了：${detail}`,
    })
    scrollToBottom()
  } finally {
    sending.value = false
  }
}

function onApplyChangePlan(_msg: ChatMsg) {
  // Stub: real apply will route through incremental_update API.
  // Plan D+1 will replace this with a confirmation modal + executeUpdate call.
  ElMessage.info('应用 ChangePlan 功能待 Plan D+1 接入 incremental_update apply')
}

function onPreviewDiff(_msg: ChatMsg) {
  // Stub: Plan D+1 will wire this to incrementalApi.previewUpdate.
  ElMessage.info('Diff preview 待 Plan D+1 接入')
}

const emptyHint = computed(
  () => `配置「${props.appName ?? '应用'}」— 描述你想调整的字段、流程、权限...`
)

function pickExample(text: string) {
  input.value = text
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
</script>

<template>
  <aside class="config-assistant" data-design="v2">
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
          <div class="ca-bubble-text" v-html="renderMd(m.content)" />
          <div v-if="m.change_plan" class="ca-change-card">
            <div class="ca-change-title">📋 提议的变更</div>
            <ul
              v-if="m.actions_summary && m.actions_summary.length"
              class="ca-change-list"
            >
              <li v-for="(a, i) in m.actions_summary" :key="i">{{ a }}</li>
            </ul>
            <pre v-else class="ca-change-json">{{ JSON.stringify(m.change_plan, null, 2) }}</pre>
            <div class="ca-change-actions">
              <button class="ca-btn-secondary" @click="onPreviewDiff(m)">预览 diff</button>
              <button class="ca-btn-primary" @click="onApplyChangePlan(m)">应用变更</button>
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
.config-assistant {
  width: 360px;
  flex-shrink: 0;
  display: flex;
  flex-direction: column;
  height: 100%;
  background: var(--surface);
  border-left: 1px solid var(--border);
}
.ca-head {
  padding: 14px 16px;
  border-bottom: 1px solid var(--border);
  background: var(--surface-2);
}
.ca-title {
  font-size: 14px;
  font-weight: 600;
  color: var(--text);
}
.ca-sub {
  font-size: 11.5px;
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
  opacity: 0.6;
}
.ca-empty-title {
  font-size: 13px;
  font-weight: 600;
  color: var(--text);
  margin-top: 4px;
}
.ca-empty-hint {
  font-size: 11.5px;
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
  background: var(--surface-2);
  border: 1px solid var(--border);
  color: var(--text-2);
  font-size: 12px;
  padding: 8px 12px;
  border-radius: 8px;
  cursor: pointer;
  text-align: left;
  font-family: inherit;
  transition: all 0.12s;
}
.ca-example:hover {
  border-color: var(--brand);
  color: var(--brand-text);
  background: var(--brand-soft);
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
  padding: 8px 12px;
  border-radius: 10px;
  font-size: 12.5px;
  line-height: 1.6;
  color: var(--text);
  word-break: break-word;
}
.ca-msg-user .ca-bubble {
  background: var(--brand);
  color: #fff;
}
.ca-msg-assistant .ca-bubble {
  background: var(--surface-2);
  border: 1px solid var(--border);
}
.ca-bubble-text :deep(strong) {
  font-weight: 600;
}
.ca-bubble-text :deep(code) {
  background: var(--surface-3);
  padding: 1px 5px;
  border-radius: 4px;
  font-family: var(--d-font-mono);
  font-size: 11.5px;
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
  border-radius: 10px;
  font-family: var(--d-font-mono);
  font-size: 10.5px;
  line-height: 1.6;
  border: 1px solid transparent;
  cursor: default;
}
.ca-tool-chip-ok {
  background: rgba(29, 137, 168, 0.08);
  color: var(--ai-strong, #1d89a8);
  border-color: rgba(29, 137, 168, 0.2);
}
.ca-tool-chip-err {
  background: rgba(220, 38, 38, 0.08);
  color: #b91c1c;
  border-color: rgba(220, 38, 38, 0.2);
}

.ca-change-card {
  margin-top: 10px;
  padding: 10px 12px;
  background: var(--ai-soft);
  border: 1px solid var(--ai-soft-2);
  border-radius: 8px;
}
.ca-change-title {
  font-size: 11.5px;
  font-weight: 600;
  color: var(--ai-text);
  margin-bottom: 6px;
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
  border: 1px solid var(--border);
  padding: 8px;
  border-radius: 6px;
  max-height: 200px;
  overflow: auto;
  font-family: var(--d-font-mono);
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
  padding: 4px 12px;
  border-radius: 6px;
  font-size: 11.5px;
  cursor: pointer;
  font-family: inherit;
  border: 1px solid var(--border);
  background: var(--surface);
  color: var(--text);
}
.ca-btn-secondary:hover {
  background: var(--surface-2);
}
.ca-btn-primary {
  background: var(--brand);
  color: #fff;
  border-color: var(--brand);
}
.ca-btn-primary:hover {
  background: var(--brand-hover);
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
  border-top: 1px solid var(--border);
  background: var(--surface);
}
.ca-input {
  flex: 1;
  resize: none;
  padding: 8px 10px;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: var(--surface-2);
  color: var(--text);
  font-size: 12.5px;
  line-height: 1.5;
  font-family: inherit;
  outline: none;
  transition: border-color 0.12s, box-shadow 0.12s;
}
.ca-input:focus {
  border-color: var(--brand);
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
  border-radius: 8px;
  background: var(--brand);
  color: #fff;
  border: none;
  font-size: 12.5px;
  font-weight: 500;
  cursor: pointer;
  font-family: inherit;
}
.ca-send:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
.ca-send:not(:disabled):hover {
  background: var(--brand-hover);
}
</style>
