<!-- frontend/src/views/coding/RunDebugPanel.vue
     代码工作区「预览位」：
     - 一键「启动预览」：直接走 codingApi.startServe(props.wsId)，不依赖 agent 是否调 run_workspace_preview。
     - agent 调 run_workspace_preview / C5 自愈也会经 SSE 写 codingStore.activePreview，这里同样渲染。
     - serve 仍在编译(后端返回 status=starting) → 标「启动中」+ 3 秒后自动重试加载，避免白屏。 -->
<template>
  <div class="run-debug-panel" :class="{ dark }">
    <div class="rd-toolbar">
      <input
        v-model="address"
        class="rd-address"
        type="text"
        placeholder="输入地址,如 http://127.0.0.1:8087/"
        spellcheck="false"
        @keydown.enter="go"
      />
      <button v-if="devUrl && current !== devUrl" class="rd-btn" title="带入当前调试预览地址" @click="useDevUrl">带入调试地址</button>
      <button v-if="current" class="rd-btn" :disabled="loading" @click="reload">刷新</button>
      <button v-if="devUrl" class="rd-btn" @click="stop">停止</button>
      <button v-else class="rd-btn rd-primary" :disabled="loading || !wsId" @click="start">
        {{ loading ? '启动中…' : '启动预览' }}
      </button>
    </div>

    <div class="rd-body">
      <iframe v-if="current" :key="reloadKey" :src="current" class="rd-iframe" />
      <div v-else-if="loading" class="rd-empty">正在启动开发服务器（首次需编译，可能要等一会）…</div>
      <div v-else-if="errorMsg" class="rd-err-box">{{ errorMsg }}</div>
      <div v-else class="rd-empty">点「启动预览」运行此工作区，或在地址栏输入地址,或在对话里说「跑一下 / 调一下」</div>

      <div v-if="booting" class="rd-degrade">正在启动，编译完成后会自动刷新；若仍空白，点「刷新」重试</div>
      <div v-if="errors.length" class="rd-errs">
        <div class="rd-errs-title">运行时报错（{{ errors.length }}）</div>
        <div v-for="(e, i) in errors" :key="i" class="rd-err">{{ e }}</div>
      </div>
      <div v-if="showCaptureDegrade" class="rd-degrade">运行时抓取不可用（需 dev 模式）</div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, ref, watch, onMounted, onUnmounted } from 'vue'
import { useCodingStore } from '@/stores/coding'
import { codingApi } from '@/api/coding'

const props = defineProps<{ wsId: string; dark?: boolean }>()
const codingStore = useCodingStore()

const loading = ref(false)
const errorMsg = ref('')
const reloadKey = ref(0)
const booting = ref(false)
let bootTimer: ReturnType<typeof setTimeout> | null = null

// 预览 harness 经 postMessage 回传的运行时报错（桌面包内 CDP 不可用时的唯一信号源）。
// 本地展示 + 上报后端，供 AI 用 get_runtime_errors 按需读取（模式 B：不自动改）。
const capturedErrors = ref<string[]>([])

const preview = computed(() => codingStore.activePreview)
const devUrl = computed(() => preview.value?.dev_url || '')

// 浏览器地址栏:current=实际加载到 iframe 的地址,可手动输入,也可一键带入调试 serve 地址。
const address = ref('')
const current = ref('')
function normalizeUrl(u: string): string {
  const s = u.trim()
  if (!s) return ''
  return /^https?:\/\//i.test(s) ? s : 'http://' + s
}
function go() {
  const u = normalizeUrl(address.value)
  if (!u) return
  address.value = u
  current.value = u
  reloadKey.value++
}
function useDevUrl() {
  if (!devUrl.value) return
  address.value = devUrl.value
  current.value = devUrl.value
  reloadKey.value++
}
// 调试 serve 地址变化(启动预览 / 对话带入)→ 自动加载到地址栏。
watch(devUrl, (u) => { if (u) { address.value = u; current.value = u; reloadKey.value++ } })
// 合并两路：SSE(CDP，dev 模式) + postMessage(harness，包内可用)。
const errors = computed<string[]>(() => [...(preview.value?.errors || []), ...capturedErrors.value])
const captureAvailable = computed(() => preview.value?.capture_available ?? false)
// 手动一键起的预览(source=panel)没尝试 CDP 抓取，不显示「抓取不可用」这条噪音；agent 驱动的才显示。
// 但只要 harness 已经 postMessage 抓到了报错，说明采集其实是通的 → 不再显示「不可用」误导。
const showCaptureDegrade = computed(
  () =>
    !!devUrl.value &&
    !captureAvailable.value &&
    preview.value?.source !== 'panel' &&
    capturedErrors.value.length === 0,
)

function _fmtRuntimeError(p: any): string {
  const kind = p?.kind || 'error'
  let s = `[${kind}] ${p?.message ?? ''}`
  if (p?.source) s += ` @ ${p.source}${p.line ? ':' + p.line : ''}`
  return s
}

