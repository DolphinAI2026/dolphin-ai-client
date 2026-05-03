<template>
  <div
    class="vibe-chat-panel"
    :class="[isDark ? 'theme-dark' : 'theme-light', { 'is-wide': wide }]"
    v-loading="loading"
  >
    <!-- header / preview / 清空 都挪到顶部 BuilderFrame actions slot 里了，节省空间 -->

    <!-- ─── Messages timeline ──────────────────────────── -->
    <AgentConversation
      ref="conversationRef"
      :messages="agentMessages"
      :tool-grouping="true"
      :empty-title="emptyPrompt"
      empty-hint=""
      @answer-ask="(opt) => answerAsk(opt)"
    >
      <template #tool-renderer="{ tool }">
        <div class="tool-card" :class="`tool-${tool.status}`">
          <div class="tool-header" @click="toggleVibeTool(Number(tool.id))">
            <span class="tool-icon">{{ toolIcon(tool.name) }}</span>
            <span class="tool-name">{{ humanToolName(tool.name) }}</span>
            <span class="tool-summary">{{ tool.argsBrief }}</span>
            <span class="tool-status">
              <span v-if="tool.status === 'running'" class="dot dot-running" />
              <span v-else-if="tool.status === 'success'" class="dot dot-ok">✓</span>
              <span v-else class="dot dot-err">✗</span>
              <span v-if="tool.duration_ms" class="duration">{{ tool.duration_ms }}ms</span>
            </span>
          </div>
          <div v-if="vibeToolExpanded[Number(tool.id)]" class="tool-body">
            <template v-if="['write_file', 'edit_file'].includes(tool.name)">
              <div class="tool-path">📄 {{ tool.args?.path }}</div>
              <pre class="tool-code"><code>{{ writeFilePreviewArgs(tool) }}</code></pre>
            </template>
            <template v-else-if="tool.name === 'run_command'">
              <pre class="tool-cmd"><span class="cmd-prompt">$</span> {{ tool.args?.command }}</pre>
              <pre v-if="tool.result" class="tool-result">{{ tool.result }}</pre>
              <div v-else-if="tool.status === 'running'" class="tool-running-tip">命令运行中…</div>
            </template>
            <template v-else-if="tool.name === 'read_file'">
              <div class="tool-path">📄 {{ tool.args?.path }}</div>
              <pre v-if="tool.result" class="tool-result">{{ tool.result }}</pre>
            </template>
            <template v-else-if="tool.name === 'todo_write'">
              <ol class="tool-todos">
                <li v-for="t in (tool.args?.todos || [])" :key="t.id" :class="`todo-st-${t.status}`">
                  <span class="tool-todo-mark">{{ t.status === 'completed' ? '✓' : t.status === 'in_progress' ? '▸' : '○' }}</span>
                  {{ t.content }}
                </li>
              </ol>
            </template>
            <pre v-else-if="tool.result" class="tool-result">{{ tool.result }}</pre>
            <div v-else-if="tool.status === 'running'" class="tool-running-tip">执行中…</div>
          </div>
        </div>
      </template>

      <template #list-suffix>
        <div v-if="errorBanner" class="error-banner">⚠ {{ errorBanner }}</div>
      </template>
    </AgentConversation>

    <!-- ─── Input area（参考 ai-chat: input-card 单容器） ─── -->
    <footer class="input-area">
      <!-- TODO 紧贴输入卡上方 -->
      <div
        v-if="thread.todos && thread.todos.length"
        class="todo-strip"
      >
        <div class="todo-strip-head" @click="todosCollapsed = !todosCollapsed">
          <span class="todo-strip-title">
            任务清单
            <span class="todo-strip-count">{{ todoCompletedCount }} / {{ thread.todos.length }}</span>
          </span>
          <span class="todo-strip-toggle">{{ todosCollapsed ? '展开' : '收起' }}</span>
        </div>
        <ul v-if="!todosCollapsed" class="todo-strip-list">
          <li
            v-for="t in thread.todos"
            :key="t.id"
            :class="['todo-row', `todo-${t.status}`]"
          >
            <span class="todo-row-mark">
              <span v-if="t.status === 'completed'">✓</span>
              <span v-else-if="t.status === 'in_progress'" class="todo-pulse">▸</span>
              <span v-else>○</span>
            </span>
            <span class="todo-row-text">{{ t.content }}</span>
          </li>
        </ul>
      </div>

      <div class="input-card" @paste="onPaste">
        <!-- 附件预览缩略图 -->
        <div v-if="pendingAttachments.length" class="input-attaches">
          <div
            v-for="(att, i) in pendingAttachments"
            :key="i"
            class="input-chip"
            :title="att.filename"
          >
            <img v-if="att.kind === 'image'" :src="att.dataUrl" class="chip-thumb" alt="" />
            <span v-else class="chip-icon">📄</span>
            <span class="chip-name">{{ att.filename }}</span>
            <button class="chip-x" @click="pendingAttachments.splice(i, 1)">×</button>
          </div>
        </div>
        <div class="input-row">
          <button class="icon-btn" @click="fileInputRef?.click()" title="上传附件（图片可粘贴）">
            <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
              <path d="M11 5L6 10a2 2 0 0 0 2.83 2.83l5.66-5.66a3.5 3.5 0 0 0-4.95-4.95L4.05 7.74a5 5 0 1 0 7.07 7.07L13 13" stroke="currentColor" stroke-width="1.2" stroke-linecap="round"/>
            </svg>
          </button>
          <input ref="fileInputRef" type="file" hidden multiple accept="image/*,.pdf,.txt,.md,.json,.csv,.log" @change="onFilePick" />
          <VoiceInputButton v-model="input" :llm-config-id="thread.selected_llm_config_id" />
          <textarea
            v-model="input"
            class="textarea"
            :placeholder="running ? 'AI 正在工作中…' : '描述你想做什么…（图片可直接粘贴）'"
            rows="1"
            ref="textareaRef"
            @keydown.enter.exact.prevent="onSend"
            @keydown.enter.shift.exact="input += '\n'"
            @input="autosizeTextarea"
          />
          <button v-if="running" class="send-btn stop" @click="onAbort" title="中断">
            <svg width="11" height="11" viewBox="0 0 11 11" fill="currentColor"><rect x="1" y="1" width="9" height="9" rx="1"/></svg>
          </button>
          <button v-else class="send-btn" :disabled="!input.trim() && !pendingAttachments.length" @click="onSend" title="发送 (Enter)">
            <svg width="14" height="14" viewBox="0 0 14 14" fill="none"><path d="M12 2L6 8M12 2l-4 10-1.5-4.5L2 6 12 2z" stroke="currentColor" stroke-width="1.4" stroke-linejoin="round"/></svg>
          </button>
        </div>
        <div class="input-foot">
          <select
            v-model="thread.selected_llm_config_id"
            class="model-select-inline"
            @change="onModelChange"
            :title="messages.length === 0 ? '首条消息会用当前选定模型' : '切换仅影响后续对话'"
          >
            <option :value="null">默认模型</option>
            <option v-for="c in llmConfigs" :key="c.id" :value="c.id">
              {{ c.config_name }}
            </option>
          </select>
          <span v-if="running" class="hint">AI 思考中…</span>
        </div>
      </div>
    </footer>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref, watch, nextTick } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useThemeStore } from '@/stores/theme'
