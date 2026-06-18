<!-- frontend/src/views/coding/RunDebugPanel.vue -->
<template>
  <div class="run-debug-panel" :class="{ dark }">
    <div class="rd-toolbar">
      <button class="rd-btn" :disabled="busy" @click="running ? stop() : start()">
        {{ running ? '停止' : '运行' }}
      </button>
      <span v-if="devUrl" class="rd-url">{{ devUrl }}</span>
      <span class="rd-spacer" />
      <button class="rd-btn" :disabled="!captureSession" @click="openDevtools">在 DevTools 打开</button>
    </div>

    <div class="rd-body">
      <div class="rd-col rd-preview">
        <div class="rd-col-title">预览</div>
        <iframe v-if="devUrl" :src="devUrl" class="rd-iframe" />
        <div v-else class="rd-empty">点「运行」启动开发服务器后在此预览</div>
      </div>

      <div class="rd-col rd-logs">
        <div class="rd-col-title">实时日志</div>
        <div ref="logBox" class="rd-logbox">
          <div
            v-for="l in logs"
            :key="l.seq"
            class="rd-logline"
            :class="{ 'is-error': isErrorLog(l) }"
          >{{ l.line }}</div>
        </div>
      </div>

      <div class="rd-col rd-obs">
        <div class="rd-tabs">
          <button :class="{ active: obsTab === 'console' }" @click="obsTab = 'console'">控制台 ({{ consoleLogs.length }})</button>
          <button :class="{ active: obsTab === 'network' }" @click="obsTab = 'network'">网络 ({{ netLogs.length }})</button>
        </div>
        <div v-show="obsTab === 'console'" class="rd-obs-list">
          <div v-for="c in consoleLogs" :key="c.seq" class="rd-obs-row" :class="{ 'is-error': c.level === 'error' }">
            <span class="rd-lvl">{{ c.level }}</span> {{ c.text }}
            <span v-if="c.location" class="rd-loc">{{ c.location }}</span>
          </div>
        </div>
        <div v-show="obsTab === 'network'" class="rd-obs-list">
          <div v-for="n in netLogs" :key="n.seq" class="rd-obs-row" :class="{ 'is-error': n.failed || n.status >= 400 }">
            <span class="rd-status">{{ n.failed ? 'ERR' : n.status }}</span>
            <span class="rd-method">{{ n.method }}</span> {{ n.url }}
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, nextTick, watch, onBeforeUnmount } from 'vue'
import { codingApi } from '@/api/coding'
import { openExternal } from '@/utils/openExternal'
import {
  appendLogLine,
  nextAfterSeq,
  mergeBySeq,
  isErrorLog,
  type LogLine,
  type ConsoleEntry,
  type NetEntry,
} from './runDebugState'

const props = defineProps<{ wsId: string; dark?: boolean }>()

const running = ref(false)
const busy = ref(false)
const devUrl = ref('')
const logs = ref<LogLine[]>([])
const consoleLogs = ref<ConsoleEntry[]>([])
const netLogs = ref<NetEntry[]>([])
const obsTab = ref<'console' | 'network'>('console')
const captureSession = ref('')
const logBox = ref<HTMLElement | null>(null)

let es: EventSource | null = null
let pollTimer: number | null = null
let lastSeq = 0
let consoleSeq = 0
let netSeq = 0

function teardown() {
  if (es) { try { es.close() } catch { /* ignore */ } es = null }
  if (pollTimer != null) { clearInterval(pollTimer); pollTimer = null }
}

async function scrollLogs() {
  await nextTick()
  if (logBox.value) logBox.value.scrollTop = logBox.value.scrollHeight
}

function openLogStream() {
  es = new EventSource(codingApi.serveLogsUrl(props.wsId, lastSeq))
  es.addEventListener('log', (ev: MessageEvent) => {
    try {
      const data = JSON.parse(ev.data) as LogLine
      logs.value = appendLogLine(logs.value, data)
      lastSeq = nextAfterSeq([data], lastSeq)
      void scrollLogs()
    } catch { /* ignore malformed line */ }
  })
}

