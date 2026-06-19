<template>
  <div class="preview-panel">
    <header class="pv-toolbar">
      <span class="pv-title">预览</span>
      <span v-if="devUrl" class="pv-url" :title="devUrl">{{ devUrl }}</span>
      <span class="pv-spacer" />
      <button v-if="!devUrl" class="pv-btn pv-primary" :disabled="loading || !wsId" @click="start">
        {{ loading ? '启动中…' : '启动预览' }}
      </button>
      <template v-else>
        <button class="pv-btn" title="刷新页面" @click="reload">刷新</button>
        <button class="pv-btn" :disabled="loading" @click="stop">停止</button>
      </template>
    </header>
    <div class="pv-body">
      <iframe v-if="devUrl" ref="frame" :src="devUrl" class="pv-iframe" />
      <div v-else-if="loading" class="pv-empty">正在启动开发服务器(首次需构建,可能 1-2 分钟)…</div>
      <div v-else-if="error" class="pv-error">{{ error }}</div>
      <div v-else class="pv-empty">点「启动预览」运行此工作区的页面</div>
    </div>
  </div>
</template>
<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { codingApi } from '@/api/coding'
import type { Binding } from '../binding'

const props = defineProps<{ binding: Binding; sessionId?: number | null; artifact?: any }>()
const wsId = computed(() => (props.binding.kind === 'workspace' ? props.binding.workspaceId : null))

const devUrl = ref('')
const loading = ref(false)
const error = ref('')
const frame = ref<HTMLIFrameElement | null>(null)

async function refreshStatus() {
  if (!wsId.value) return
  try {
    const s = await codingApi.getServeStatus(wsId.value)
    if (s.running && s.url) devUrl.value = s.url
  } catch {
    /* 状态查询失败不致命 */
  }
}

async function start() {
  if (!wsId.value) return
  loading.value = true
  error.value = ''
  try {
    const r = await codingApi.startServe(wsId.value)
    if (r.status === 'error') {
      error.value = r.message || '启动失败'
      return
    }
    const url = r.url || (r.port ? `http://127.0.0.1:${r.port}/` : '')
    if (!url) {
      error.value = r.message || '启动失败:未拿到 dev url'
      return
    }
    devUrl.value = url
    // starting=首屏还在编译: 3 秒后自动重载一次, 避免指向没就绪的地址白屏。
    if (r.status !== 'ok') setTimeout(reload, 3000)
  } catch (e: any) {
    error.value = e?.response?.data?.detail || e?.message || '启动失败'
  } finally {
    loading.value = false
  }
}

async function stop() {
  if (!wsId.value) return
  loading.value = true
  try {
    await codingApi.stopServe(wsId.value)
  } catch {
    /* ignore */
  }
  devUrl.value = ''
  loading.value = false
}

function reload() {
  if (frame.value) frame.value.src = devUrl.value
}

onMounted(refreshStatus)
</script>
<style scoped>
.preview-panel {
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: 0;
}
.pv-toolbar {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 10px;
  border-bottom: 1px solid var(--line);
  flex-shrink: 0;
}
.pv-title {
  font-size: 13px;
  font-weight: var(--fw-semibold, 600);
  color: var(--text);
}
.pv-url {
  font-size: 11px;
  color: var(--text-3);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 40%;
  font-family: ui-monospace, monospace;
}
.pv-spacer {
  flex: 1;
}
.pv-btn {
  padding: 4px 10px;
  border: 1px solid var(--line);
  border-radius: 6px;
  background: var(--surface);
  color: var(--text-2);
  cursor: pointer;
  font-size: 12px;
}
.pv-btn:hover:not(:disabled) {
  border-color: var(--brand);
  color: var(--brand);
}
.pv-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
.pv-primary {
  color: var(--brand);
  border-color: var(--brand);
}
.pv-body {
  flex: 1;
  min-height: 0;
  position: relative;
}
.pv-iframe {
  width: 100%;
  height: 100%;
  border: 0;
  background: #fff;
}
.pv-empty,
.pv-error {
  padding: 24px;
  opacity: 0.6;
}
.pv-error {
  color: #dc2626;
  opacity: 1;
}
</style>
