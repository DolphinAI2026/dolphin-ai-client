<template>
  <div class="app-chat-panel" v-if="visible">
    <header class="app-chat-header">
      <div class="app-chat-title">
        <span class="title-icon"><AppIcon name="message" :size="16" /></span>
        <span class="title-text">用 AI 调整应用</span>
        <span v-if="boundAppName" class="title-app">— {{ boundAppName }}</span>
      </div>
      <div class="app-chat-actions">
        <button
          class="apply-btn"
          :disabled="applying || !currentSession"
          @click="applyToBuilder"
          title="把当前对话产出的最新 md 应用到 Builder（生成新版变更计划）"
        ><template v-if="applying">应用中...</template><template v-else><AppIcon name="download" :size="14" /> 应用最新 md 到 Builder</template></button>
        <button class="close-btn" @click="$emit('close')" title="关闭"><AppIcon name="x" :size="14" /></button>
      </div>
    </header>

    <div class="app-chat-hint">
      在下面对话里跟 AI 说要怎么改设计文档（AI 会用 write_artifact 写新版 md）。改完点上方按钮一键应用到 Builder。
    </div>

    <div class="app-chat-body" v-loading="loading">
      <AgentConversation
        v-if="currentSession"
        :messages="agentMessages"
        :typing="isSending"
        :tool-grouping="true"
      />
      <div v-else-if="!loading" class="app-chat-empty">
        会话初始化失败。请关闭面板重试。
      </div>
    </div>

    <div class="app-chat-input" v-if="currentSession">
      <UnifiedChatComposer
        v-model="inputText"
        :attachments="composerAttachments"
        :disabled="isSending"
        :sending="isSending"
        :send-disabled="!canSend"
        :native-file-picker="false"
        placeholder="输入需求，粘贴图片或点附件..."
        @send="onSend"
        @stop="onAbort"
        @paste-images="onPasteImageFiles"
        @remove-attachment="removePastedImage(Number($event.id))"
      />
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onUnmounted, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import AgentConversation from '@/components/common/AgentConversation.vue'
import AppIcon from '@/components/common/AppIcon.vue'
import { aiChatApi, type AIChatMessage, type AIChatToolCall } from '@/api/aiChat'
import { applicationApi } from '@/api/application'
import UnifiedChatComposer from '@/components/common/UnifiedChatComposer.vue'
import type { UnifiedChatAttachment } from '@/components/common/chatComposer'

const props = defineProps<{
  visible: boolean
  appId: number | null
  appName?: string
}>()

const emit = defineEmits<{
  close: []
  applied: [{ filename: string; content: string }]  // 用户点应用，主页接管走 upload-doc-version
}>()

const loading = ref(false)
const isSending = ref(false)
const applying = ref(false)
const inputText = ref('')
const textareaRef = ref<HTMLTextAreaElement | null>(null)
type PastedImage = { id: number; name: string; previewUrl: string }
const pastedImages = ref<PastedImage[]>([])
const composerAttachments = computed<UnifiedChatAttachment[]>(() =>
  pastedImages.value.map(item => ({
    id: item.id,
    name: item.name,
    previewUrl: item.previewUrl,
    kind: 'image',
  })),
)

const currentSession = ref<{ id: number; title: string } | null>(null)
const messages = ref<AIChatMessage[]>([])
const toolCalls = ref<AIChatToolCall[]>([])
const boundAppName = computed(() => props.appName || '')

let abortCtl: AbortController | null = null

// ─── 加载会话 ───
async function loadSession(sessionId: number) {
  const detail = await aiChatApi.getSession(sessionId, props.appId ? { app_id: props.appId } : undefined)
  currentSession.value = { id: detail.session.id, title: detail.session.title }
  messages.value = detail.messages || []
  toolCalls.value = detail.tool_calls || []
}

async function ensureAndLoad() {
  if (!props.appId) return
  loading.value = true
  try {
    const ensured = await applicationApi.ensureChatSession(props.appId)
    await loadSession(ensured.session_id)
  } catch (err: any) {
    ElMessage.error(err?.response?.data?.detail || err?.message || '加载会话失败')
  } finally {
    loading.value = false
  }
}