async function pollCapture() {
  if (!captureSession.value) return
  try {
    const [c, n] = await Promise.all([
      codingApi.captureConsole(props.wsId, consoleSeq),
      codingApi.captureNetwork(props.wsId, netSeq),
    ])
    consoleLogs.value = mergeBySeq(consoleLogs.value, c)
    netLogs.value = mergeBySeq(netLogs.value, n)
    consoleSeq = nextAfterSeq(c, consoleSeq)
    netSeq = nextAfterSeq(n, netSeq)
  } catch { /* transient; next tick retries */ }
}

async function start() {
  if (!props.wsId) return
  busy.value = true
  try {
    const res = await codingApi.startServe(props.wsId)
    // 后端 start_serve 返回 {status, port, message}（无 url）→ 用 port 拼 dev server URL。
    devUrl.value = res.url || (res.port ? `http://127.0.0.1:${res.port}/` : '')
    running.value = true
    lastSeq = 0
    openLogStream()
    if (devUrl.value) {
      try {
        const cap = await codingApi.captureStart(props.wsId, devUrl.value)
        captureSession.value = cap.session_id
        consoleSeq = 0
        netSeq = 0
        pollTimer = window.setInterval(pollCapture, 2000)
      } catch { /* CDP 缺失时降级为仅日志 + iframe 预览（spec §6） */ }
    }
  } finally {
    busy.value = false
  }
}

async function stop() {
  busy.value = true
  try {
    if (captureSession.value) { await codingApi.captureStop(props.wsId).catch(() => {}) }
    await codingApi.stopServe(props.wsId).catch(() => {})
  } finally {
    teardown()
    running.value = false
    devUrl.value = ''
    captureSession.value = ''
    busy.value = false
  }
}

async function openDevtools() {
  if (!captureSession.value) {
    if (devUrl.value) await openExternal(devUrl.value)
    return
  }
  await codingApi.captureDevtools(props.wsId).catch(() => {})
}

// 切工作区：停掉旧会话，重置面板。
watch(() => props.wsId, () => { void stop() })
onBeforeUnmount(teardown)
</script>

<style scoped>
.run-debug-panel { display: flex; flex-direction: column; height: 100%; min-width: 0; }
.rd-toolbar { display: flex; align-items: center; gap: 10px; padding: 8px 12px; border-bottom: 1px solid var(--border-1, #e5e7eb); }
.rd-btn { font-size: 13px; padding: 4px 12px; border: 1px solid var(--border-1, #e5e7eb); border-radius: 6px; background: var(--bg-1, #fff); cursor: pointer; }
.rd-btn:disabled { opacity: .5; cursor: default; }
.rd-url { font-size: 12px; color: var(--text-3, #888); }
.rd-spacer { flex: 1; }
.rd-body { flex: 1; display: flex; min-height: 0; }
.rd-col { display: flex; flex-direction: column; min-height: 0; border-right: 1px solid var(--border-1, #e5e7eb); }
.rd-preview { flex: 2; }
.rd-logs { flex: 1.2; }
.rd-obs { flex: 1.2; border-right: none; }
.rd-col-title { font-size: 12px; color: var(--text-3, #888); padding: 6px 10px; }
.rd-iframe { flex: 1; width: 100%; border: 0; }
.rd-empty { flex: 1; display: flex; align-items: center; justify-content: center; color: var(--text-3, #888); font-size: 13px; }
.rd-logbox { flex: 1; overflow: auto; font-family: ui-monospace, monospace; font-size: 12px; padding: 6px 10px; }
.rd-logline { white-space: pre-wrap; word-break: break-all; }
.rd-logline.is-error { color: var(--err, #e54d42); }
.rd-tabs { display: flex; gap: 6px; padding: 6px 10px; }
.rd-tabs button { font-size: 12px; border: none; background: none; cursor: pointer; color: var(--text-3, #888); }
.rd-tabs button.active { color: var(--text-1, #222); font-weight: 600; }
.rd-obs-list { flex: 1; overflow: auto; font-family: ui-monospace, monospace; font-size: 12px; padding: 4px 10px; }
.rd-obs-row { padding: 2px 0; word-break: break-all; }
.rd-obs-row.is-error { color: var(--err, #e54d42); }
.rd-lvl, .rd-status, .rd-method { font-weight: 600; margin-right: 6px; }
.rd-loc { color: var(--text-3, #888); margin-left: 6px; }
.run-debug-panel.dark { color: var(--text-1, #ddd); }
</style>
