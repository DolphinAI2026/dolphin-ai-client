<template>
  <el-drawer
    v-model="visible"
    :size="540"
    direction="rtl"
    :with-header="false"
    :modal="false"
    :destroy-on-close="false"
    class="app-adjust-drawer"
  >
    <div class="aad-shell">
      <header class="aad-header">
        <div class="aad-title">
          <span class="aad-icon">🤖</span>
          <div>
            <div class="aad-title-main">AI 调整应用</div>
            <div class="aad-title-sub">{{ appName || `应用 #${appId}` }}</div>
          </div>
        </div>
        <button class="aad-close" type="button" title="关闭" @click="visible = false">×</button>
      </header>

      <div ref="scrollRef" class="aad-messages">
        <div v-if="messages.length === 0" class="aad-welcome">
          <p>我可以帮你调整 <b>{{ appName || `应用 #${appId}` }}</b>。</p>
          <ul>
            <li>"列出我能访问的所有应用"</li>
            <li>"看看当前应用的详情"</li>
            <li>"我想给当前应用加一个 xxx 字段"</li>
          </ul>
        </div>

        <div v-for="(msg, i) in messages" :key="i" :class="['aad-msg', `role-${msg.role}`]">
          <div v-if="msg.role === 'user'" class="aad-bubble user">{{ msg.content }}</div>

          <template v-else-if="msg.role === 'assistant'">
            <div v-if="msg.tools.length" class="aad-tools">
              <details v-for="(t, ti) in msg.tools" :key="ti" class="aad-tool" :open="t.status === 'running'">
                <summary>
                  <span :class="['aad-tool-status', t.status]"></span>
                  <code>{{ t.name }}</code>
                  <span v-if="t.status === 'running'" class="aad-tool-hint">运行中…</span>
                  <span v-else-if="t.status === 'done'" class="aad-tool-hint">完成</span>
                  <span v-else class="aad-tool-hint">{{ t.status }}</span>
                </summary>
                <div class="aad-tool-body">
                  <div class="aad-tool-args"><b>参数：</b><code>{{ JSON.stringify(t.arguments) }}</code></div>
                  <div v-if="t.result" class="aad-tool-result"><b>返回：</b><code>{{ t.result }}</code></div>
                </div>
              </details>
            </div>
            <div v-if="msg.content" class="aad-bubble assistant" v-html="renderMd(msg.content)"></div>
          </template>

          <div v-else-if="msg.role === 'error'" class="aad-bubble error">⚠️ {{ msg.content }}</div>
        </div>

        <div v-if="streaming" class="aad-thinking">
          <span class="dot"></span><span class="dot"></span><span class="dot"></span>
        </div>
      </div>

      <footer class="aad-input">
        <textarea
          ref="textareaRef"
          v-model="input"
          rows="2"
          placeholder="告诉我你想改什么…（Cmd/Ctrl + Enter 发送）"
          :disabled="streaming"
          @keydown.exact.enter.prevent="onTextareaEnter"
          @keydown.meta.enter.prevent="send"
          @keydown.ctrl.enter.prevent="send"
        />
        <div class="aad-input-actions">
          <button v-if="streaming" type="button" class="btn-stop" @click="stop">停止</button>
          <button v-else type="button" class="btn-send" :disabled="!input.trim()" @click="send">发送</button>
        </div>
      </footer>
    </div>
  </el-drawer>
</template>

<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'
import { marked } from 'marked'
import { ElDrawer, ElMessage } from 'element-plus'

interface Tool {
  id: string
  name: string
  arguments: Record<string, unknown>
  status: 'running' | 'done' | 'error'
  result?: string
}
interface Msg {
  role: 'user' | 'assistant' | 'error'
  content: string
  tools: Tool[]
}

const props = defineProps<{
  modelValue: boolean
  appId: number
  appName: string
}>()
const emit = defineEmits<{ (e: 'update:modelValue', v: boolean): void }>()

const visible = computed({
  get: () => props.modelValue,
  set: (v) => emit('update:modelValue', v),
})

const input = ref('')
const messages = ref<Msg[]>([])
const streaming = ref(false)
const scrollRef = ref<HTMLDivElement | null>(null)
const textareaRef = ref<HTMLTextAreaElement | null>(null)
let abort: AbortController | null = null

watch(visible, (v) => {
  if (v) nextTick(() => textareaRef.value?.focus())
})

function renderMd(text: string): string {
  try {
    return marked.parse(text, { breaks: true, gfm: true }) as string
  } catch {
    return text
  }
}

function onTextareaEnter(e: KeyboardEvent) {
  // 单 Enter 默认换行；Cmd/Ctrl + Enter 才发送（已在 keydown 单独绑定）
  // 这里 prevent 单 Enter 然后插入 \n
  const ta = e.target as HTMLTextAreaElement
  const start = ta.selectionStart
  const end = ta.selectionEnd
  input.value = input.value.slice(0, start) + '\n' + input.value.slice(end)
  nextTick(() => {
    ta.selectionStart = ta.selectionEnd = start + 1
  })
}

