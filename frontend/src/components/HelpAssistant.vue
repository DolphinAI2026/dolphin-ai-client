<template>
  <!-- 浮动按钮（关闭时）：作为 WorkbenchShell 的兄弟元素 fixed 在右下角 -->
  <Teleport to="body">
    <button
      v-if="!open"
      class="ha-fab"
      type="button"
      title="问问 aPaaS Builder 助手"
      @click="openPanel"
    >
      <svg viewBox="0 0 24 24" width="22" height="22" fill="none" aria-hidden="true">
        <path d="M21 11.5a8.38 8.38 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 8.38 8.38 0 0 1-3.8-.9L3 21l1.9-5.7a8.38 8.38 0 0 1-.9-3.8 8.5 8.5 0 0 1 4.7-7.6 8.38 8.38 0 0 1 3.8-.9h.5a8.48 8.48 0 0 1 8 8v.5z"
          stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" />
      </svg>
      <span>使用助手</span>
    </button>
  </Teleport>

  <!-- 抽屉作为 inline flex item，主区被挤压而不是覆盖；fullscreen 切换 -->
  <aside
    v-if="open"
    class="ha-drawer"
    :class="{ fullscreen }"
    role="dialog"
    aria-label="aPaaS Builder 助手"
  >
        <transition name="ha-fade" appear>
          <div class="ha-drawer-inner">
          <header class="ha-head">
            <div class="ha-head-title" :title="meta ? `aPaaS Builder 助手 · 基于 ${meta.kb_files} 篇知识` : 'aPaaS Builder 助手'">
              <span class="ha-dot"></span>
              <strong>aPaaS Builder 助手</strong>
            </div>
            <select
              v-if="modelOptions.length"
              v-model.number="selectedLlmId"
              class="ha-model-select"
              :title="selectedModelLabel || '选择 LLM 模型'"
              :disabled="streaming"
              @change="onLlmChange"
            >
              <option
                v-for="opt in modelOptions"
                :key="opt.id"
                :value="opt.id"
              >{{ opt.config_name }}{{ opt.is_default ? ' ★' : '' }}</option>
            </select>
            <button
              class="ha-icon-btn"
              type="button"
              title="会话历史"
              :class="{ 'is-on': historyOpen }"
              @click="historyOpen = !historyOpen"
            >☰</button>
            <button
              v-if="speechSupported"
              class="ha-icon-btn"
              type="button"
              :title="ttsEnabled ? '关闭语音朗读' : '开启语音朗读'"
              :class="{ 'is-on': ttsEnabled }"
              @click="toggleTts"
            >{{ ttsEnabled ? '🔊' : '🔈' }}</button>
            <button
              class="ha-icon-btn"
              type="button"
              :title="fullscreen ? '还原' : '全屏'"
              @click="toggleFullscreen"
            >⛶</button>
            <button class="ha-icon-btn" type="button" title="关闭" @click="closePanel">×</button>
          </header>

          <!-- 历史面板：下拉式，点 ≡ 切换显隐 -->
          <transition name="ha-fade">
            <div v-if="historyOpen" class="ha-history">
              <div class="ha-history-head">
                <span>对话历史 · {{ threads.length }} 条</span>
                <button class="ha-history-new" type="button" @click="newThread">+ 新对话</button>
              </div>
              <div v-if="!threads.length" class="ha-history-empty">还没有历史，发一条消息就会自动归档。</div>
              <ul v-else class="ha-history-list">
                <li
                  v-for="t in sortedThreads"
                  :key="t.id"
                  :class="['ha-history-item', { active: t.id === currentThreadId }]"
                  @click="switchThread(t.id)"
                >
                  <div class="ha-history-item-main">
                    <strong>{{ t.title }}</strong>
                    <small>{{ formatTime(t.updated_at) }}</small>
                  </div>
                  <button
                    class="ha-history-del"
                    type="button"
                    title="删除"
                    @click.stop="deleteThread(t.id)"
                  >×</button>
                </li>
              </ul>
            </div>
          </transition>

          <div ref="bodyRef" class="ha-body" @click="onBodyClick">
            <div v-if="messages.length === 0" class="ha-welcome">
              <h3>👋 你好！</h3>
              <p>问我关于 <strong>aPaaS Builder AI</strong> 的任何问题——AI 对话、AI 搭建、AI 编码、Vibe Coding、DevOps 怎么用，从哪开始，都能聊。</p>
              <div class="ha-suggestions">
                <button
                  v-for="q in suggestions"
                  :key="q"
                  class="ha-chip"
                  type="button"
                  @click="ask(q)"
                >{{ q }}</button>
              </div>
            </div>

            <template v-else>
              <div
                v-for="(m, i) in messages"
                :key="i"
                class="ha-msg"
                :class="m.role"
              >
                <div class="ha-bubble" v-html="render(m.content)"></div>
              </div>
              <div v-if="streaming" class="ha-msg assistant">
                <div class="ha-bubble">
                  <span v-html="render(streamingText || '')"></span>
                  <span class="ha-cursor"></span>
                </div>
              </div>
              <div v-if="errorMsg" class="ha-error">{{ errorMsg }}</div>
            </template>
          </div>

          <footer class="ha-input-area">
            <textarea
              ref="textareaRef"
              v-model="input"
              class="ha-input"
              :placeholder="recognizing ? '正在听…（再次点麦克风停止）' : '问问助手…（Enter 发送 / Shift+Enter 换行）'"
              rows="2"
              :disabled="streaming"
              @keydown.enter.exact.prevent="onSubmit"
              @keydown.shift.enter.exact="$event"
            ></textarea>
            <div class="ha-input-foot">
              <button
                v-if="speechSupported"
                class="ha-mic"
                type="button"
                :class="{ 'is-recording': recognizing }"
                :title="recognizing ? '停止录音' : '语音输入（点一下开始说话）'"
                :disabled="streaming"
                @click="toggleRecording"
              >🎙</button>
              <span class="ha-foot-hint">{{ speechSupported ? '回答仅基于内置知识库' : '回答仅基于内置知识库（当前浏览器不支持语音）' }}</span>
              <button
                v-if="streaming"
                class="ha-send abort"
                type="button"
                @click="abort"
              >停止</button>
              <button
                v-else
                class="ha-send"
                type="button"
                :disabled="!canSend"
                @click="onSubmit"
              >发送</button>
            </div>
          </footer>
          </div>
        </transition>
  </aside>