import AgentConversation from '@/components/common/AgentConversation.vue'
import VoiceInputButton from '@/components/common/VoiceInputButton.vue'
import type { AgentMessage, AgentToolPayload } from '@/components/common/agent-conversation/types'
import {
  vibeCodingChatApi,
  type VibeChatThread,
  type VibeChatMessage,
  type VibeChatToolCall,
  type VibeChatLLMConfig,
} from '@/api/vibeCodingChat'

const props = withDefaults(
  defineProps<{
    workspaceId: string
    /** 全宽模式 — 居中限宽提升阅读 */
    wide?: boolean
  }>(),
  { wide: false },
)

const emit = defineEmits<{
  (e: 'workspace-changed'): void
  (e: 'open-preview', link: { containerPort: number; hostPort?: number; url: string; label: string }): void
  (e: 'ports-updated', links: Array<{ containerPort: number; url: string; label: string }>): void
}>()

const themeStore = useThemeStore()
const isDark = computed(() => themeStore.isDark)

const loading = ref(false)
const running = ref(false)
const errorBanner = ref('')
const thread = ref<VibeChatThread>({
  id: 0,
  workspace_id: '',
  tenant_id: 0,
  owner_user_id: 0,
  title: '新对话',
  status: 'active',
  selected_llm_config_id: null,
  todos: [],
  created_at: null,
  updated_at: null,
})
const messages = ref<VibeChatMessage[]>([])
const toolCalls = ref<(VibeChatToolCall & { expanded?: boolean })[]>([])
const llmConfigs = ref<VibeChatLLMConfig[]>([])
const input = ref('')
const streamingAssistant = ref('')
const pendingAsk = ref<{ key: string; question: string; options: string[]; answered: boolean } | null>(null)
const todosCollapsed = ref(false)

// 待发送的附件（图片 / 文件）
type PendingAttachment = {
  kind: 'image' | 'file'
  filename: string
  mime: string
  dataUrl: string  // data:...;base64,xxx
}
const pendingAttachments = ref<PendingAttachment[]>([])
const fileInputRef = ref<HTMLInputElement | null>(null)

const MAX_ATTACH_BYTES = 8 * 1024 * 1024  // 单个附件 8MB 限制（base64 后体积更大）

function readFileAsDataURL(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const r = new FileReader()
    r.onload = () => resolve(r.result as string)
    r.onerror = () => reject(r.error)
    r.readAsDataURL(file)
  })
}

async function addFile(file: File) {
  if (file.size > MAX_ATTACH_BYTES) {
    ElMessage.warning(`${file.name} 超过 8MB 上限，已忽略`)
    return
  }
  const isImage = file.type.startsWith('image/')
  try {
    const dataUrl = await readFileAsDataURL(file)
    pendingAttachments.value.push({
      kind: isImage ? 'image' : 'file',
      filename: file.name || (isImage ? `pasted-${Date.now()}.png` : 'attachment'),
      mime: file.type || 'application/octet-stream',
      dataUrl,
    })
  } catch (err) {
    ElMessage.error(`读取 ${file.name} 失败`)
  }
}

async function onFilePick(e: Event) {
  const t = e.target as HTMLInputElement
  if (!t.files) return
  for (const f of Array.from(t.files)) await addFile(f)
  t.value = ''  // 允许再次选同一个文件
}

async function onPaste(e: ClipboardEvent) {
  if (!e.clipboardData) return
  const items = e.clipboardData.items
  for (const item of items) {
    if (item.kind === 'file') {
      const f = item.getAsFile()
      if (f) {
        e.preventDefault()
        await addFile(f)
      }
    }
  }
}

// docker 沙箱端口映射（容器内端口 → host 端口） — agent 起 dev server 后通过 SSE 推过来
const sandboxPorts = ref<Record<number, number>>({})

const PORT_LABELS: Record<number, string> = {
  6173: '前端 (Vite)',
  6300: 'Next.js / 后端',
  6400: '后端服务',
  6500: '附加端口',
}

// 子域名前缀基底：默认空（dev 模式用 localhost），通过 VITE_SANDBOX_PREVIEW_BASE
// 配成 ".dfy.definesys.cn" 时拼成 https://p{hostPort}.dfy.definesys.cn/，
// 让 nginx 用 server_name 正则路由到对应 host 端口（podman 自动分配的）。
// 见 deploy/nginx/vibe-preview.conf.example
const SANDBOX_PREVIEW_BASE: string = import.meta.env.VITE_SANDBOX_PREVIEW_BASE || ''