// 抽屉打开时初始化；关闭时不清状态（再打开能继续看）
watch(
  () => [props.visible, props.appId] as const,
  ([v, aid]) => {
    if (v && aid && (!currentSession.value || currentSession.value.id === 0)) {
      ensureAndLoad()
    }
  },
  { immediate: true },
)

// ─── 发送消息（流式） ───
const canSend = computed(() => inputText.value.trim().length > 0 && !isSending.value)

function appendContextLine(line: string) {
  const current = inputText.value.trimEnd()
  inputText.value = current ? `${current}\n${line}` : line
}

function removePastedImage(id: number) {
  const img = pastedImages.value.find(item => item.id === id)
  if (img?.previewUrl) URL.revokeObjectURL(img.previewUrl)
  pastedImages.value = pastedImages.value.filter(item => item.id !== id)
}

function clearPastedImages() {
  pastedImages.value.forEach(item => URL.revokeObjectURL(item.previewUrl))
  pastedImages.value = []
}

function onPasteImageFiles(images: File[]) {
  if (!images.length) return
  for (const file of images) {
    const item = {
      id: Date.now() + pastedImages.value.length,
      name: file.name,
      previewUrl: URL.createObjectURL(file),
    }
    pastedImages.value.push(item)
    appendContextLine(`[已粘贴图片：${file.name}] 请结合这张图片理解我的需求。`)
  }
  nextTick(autosize)
}

async function onSend() {
  if (!currentSession.value || !canSend.value) return
  const text = inputText.value.trim()
  inputText.value = ''
  clearPastedImages()

  // 立刻 push 用户消息让 UI 即时反馈
  const userMsg: AIChatMessage = {
    id: Date.now(),
    session_id: currentSession.value.id,
    role: 'user',
    content: text,
    extra_meta: null,
    created_at: new Date().toISOString(),
  }
  messages.value.push(userMsg)

  isSending.value = true
  abortCtl = new AbortController()
  try {
    await aiChatApi.sendMessage(
      currentSession.value.id,
      { message: text },
      {
        signal: abortCtl.signal,
        onEvent: handleSseEvent,
      },
    )
  } catch (err: any) {
    if (err?.name !== 'AbortError') {
      ElMessage.error(`发送失败：${err?.message || err}`)
    }
  } finally {
    isSending.value = false
    abortCtl = null
  }
}

function onAbort() {
  if (abortCtl) abortCtl.abort()
}

// ─── SSE 事件处理（精简版：只处理对话核心事件） ───
let streamingMsg: AIChatMessage | null = null

function handleSseEvent(eventName: string, data: any) {
  switch (eventName) {
    case 'user_message':
      // 服务端持久化的 user 消息（替换之前 push 的临时 id）
      if (data && data.id) {
        const tempIdx = messages.value.findIndex((m) => m.role === 'user' && m.content === data.content && !messages.value.some(x => x.id === data.id))
        if (tempIdx >= 0) messages.value.splice(tempIdx, 1, data)
        else if (!messages.value.find(m => m.id === data.id)) messages.value.push(data)
      }
      break
    case 'assistant_delta': {
      const delta = data?.text || ''
      if (!streamingMsg) {
        streamingMsg = {
          id: -Date.now(),
          session_id: currentSession.value?.id || 0,
          role: 'assistant',
          content: delta,
          extra_meta: null,
          created_at: new Date().toISOString(),
        }
        messages.value.push(streamingMsg)
      } else {
        streamingMsg.content += delta
      }
      break
    }
    case 'assistant_message':
      // 服务端持久化的 assistant 消息：替换 streaming
      if (streamingMsg) {
        const idx = messages.value.findIndex((m) => m.id === streamingMsg!.id)
        if (idx >= 0) messages.value.splice(idx, 1, data)
        else messages.value.push(data)
        streamingMsg = null
      } else if (data) {
        messages.value.push(data)
      }
      break
    case 'tool_call_start': {
      const tc: AIChatToolCall = {
        id: data.id,
        session_id: currentSession.value?.id || 0,
        message_id: null,
        tool_name: data.tool_name,
        args_json: data.args || {},
        result_text: null,
        status: 'running',
        error_message: null,
        duration_ms: null,
        started_at: data.started_at || null,
        ended_at: null,
      }
      toolCalls.value.push(tc)
      break
    }
    case 'tool_call_end': {
      const found = toolCalls.value.find((t) => t.id === data.id)
      if (found) {
        found.status = data.status
        found.result_text = data.result_text
        found.duration_ms = data.duration_ms
      }
      break
    }
    case 'error':
      ElMessage.error(data?.error || '出错了')
      break
  }
}

