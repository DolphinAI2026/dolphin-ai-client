<!-- 终端面板:消费 serve-logs SSE(event=log,data={seq,stream,line}),等宽日志流。
     stdout/stderr/runtime 分色,自动滚到底,环形 buffer 2000 行,断点续传(last_seen_seq)。 -->
<template>
  <div class="term-panel">
    <div class="term-toolbar">
      <span class="term-title">serve 日志</span>
      <span class="term-spacer" />
      <span class="term-state" :class="'is-' + connState">{{ connLabel }}</span>
      <button class="term-tbtn" title="清屏" @click="clear">清屏</button>
      <button class="term-tbtn" title="重连" @click="reconnect">重连</button>
    </div>
    <pre v-if="lines.length" ref="bodyEl" class="term-body">
<span v-for="l in lines" :key="l.seq" class="term-line" :class="'st-' + l.stream">{{ l.line }}
</span></pre>
    <div v-else class="term-empty">启动预览后,这里出现构建 / 运行日志。</div>
  </div>
</template>

<script setup lang="ts">
import { ref, watch, nextTick, onBeforeUnmount } from 'vue'
import { API_PREFIX } from '@/utils/request'
import { buildServeLogsUrl } from '../serveLogsUrl'

const props = defineProps<{ wsId: string }>()

interface LogLine { seq: number; stream: string; line: string }

const lines = ref<LogLine[]>([])
const bodyEl = ref<HTMLElement | null>(null)
const connState = ref<'idle' | 'open' | 'closed'>('idle')
const RING_MAX = 2000

let es: EventSource | null = null
let lastSeq = 0

const connLabel = ref('未连接')
watch(connState, (s) => {
  connLabel.value = s === 'open' ? '已连接' : s === 'closed' ? '已断开' : '未连接'
})

function close() {
  if (es) { es.close(); es = null }
}

function connect() {
  close()
  if (!props.wsId) { connState.value = 'idle'; return }
  const token = localStorage.getItem('token') || ''
  const url = buildServeLogsUrl(API_PREFIX, props.wsId, lastSeq, token)
  es = new EventSource(url, { withCredentials: true })
  es.onopen = () => { connState.value = 'open' }
  es.onerror = () => { connState.value = 'closed' }
  es.addEventListener('log', (e: MessageEvent) => {
    try {
      const p = JSON.parse(e.data) as LogLine
      if (typeof p.seq === 'number') lastSeq = Math.max(lastSeq, p.seq)
      lines.value.push({ seq: p.seq, stream: p.stream || 'stdout', line: p.line ?? '' })
      if (lines.value.length > RING_MAX) lines.value.splice(0, lines.value.length - RING_MAX)
      scrollToBottom()
    } catch { /* 忽略坏行 */ }
  })
}

function reconnect() { connState.value = 'idle'; connect() }
function clear() { lines.value = [] }

function scrollToBottom() {
  nextTick(() => { if (bodyEl.value) bodyEl.value.scrollTop = bodyEl.value.scrollHeight })
}

watch(() => props.wsId, () => { lines.value = []; lastSeq = 0; connect() }, { immediate: true })
onBeforeUnmount(close)
</script>

<style scoped>
.term-panel { display: flex; flex-direction: column; height: 100%; overflow: hidden; background: var(--cx-bg-0); }
.term-toolbar {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 12px;
  border-bottom: 1px solid var(--cx-border);
  font-size: 12px;
}
.term-title { color: var(--cx-text-1); font-weight: 500; }
.term-spacer { flex: 1; }
.term-state { font-family: var(--cx-mono); font-size: 11px; color: var(--cx-text-3); }
.term-state.is-open { color: var(--cx-green); }
.term-state.is-closed { color: var(--cx-red); }
.term-tbtn {
  background: transparent;
  border: 1px solid var(--cx-border);
  color: var(--cx-text-2);
  border-radius: 4px;
  padding: 2px 8px;
  font-size: 11px;
  cursor: pointer;
}
.term-tbtn:hover { background: var(--cx-bg-3); color: var(--cx-text-1); }
.term-body {
  flex: 1;
  overflow-y: auto;
  margin: 0;
  padding: 10px 12px;
  background: #000;
  font-family: var(--cx-mono);
  font-size: 12px;
  line-height: 1.55;
  white-space: pre-wrap;
  word-break: break-all;
}
.term-line { color: var(--cx-text-2); }
.term-line.st-stderr { color: var(--cx-red); }
.term-line.st-runtime { color: var(--cx-accent); }
.term-empty { flex: 1; display: grid; place-items: center; color: var(--cx-text-3); font-size: 13px; padding: 24px; }
</style>