function buildPreviewUrl(hostPort: number): string {
  if (SANDBOX_PREVIEW_BASE) {
    // 线上：通过 nginx 子域名反代（避免 mixed content + 解决远端不可达）
    return `https://p${hostPort}${SANDBOX_PREVIEW_BASE}/`
  }
  // 本地 dev：浏览器跟容器在同机，localhost 能直接通
  return `http://localhost:${hostPort}`
}

const previewLinks = computed(() => {
  return Object.entries(sandboxPorts.value)
    .map(([containerPort, hostPort]) => ({
      containerPort: Number(containerPort),
      url: buildPreviewUrl(Number(hostPort)),
      label: `${PORT_LABELS[Number(containerPort)] || `端口 ${containerPort}`} → :${hostPort}`,
    }))
    .sort((a, b) => a.containerPort - b.containerPort)
})

const todoCompletedCount = computed(() =>
  (thread.value.todos || []).filter((t) => t.status === 'completed').length,
)
const emptyPrompt = computed(() => {
  const t = (thread.value.title || '').trim()
  return t && t !== '新对话' ? `我们该在 ${t} 中做什么？` : '今天想搭点什么？'
})

const conversationRef = ref<{ scrollToBottom: (force?: boolean) => Promise<void> } | null>(null)
const textareaRef = ref<HTMLTextAreaElement | null>(null)
let abortCtl: AbortController | null = null

function autosizeTextarea() {
  const el = textareaRef.value
  if (!el) return
  el.style.height = 'auto'
  el.style.height = Math.min(el.scrollHeight, 160) + 'px'
}

watch(input, () => {
  nextTick(autosizeTextarea)
})

type TimelineItem =
  | { kind: 'user'; key: string; content: string; attachments?: Array<{ kind: string; filename: string }> }
  | { kind: 'assistant'; key: string; content: string }
  | { kind: 'tool'; key: string; tool: VibeChatToolCall & { expanded?: boolean } }
  | { kind: 'ask'; key: string; question: string; options: string[] }

function tsOf(s: string | null | undefined): number {
  if (!s) return 0
  const t = Date.parse(s)
  return Number.isNaN(t) ? 0 : t
}

const timeline = computed<TimelineItem[]>(() => {
  // 把 messages + tool_calls 按时间戳交错排（mirror AIChatPage 做法）—
  // 旧实现是先列完所有 msg 再追加未关联 tool，SSE 实时跑时所有 tool 都堆在末尾，对话顺序错乱。
  type Sortable =
    | { ts: number; seq: number; kind: 'msg'; m: VibeChatMessage }
    | { ts: number; seq: number; kind: 'tc'; t: VibeChatToolCall & { expanded?: boolean } }
  const sortable: Sortable[] = []
  for (const m of messages.value) {
    sortable.push({ ts: tsOf(m.created_at), seq: m.id, kind: 'msg', m })
  }
  for (const t of toolCalls.value) {
    sortable.push({ ts: tsOf(t.started_at), seq: t.id, kind: 'tc', t })
  }
  sortable.sort((a, b) => {
    if (a.ts !== b.ts) return a.ts - b.ts
    // 同 ts 时 msg 优先于 tool（确保 user 消息在它触发的工具之前），再按 seq(id)
    if (a.kind !== b.kind) return a.kind === 'msg' ? -1 : 1
    return a.seq - b.seq
  })

  const items: TimelineItem[] = []
  for (const it of sortable) {
    if (it.kind === 'msg') {
      const m = it.m
      const isToolUsePlaceholder =
        m.role === 'assistant' && !(m.content || '').trim() && m.extra_meta?.tool_calls
      if (m.role === 'user') {
        const att = (m.extra_meta?.attachments as any[]) || []
        items.push({
          kind: 'user',
          key: `m${m.id}`,
          content: m.content,
          attachments: att.length ? att : undefined,
        })
      } else if (m.role === 'assistant') {
        if (!isToolUsePlaceholder && m.content) {
          items.push({ kind: 'assistant', key: `m${m.id}`, content: m.content })
        }
      }
    } else {
      items.push({ kind: 'tool', key: `t${it.t.id}`, tool: it.t })
    }
  }

  if (pendingAsk.value && !pendingAsk.value.answered) {
    items.push({
      kind: 'ask',
      key: pendingAsk.value.key,
      question: pendingAsk.value.question,
      options: pendingAsk.value.options,
    })
  }
  return items
})

// AgentConversation 公共契约映射
const vibeToolExpanded = ref<Record<number, boolean>>({})
function toggleVibeTool(id: number) {
  vibeToolExpanded.value[id] = !vibeToolExpanded.value[id]
}
function writeFilePreviewArgs(tool: AgentToolPayload): string {
  const a = tool.args || {}
  const content = tool.name === 'edit_file' ? (a.new_string || '') : (a.content || '')
  if (!content) return '（暂无内容）'
  const lines = content.split('\n')
  if (lines.length <= 40) return content
  return lines.slice(0, 40).join('\n') + `\n\n... 还有 ${lines.length - 40} 行`
}

