<template>
  <div class="rp">
    <div class="rp-bar">
      <span class="rp-status" :class="runtime?.status">{{ statusLabel }}</span>
      <button class="rp-btn" :disabled="starting" @click="onStart">
        {{ starting ? '启动中…' : (runtime?.preview_url ? '重启预览' : '启动预览') }}
      </button>
      <a v-if="runtime?.preview_url" class="rp-open" :href="runtime.preview_url" target="_blank">新窗口打开 ↗</a>
    </div>
    <iframe v-if="runtime?.preview_url" class="rp-frame" :src="runtime.preview_url"></iframe>
    <div v-else class="rp-empty">
      <p v-if="project && !project.supported">该工作区暂不支持自动预览：{{ project.reason || '未检测到可运行项目' }}</p>
      <p v-else>点上面「启动预览」跑起 dev server</p>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { onlineCodingApi, type OnlinePreviewProject, type OnlinePreviewRuntime } from '@/api/onlineCoding'

const props = defineProps<{ workspaceId: string }>()
const project = ref<OnlinePreviewProject | null>(null)
const runtime = ref<OnlinePreviewRuntime | null>(null)
const starting = ref(false)

const statusLabel = computed(() => ({
  unsupported: '不支持', detected: '已检测', installing: '安装依赖中',
  starting: '启动中', running: '运行中', stopped: '已停止', error: '出错',
} as Record<string, string>)[runtime.value?.status || project.value?.status || ''] || '未知')

async function detect() {
  try { project.value = await onlineCodingApi.detectPreviewRuntime(props.workspaceId) } catch (_) {}
}
async function pollStatus() {
  try {
    runtime.value = await onlineCodingApi.getPreviewRuntimeStatus(props.workspaceId)
  } catch (_) {}
}
async function onStart() {
  starting.value = true
  try {
    const r = await onlineCodingApi.startPreviewRuntime(props.workspaceId)
    runtime.value = r.runtime
    project.value = r.project
    if (!r.runtime?.preview_url) ElMessage.info('已触发启动，稍后点状态刷新或重启')
  } catch (e: any) {
    ElMessage.error('启动预览失败：' + (e?.message || e))
  } finally {
    starting.value = false
  }
}
onMounted(async () => { await detect(); await pollStatus() })
</script>

<style scoped>
.rp { display: flex; flex-direction: column; height: 100%; }
.rp-bar { display: flex; align-items: center; gap: 12px; padding: 8px 12px; border-bottom: 1px solid var(--line); flex-shrink: 0; }
.rp-status { font-size: 12px; color: var(--text-3); padding: 2px 8px; border-radius: 10px; background: var(--surface-3); }
.rp-status.running { color: #16a34a; }
.rp-status.error { color: #dc4040; }
.rp-btn { border: 1px solid var(--brand); background: var(--brand-soft); color: var(--brand); border-radius: 6px; padding: 4px 12px; font-size: 13px; cursor: pointer; }
.rp-btn:disabled { opacity: .6; cursor: default; }
.rp-open { margin-left: auto; font-size: 12px; color: var(--text-3); }
.rp-frame { flex: 1 1 auto; width: 100%; border: 0; background: #fff; }
.rp-empty { flex: 1 1 auto; display: flex; align-items: center; justify-content: center; color: var(--text-4); padding: 24px; text-align: center; }
</style>
