<template>
  <div class="ob">
    <div class="ob-grid">
      <div class="ob-card">
        <div class="ob-num">{{ tu.total_tokens.toLocaleString() }}</div>
        <div class="ob-label">总 token <span v-if="tu.estimated" class="ob-est">约</span></div>
      </div>
      <div class="ob-card">
        <div class="ob-num">{{ toolCount }}</div>
        <div class="ob-label">工具调用</div>
      </div>
      <div class="ob-card">
        <div class="ob-num">{{ durationSec }}<span class="ob-unit">s</span></div>
        <div class="ob-label">总耗时</div>
      </div>
      <div class="ob-card">
        <div class="ob-num">¥{{ cost }}</div>
        <div class="ob-label">成本约算</div>
      </div>
    </div>

    <div class="ob-detail">
      <div class="ob-row"><span>输入 token</span><b>{{ tu.prompt_tokens.toLocaleString() }}</b></div>
      <div class="ob-row"><span>输出 token</span><b>{{ tu.completion_tokens.toLocaleString() }}</b></div>
      <div class="ob-row"><span>计费假设</span><b>¥{{ RATE }} / 千 token（粗估）</b></div>
    </div>

    <div v-if="tu.estimated" class="ob-note">⚠ token 为按字符数估算（网关未返回精确 usage）</div>
    <div v-if="tu.total_tokens === 0" class="ob-empty">还没有用量 —— 去左边让 AI 干点活</div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { vibeCodingChatApi } from '@/api/vibeCodingChat'

const props = defineProps<{ workspaceId: string }>()
const RATE = 0.02 // ¥/千 token —— 粗估假设，仅供参考
const EMPTY = { prompt_tokens: 0, completion_tokens: 0, total_tokens: 0, estimated: false }
const tu = ref<{ prompt_tokens: number; completion_tokens: number; total_tokens: number; estimated: boolean }>({ ...EMPTY })
const toolCount = ref(0)
const durationMs = ref(0)
const durationSec = computed(() => (durationMs.value / 1000).toFixed(1))
const cost = computed(() => ((tu.value.total_tokens / 1000) * RATE).toFixed(3))
let timer: ReturnType<typeof setInterval> | null = null

async function refresh() {
  if (!props.workspaceId) return
  try {
    const d = await vibeCodingChatApi.getThread(props.workspaceId)
    tu.value = { ...EMPTY, ...((d.thread?.token_usage as any) || {}) }
    const tcs = d.tool_calls || []
    toolCount.value = tcs.length
    durationMs.value = tcs.reduce((s, t) => s + (t.duration_ms || 0), 0)
  } catch (_) { /* 静默：还没线程 */ }
}
onMounted(() => { refresh(); timer = setInterval(refresh, 3000) })
onUnmounted(() => { if (timer) clearInterval(timer) })
</script>

<style scoped>
.ob { padding: 16px; display: flex; flex-direction: column; gap: 16px; }
.ob-grid { display: grid; grid-template-columns: repeat(2, 1fr); gap: 12px; }
.ob-card { border: 1px solid var(--line); border-radius: 10px; padding: 14px 16px; background: var(--surface-3); }
.ob-num { font-size: 24px; font-weight: 700; color: var(--text-2); line-height: 1.1; }
.ob-unit { font-size: 14px; font-weight: 500; color: var(--text-3); margin-left: 2px; }
.ob-label { font-size: 12px; color: var(--text-4); margin-top: 4px; }
.ob-est { font-size: 10px; color: var(--brand); background: var(--brand-soft); border-radius: 6px; padding: 0 5px; margin-left: 4px; }
.ob-detail { display: flex; flex-direction: column; gap: 6px; }
.ob-row { display: flex; justify-content: space-between; font-size: 13px; color: var(--text-3); padding: 4px 0; border-bottom: 1px dashed var(--line); }
.ob-row b { color: var(--text-2); font-weight: 600; }
.ob-note { font-size: 12px; color: var(--text-4); }
.ob-empty { padding: 32px; text-align: center; color: var(--text-4); }
</style>