const agentMessages = computed<AgentMessage[]>(() => {
  const out: AgentMessage[] = []
  const mapStatus = (s: string): 'pending' | 'running' | 'success' | 'error' =>
    (s === 'aborted' ? 'error' : (s as any)) || 'pending'
  for (const item of timeline.value) {
    if (item.kind === 'user') {
      out.push({
        id: item.key,
        kind: 'user',
        content: item.content,
        attachments: item.attachments?.length
          ? item.attachments.map((a, i) => ({
              id: i,
              kind: a.kind === 'image' ? 'image' : 'file',
              filename: a.filename,
            }))
          : undefined,
      })
    } else if (item.kind === 'assistant') {
      out.push({ id: item.key, kind: 'assistant', content: item.content })
    } else if (item.kind === 'tool') {
      out.push({
        id: item.key,
        kind: 'tool',
        tool: {
          id: item.tool.id,
          name: item.tool.tool_name,
          args: item.tool.args_json,
          argsBrief: summarizeArgs(item.tool),
          result: item.tool.result_text || undefined,
          status: mapStatus(item.tool.status),
          duration_ms: item.tool.duration_ms ?? undefined,
        },
      })
    } else if (item.kind === 'ask') {
      out.push({
        id: item.key,
        kind: 'ask',
        ask: { question: item.question, options: item.options },
      })
    }
  }
  if (streamingAssistant.value) {
    out.push({ id: 'streaming', kind: 'streaming', content: streamingAssistant.value, streaming: true })
  }
  return out
})

function toolIcon(name: string): string {
  const map: Record<string, string> = {
    read_file: '📖',
    write_file: '✏️',
    edit_file: '✂️',
    glob: '🗂',
    grep: '🔎',
    run_command: '⚡',
    todo_write: '📋',
    http_check: '🌐',
    ask_clarifying_question: '❓',
  }
  return map[name] || '🔧'
}

function humanToolName(name: string): string {
  const map: Record<string, string> = {
    read_file: '读取文件',
    write_file: '写入文件',
    edit_file: '编辑文件',
    glob: '搜索文件',
    grep: '搜索内容',
    run_command: '运行命令',
    todo_write: '更新任务清单',
    http_check: '健康检查',
    ask_clarifying_question: '澄清提问',
  }
  return map[name] || name
}

function summarizeArgs(t: VibeChatToolCall): string {
  const a = t.args_json || {}
  switch (t.tool_name) {
    case 'read_file':
      return a.path || ''
    case 'write_file':
      return `${a.path || ''} (${(a.content || '').length} 字符)`
    case 'edit_file':
      return a.path || ''
    case 'glob':
      return a.pattern || ''
    case 'grep':
      return a.pattern || ''
    case 'run_command':
      return a.description || (a.command || '').slice(0, 80)
    case 'todo_write':
      return `${(a.todos || []).length} 条`
    case 'http_check':
      return a.url || ''
    case 'ask_clarifying_question':
      return (a.question || '').slice(0, 60)
    default:
      return JSON.stringify(a).slice(0, 80)
  }
}

async function loadThread() {
  loading.value = true
  try {
    const detail = await vibeCodingChatApi.getThread(props.workspaceId)
    thread.value = detail.thread
    messages.value = detail.messages
    toolCalls.value = detail.tool_calls.map((t) => ({ ...t, expanded: false }))
  } catch (err: any) {
    errorBanner.value = `加载失败：${err?.message || err}`
  } finally {
    loading.value = false
    await scrollToBottom()
  }
}

async function loadLLMConfigs() {
  try {
    const r = await vibeCodingChatApi.listLLMConfigs(props.workspaceId)
    llmConfigs.value = r.configs
  } catch {
    /* no fatal */
  }
}

async function loadSandboxPorts() {
  try {
    const r = await vibeCodingChatApi.getSandboxPorts(props.workspaceId)
    if (r.running && r.ports) {
      sandboxPorts.value = r.ports
    } else {
      sandboxPorts.value = {}
    }
  } catch {
    /* docker 不可用或没起容器 — 静默 */
  }
  emit('ports-updated', previewLinks.value)
}

// 端口变化时同步给父级（preview panel 用）
watch(previewLinks, (links) => {
  emit('ports-updated', links)
})

async function onTitleBlur() {
  try {
    await vibeCodingChatApi.updateThread(props.workspaceId, { title: thread.value.title })
  } catch (err: any) {
    ElMessage.error(`保存标题失败：${err?.message || err}`)
  }
}

async function onModelChange() {
  try {
    await vibeCodingChatApi.updateThread(props.workspaceId, {
      selected_llm_config_id: thread.value.selected_llm_config_id ?? null,
    })
  } catch (err: any) {
    ElMessage.error(`切换模型失败：${err?.message || err}`)
  }
}

async function onClearThread() {
  try {
    await ElMessageBox.confirm('清空当前对话记录（不影响 workspace 文件）？', '确认', { type: 'warning' })
  } catch {
    return
  }
  try {
    await vibeCodingChatApi.clearThread(props.workspaceId)
    messages.value = []
    toolCalls.value = []
    thread.value.todos = []
    streamingAssistant.value = ''
    pendingAsk.value = null
    errorBanner.value = ''
  } catch (err: any) {
    ElMessage.error(`清空失败：${err?.message || err}`)
  }
}

async function scrollToBottom() {
  await nextTick()
  await conversationRef.value?.scrollToBottom(true)
}

async function answerAsk(option: string) {
  if (!pendingAsk.value) return
  pendingAsk.value.answered = true
  input.value = option
  await onSend()
}