</template>

<script setup lang="ts">
import { computed, nextTick, onMounted, onBeforeUnmount, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { marked } from 'marked'
import { ElMessage } from 'element-plus'
import { helpAssistantApi, consumeHelpStream, type HelpMessage, type HelpMeta } from '@/api/helpAssistant'
import { llmConfigApi, type BuilderModelOption } from '@/api/llmConfig'

const router = useRouter()
const route = useRoute()

marked.setOptions({ breaks: true, gfm: true })

// ── 多会话持久化（threads）──
// 每个 thread = { id, title, messages, updated_at }，全部 localStorage（key: help-assistant:threads）
// 老的单 messages 数据自动迁移到一个 default thread，迁完删旧 key
const THREADS_KEY = 'help-assistant:threads'
const CURRENT_THREAD_KEY = 'help-assistant:current-thread-id'
const LEGACY_MESSAGES_KEY = 'help-assistant:messages'
const MAX_MESSAGES_PER_THREAD = 50
const MAX_THREADS = 30

interface HelpThread {
  id: string
  title: string
  messages: HelpMessage[]
  updated_at: number
}

function genThreadId(): string {
  return `t_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 8)}`
}

function loadThreads(): HelpThread[] {
  try {
    const raw = localStorage.getItem(THREADS_KEY)
    if (raw) {
      const parsed = JSON.parse(raw)
      if (Array.isArray(parsed)) {
        return parsed
          .filter((t: any) => t && typeof t.id === 'string' && Array.isArray(t.messages))
          .map((t: any) => ({
            id: t.id,
            title: typeof t.title === 'string' ? t.title : '新对话',
            updated_at: typeof t.updated_at === 'number' ? t.updated_at : Date.now(),
            messages: (t.messages as any[])
              .filter(m => m && (m.role === 'user' || m.role === 'assistant') && typeof m.content === 'string')
              .slice(-MAX_MESSAGES_PER_THREAD),
          }))
          .slice(0, MAX_THREADS)
      }
    }
    // 迁移：老 key 'help-assistant:messages' → default thread
    const legacy = localStorage.getItem(LEGACY_MESSAGES_KEY)
    if (legacy) {
      try {
        const parsed = JSON.parse(legacy)
        if (Array.isArray(parsed) && parsed.length) {
          const migrated: HelpThread = {
            id: genThreadId(),
            title: deriveTitle(parsed),
            messages: parsed.slice(-MAX_MESSAGES_PER_THREAD),
            updated_at: Date.now(),
          }
          localStorage.removeItem(LEGACY_MESSAGES_KEY)
          return [migrated]
        }
      } catch { /* ignore */ }
    }
  } catch { /* ignore */ }
  return []
}

function persistThreads(list: HelpThread[]) {
  try {
    localStorage.setItem(THREADS_KEY, JSON.stringify(list.slice(0, MAX_THREADS)))
  } catch { /* quota / privacy mode：忽略 */ }
}

function deriveTitle(messages: HelpMessage[]): string {
  const first = messages.find(m => m.role === 'user')?.content?.trim()
  if (!first) return '新对话'
  const oneLine = first.replace(/\s+/g, ' ')
  return oneLine.length > 24 ? oneLine.slice(0, 24) + '…' : oneLine
}

function formatTime(ts: number): string {
  const diff = Date.now() - ts
  if (diff < 60_000) return '刚刚'
  const m = Math.floor(diff / 60_000)
  if (m < 60) return `${m} 分钟前`
  const h = Math.floor(m / 60)
  if (h < 24) return `${h} 小时前`
  const d = Math.floor(h / 24)
  if (d < 7) return `${d} 天前`
  return new Date(ts).toLocaleDateString()
}

const FULLSCREEN_KEY = 'help-assistant:fullscreen'
const open = ref(false)
const fullscreen = ref<boolean>(localStorage.getItem(FULLSCREEN_KEY) === '1')
const historyOpen = ref(false)

// thread 状态
const threads = ref<HelpThread[]>(loadThreads())
const currentThreadId = ref<string>(
  localStorage.getItem(CURRENT_THREAD_KEY) || threads.value[0]?.id || '',
)
function ensureCurrentThread(): HelpThread {
  let cur = threads.value.find(t => t.id === currentThreadId.value)
  if (!cur) {
    cur = { id: genThreadId(), title: '新对话', messages: [], updated_at: Date.now() }
    threads.value.unshift(cur)
    currentThreadId.value = cur.id
    try { localStorage.setItem(CURRENT_THREAD_KEY, cur.id) } catch {}
  }
  return cur
}
const messages = computed<HelpMessage[]>({
  get: () => threads.value.find(t => t.id === currentThreadId.value)?.messages ?? [],
  set: (v) => {
    const cur = ensureCurrentThread()
    cur.messages = v
  },
})

const sortedThreads = computed(() => [...threads.value].sort((a, b) => b.updated_at - a.updated_at))

function newThread() {
  const t: HelpThread = { id: genThreadId(), title: '新对话', messages: [], updated_at: Date.now() }
  threads.value.unshift(t)
  currentThreadId.value = t.id
  try { localStorage.setItem(CURRENT_THREAD_KEY, t.id) } catch {}
  historyOpen.value = false
  errorMsg.value = ''
  streamingText.value = ''
}

function switchThread(id: string) {
  if (streaming.value) return
  if (id === currentThreadId.value) {
    historyOpen.value = false
    return
  }
  currentThreadId.value = id
  try { localStorage.setItem(CURRENT_THREAD_KEY, id) } catch {}
  historyOpen.value = false
  errorMsg.value = ''
  streamingText.value = ''
}

function deleteThread(id: string) {
  threads.value = threads.value.filter(t => t.id !== id)
  if (currentThreadId.value === id) {
    currentThreadId.value = threads.value[0]?.id || ''
    try {
      if (currentThreadId.value) localStorage.setItem(CURRENT_THREAD_KEY, currentThreadId.value)
      else localStorage.removeItem(CURRENT_THREAD_KEY)
    } catch {}
  }
}

const input = ref('')
const streaming = ref(false)
const streamingText = ref('')
const errorMsg = ref('')
const meta = ref<HelpMeta | null>(null)
const abortCtrl = ref<AbortController | null>(null)

function toggleFullscreen() {
  fullscreen.value = !fullscreen.value
  try { localStorage.setItem(FULLSCREEN_KEY, fullscreen.value ? '1' : '0') } catch {}
}

// ── 模型切换 ──
const LLM_KEY = 'help-assistant:llm-id'
const TTS_KEY = 'help-assistant:tts-enabled'
const modelOptions = ref<BuilderModelOption[]>([])
const selectedLlmId = ref<number | null>(
  Number(localStorage.getItem(LLM_KEY) || '') || null,
)
const selectedModelLabel = computed(() => {
  const opt = modelOptions.value.find(o => o.id === selectedLlmId.value)
  return opt ? `${opt.config_name} · ${opt.model}` : ''
})
async function loadModels() {
  try {
    const list = await llmConfigApi.listOptions('all')
    modelOptions.value = Array.isArray(list) ? list : []
    // 没有保存或保存的 id 已不存在 → 自动选默认
    if (!selectedLlmId.value || !modelOptions.value.find(o => o.id === selectedLlmId.value)) {
      const def = modelOptions.value.find(o => o.is_default) || modelOptions.value[0]
      selectedLlmId.value = def?.id ?? null
    }
  } catch {
    /* 静默：没有模型也不挡用，后端 fallback 到环境变量 */
  }
}
function onLlmChange() {
  if (selectedLlmId.value == null) {
    try { localStorage.removeItem(LLM_KEY) } catch {}
  } else {
    try { localStorage.setItem(LLM_KEY, String(selectedLlmId.value)) } catch {}
  }
}

// ── 语音支持（浏览器原生 API，部署到线上无任何额外依赖） ──
type SpeechRecognitionLike = any
const speechSupported = ref(false)
const recognizing = ref(false)
const ttsEnabled = ref<boolean>(localStorage.getItem(TTS_KEY) === '1')
let recognition: SpeechRecognitionLike | null = null
let ttsLastSpokenIdx = -1

function detectSpeech() {
  const w = window as any
  const SR = w.SpeechRecognition || w.webkitSpeechRecognition
  const synth = w.speechSynthesis
  speechSupported.value = !!(SR && synth)
  if (!SR) return
  try {
    recognition = new SR()
    recognition.lang = 'zh-CN'
    recognition.continuous = false
    recognition.interimResults = true
    recognition.onresult = (event: any) => {
      let finalText = ''
      let interimText = ''
      for (let i = event.resultIndex; i < event.results.length; i++) {
        const res = event.results[i]
        if (res.isFinal) finalText += res[0].transcript
        else interimText += res[0].transcript
      }
      if (finalText) {
        input.value = (input.value ? input.value + ' ' : '') + finalText.trim()
      } else if (interimText) {
        // 把临时识别文本附在已有内容尾部展示，不持久；这里直接覆盖式追加
        // 简单处理：interim 不写入 input，避免抖动；只在 final 时合入
      }
    }
    recognition.onerror = (e: any) => {
      console.warn('[HelpAssistant] SpeechRecognition error', e?.error)
      recognizing.value = false
    }
    recognition.onend = () => {
      recognizing.value = false
    }
  } catch (e) {
    console.warn('[HelpAssistant] SpeechRecognition init failed', e)
    speechSupported.value = false
    recognition = null
  }
}

function toggleRecording() {
  if (!recognition) return
  if (recognizing.value) {
    try { recognition.stop() } catch {}
    recognizing.value = false
    return
  }
  try {
    recognition.start()
    recognizing.value = true
  } catch (e) {
    // 已 start 报错时忽略
    recognizing.value = false
  }
}

function toggleTts() {
  ttsEnabled.value = !ttsEnabled.value
  try { localStorage.setItem(TTS_KEY, ttsEnabled.value ? '1' : '0') } catch {}
  // 关闭时立即停止当前朗读
  if (!ttsEnabled.value && window.speechSynthesis) {
    try { window.speechSynthesis.cancel() } catch {}
  }
}

/** 清掉 markdown 标记 + 动作链接，留纯文本朗读 */
function stripForTts(text: string): string {
  return text
    // 链接 [文字](url) → 文字
    .replace(/\[([^\]]+)\]\([^)]+\)/g, '$1')
    // 行内代码 `code` → code
    .replace(/`([^`]+)`/g, '$1')
    // 标题 / 列表标记
    .replace(/^[#>*-]+\s*/gm, '')
    // 加粗 / 斜体
    .replace(/\*\*([^*]+)\*\*/g, '$1')
    .replace(/\*([^*]+)\*/g, '$1')
    .trim()
}

function speakText(text: string) {
  if (!ttsEnabled.value) return
  const synth = (window as any).speechSynthesis
  if (!synth) return
  const clean = stripForTts(text)
  if (!clean) return
  try {
    synth.cancel()
    const u = new (window as any).SpeechSynthesisUtterance(clean)
    u.lang = 'zh-CN'
    u.rate = 1.05
    synth.speak(u)
  } catch (e) {
    console.warn('[HelpAssistant] speak failed', e)
  }
}

const bodyRef = ref<HTMLElement>()
const textareaRef = ref<HTMLTextAreaElement>()

const suggestions = [
  '我应该从哪个模块开始？',
  'AI 对话和 AI 搭建有什么区别？',
  'Vibe Coding 怎么用？',
  'DevOps 提案流程是怎样的？',
  '怎么把应用部署上线？',
]

const canSend = computed(() => input.value.trim().length > 0 && !streaming.value)

function openPanel() {
  open.value = true
  nextTick(() => textareaRef.value?.focus())
}

function closePanel() {
  if (streaming.value) abort()
  open.value = false
}

function resetChat() {
  // 等价于"在当前 thread 上清空消息"——不再删整个 thread
  if (streaming.value) abort()
  const cur = ensureCurrentThread()
  cur.messages = []
  cur.title = '新对话'
  cur.updated_at = Date.now()
  streamingText.value = ''
  errorMsg.value = ''
}

// threads 变化时整体持久化
watch(threads, (list) => persistThreads(list), { deep: true })

function abort() {
  abortCtrl.value?.abort()
  abortCtrl.value = null
  if (streamingText.value) {
    const cur = ensureCurrentThread()
    cur.messages.push({ role: 'assistant', content: streamingText.value + '\n\n_（已中止）_' })
    cur.updated_at = Date.now()
  }
  streamingText.value = ''
  streaming.value = false
  // 同步停掉 TTS 朗读
  if ((window as any).speechSynthesis) {
    try { (window as any).speechSynthesis.cancel() } catch {}
  }
}

function render(text: string): string {
  if (!text) return ''
  try {
    return marked.parse(text) as string
  } catch {
    return text
  }
}

/**
 * 点击代理：识别 ha-body 内的 a[href^="#nav:"] 链接，preventDefault + router.push
 * —— 让助手"说能跳就真能跳"
 */
function onBodyClick(e: MouseEvent) {
  const target = e.target as HTMLElement | null
  if (!target) return
  const link = target.closest('a') as HTMLAnchorElement | null
  if (!link) return
  const href = link.getAttribute('href') || ''
  if (!href.startsWith('#nav:')) return

  e.preventDefault()
  const path = href.slice('#nav:'.length).trim()
  if (!path || !path.startsWith('/')) {
    ElMessage.warning('助手返回了无效的跳转路径')
    return
  }
  router.push(path).catch(() => { /* NavigationDuplicated 忽略 */ })
  // 跳转后关闭抽屉，让用户看到目标页面
  open.value = false
}

async function scrollToBottom() {
  await nextTick()
  const el = bodyRef.value
  if (el) el.scrollTop = el.scrollHeight
}

async function ask(question: string) {
  input.value = question
  await onSubmit()
}

async function onSubmit() {
  if (!canSend.value) return
  const text = input.value.trim()
  if (!text) return
  input.value = ''
  errorMsg.value = ''
  // 确保有当前 thread
  const cur = ensureCurrentThread()
  cur.messages.push({ role: 'user', content: text })
  cur.updated_at = Date.now()
  // 第一条 user 消息时自动取标题
  if (cur.title === '新对话' || !cur.title) {
    cur.title = deriveTitle(cur.messages)
  }
  streaming.value = true
  streamingText.value = ''
  await scrollToBottom()

  abortCtrl.value = new AbortController()
  try {
    const res = await helpAssistantApi.stream(messages.value, {
      signal: abortCtrl.value.signal,
      selected_llm_config_id: selectedLlmId.value,
      current_path: route.fullPath,
    })
    await consumeHelpStream(res, {
      onDelta: (delta) => {
        streamingText.value += delta
        scrollToBottom()
      },
      onError: (err) => {
        errorMsg.value = err
      },
      onDone: () => {
        if (streamingText.value) {
          const final = streamingText.value
          const cur2 = ensureCurrentThread()
          cur2.messages.push({ role: 'assistant', content: final })
          cur2.updated_at = Date.now()
          // 朗读最新一条 AI 回答（如开启）
          if (ttsEnabled.value) speakText(final)
        }
        streamingText.value = ''
        streaming.value = false
        abortCtrl.value = null
      },
    })
  } catch (e: any) {
    if (e?.name === 'AbortError') {
      // 已由 abort() 处理
      return
    }
    errorMsg.value = e?.message || '请求失败'
    streaming.value = false
    streamingText.value = ''
    abortCtrl.value = null
  }
}

watch(open, (v) => {
  if (v && !meta.value) {
    helpAssistantApi.meta().then((m) => (meta.value = m)).catch(() => {})
  }
})

// Esc 关闭
function onKeydown(e: KeyboardEvent) {
  if (e.key === 'Escape' && open.value) closePanel()
}
onMounted(() => {
  window.addEventListener('keydown', onKeydown)
  detectSpeech()
  loadModels()
})

onBeforeUnmount(() => {
  window.removeEventListener('keydown', onKeydown)
  if (recognizing.value && recognition) {
    try { recognition.stop() } catch {}
  }
  if ((window as any).speechSynthesis) {
    try { (window as any).speechSynthesis.cancel() } catch {}
  }
})
</script>

<style scoped>
/* ── 浮动按钮 ── */
.ha-fab {
  position: fixed;
  right: 20px;
  bottom: 20px;
  z-index: 1500;
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 10px 16px 10px 13px;
  border: none;
  border-radius: 999px;
  background: var(--t-brand, #4f6ef7);
  color: #fff;
  font-size: 13px;
  font-weight: 700;
  cursor: pointer;
  box-shadow: 0 8px 24px rgba(79, 110, 247, 0.32);
  transition: transform 0.18s ease, box-shadow 0.18s ease;
}
.ha-fab:hover {
  transform: translateY(-2px);
  box-shadow: 0 12px 32px rgba(79, 110, 247, 0.42);
}

.ha-fade-enter-active, .ha-fade-leave-active { transition: opacity 0.18s ease; }
.ha-fade-enter-from, .ha-fade-leave-to { opacity: 0; }

/* ── 抽屉面板：作为 WorkbenchShell 的 flex item，挤压主区而不覆盖 ── */
.ha-drawer {
  width: min(440px, 96vw);
  max-width: 440px;
  flex-shrink: 0;
  height: 100vh;
  background: var(--t-bg-elevated, #fff);
  border-left: 1px solid var(--t-border-subtle, rgba(99, 102, 241, 0.08));
  box-shadow: -8px 0 24px rgba(15, 23, 42, 0.06);
  display: flex;
  flex-direction: column;
  position: relative;
  z-index: 10;
}
/* 全屏：覆盖整个视口（除主导航），用 fixed 定位 */
.ha-drawer.fullscreen {
  position: fixed;
  top: 0;
  right: 0;
  bottom: 0;
  /* 留出主导航 56px，避免遮住导航栏 */
  left: 56px;
  width: auto;
  max-width: none;
  z-index: 1700;
  box-shadow: -16px 0 48px rgba(15, 23, 42, 0.18);
}
.ha-drawer-inner {
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: 0;
}

.ha-head {
  flex-shrink: 0;
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 10px 12px;
  border-bottom: 1px solid var(--t-border-subtle, rgba(99, 102, 241, 0.1));
  flex-wrap: nowrap;
  min-width: 0;
}
.ha-head-title {
  flex: 1 1 0;
  min-width: 0;
  display: inline-flex;
  align-items: center;
  gap: 6px;
  color: var(--t-text-primary);
  font-size: 13.5px;
  overflow: hidden;
}
.ha-head-title strong {
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.ha-dot {
  width: 8px;
  height: 8px;
  border-radius: 999px;
  background: var(--t-brand, #4f6ef7);
}
.ha-icon-btn {
  width: 26px;
  height: 26px;
  flex-shrink: 0;
  display: inline-grid;
  place-items: center;
  border: none;
  background: transparent;
  border-radius: 6px;
  color: var(--t-text-muted);
  cursor: pointer;
  font-size: 14px;
  line-height: 1;
}
.ha-icon-btn:hover {
  background: var(--t-bg-panel-hover, rgba(99, 102, 241, 0.08));
  color: var(--t-text-primary);
}
.ha-icon-btn.is-on {
  background: var(--t-brand-subtle, rgba(79, 110, 247, 0.14));
  color: var(--t-brand, #4f6ef7);
}

.ha-model-select {
  flex-shrink: 0;
  max-width: 100px;
  height: 26px;
  padding: 0 4px;
  border: 1px solid var(--t-border-subtle, rgba(99, 102, 241, 0.16));
  border-radius: 6px;
  background: var(--t-bg-panel, #fff);
  color: var(--t-text-primary);
  font-size: 11px;
  font-family: inherit;
  cursor: pointer;
  outline: none;
}
.ha-model-select:focus {
  border-color: var(--t-brand, #4f6ef7);
}
.ha-model-select:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

/* ── 历史面板 ── */
.ha-history {
  flex-shrink: 0;
  border-bottom: 1px solid var(--t-border-subtle, rgba(99, 102, 241, 0.1));
  background: var(--t-bg-panel, #f7f8fb);
  max-height: 280px;
  display: flex;
  flex-direction: column;
}
.ha-history-head {
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 14px;
  font-size: 11.5px;
  color: var(--t-text-muted);
  font-weight: 600;
  border-bottom: 1px solid var(--t-border-subtle, rgba(99, 102, 241, 0.06));
}
.ha-history-new {
  height: 24px;
  padding: 0 10px;
  border: 1px solid var(--t-border-subtle, rgba(99, 102, 241, 0.18));
  background: var(--t-bg-elevated, #fff);
  color: var(--t-text-primary);
  border-radius: 6px;
  font-size: 11.5px;
  font-weight: 700;
  cursor: pointer;
}
.ha-history-new:hover {
  border-color: var(--t-brand, #4f6ef7);
  background: var(--t-brand-subtle, rgba(79, 110, 247, 0.08));
  color: var(--t-brand, #4f6ef7);
}
.ha-history-empty {
  padding: 18px 14px;
  text-align: center;
  color: var(--t-text-muted);
  font-size: 12px;
}
.ha-history-list {
  list-style: none;
  margin: 0;
  padding: 4px 6px;
  overflow-y: auto;
  flex: 1;
  min-height: 0;
}
.ha-history-item {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 7px 10px;
  border-radius: 6px;
  cursor: pointer;
  transition: background 0.14s;
}
.ha-history-item:hover {
  background: var(--t-bg-panel-hover, rgba(99, 102, 241, 0.08));
}
.ha-history-item.active {
  background: var(--t-brand-subtle, rgba(79, 110, 247, 0.12));
}
.ha-history-item-main {
  flex: 1;
  min-width: 0;
}
.ha-history-item-main strong {
  display: block;
  color: var(--t-text-primary);
  font-size: 12.5px;
  font-weight: 600;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.ha-history-item-main small {
  color: var(--t-text-muted);
  font-size: 10.5px;
}
.ha-history-del {
  visibility: hidden;
  width: 22px;
  height: 22px;
  border: none;
  background: transparent;
  border-radius: 4px;
  color: var(--t-text-muted);
  cursor: pointer;
  font-size: 14px;
}
.ha-history-item:hover .ha-history-del {
  visibility: visible;
}
.ha-history-del:hover {
  background: rgba(239, 68, 68, 0.12);
  color: #dc2626;
}

/* ── 消息区 ── */
.ha-body {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: 14px 14px 8px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.ha-welcome {
  padding: 6px 4px 12px;
}
.ha-welcome h3 {
  margin: 0 0 6px;
  font-size: 17px;
  color: var(--t-text-primary);
}
.ha-welcome p {
  margin: 0 0 12px;
  color: var(--t-text-secondary);
  font-size: 13px;
  line-height: 1.6;
}
.ha-suggestions {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.ha-chip {
  padding: 8px 12px;
  border: 1px solid var(--t-border-subtle, rgba(99, 102, 241, 0.14));
  background: var(--t-bg-panel, #f7f8fb);
  border-radius: 10px;
  color: var(--t-text-primary);
  font-size: 13px;
  text-align: left;
  cursor: pointer;
  transition: border-color 0.14s, background 0.14s, color 0.14s;
}
.ha-chip:hover {
  border-color: var(--t-brand, #4f6ef7);
  background: var(--t-brand-subtle, rgba(79, 110, 247, 0.07));
  color: var(--t-brand-text, var(--t-brand, #4f6ef7));
}

.ha-msg {
  display: flex;
}
.ha-msg.user {
  justify-content: flex-end;
}
.ha-bubble {
  max-width: 88%;
  padding: 9px 13px;
  border-radius: 12px;
  font-size: 13.5px;
  line-height: 1.6;
  word-break: break-word;
}
.ha-msg.user .ha-bubble {
  background: var(--t-brand, #4f6ef7);
  color: #fff;
}
.ha-msg.assistant .ha-bubble {
  background: var(--t-bg-panel, #f5f7fc);
  color: var(--t-text-primary);
  border: 1px solid var(--t-border-subtle, rgba(99, 102, 241, 0.08));
}

.ha-bubble :deep(p) { margin: 0 0 6px; }
.ha-bubble :deep(p:last-child) { margin-bottom: 0; }
.ha-bubble :deep(ul), .ha-bubble :deep(ol) {
  margin: 4px 0;
  padding-left: 22px;
}
.ha-bubble :deep(code) {
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  background: rgba(15, 23, 42, 0.06);
  padding: 1px 5px;
  border-radius: 4px;
  font-size: 12px;
}
.ha-bubble :deep(pre) {
  background: rgba(15, 23, 42, 0.06);
  padding: 8px 10px;
  border-radius: 6px;
  overflow-x: auto;
  font-size: 12px;
  margin: 6px 0;
}
.ha-bubble :deep(table) {
  width: 100%;
  border-collapse: collapse;
  margin: 6px 0;
  font-size: 12px;
}
.ha-bubble :deep(th), .ha-bubble :deep(td) {
  border: 1px solid var(--t-border-subtle, rgba(99, 102, 241, 0.12));
  padding: 4px 8px;
  text-align: left;
}

/* 动作链接（#nav:/path）— 渲染成按钮样式，区别于普通 markdown link */
.ha-bubble :deep(a[href^="#nav:"]) {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  padding: 3px 11px;
  margin: 3px 4px 3px 0;
  background: var(--t-brand, #4f6ef7);
  color: #fff !important;
  border-radius: 999px;
  font-size: 12px;
  font-weight: 700;
  text-decoration: none !important;
  cursor: pointer;
  transition: transform 0.14s, box-shadow 0.14s, background 0.14s;
  vertical-align: baseline;
}
.ha-bubble :deep(a[href^="#nav:"])::before {
  content: '→';
  margin-right: 1px;
}
.ha-bubble :deep(a[href^="#nav:"]):hover {
  transform: translateY(-1px);
  box-shadow: 0 6px 16px rgba(79, 110, 247, 0.32);
  background: var(--t-brand-dark, #3b53d9);
}
.ha-msg.user .ha-bubble :deep(a[href^="#nav:"]) {
  background: rgba(255, 255, 255, 0.22);
}

.ha-cursor {
  display: inline-block;
  width: 6px;
  height: 12px;
  background: var(--t-brand, #4f6ef7);
  margin-left: 2px;
  vertical-align: -2px;
  animation: ha-blink 1.1s infinite;
}
@keyframes ha-blink {
  0%, 49% { opacity: 1; }
  50%, 100% { opacity: 0; }
}

.ha-error {
  margin-top: 4px;
  padding: 8px 12px;
  background: rgba(239, 68, 68, 0.08);
  border: 1px solid rgba(239, 68, 68, 0.2);
  border-radius: 8px;
  color: #b91c1c;
  font-size: 12px;
}

/* ── 输入区 ── */
.ha-input-area {
  flex-shrink: 0;
  padding: 10px 14px 14px;
  border-top: 1px solid var(--t-border-subtle, rgba(99, 102, 241, 0.08));
  background: var(--t-bg-elevated, #fff);
}
.ha-input {
  width: 100%;
  resize: none;
  border: 1px solid var(--t-border-subtle, rgba(99, 102, 241, 0.16));
  border-radius: 10px;
  padding: 9px 12px;
  font-size: 13px;
  font-family: inherit;
  background: var(--t-bg-panel, #fff);
  color: var(--t-text-primary);
  outline: none;
  transition: border-color 0.14s, box-shadow 0.14s;
}
.ha-input:focus {
  border-color: var(--t-brand, #4f6ef7);
  box-shadow: 0 0 0 3px var(--t-brand-subtle, rgba(79, 110, 247, 0.14));
}
.ha-input:disabled {
  opacity: 0.7;
  cursor: not-allowed;
}
.ha-input-foot {
  margin-top: 6px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}
.ha-foot-hint {
  flex: 1;
  color: var(--t-text-muted);
  font-size: 11px;
}
.ha-mic {
  width: 28px;
  height: 28px;
  display: inline-grid;
  place-items: center;
  border: 1px solid var(--t-border-subtle, rgba(99, 102, 241, 0.18));
  background: var(--t-bg-panel, #fff);
  color: var(--t-text-secondary);
  border-radius: 999px;
  cursor: pointer;
  font-size: 14px;
  transition: background 0.14s, color 0.14s, border-color 0.14s;
}
.ha-mic:hover {
  border-color: var(--t-brand, #4f6ef7);
  color: var(--t-brand, #4f6ef7);
}
.ha-mic:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}
.ha-mic.is-recording {
  background: rgba(239, 68, 68, 0.12);
  border-color: #dc2626;
  color: #dc2626;
  animation: ha-pulse 1.1s ease-in-out infinite;
}
@keyframes ha-pulse {
  0%, 100% { box-shadow: 0 0 0 0 rgba(239, 68, 68, 0.5); }
  50% { box-shadow: 0 0 0 6px rgba(239, 68, 68, 0); }
}
.ha-send {
  height: 28px;
  padding: 0 14px;
  border: none;
  border-radius: 8px;
  background: var(--t-brand, #4f6ef7);
  color: #fff;
  font-size: 12px;
  font-weight: 700;
  cursor: pointer;
}
.ha-send:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}
.ha-send.abort {
  background: rgba(239, 68, 68, 0.92);
}

/* dark mode（跟随 html[data-theme="dark"]） */
:global(html[data-theme="dark"]) .ha-drawer {
  background: var(--t-bg-elevated, rgba(20, 24, 33, 0.98));
  border-left-color: rgba(148, 163, 184, 0.16);
  box-shadow: -8px 0 24px rgba(0, 0, 0, 0.4);
}
:global(html[data-theme="dark"]) .ha-msg.assistant .ha-bubble,
:global(html[data-theme="dark"]) .ha-chip {
  background: rgba(15, 18, 25, 0.88);
  border-color: rgba(148, 163, 184, 0.18);
}
:global(html[data-theme="dark"]) .ha-input {
  background: rgba(15, 18, 25, 0.88);
  border-color: rgba(148, 163, 184, 0.18);
  color: #e7edf8;
}
:global(html[data-theme="dark"]) .ha-input-area {
  background: rgba(20, 24, 33, 0.98);
  border-top-color: rgba(148, 163, 184, 0.16);
}
:global(html[data-theme="dark"]) .ha-bubble :deep(code),
:global(html[data-theme="dark"]) .ha-bubble :deep(pre) {
  background: rgba(255, 255, 255, 0.06);
}
</style>