// ─── timeline 转换给 AgentConversation ───
const agentMessages = computed(() => {
  // 复用现有 AgentConversation 的 message 形状
  type Item = any
  const out: Item[] = []
  // 按时间戳交错排序（mirror AIChatPage / VibeChatPanel 做法）
  const ts = (s: string | null | undefined) => (s ? Date.parse(s) || 0 : 0)
  type Sortable = { ts: number; seq: number; kind: 'msg' | 'tc'; data: any }
  const sortable: Sortable[] = []
  for (const m of messages.value) sortable.push({ ts: ts(m.created_at), seq: m.id, kind: 'msg', data: m })
  for (const t of toolCalls.value) sortable.push({ ts: ts(t.started_at), seq: t.id, kind: 'tc', data: t })
  sortable.sort((a, b) => {
    if (a.ts !== b.ts) return a.ts - b.ts
    if (a.kind !== b.kind) return a.kind === 'msg' ? -1 : 1
    return a.seq - b.seq
  })

  for (const it of sortable) {
    if (it.kind === 'msg') {
      const m = it.data as AIChatMessage
      // 跳过 tool_use placeholder（content 空 + extra_meta.tool_calls）
      const isPlaceholder =
        m.role === 'assistant' && !(m.content || '').trim() && (m.extra_meta as any)?.tool_calls
      if (m.role === 'user') {
        out.push({ id: `m${m.id}`, kind: 'user', content: m.content })
      } else if (m.role === 'assistant' && !isPlaceholder) {
        out.push({ id: `m${m.id}`, kind: 'assistant', content: m.content })
      }
    } else {
      const t = it.data as AIChatToolCall
      out.push({
        id: `t${t.id}`,
        kind: 'tool',
        tool: {
          id: t.id,
          name: t.tool_name,
          args: t.args_json,
          result: t.result_text || undefined,
          status: t.status === 'aborted' ? 'error' : (t.status as any),
          duration_ms: t.duration_ms ?? undefined,
        },
      })
    }
  }
  return out
})

// ─── 应用最新 md 到 Builder ───
async function applyToBuilder() {
  if (!props.appId || applying.value) return
  applying.value = true
  try {
    const res = await applicationApi.syncMdFromChat(props.appId)
    if (!res.content?.trim()) {
      ElMessage.warning('对话里还没有可应用的 md，请先让 AI 用 write_artifact 写新版设计文档')
      return
    }
    emit('applied', { filename: res.artifact_filename, content: res.content })
  } catch (err: any) {
    ElMessage.error(err?.response?.data?.detail || err?.message || '应用失败')
  } finally {
    applying.value = false
  }
}

// ─── 输入框 autosize ───
function autosize() {
  const el = textareaRef.value
  if (!el) return
  el.style.height = 'auto'
  el.style.height = Math.min(el.scrollHeight, 160) + 'px'
}
watch(inputText, () => nextTick(autosize))

onUnmounted(() => {
  if (abortCtl) abortCtl.abort()
  clearPastedImages()
})
</script>