async function onSend() {
  const text = input.value.trim()
  const hasAttach = pendingAttachments.value.length > 0
  if ((!text && !hasAttach) || running.value) return
  // 复制附件再清空 — 防止用户在网络飞行中再传一份
  const attachments = pendingAttachments.value.map((a) => ({
    kind: a.kind,
    filename: a.filename,
    mime: a.mime,
    data_url: a.dataUrl,
  }))
  pendingAttachments.value = []
  input.value = ''
  await nextTick(autosizeTextarea)
  pendingAsk.value = null
  errorBanner.value = ''
  streamingAssistant.value = ''
  running.value = true
  abortCtl = new AbortController()

  const tempUserId = -Date.now()
  messages.value.push({
    id: tempUserId,
    thread_id: thread.value.id,
    role: 'user',
    content: text,
    user_id: null,
    extra_meta: attachments.length ? { attachments: attachments.map((a) => ({ kind: a.kind, filename: a.filename })) } : {},
    created_at: new Date().toISOString(),
  })
  await scrollToBottom()

  let workspaceTouched = false

  try {
    await vibeCodingChatApi.sendMessage(props.workspaceId, { message: text, attachments: attachments.length ? attachments : undefined }, {
      signal: abortCtl.signal,
      onEvent: async (name, data) => {
        switch (name) {
          case 'user_message': {
            const idx = messages.value.findIndex((m) => m.id === tempUserId)
            if (idx >= 0) messages.value.splice(idx, 1, data)
            else messages.value.push(data)
            break
          }
          case 'thinking':
            console.debug('[vibe-chat] thinking:', data?.text)
            break
          case 'assistant_delta':
            streamingAssistant.value += data.text || ''
            break
          case 'assistant_thinking_lock':
            if (streamingAssistant.value) {
              messages.value.push({
                id: -Math.floor(Math.random() * 1e9) - 1,
                thread_id: thread.value.id,
                role: 'assistant',
                content: streamingAssistant.value,
                user_id: null,
                extra_meta: {},
                created_at: new Date().toISOString(),
              })
              streamingAssistant.value = ''
            }
            break
          case 'tool_call_start':
            toolCalls.value.push({
              id: data.id,
              thread_id: thread.value.id,
              message_id: data.message_id ?? null,
              tool_name: data.tool_name,
              args_json: data.args || {},
              result_text: null,
              status: 'running',
              error_message: null,
              duration_ms: null,
              started_at: data.started_at,
              ended_at: null,
              expanded: true,  // 默认展开 — 让用户实时看到 AI 在做什么
            })
            break
          case 'tool_call_end': {
            const tc = toolCalls.value.find((t) => t.id === data.id)
            if (tc) {
              tc.status = data.status
              tc.result_text = data.result_text
              tc.duration_ms = data.duration_ms
              tc.ended_at = new Date().toISOString()
            }
            if (data.status === 'success' && ['write_file', 'edit_file', 'run_command'].includes(data.tool_name)) {
              workspaceTouched = true
            }
            break
          }
          case 'todos_updated':
            thread.value.todos = data.todos || []
            break
          case 'sandbox_ports_updated':
            sandboxPorts.value = data.ports || {}
            break
          case 'ask_user':
            pendingAsk.value = {
              key: `ask-${data.tool_call_id}`,
              question: data.question,
              options: data.options || [],
              answered: false,
            }
            break
          case 'assistant_message':
            messages.value.push(data)
            streamingAssistant.value = ''
            break
          case 'aborted':
            errorBanner.value = '已中断'
            break
          case 'error':
            errorBanner.value = data.error || '未知错误'
            break
          case 'done':
            break
        }
        await scrollToBottom()
      },
    })
  } catch (err: any) {
    if (err?.name !== 'AbortError') {
      errorBanner.value = `请求失败：${err?.message || err}`
    }
  } finally {
    running.value = false
    abortCtl = null
    streamingAssistant.value = ''
    if (workspaceTouched) emit('workspace-changed')
  }
}

async function onAbort() {
  if (abortCtl) abortCtl.abort()
  try {
    await vibeCodingChatApi.abort(props.workspaceId)
  } catch {
    /* ignore */
  }
}

watch(
  () => props.workspaceId,
  async () => {
    if (props.workspaceId) {
      await Promise.all([loadThread(), loadLLMConfigs(), loadSandboxPorts()])
    }
  },
)

onMounted(async () => {
  if (props.workspaceId) {
    await Promise.all([loadThread(), loadLLMConfigs(), loadSandboxPorts()])
  }
  await nextTick(autosizeTextarea)
  // Landing 自动建工作区时把 prompt 暂存在 sessionStorage，这里取出自动 send 首条
  await maybeSendPendingPrompt()
})

async function maybeSendPendingPrompt() {
  if (!props.workspaceId) return
  const key = `vibe_pending_prompt_${props.workspaceId}`
  const pending = sessionStorage.getItem(key)
  if (!pending) return
  sessionStorage.removeItem(key)
  // 已有历史消息（thread 里有过对话）就不重发，避免误触
  if (messages.value.length > 0) return
  input.value = pending
  await nextTick()
  await onSend()
}

// 暴露给父组件 — 让 oc-ide-toolbar 显示 thread.title 并触发清空
defineExpose({
  thread,
  clearThread: onClearThread,
  running,
})
</script>

<style scoped>
/* ─── 主题（参考 ai-chat 命名 + 调色板） ─── */
.vibe-chat-panel {
  --vc-brand: #5a78ff;

  display: flex;
  flex-direction: column;
  height: 100%;
  background: var(--vc-bg);
  color: var(--vc-text);
  font-family: -apple-system, BlinkMacSystemFont, "PingFang SC", "Microsoft YaHei", sans-serif;
  font-size: 14px;
  line-height: 1.6;
}

.vibe-chat-panel.theme-light {
  --vc-bg: #f7f8fa;
  --vc-panel: #ffffff;
  --vc-input: #f1f3f6;
  --vc-btn: #ffffff;
  --vc-text: #0f172a;
  --vc-text-mute: #475569;
  --vc-text-faint: #64748b;
  --vc-border: rgba(15, 23, 42, 0.10);
  --vc-border-faint: rgba(15, 23, 42, 0.05);
  --vc-border-strong: rgba(15, 23, 42, 0.18);
  --vc-warn: #b45309;
  --vc-warn-soft: rgba(245, 158, 11, 0.10);
  --vc-success: #15803d;
  --vc-danger: #dc2626;
  --vc-danger-soft: rgba(220, 38, 38, 0.08);
}