async function onPreviewMessage(e: MessageEvent) {
  const d = e?.data
  if (!d || d.source !== 'ruijing-preview' || d.type !== 'runtime-error') return
  capturedErrors.value.push(_fmtRuntimeError(d.payload))
  if (capturedErrors.value.length > 50) capturedErrors.value = capturedErrors.value.slice(-50)
  // 上报后端供 agent 读取；失败静默（采集是尽力而为，不能影响预览）。
  if (props.wsId) {
    try { await codingApi.ingestRuntimeErrors(props.wsId, [d.payload]) } catch { /* noop */ }
  }
}

// 一键启动预览：不依赖对话里的 agent 调 run_workspace_preview。
async function start() {
  if (!props.wsId || loading.value) return
  loading.value = true
  errorMsg.value = ''
  capturedErrors.value = []
  try {
    const r = await codingApi.startServe(props.wsId)
    if (r.status === 'error') {
      // 真失败：把后端日志尾(message)显给用户，绝不拼假地址当成功(否则白屏吞错)。
      errorMsg.value = r.message || '启动失败'
      return
    }
    const url = r.url || (r.port ? `http://127.0.0.1:${r.port}/` : '')
    if (!url) {
      errorMsg.value = r.message || '启动失败：未拿到 dev 地址'
      return
    }
    const ready = r.status === 'ok'  // ok=端口已通 / starting=首屏还在编译
    codingStore.activePreview = {
      source: 'panel',
      dev_url: url,
      status: ready ? 'ok' : 'running',
      errors: [],
      capture_available: false,
      round: null,
    }
    if (!ready) {
      booting.value = true
      if (bootTimer) clearTimeout(bootTimer)
      bootTimer = setTimeout(() => { reload(); booting.value = false }, 3000)
    }
  } catch (e: any) {
    errorMsg.value = e?.response?.data?.detail || e?.message || '启动失败'
  } finally {
    loading.value = false
  }
}

function reload() {
  capturedErrors.value = []   // 重新加载即清旧报错，避免上一轮的噪音
  reloadKey.value++
}

async function stop() {
  if (bootTimer) { clearTimeout(bootTimer); bootTimer = null }
  booting.value = false
  if (props.wsId) await codingApi.stopServe(props.wsId).catch(() => {})
  codingStore.activePreview = null
  errorMsg.value = ''
  capturedErrors.value = []
  current.value = ''
  address.value = ''
}

onMounted(() => { window.addEventListener('message', onPreviewMessage) })
onUnmounted(() => {
  window.removeEventListener('message', onPreviewMessage)
  if (bootTimer) clearTimeout(bootTimer)
})
</script>

<style scoped>
.run-debug-panel { display: flex; flex-direction: column; height: 100%; min-width: 0; }
.rd-toolbar { display: flex; align-items: center; gap: 10px; padding: 8px 12px; border-bottom: 1px solid var(--line, #e5e7eb); flex: 0 0 auto; }
.rd-title { font-size: 13px; font-weight: 600; color: var(--text-1, #222); }
.rd-url { font-size: 12px; color: var(--text-3, #888); font-family: ui-monospace, monospace; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; max-width: 50%; }
.rd-spacer { flex: 1; }
.rd-address {
  flex: 1;
  min-width: 0;
  background: var(--surface, var(--t-bg-input, #fff));
  border: 1px solid var(--line, #e5e7eb);
  border-radius: 8px;
  color: var(--text-1, #222);
  font-family: ui-monospace, SFMono-Regular, "SF Mono", Menlo, monospace;
  font-size: 12px;
  padding: 5px 10px;
  outline: none;
}
.rd-address:focus { border-color: var(--brand, #2f6bff); }
.rd-btn { font-size: 13px; padding: 4px 12px; border: 1px solid var(--line, #e5e7eb); border-radius: 6px; background: var(--surface, #fff); cursor: pointer; }
.rd-btn:hover:not(:disabled) { border-color: var(--brand, #2f6bff); color: var(--brand, #2f6bff); }
.rd-btn:disabled { opacity: 0.5; cursor: not-allowed; }
.rd-primary { color: var(--brand, #2f6bff); border-color: var(--brand, #2f6bff); }
.rd-body { flex: 1; display: flex; flex-direction: column; min-height: 0; }
.rd-iframe { flex: 1; width: 100%; border: 0; display: block; background: #fff; }
.rd-empty { flex: 1; display: flex; align-items: center; justify-content: center; color: var(--text-3, #888); font-size: 13px; padding: 20px; text-align: center; }
.rd-err-box { flex: 1; display: flex; align-items: center; justify-content: center; color: var(--err, #e54d42); font-size: 13px; padding: 20px; text-align: center; }
.rd-errs { flex: 0 0 auto; max-height: 30%; overflow: auto; border-top: 1px solid var(--line, #e5e7eb); padding: 8px 12px; font-family: ui-monospace, monospace; font-size: 12px; }
.rd-errs-title { color: var(--text-2, #666); margin-bottom: 4px; }
.rd-err { color: var(--err, #e54d42); word-break: break-all; padding: 1px 0; }
.rd-degrade { flex: 0 0 auto; padding: 6px 12px; font-size: 12px; color: var(--text-3, #888); border-top: 1px solid var(--line, #e5e7eb); }
</style>
