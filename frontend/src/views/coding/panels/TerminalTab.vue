<!-- 单个 PTY 终端会话(xterm.js + WebSocket)。一个 tab 一个 shell。
     连接在挂载时建立(加 tab 即想用);切走(v-show 隐藏)不断连,server 继续跑。 -->
<template>
  <div ref="hostEl" class="tt-host"></div>
</template>

<script setup lang="ts">
import { ref, watch, onMounted, onBeforeUnmount } from 'vue'
import { Terminal } from '@xterm/xterm'
import { FitAddon } from '@xterm/addon-fit'
import '@xterm/xterm/css/xterm.css'
import { API_PREFIX } from '@/utils/request'
import { detectServerUrl } from '../detectServerUrl'

const props = defineProps<{ wsId: string }>()
const emit = defineEmits<{
  (e: 'state', s: 'idle' | 'open' | 'closed'): void
  (e: 'server-detected', p: { url: string; port: number }): void
}>()

// 旁路嗅探终端输出里的 dev server 地址(不动 xterm 渲染),跨帧缓冲后交纯函数 detectServerUrl 解析。
const sniffDecoder = new TextDecoder()
let sniffBuf = ''
let lastDetectedUrl = ''
function sniffServerUrl(chunk: string) {
  sniffBuf = (sniffBuf + chunk).slice(-4096)
  const hit = detectServerUrl(sniffBuf)
  if (hit && hit.url !== lastDetectedUrl) {
    lastDetectedUrl = hit.url
    emit('server-detected', hit)
    sniffBuf = ''
  }
}

const hostEl = ref<HTMLElement | null>(null)
const CX_THEME = {
  background: '#0a0a0c', foreground: '#e8eaed', cursor: '#5a78ff',
  selectionBackground: 'rgba(90,120,255,0.3)',
  black: '#16171b', red: '#f87171', green: '#34d399', yellow: '#f0824a',
  blue: '#5a78ff', magenta: '#a78bfa', cyan: '#22d3ee', white: '#e8eaed',
  brightBlack: '#6c707a', brightWhite: '#ffffff',
}

let term: Terminal | null = null
let fit: FitAddon | null = null
let ws: WebSocket | null = null
let ro: ResizeObserver | null = null

function wsUrl(): string {
  const proto = location.protocol === 'https:' ? 'wss:' : 'ws:'
  const token = localStorage.getItem('token') || ''
  return `${proto}//${location.host}${API_PREFIX}/coding/workspace/${props.wsId}/pty?token=${encodeURIComponent(token)}`
}
function sendResize() {
  if (term && ws && ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify({ type: 'resize', cols: term.cols, rows: term.rows }))
  }
}
function closeWs() { if (ws) { try { ws.close() } catch { /* noop */ } ws = null } }
function connect() {
  if (!props.wsId || !term) return
  closeWs()
  sniffBuf = ''
  lastDetectedUrl = ''
  emit('state', 'idle')
  ws = new WebSocket(wsUrl())
  ws.binaryType = 'arraybuffer'
  ws.onopen = () => { emit('state', 'open'); sendResize(); term?.focus() }
  ws.onclose = () => emit('state', 'closed')
  ws.onerror = () => emit('state', 'closed')
  ws.onmessage = (ev) => {
    if (typeof ev.data === 'string') { term?.write(ev.data); sniffServerUrl(ev.data) }
    else {
      const u8 = new Uint8Array(ev.data)
      term?.write(u8)
      sniffServerUrl(sniffDecoder.decode(u8, { stream: true }))
    }
  }
}

function init() {
  if (term || !hostEl.value) return
  term = new Terminal({
    fontFamily: 'ui-monospace, SFMono-Regular, "SF Mono", Menlo, monospace',
    fontSize: 12.5, theme: CX_THEME, cursorBlink: true, scrollback: 5000,
  })
  fit = new FitAddon()
  term.loadAddon(fit)
  term.open(hostEl.value)
  try { fit.fit() } catch { /* 容器还没尺寸 */ }
  term.onData((d) => { if (ws && ws.readyState === WebSocket.OPEN) ws.send(new TextEncoder().encode(d)) })
  connect()
  ro = new ResizeObserver(() => {
    const el = hostEl.value
    if (!el || el.clientWidth === 0 || el.clientHeight === 0) return
    try { fit?.fit() } catch { /* noop */ }
    sendResize()
  })
  ro.observe(hostEl.value)
}

// 暴露给 TerminalPanel 的工具栏调用
function clear() { term?.clear() }
function reconnect() { term?.reset(); connect() }
function refit() { try { fit?.fit() } catch { /* noop */ } sendResize(); term?.focus() }
defineExpose({ clear, reconnect, refit })

watch(() => props.wsId, () => { if (term) { term.reset(); connect() } })
onMounted(init)
onBeforeUnmount(() => { ro?.disconnect(); closeWs(); term?.dispose() })
</script>

<style scoped>
.tt-host { width: 100%; height: 100%; padding: 6px 8px; background: #0a0a0c; overflow: hidden; box-sizing: border-box; }
.tt-host :deep(.xterm) { height: 100%; }
</style>
