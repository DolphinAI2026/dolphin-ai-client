<!-- frontend/src/views/coding/RunDebugPanel.vue
     对话驱动的「预览位」：运行/调试由对话里的 agent 触发（run_workspace_preview / C5 自愈），
     本面板只读 codingStore.activePreview 渲染预览 + 报错，不再有手动运行按钮/capture 轮询。 -->
<template>
  <div class="run-debug-panel" :class="{ dark }">
    <div class="rd-toolbar">
      <span class="rd-title">预览</span>
      <span v-if="devUrl" class="rd-url">{{ devUrl }}</span>
      <span class="rd-spacer" />
      <button v-if="devUrl" class="rd-btn" @click="stop">停止</button>
    </div>

    <div class="rd-body">
      <iframe v-if="devUrl" :src="devUrl" class="rd-iframe" />
      <div v-else class="rd-empty">在对话里说「跑一下 / 调一下」，结果会在这里预览</div>

      <div v-if="errors.length" class="rd-errs">
        <div class="rd-errs-title">运行时报错（{{ errors.length }}）</div>
        <div v-for="(e, i) in errors" :key="i" class="rd-err">{{ e }}</div>
      </div>
      <div v-if="devUrl && !captureAvailable" class="rd-degrade">运行时抓取不可用（需 dev 模式）</div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useCodingStore } from '@/stores/coding'
import { codingApi } from '@/api/coding'

const props = defineProps<{ wsId: string; dark?: boolean }>()
const codingStore = useCodingStore()

const preview = computed(() => codingStore.activePreview)
const devUrl = computed(() => preview.value?.dev_url || '')
const errors = computed<string[]>(() => preview.value?.errors || [])
const captureAvailable = computed(() => preview.value?.capture_available ?? false)

async function stop() {
  if (props.wsId) await codingApi.stopServe(props.wsId).catch(() => {})
  codingStore.activePreview = null
}
</script>

<style scoped>
.run-debug-panel { display: flex; flex-direction: column; height: 100%; min-width: 0; }
.rd-toolbar { display: flex; align-items: center; gap: 10px; padding: 8px 12px; border-bottom: 1px solid var(--line, #e5e7eb); flex: 0 0 auto; }
.rd-title { font-size: 13px; font-weight: 600; color: var(--text-1, #222); }
.rd-url { font-size: 12px; color: var(--text-3, #888); font-family: ui-monospace, monospace; }
.rd-spacer { flex: 1; }
.rd-btn { font-size: 13px; padding: 4px 12px; border: 1px solid var(--line, #e5e7eb); border-radius: 6px; background: var(--surface, #fff); cursor: pointer; }
.rd-body { flex: 1; display: flex; flex-direction: column; min-height: 0; }
.rd-iframe { flex: 1; width: 100%; border: 0; display: block; background: #fff; }
.rd-empty { flex: 1; display: flex; align-items: center; justify-content: center; color: var(--text-3, #888); font-size: 13px; padding: 20px; text-align: center; }
.rd-errs { flex: 0 0 auto; max-height: 30%; overflow: auto; border-top: 1px solid var(--line, #e5e7eb); padding: 8px 12px; font-family: ui-monospace, monospace; font-size: 12px; }
.rd-errs-title { color: var(--text-2, #666); margin-bottom: 4px; }
.rd-err { color: var(--err, #e54d42); word-break: break-all; padding: 1px 0; }
.rd-degrade { flex: 0 0 auto; padding: 6px 12px; font-size: 12px; color: var(--text-3, #888); border-top: 1px solid var(--line, #e5e7eb); }
</style>