function scrollToBottom() {
  nextTick(() => {
    const el = scrollRef.value
    if (el) el.scrollTop = el.scrollHeight
  })
}

async function send() {
  const text = input.value.trim()
  if (!text || streaming.value) return

  // 拷贝当前对话历史（不含本次 user message）发给后端
  const history = messages.value
    .filter((m) => m.role === 'user' || (m.role === 'assistant' && m.content))
    .map((m) => ({ role: m.role as 'user' | 'assistant', content: m.content }))

  messages.value.push({ role: 'user', content: text, tools: [] })
  input.value = ''
  scrollToBottom()

  streaming.value = true
  const assistantMsg: Msg = { role: 'assistant', content: '', tools: [] }
  messages.value.push(assistantMsg)

  abort = new AbortController()
  try {
    const token = localStorage.getItem('token') || ''
    const baseUrl = '/api'
    const resp = await fetch(`${baseUrl}/app-adjust/chat/stream`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${token}`,
      },
      body: JSON.stringify({
        app_id: props.appId,
        app_name: props.appName,
        message: text,
        history,
      }),
      signal: abort.signal,
    })
    if (!resp.ok || !resp.body) {
      const errText = await resp.text().catch(() => '')
      throw new Error(`HTTP ${resp.status}: ${errText.slice(0, 200)}`)
    }

    // SSE 解析
    const reader = resp.body.getReader()
    const decoder = new TextDecoder()
    let buf = ''
    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      buf += decoder.decode(value, { stream: true })
      let idx
      while ((idx = buf.indexOf('\n\n')) >= 0) {
        const block = buf.slice(0, idx)
        buf = buf.slice(idx + 2)
        const lines = block.split('\n')
        let event = 'message'
        let data = ''
        for (const ln of lines) {
          if (ln.startsWith('event:')) event = ln.slice(6).trim()
          else if (ln.startsWith('data:')) data += ln.slice(5).trim()
        }
        if (!data) continue
        let payload: any
        try {
          payload = JSON.parse(data)
        } catch {
          continue
        }
        if (event === 'text') {
          assistantMsg.content += payload.content || ''
        } else if (event === 'tool_call_start') {
          assistantMsg.tools.push({
            id: payload.id,
            name: payload.name,
            arguments: payload.arguments || {},
            status: 'running',
          })
        } else if (event === 'tool_call_done') {
          const t = assistantMsg.tools.find((x) => x.id === payload.id)
          if (t) {
            t.status = 'done'
            t.result = payload.result_preview || ''
          }
        } else if (event === 'error') {
          messages.value.push({ role: 'error', content: payload.message || '未知错误', tools: [] })
        }
        scrollToBottom()
      }
    }
  } catch (err: any) {
    if (err?.name !== 'AbortError') {
      messages.value.push({ role: 'error', content: String(err?.message || err), tools: [] })
      ElMessage.error('对话失败：' + String(err?.message || err).slice(0, 100))
    }
  } finally {
    streaming.value = false
    abort = null
    scrollToBottom()
  }
}

function stop() {
  abort?.abort()
  streaming.value = false
}
</script>

<style scoped>
.app-adjust-drawer :deep(.el-drawer__body) {
  padding: 0;
  height: 100%;
}

.aad-shell {
  display: flex;
  flex-direction: column;
  height: 100%;
  background: #f7f8fa;
}

.aad-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 14px 16px;
  background: #fff;
  border-bottom: 1px solid #e6e8eb;
}

.aad-title {
  display: flex;
  align-items: center;
  gap: 10px;
}

.aad-icon {
  font-size: 22px;
}

.aad-title-main {
  font-size: 15px;
  font-weight: 600;
  color: #1f2329;
}

.aad-title-sub {
  font-size: 12px;
  color: #8a9099;
  margin-top: 2px;
}

.aad-close {
  width: 30px;
  height: 30px;
  border: none;
  background: transparent;
  font-size: 22px;
  color: #999;
  cursor: pointer;
  border-radius: 6px;
}

.aad-close:hover {
  background: #f1f2f4;
  color: #333;
}

.aad-messages {
  flex: 1;
  overflow-y: auto;
  padding: 16px;
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.aad-welcome {
  background: #fff;
  border: 1px dashed #d9dde2;
  padding: 12px 14px;
  border-radius: 8px;
  font-size: 13px;
  color: #555;
}

.aad-welcome ul {
  margin: 8px 0 0;
  padding-left: 20px;
  color: #7a8088;
}

.aad-msg {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.aad-msg.role-user {
  align-items: flex-end;
}

.aad-msg.role-assistant {
  align-items: flex-start;
}

.aad-bubble {
  max-width: 85%;
  padding: 10px 14px;
  border-radius: 12px;
  font-size: 14px;
  line-height: 1.55;
  word-break: break-word;
}

.aad-bubble.user {
  background: #7c3aed;
  color: #fff;
  border-bottom-right-radius: 4px;
  white-space: pre-wrap;
}

.aad-bubble.assistant {
  background: #fff;
  color: #1f2329;
  border: 1px solid #e6e8eb;
  border-bottom-left-radius: 4px;
}

.aad-bubble.assistant :deep(p) {
  margin: 0 0 6px;
}

.aad-bubble.assistant :deep(p:last-child) {
  margin-bottom: 0;
}

.aad-bubble.assistant :deep(table) {
  width: 100%;
  border-collapse: collapse;
  margin: 6px 0;
  font-size: 13px;
}

.aad-bubble.assistant :deep(th),
.aad-bubble.assistant :deep(td) {
  border: 1px solid #e6e8eb;
  padding: 6px 8px;
  text-align: left;
}

.aad-bubble.assistant :deep(th) {
  background: #f5f6f7;
}

.aad-bubble.assistant :deep(code) {
  background: #f1f2f4;
  padding: 2px 5px;
  border-radius: 3px;
  font-size: 12.5px;
}

.aad-bubble.assistant :deep(pre) {
  background: #f5f6f7;
  padding: 10px;
  border-radius: 6px;
  overflow-x: auto;
}

.aad-bubble.assistant :deep(pre code) {
  background: transparent;
  padding: 0;
}

.aad-bubble.error {
  background: #fff1f0;
  color: #cf1322;
  border: 1px solid #ffd6d3;
  font-size: 13px;
}

.aad-tools {
  width: 100%;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.aad-tool {
  background: #fff;
  border: 1px solid #e6e8eb;
  border-radius: 6px;
  font-size: 12px;
}

.aad-tool summary {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 10px;
  cursor: pointer;
  user-select: none;
  list-style: none;
}

.aad-tool summary::-webkit-details-marker {
  display: none;
}

.aad-tool-status {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: #ccc;
}

.aad-tool-status.running {
  background: #faad14;
  animation: pulse 1s ease-in-out infinite;
}

.aad-tool-status.done {
  background: #52c41a;
}

.aad-tool-status.error {
  background: #f5222d;
}

@keyframes pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.4; }
}

.aad-tool summary code {
  font-size: 12px;
  color: #7c3aed;
}

.aad-tool-hint {
  color: #8a9099;
  font-size: 11px;
}

.aad-tool-body {
  padding: 6px 10px 8px;
  border-top: 1px dashed #e6e8eb;
  color: #555;
}

.aad-tool-body code {
  background: #f5f6f7;
  padding: 1px 4px;
  border-radius: 3px;
  word-break: break-all;
  font-size: 11.5px;
}

.aad-tool-args, .aad-tool-result {
  margin: 4px 0;
  font-size: 12px;
}

.aad-thinking {
  display: flex;
  gap: 4px;
  padding: 4px 0;
}

.aad-thinking .dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: #999;
  animation: bounce 1.4s ease-in-out infinite;
}

.aad-thinking .dot:nth-child(2) { animation-delay: 0.2s; }
.aad-thinking .dot:nth-child(3) { animation-delay: 0.4s; }

@keyframes bounce {
  0%, 80%, 100% { transform: scale(0.6); opacity: 0.5; }
  40% { transform: scale(1); opacity: 1; }
}

.aad-input {
  background: #fff;
  border-top: 1px solid #e6e8eb;
  padding: 12px 14px;
}

.aad-input textarea {
  width: 100%;
  border: 1px solid #d9dde2;
  border-radius: 8px;
  padding: 8px 10px;
  font-size: 13px;
  resize: vertical;
  min-height: 50px;
  max-height: 200px;
  outline: none;
  font-family: inherit;
}

.aad-input textarea:focus {
  border-color: #7c3aed;
}

.aad-input textarea:disabled {
  background: #f5f6f7;
  color: #999;
}

.aad-input-actions {
  display: flex;
  justify-content: flex-end;
  margin-top: 8px;
}

.btn-send, .btn-stop {
  padding: 6px 16px;
  border: none;
  border-radius: 6px;
  font-size: 13px;
  cursor: pointer;
}

.btn-send {
  background: #7c3aed;
  color: #fff;
}

.btn-send:disabled {
  background: #d9d4f5;
  cursor: not-allowed;
}

.btn-send:hover:not(:disabled) {
  background: #6d28d9;
}

.btn-stop {
  background: #fff1f0;
  color: #cf1322;
  border: 1px solid #ffd6d3;
}
</style>
