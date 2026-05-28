<template>
  <div class="wt-root">
    <nav class="wt-tabs">
      <button
        v-for="t in tabs" :key="t.key"
        class="wt-tab" :class="{ active: active === t.key }"
        @click="active = t.key"
      >{{ t.label }}</button>
    </nav>
    <div class="wt-body">
      <RequirementTab v-if="active === 'requirement'" :workspace-id="workspaceId" />
      <ProgressTab v-else-if="active === 'progress'" :workspace-id="workspaceId" />
      <RuntimePreviewTab v-else-if="active === 'preview'" :workspace-id="workspaceId" />
      <OutputTab v-else-if="active === 'output'" :workspace-id="workspaceId" />
      <ObservabilityTab v-else-if="active === 'observe'" :workspace-id="workspaceId" />
      <div v-else class="wt-placeholder">「{{ activeLabel }}」建设中（后续切片接入）</div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'
import RequirementTab from './RequirementTab.vue'
import ProgressTab from './ProgressTab.vue'
import RuntimePreviewTab from './RuntimePreviewTab.vue'
import OutputTab from './OutputTab.vue'
import ObservabilityTab from './ObservabilityTab.vue'

defineProps<{ workspaceId: string }>()
const tabs = [
  { key: 'requirement', label: '需求' },
  { key: 'progress',    label: '进度' },
  { key: 'preview',     label: '预览' },
  { key: 'output',      label: '产出' },
  { key: 'tools',       label: '工具链' },
  { key: 'observe',     label: '可观测' },
]
const active = ref('progress')
const activeLabel = computed(() => tabs.find(t => t.key === active.value)?.label ?? '')
</script>

<style scoped>
.wt-root { display: flex; flex-direction: column; height: 100%; }
.wt-tabs { display: flex; gap: 4px; padding: 8px; border-bottom: 1px solid var(--line); flex-shrink: 0; overflow-x: auto; }
.wt-tab { border: 0; background: transparent; padding: 8px 14px; border-radius: 8px; color: var(--text-3); cursor: pointer; font-size: 13px; white-space: nowrap; transition: background .15s, color .15s; }
.wt-tab:hover { background: var(--surface-3); color: var(--text-2); }
.wt-tab.active { background: var(--brand-soft); color: var(--brand); font-weight: 600; }
.wt-body { flex: 1 1 auto; min-height: 0; overflow: auto; }
.wt-placeholder { padding: 48px; text-align: center; color: var(--text-4); }
</style>