.vibe-chat-panel.theme-dark {
  --vc-bg: #0a0a0c;
  --vc-panel: #111114;
  --vc-input: #16171b;
  --vc-btn: #1d1e23;
  --vc-text: #e8eaed;
  --vc-text-mute: #a1a4ad;
  --vc-text-faint: #6c707a;
  --vc-border: rgba(255, 255, 255, 0.06);
  --vc-border-faint: rgba(255, 255, 255, 0.04);
  --vc-border-strong: rgba(255, 255, 255, 0.10);
  --vc-warn: #fbbf24;
  --vc-warn-soft: rgba(251, 191, 36, 0.10);
  --vc-success: #4ade80;
  --vc-danger: #f87171;
  --vc-danger-soft: rgba(248, 113, 113, 0.10);
}

/* ─── Header ─── */
.panel-header {
  flex: 0 0 auto;
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 16px;
  border-bottom: 1px solid var(--vc-border);
  background: var(--vc-panel);
}
.title-row {
  display: flex;
  align-items: center;
  gap: 8px;
  flex: 1 1 auto;
  min-width: 0;
}
.brand {
  color: var(--vc-brand);
  font-size: 15px;
  flex: 0 0 auto;
}
.title-input {
  flex: 1 1 auto;
  border: 1px solid transparent;
  outline: none;
  font-size: 13.5px;
  font-weight: 500;
  background: transparent;
  color: var(--vc-text);
  padding: 4px 6px;
  border-radius: 6px;
  min-width: 0;
}
.title-input:hover {
  border-color: var(--vc-border);
}
.title-input:focus {
  border-color: var(--vc-brand);
  background: var(--vc-bg);
}
.header-actions {
  display: flex;
  align-items: center;
  gap: 6px;
  flex: 0 0 auto;
}
.header-btn {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  height: 28px;
  padding: 0 10px;
  border: 1px solid var(--vc-border-strong);
  border-radius: 6px;
  background: var(--vc-btn);
  color: var(--vc-text-mute);
  font-size: 12.5px;
  cursor: pointer;
}
.header-btn:hover:not(:disabled) {
  background: var(--vc-input);
  color: var(--vc-text);
}
.header-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

/* ─── Preview links strip（agent 起 dev server 后顶部横条） ─── */
.preview-strip {
  flex: 0 0 auto;
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
  padding: 8px 16px;
  background: color-mix(in srgb, var(--vc-brand) 8%, var(--vc-bg));
  border-bottom: 1px solid var(--vc-border);
  font-size: 12.5px;
}
.preview-label {
  color: var(--vc-text-mute);
  font-weight: 500;
}
.preview-open-btn {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 5px 14px;
  background: var(--vc-brand);
  color: #ffffff;
  border: none;
  border-radius: 16px;
  font-size: 12.5px;
  font-weight: 500;
  cursor: pointer;
  transition: filter 0.12s, transform 0.12s;
}
.preview-open-btn:hover {
  filter: brightness(1.1);
  transform: translateY(-1px);
}
.preview-icon {
  font-size: 13px;
}
.preview-count {
  background: rgba(255, 255, 255, 0.22);
  padding: 1px 8px;
  border-radius: 10px;
  font-size: 11px;
}

/* ─── Messages ─── */
.messages {
  flex: 1 1 auto;
  overflow-y: auto;
  padding: 18px 16px;
  scrollbar-width: thin;
  scrollbar-color: var(--vc-border-strong) transparent;
}
.messages::-webkit-scrollbar { width: 8px; }
.messages::-webkit-scrollbar-thumb {
  background: var(--vc-border-strong);
  border-radius: 4px;
}

.msg {
  margin: 0 auto 12px;
  display: flex;
}
.msg-user {
  justify-content: flex-end;
}
.msg-user .msg-bubble {
  background: var(--vc-input);
  border: 1px solid var(--vc-border);
  border-radius: 14px 14px 4px 14px;
  padding: 8px 14px;
  font-size: 14px;
  color: var(--vc-text);
  white-space: pre-wrap;
  word-break: break-word;
  max-width: 80%;
}
.msg-assistant {
  justify-content: flex-start;
}
.msg-assistant .msg-bubble {
  background: transparent;
  border: none;
  padding: 0;
  font-size: 14px;
  line-height: 1.7;
  color: var(--vc-text);
  width: 100%;
}
.msg-bubble :deep(p) { margin: 0 0 6px; }
.msg-bubble :deep(p:last-child) { margin-bottom: 0; }
.msg-bubble :deep(pre) {
  background: var(--vc-input);
  padding: 8px 10px;
  border-radius: 6px;
  overflow-x: auto;
  font-size: 12.5px;
  border: 1px solid var(--vc-border);
}
.msg-bubble :deep(code) {
  background: var(--vc-input);
  padding: 1px 5px;
  border-radius: 3px;
  font-size: 12.5px;
  font-family: ui-monospace, Menlo, monospace;
}
.msg-bubble :deep(a) {
  color: var(--vc-brand);
  text-decoration: none;
}
.msg-bubble :deep(a:hover) { text-decoration: underline; }
.msg-bubble :deep(ul), .msg-bubble :deep(ol) {
  margin: 4px 0;
  padding-left: 22px;
}
.msg-bubble :deep(table) {
  border-collapse: collapse;
  margin: 6px 0;
}
.msg-bubble :deep(th), .msg-bubble :deep(td) {
  border: 1px solid var(--vc-border);
  padding: 4px 8px;
  font-size: 13px;
}
.msg-bubble :deep(th) {
  background: var(--vc-input);
}

