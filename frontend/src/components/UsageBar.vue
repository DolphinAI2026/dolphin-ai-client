<template>
  <div class="usage-bar">
    <div class="usage-bar-header">
      <span class="usage-bar-label">{{ label }}</span>
      <span class="usage-bar-numbers" :class="{ 'is-full': ratio >= 1, 'is-warn': ratio >= 0.85 && ratio < 1 }">
        {{ used }} / {{ max }}
      </span>
    </div>
    <div class="usage-bar-track">
      <div
        class="usage-bar-fill"
        :class="{ 'is-full': ratio >= 1, 'is-warn': ratio >= 0.85 && ratio < 1 }"
        :style="{ width: barWidth }"
      />
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'

const props = defineProps<{
  label: string
  used: number
  max: number
}>()

const ratio = computed(() => {
  if (!props.max || props.max <= 0) return 0
  return Math.min(props.used / props.max, 1)
})

const barWidth = computed(() => `${Math.round(ratio.value * 100)}%`)
</script>

<style scoped>
.usage-bar {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.usage-bar-header {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
  font-size: 12px;
}
.usage-bar-label { color: var(--t-text-secondary); }
.usage-bar-numbers {
  font-variant-numeric: tabular-nums;
  font-weight: 500;
  color: var(--t-text-primary);
}
.usage-bar-numbers.is-warn { color: var(--warn); }
.usage-bar-numbers.is-full { color: var(--err); }

.usage-bar-track {
  height: 6px;
  border-radius: 4px;
  background: var(--t-bg-input);
  overflow: hidden;
}
.usage-bar-fill {
  height: 100%;
  background: var(--t-brand-color, #4f46e5);
  transition: width 0.25s ease;
}
.usage-bar-fill.is-warn { background: var(--warn); }
.usage-bar-fill.is-full { background: var(--err); }
</style>
