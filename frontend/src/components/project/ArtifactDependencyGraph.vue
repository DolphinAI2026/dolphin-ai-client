<template>
  <section v-if="edges.length" class="dep-graph">
    <h3 class="dg-title">跨产物依赖</h3>
    <div v-for="(e, i) in shown" :key="i" class="dg-edge">
      <div class="dg-row">
        <span class="dg-chip" :style="chip(e.from.mode)">{{ e.from.name }}</span>
        <span class="dg-flow">
          <span class="dg-label">{{ e.exposeLabel }}</span>
          <span class="dg-arrow">→</span>
          <span class="dg-label">{{ e.consumeLabel }}</span>
        </span>
        <span class="dg-chip" :style="chip(e.to.mode)">{{ e.to.name }}</span>
      </div>
      <div v-if="e.note" class="dg-note">⚠ {{ e.note }}</div>
    </div>
    <button v-if="edges.length > LIMIT && !expanded" class="dg-more" @click="expanded = true">
      展开其余 {{ edges.length - LIMIT }} 条
    </button>
  </section>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'
import type { ResolvedEdge } from '@/composables/projectVM'

const props = defineProps<{ edges: ResolvedEdge[] }>()
const LIMIT = 6
const expanded = ref(false)
const shown = computed(() => expanded.value ? props.edges : props.edges.slice(0, LIMIT))

function chip(mode: string) {
  return { background: `var(--${mode}-bg)`, color: `var(--${mode})` }
}
</script>

<style scoped>
.dep-graph {
  margin-top: 8px;
  padding: 16px;
  border: 1px solid var(--line-2);
  border-radius: 14px;
  background: var(--surface-2, #fff);
}

.dg-title {
  font-size: 13px;
  color: var(--text-2, #888);
  margin-bottom: 12px;
  font-weight: 600;
}

.dg-edge {
  padding: 10px 0;
  border-top: 1px solid var(--line-1, #eee);
}

.dg-edge:first-of-type {
  border-top: none;
}

.dg-row {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}

.dg-chip {
  padding: 4px 10px;
  border-radius: 8px;
  font-size: 12px;
  font-weight: 600;
  max-width: 160px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.dg-flow {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 11px;
  color: var(--text-2, #888);
}

.dg-label {
  max-width: 160px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.dg-note {
  margin-top: 6px;
  font-size: 12px;
  color: var(--warning, #d9a441);
}

.dg-more {
  margin-top: 8px;
  font-size: 12px;
  background: none;
  border: none;
  color: var(--m, #7C8CFF);
  cursor: pointer;
}
</style>
