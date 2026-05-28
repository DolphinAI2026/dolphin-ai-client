<template>
  <div class="wt-root">
    <nav class="wt-tabs">
      <button
        v-for="t in tabs"
        :key="t.key"
        class="wt-tab"
        :class="{ active: active === t.key, disabled: t.disabled }"
        :disabled="t.disabled"
        @click="active = t.key"
      >
        {{ t.label }}<span v-if="t.disabled" class="wt-soon">敬请期待</span>
      </button>
    </nav>
    <div class="wt-body">
      <SpecDesignPanel v-if="active === 'requirement'" :app-id="appId" />
      <PreviewTab
        v-else-if="active === 'preview'"
        :app-id="appId"
        @select-block="$emit('select-block', $event)"
      />
      <div v-else class="wt-placeholder">「{{ activeLabel }}」敬请期待</div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'
import SpecDesignPanel from '@/components/v3/SpecDesignPanel.vue'
import PreviewTab from '@/components/ai-coding/PreviewTab.vue'

defineProps<{ appId: number }>()
defineEmits<{ (e: 'select-block', label: string): void }>()

const tabs = [
  { key: 'requirement', label: '需求', disabled: false },
  { key: 'preview',     label: '预览', disabled: false },
  { key: 'progress',   label: '进度', disabled: true },
  { key: 'output',     label: '产出', disabled: true },
  { key: 'tools',      label: '工具', disabled: true },
  { key: 'observe',    label: '可观测', disabled: true },
]

const active = ref('requirement')
const activeLabel = computed(() => tabs.find(t => t.key === active.value)?.label ?? '')
</script>

<style scoped>
.wt-root {
  display: flex;
  flex-direction: column;
  height: 100%;
}

.wt-tabs {
  display: flex;
  gap: 4px;
  padding: 8px;
  border-bottom: 1px solid var(--line);
  flex-shrink: 0;
}

.wt-tab {
  border: 0;
  background: transparent;
  padding: 8px 12px;
  border-radius: 8px;
  color: var(--text-3);
  cursor: pointer;
  font-size: 13px;
  transition: background 0.15s, color 0.15s;
}

.wt-tab:hover:not(.disabled) {
  background: var(--surface-3);
  color: var(--text-2);
}

.wt-tab.active {
  background: var(--brand-soft);
  color: var(--brand);
  font-weight: 600;
}

.wt-tab.disabled {
  color: var(--text-4);
  cursor: not-allowed;
}

.wt-soon {
  font-size: 10px;
  margin-left: 4px;
  opacity: 0.7;
}

.wt-body {
  flex: 1 1 auto;
  min-height: 0;
  overflow: auto;
}

.wt-placeholder {
  padding: 48px;
  text-align: center;
  color: var(--text-4);
}
</style>
