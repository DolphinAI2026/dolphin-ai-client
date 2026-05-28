<template>
  <div class="rq">
    <div v-if="isEmpty" class="rq-empty">AI 还没产出需求基线 —— 去左边描述你想做的应用</div>
    <template v-else>
      <section v-for="s in sections" :key="s.key" v-show="(baseline[s.key] || []).length" class="rq-sec">
        <div class="rq-label">{{ s.label }}</div>
        <ul class="rq-list">
          <li v-for="(item, i) in baseline[s.key]" :key="i">{{ item }}</li>
        </ul>
      </section>
    </template>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { vibeCodingChatApi } from '@/api/vibeCodingChat'

const props = defineProps<{ workspaceId: string }>()
const EMPTY: Record<string, string[]> = { roles: [], features: [], flows: [], external: [], ai_points: [], acceptance: [] }
const baseline = ref<Record<string, string[]>>({ ...EMPTY })
const sections = [
  { key: 'roles', label: '角色' },
  { key: 'features', label: '功能' },
  { key: 'flows', label: '流程' },
  { key: 'external', label: '外部交互' },
  { key: 'ai_points', label: 'AI 决策点' },
  { key: 'acceptance', label: '验收标准' },
]
const isEmpty = computed(() => sections.every(s => !(baseline.value[s.key] || []).length))
let timer: ReturnType<typeof setInterval> | null = null

async function refresh() {
  if (!props.workspaceId) return
  try {
    const d = await vibeCodingChatApi.getThread(props.workspaceId)
    baseline.value = { ...EMPTY, ...((d.thread?.requirement_baseline as any) || {}) }
  } catch (_) { /* 静默：还没线程 */ }
}
onMounted(() => { refresh(); timer = setInterval(refresh, 3000) })
onUnmounted(() => { if (timer) clearInterval(timer) })
</script>

<style scoped>
.rq { padding: 16px; display: flex; flex-direction: column; gap: 18px; }
.rq-empty { padding: 48px; text-align: center; color: var(--text-4); }
.rq-label { font-size: 11px; text-transform: uppercase; letter-spacing: .04em; color: var(--text-4); margin-bottom: 8px; }
.rq-list { margin: 0; padding-left: 18px; display: flex; flex-direction: column; gap: 5px; }
.rq-list li { font-size: 13px; color: var(--text-2); line-height: 1.5; }
</style>