<style scoped>
.app-chat-panel {
  display: flex;
  flex-direction: column;
  height: 100%;
  width: 100%;
  background: var(--t-bg-base);
  color: var(--t-text-primary);
}
.app-chat-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 12px 16px;
  border-bottom: 1px solid var(--t-border-subtle);
  background: var(--t-bg-panel);
  flex-shrink: 0;
  gap: 12px;
}
.app-chat-title {
  display: flex;
  align-items: baseline;
  gap: 8px;
  min-width: 0;
}
.title-icon { font-size: 16px; }
.title-text {
  font-size: 14px;
  font-weight: 600;
  color: var(--t-text-primary);
}
.title-app {
  color: var(--t-text-muted);
  font-size: 12px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.app-chat-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-shrink: 0;
}
.apply-btn {
  height: 30px;
  padding: 0 14px;
  border: 0;
  border-radius: 7px;
  background: var(--t-brand, #5a78ff);
  color: #fff;
  font-size: 12.5px;
  font-weight: 600;
  cursor: pointer;
  white-space: nowrap;
}
.apply-btn:hover:not(:disabled) {
  background: color-mix(in srgb, var(--t-brand, #5a78ff) 88%, black);
}
.apply-btn:disabled {
  opacity: 0.55;
  cursor: not-allowed;
}
.close-btn {
  width: 28px;
  height: 28px;
  border: 1px solid var(--t-border-subtle);
  border-radius: 6px;
  background: transparent;
  color: var(--t-text-muted);
  cursor: pointer;
  font-size: 14px;
}
.close-btn:hover {
  color: var(--t-text-primary);
  border-color: var(--t-border-strong);
}

.app-chat-hint {
  padding: 10px 16px;
  font-size: 12px;
  color: var(--t-text-muted);
  background: var(--t-bg-input);
  border-bottom: 1px solid var(--t-border-subtle);
  line-height: 1.5;
  flex-shrink: 0;
}

.app-chat-body {
  flex: 1;
  min-height: 0;
  overflow: hidden;
  display: flex;
  flex-direction: column;
}
.app-chat-empty {
  display: flex;
  align-items: center;
  justify-content: center;
  height: 100%;
  color: var(--t-text-muted);
  font-size: 13px;
}

.app-chat-input {
  display: flex;
  align-items: flex-end;
  gap: 8px;
  padding: 12px 16px;
  border-top: 1px solid var(--t-border-subtle);
  background: var(--t-bg-panel);
  flex-shrink: 0;
}
.input-composer {
  flex: 1;
  min-width: 0;
  border: 1px solid var(--t-border-subtle);
  border-radius: 8px;
  background: var(--t-bg-input);
  overflow: hidden;
}
.input-composer:focus-within {
  border-color: var(--t-brand, #5a78ff);
}
.app-chat-attachments {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  padding: 8px 8px 0;
}
.app-chat-attachment {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  max-width: 100%;
  min-height: 28px;
  padding: 3px 6px 3px 3px;
  border: 1px solid var(--t-border-subtle);
  border-radius: 999px;
  background: var(--t-bg-panel);
  color: var(--t-text-muted);
  font-size: 11px;
}
.app-chat-attachment img {
  width: 22px;
  height: 22px;
  border-radius: 999px;
  object-fit: cover;
}
.app-chat-attachment span {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.app-chat-attachment button {
  width: 18px;
  height: 18px;
  padding: 0;
  border: 0;
  border-radius: 999px;
  background: transparent;
  color: var(--t-text-muted);
  cursor: pointer;
  font-size: 14px;
  line-height: 18px;
}
.app-chat-attachment button:hover {
  background: var(--t-border-subtle);
  color: var(--t-text-primary);
}
.input-textarea {
  display: block;
  width: 100%;
  min-height: 36px;
  max-height: 160px;
  padding: 9px 12px;
  border: 0;
  background: transparent;
  color: var(--t-text-primary);
  font-size: 13px;
  font-family: inherit;
  resize: none;
  outline: none;
  line-height: 1.5;
}
.send-btn,
.abort-btn {
  width: 36px;
  height: 36px;
  border: 0;
  border-radius: 8px;
  background: var(--t-brand, #5a78ff);
  color: #fff;
  font-size: 14px;
  cursor: pointer;
  flex-shrink: 0;
}
.send-btn:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}
.abort-btn {
  background: #d33;
}
</style>
