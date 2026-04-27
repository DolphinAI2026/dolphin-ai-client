<template>
  <div class="confidence-indicator" :class="levelClass" :title="hint">
    <div class="bar-track">
      <div class="bar-fill" :style="{ width: percent + '%' }"></div>
    </div>
    <span class="label">置信度 {{ percent }}%</span>
    <span class="tag">{{ levelLabel }}</span>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'

const props = defineProps<{ confidence: number }>()

const percent = computed(() => Math.round(Math.max(0, Math.min(1, props.confidence)) * 100))

const levelClass = computed(() => {
  if (props.confidence >= 0.75) return 'lvl-ok'
  if (props.confidence >= 0.5) return 'lvl-warn'
  return 'lvl-block'
})

const levelLabel = computed(() => {
  if (props.confidence >= 0.75) return '高'
  if (props.confidence >= 0.5) return '中（建议确认）'
  return '低（建议重问）'
})

const hint = computed(() =>
  `0.4 × scene_confidence + 0.6 × p1_coverage = ${percent.value}%`,
)
</script>

<style scoped>
.confidence-indicator {
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: 13px;
}
.bar-track {
  flex: 1;
  height: 6px;
  background: #e5e7eb;
  border-radius: 3px;
  overflow: hidden;
  min-width: 120px;
  max-width: 220px;
}
.bar-fill {
  height: 100%;
  border-radius: 3px;
  transition: width 200ms ease;
}
.lvl-ok .bar-fill { background: #10b981; }
.lvl-warn .bar-fill { background: #f59e0b; }
.lvl-block .bar-fill { background: #ef4444; }
.label { color: #374151; font-variant-numeric: tabular-nums; }
.tag {
  padding: 2px 8px;
  border-radius: 999px;
  font-size: 11px;
}
.lvl-ok .tag { background: #d1fae5; color: #047857; }
.lvl-warn .tag { background: #fef3c7; color: #92400e; }
.lvl-block .tag { background: #fee2e2; color: #b91c1c; }
</style>