/* ─── Tool card ─── */
.tool-card {
  margin: 6px auto 10px;
  border: 1px solid var(--vc-border);
  border-radius: 8px;
  background: var(--vc-panel);
  font-size: 12.5px;
  overflow: hidden;
  width: 100%;
}
.tool-card.tool-error {
  border-color: var(--vc-danger);
  background: var(--vc-danger-soft);
}
.tool-header {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 12px;
  cursor: pointer;
  user-select: none;
}
.tool-header:hover {
  background: var(--vc-input);
}
.tool-icon { flex: 0 0 auto; font-size: 13px; }
.tool-name {
  flex: 0 0 auto;
  font-family: ui-monospace, Menlo, monospace;
  color: var(--vc-brand);
  font-weight: 500;
}
.tool-summary {
  flex: 1 1 auto;
  color: var(--vc-text-mute);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 12px;
}
.tool-status {
  flex: 0 0 auto;
  display: flex;
  align-items: center;
  gap: 6px;
}
.duration {
  color: var(--vc-text-faint);
  font-size: 11px;
  font-variant-numeric: tabular-nums;
}
.dot {
  display: inline-block;
  width: 12px;
  height: 12px;
  text-align: center;
  line-height: 12px;
  font-size: 11px;
}
.dot-running {
  border-radius: 50%;
  background: var(--vc-brand);
  animation: pulse 1.2s ease-in-out infinite;
}
.dot-ok { color: var(--vc-success); }
.dot-err { color: var(--vc-danger); }
@keyframes pulse {
  0%, 100% { opacity: 0.4; transform: scale(0.85); }
  50% { opacity: 1; transform: scale(1); }
}
.tool-body {
  border-top: 1px solid var(--vc-border);
}
.tool-path {
  padding: 6px 12px 4px;
  font-family: ui-monospace, Menlo, monospace;
  font-size: 12px;
  color: var(--vc-text-mute);
  background: var(--vc-input);
}
.tool-code {
  margin: 0;
  padding: 8px 12px;
  background: var(--vc-input);
  font-family: ui-monospace, Menlo, monospace;
  font-size: 12px;
  color: var(--vc-text);
  white-space: pre;
  overflow-x: auto;
  max-height: 360px;
  overflow-y: auto;
  border-top: 1px dashed var(--vc-border);
  line-height: 1.5;
}
.tool-cmd {
  margin: 0;
  padding: 8px 12px;
  background: #0d1117;
  color: #d2a8ff;
  font-family: ui-monospace, Menlo, monospace;
  font-size: 12.5px;
  white-space: pre-wrap;
  word-break: break-all;
}
.cmd-prompt {
  color: #56d364;
  margin-right: 6px;
  font-weight: 600;
}
.tool-running-tip {
  padding: 8px 12px;
  font-size: 12px;
  color: var(--vc-text-faint);
  font-style: italic;
}
.tool-todos {
  margin: 0;
  padding: 6px 12px 8px 28px;
  list-style: none;
  background: var(--vc-input);
}
.tool-todos li {
  display: flex;
  gap: 8px;
  padding: 2px 0;
  font-size: 12.5px;
  color: var(--vc-text);
}
.tool-todos li.todo-st-completed {
  text-decoration: line-through;
  color: var(--vc-text-faint);
}
.tool-todo-mark {
  flex: 0 0 14px;
  color: var(--vc-text-faint);
  font-family: ui-monospace, Menlo, monospace;
}
.todo-st-completed .tool-todo-mark { color: var(--vc-success); }
.todo-st-in_progress .tool-todo-mark { color: var(--vc-brand); }
.tool-result {
  margin: 0;
  padding: 8px 12px;
  background: var(--vc-input);
  font-family: ui-monospace, Menlo, monospace;
  font-size: 11.5px;
  color: var(--vc-text-mute);
  white-space: pre-wrap;
  word-break: break-word;
  max-height: 240px;
  overflow-y: auto;
}
.tool-cmd + .tool-result {
  border-top: 1px dashed var(--vc-border);
}

/* ─── Ask card ─── */
.ask-card {
  margin: 8px auto;
  padding: 10px 14px;
  border: 1px solid var(--vc-warn);
  background: var(--vc-warn-soft);
  border-radius: 8px;
  width: 100%;
}
.ask-q {
  font-size: 14px;
  color: var(--vc-text);
  margin-bottom: 4px;
}
.ask-q :deep(p) { margin: 0; }
.ask-options {
  margin-top: 10px;
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.ask-option-btn {
  width: 100%;
  text-align: left;
  background: var(--vc-btn);
  border: 1px solid var(--vc-border-strong);
  color: var(--vc-text);
  padding: 8px 12px;
  border-radius: 6px;
  font-size: 13px;
  line-height: 1.45;
  cursor: pointer;
  transition: border-color 0.12s, background 0.12s;
  font-family: inherit;
}
.ask-option-btn:hover:not(:disabled) {
  border-color: var(--vc-warn);
  background: var(--vc-input);
}
.ask-option-btn:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.cursor-blink {
  display: inline-block;
  margin-left: 2px;
  color: var(--vc-brand);
  animation: blink 1s steps(2, start) infinite;
}
@keyframes blink {
  to { visibility: hidden; }
}

.error-banner {
  margin: 8px auto;
  padding: 8px 12px;
  background: var(--vc-danger-soft);
  color: var(--vc-danger);
  border: 1px solid var(--vc-danger);
  border-radius: 6px;
  font-size: 13px;
}

/* ─── Empty state ─── */
.empty-state {
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 220px;
  padding: 60px 20px;
}
.empty-title {
  font-size: 22px;
  font-weight: 500;
  color: var(--vc-text-mute);
  text-align: center;
}

/* ─── TODO strip（紧贴 input-card 上方） ─── */
.todo-strip {
  margin: 0 auto 8px;
  background: var(--vc-panel);
  border: 1px solid var(--vc-border);
  border-radius: 10px;
  overflow: hidden;
}
.todo-strip-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 8px 12px;
  cursor: pointer;
  user-select: none;
  font-size: 12px;
  color: var(--vc-text-mute);
}
.todo-strip-head:hover {
  background: var(--vc-input);
}
.todo-strip-title {
  display: flex;
  align-items: center;
  gap: 8px;
  font-weight: 500;
  color: var(--vc-text);
}
.todo-strip-count {
  font-size: 11px;
  color: var(--vc-text-faint);
  font-variant-numeric: tabular-nums;
}
.todo-strip-toggle {
  font-size: 11px;
  color: var(--vc-text-faint);
}
.todo-strip-list {
  margin: 0;
  padding: 4px 12px 10px;
  list-style: none;
  border-top: 1px solid var(--vc-border);
}
.todo-row {
  display: flex;
  gap: 8px;
  align-items: baseline;
  padding: 4px 0;
  font-size: 13px;
  color: var(--vc-text);
}
.todo-row-mark {
  flex: 0 0 14px;
  color: var(--vc-text-faint);
  font-family: ui-monospace, Menlo, monospace;
  font-size: 12px;
}
.todo-row-text {
  flex: 1 1 auto;
  line-height: 1.5;
}
.todo-completed .todo-row-mark { color: var(--vc-success); }
.todo-completed .todo-row-text {
  text-decoration: line-through;
  color: var(--vc-text-faint);
}
.todo-in_progress .todo-row-mark { color: var(--vc-brand); }
.todo-in_progress .todo-row-text {
  color: var(--vc-text);
  font-weight: 500;
}
.todo-pulse {
  display: inline-block;
  animation: todoPulse 1.4s ease-in-out infinite;
}
@keyframes todoPulse {
  0%, 100% { opacity: 0.5; }
  50% { opacity: 1; }
}

