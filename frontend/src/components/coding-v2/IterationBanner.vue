<template>
  <div class="iter-banner" :class="'lvl-' + banner.level">
    <div class="head">
      <span class="icon">{{ iconFor(banner.level) }}</span>
      <span class="lvl">{{ labelFor(banner.level) }}</span>
      <span v-if="banner.confidence > 0" class="conf">
        confidence {{ Math.round(banner.confidence * 100) }}%
      </span>
    </div>
    <div class="body">{{ banner.message || banner.rationale }}</div>
    <div v-if="banner.level === 'cross_scene'" class="action-hint">
      建议点击"新建工作区"重新开始，当前工作区将被保留。
    </div>
  </div>
</template>

<script setup lang="ts">
import type { IterationBanner } from '@/stores/codingV2'

defineProps<{
  banner: IterationBanner
}>()

function iconFor(level: string): string {
  switch (level) {
    case 'trivial': return '⚡'
    case 'minor': return '🔧'
    case 'major': return '🛠️'
    case 'cross_scene': return '⚠️'
    default: return 'ℹ️'
  }
}

function labelFor(level: string): string {
  switch (level) {
    case 'trivial': return '快速修改（直接产 Patch）'
    case 'minor': return '模糊修改（需反问 1 轮）'
    case 'major': return '重大改动（完整 brainstorm）'
    case 'cross_scene': return '跨场景修改'
    default: return level
  }
}
</script>

<style scoped>
.iter-banner {
  padding: 10px 14px;
  border-radius: 8px;
  border: 1px solid transparent;
  display: flex;
  flex-direction: column;
  gap: 6px;
  font-size: 13px;
}
.lvl-trivial { background: #dcfce7; border-color: #bbf7d0; color: #065f46; }
.lvl-minor { background: #dbeafe; border-color: #bfdbfe; color: #1e40af; }
.lvl-major { background: #fef3c7; border-color: #fde68a; color: #92400e; }
.lvl-cross_scene { background: #fee2e2; border-color: #fecaca; color: #991b1b; }

.head { display: flex; align-items: center; gap: 8px; font-weight: 500; }
.icon { font-size: 16px; }
.lvl { flex: 1; }
.conf {
  font-size: 11px;
  opacity: 0.7;
  font-variant-numeric: tabular-nums;
}
.body { font-size: 13px; line-height: 1.5; opacity: 0.9; }
.action-hint { font-size: 12px; opacity: 0.8; font-style: italic; }
</style>