/* ─── Input area（参考 ai-chat: input-card 单容器） ─── */
.input-area {
  flex: 0 0 auto;
  border-top: 1px solid var(--vc-border);
  padding: 14px 16px 18px;
  background: var(--vc-bg);
}
.input-card {
  background: var(--vc-input);
  border: 1px solid var(--vc-border-strong);
  border-radius: 14px;
  padding: 8px;
  transition: border-color 0.15s;
}
.input-card:focus-within {
  border-color: color-mix(in srgb, var(--vc-brand) 50%, transparent);
}
.input-attaches {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  padding: 6px 6px 0;
}
.input-chip {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 3px 8px 3px 6px;
  background: var(--vc-bg);
  border: 1px solid var(--vc-border);
  border-radius: 6px;
  font-size: 12px;
  max-width: 240px;
}
.chip-thumb {
  width: 22px;
  height: 22px;
  object-fit: cover;
  border-radius: 4px;
  border: 1px solid var(--vc-border);
}
.chip-icon { font-size: 14px; }
.chip-name {
  flex: 1 1 auto;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--vc-text-mute);
  font-family: ui-monospace, Menlo, monospace;
}
.chip-x {
  background: transparent;
  border: none;
  color: var(--vc-text-faint);
  cursor: pointer;
  padding: 0 2px;
  font-size: 14px;
  line-height: 1;
}
.chip-x:hover { color: var(--vc-danger); }

.input-row {
  display: flex;
  align-items: flex-end;
  gap: 4px;
  padding: 4px 4px 4px 4px;
}
.icon-btn {
  flex: 0 0 auto;
  width: 30px;
  height: 30px;
  display: grid;
  place-items: center;
  border: none;
  background: transparent;
  color: var(--vc-text-mute);
  border-radius: 6px;
  cursor: pointer;
  transition: all 0.12s;
}
.icon-btn:hover {
  background: var(--vc-bg);
  color: var(--vc-text);
}

.msg-attaches {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  margin-bottom: 6px;
}
.msg-attach-chip {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 1px 8px;
  background: rgba(15, 23, 42, 0.06);
  border-radius: 4px;
  font-size: 11px;
  color: var(--vc-text-mute);
}
:global(html[data-theme="dark"]) .msg-attach-chip {
  background: rgba(255, 255, 255, 0.06);
}
.textarea {
  flex: 1;
  background: transparent;
  border: none;
  color: var(--vc-text);
  font-family: inherit;
  font-size: 14px;
  line-height: 1.5;
  resize: none;
  outline: none;
  min-height: 22px;
  max-height: 160px;
  padding: 6px 8px;
}
.textarea::placeholder { color: var(--vc-text-faint); }
.send-btn {
  width: 32px;
  height: 32px;
  border-radius: 8px;
  background: var(--vc-brand);
  border: none;
  color: #ffffff;
  cursor: pointer;
  display: grid;
  place-items: center;
  flex-shrink: 0;
  transition: all 0.15s;
}
.send-btn:hover:not(:disabled) {
  transform: translateY(-1px);
  filter: brightness(1.1);
}
.send-btn:disabled {
  opacity: 0.3;
  cursor: not-allowed;
}
.send-btn.stop {
  background: linear-gradient(135deg, #ef4444 0%, #dc2626 100%);
}
.input-foot {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 8px 4px;
  font-size: 12px;
}
.model-select-inline {
  background: transparent;
  border: 1px solid var(--vc-border);
  border-radius: 6px;
  color: var(--vc-text-mute);
  padding: 3px 6px;
  font-size: 12px;
  cursor: pointer;
  outline: none;
  font-family: inherit;
}
.model-select-inline:hover {
  border-color: var(--vc-border-strong);
}
.model-select-inline option {
  background: var(--vc-panel);
  color: var(--vc-text);
}
.hint {
  color: var(--vc-text-faint);
  font-size: 11.5px;
}

/* ─── 全宽模式：messages / input-card / todo / tool / ask 居中限宽 ─── */
.vibe-chat-panel.is-wide .messages {
  padding: 28px 24px;
}
.vibe-chat-panel.is-wide .messages > *,
.vibe-chat-panel.is-wide .messages .empty-state {
  max-width: 820px;
  width: 100%;
  margin-left: auto;
  margin-right: auto;
}
.vibe-chat-panel.is-wide .input-area {
  padding: 14px 24px 20px;
}
.vibe-chat-panel.is-wide .todo-strip,
.vibe-chat-panel.is-wide .input-card {
  max-width: 820px;
  margin-left: auto;
  margin-right: auto;
}
</style>
