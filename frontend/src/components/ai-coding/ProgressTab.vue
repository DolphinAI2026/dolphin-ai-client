<template>
  <div class="pg">
    <div class="pg-head">
      <span class="pg-title">执行进度</span>
      <button class="pg-refresh" @click="refresh">刷新</button>
    </div>

    <div v-if="todos.length" class="pg-section">
      <div class="pg-label">任务清单</div>
      <div v-for="t in todos" :key="t.id" class="pg-todo" :class="t.status">
        <span class="pg-ic">{{ todoIcon(t.status) }}</span><span>{{ t.content }}</span>
      </div>
    </div>

    <div v-if="toolCalls.length" class="pg-section">
      <div class="pg-label">执行步骤</div>
      <ol class="pg-steps">
        <li v-for="tc in toolCalls" :key="tc.id" class="pg-step" :class="tc.status">
          <span class="pg-ic">{{ toolIcon(tc.status) }}</span>
          <code class="pg-tool">{{ tc.tool_name }}</code>
          <span class="pg-arg">{{ argSummary(tc.args_json) }}</span>
          <span v-if="tc.duration_ms != null" class="pg-dur">{{ tc.duration_ms }}ms</span>
        </li>
      </ol>
    </div>

    <div v-if="!toolCalls.length && !todos.length" class="pg-empty">
      还没有执行记录 —— 去左边跟 AI 说说要做啥
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, onUnmounted } from 'vue'
import { vibeCodingChatApi, type VibeChatToolCall } from '@/api/vibeCodingChat'

const props = defineProps<{ workspaceId: string }>()
const toolCalls = ref<VibeChatToolCall[]>([])
const todos = ref<Array<{ id: string; content: string; status: string }>>([])
let timer: ReturnType<typeof setInterval> | null = null

async function refresh() {
  if (!props.workspaceId) return
  try {
    const d = await vibeCodingChatApi.getThread(props.workspaceId)
    toolCalls.value = d.tool_calls || []
    todos.value = (d.thread?.todos as any) || []
  } catch (_) { /* 静默：工作区可能还没线程 */ }
}
function busy() {
  return toolCalls.value.some(t => t.status === 'running' || t.status === 'pending')
    || todos.value.some(t => t.status === 'in_progress' || t.status === 'pending')
}
onMounted(() => {
  refresh()
  timer = setInterval(() => { if (busy()) refresh() }, 2000)
})
onUnmounted(() => { if (timer) clearInterval(timer) })

function toolIcon(s: string) { return ({ success: '✓', error: '✗', running: '⟳', pending: '○', aborted: '⊘' } as Record<string, string>)[s] || '•' }
function todoIcon(s: string) { return ({ completed: '✓', in_progress: '⟳', pending: '○' } as Record<string, string>)[s] || '•' }
function argSummary(a: Record<string, any>) {
  const s = JSON.stringify(a || {})
  return s === '{}' ? '' : (s.length > 64 ? s.slice(0, 64) + '…' : s)
}
</script>

<style scoped>
.pg { padding: 16px; display: flex; flex-direction: column; gap: 16px; }
.pg-head { display: flex; align-items: center; justify-content: space-between; }
.pg-title { font-size: 14px; font-weight: 600; color: var(--text-2); }
.pg-refresh { border: 1px solid var(--line); background: transparent; color: var(--text-3); border-radius: 6px; padding: 3px 10px; font-size: 12px; cursor: pointer; }
.pg-refresh:hover { background: var(--surface-3); }
.pg-label { font-size: 11px; text-transform: uppercase; letter-spacing: .04em; color: var(--text-4); margin-bottom: 8px; }
.pg-todo { display: flex; gap: 8px; align-items: center; padding: 5px 0; font-size: 13px; color: var(--text-2); }
.pg-todo.completed { color: var(--text-4); text-decoration: line-through; }
.pg-todo.in_progress { color: var(--brand); }
.pg-steps { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 6px; }
.pg-step { display: flex; gap: 8px; align-items: baseline; font-size: 13px; padding: 6px 8px; border-radius: 6px; background: var(--surface-3); }
.pg-step.running { background: var(--brand-soft); }
.pg-step.error { background: rgba(220, 80, 80, .12); }
.pg-ic { flex: 0 0 auto; width: 14px; text-align: center; }
.pg-tool { font-family: monospace; color: var(--text-2); }
.pg-arg { color: var(--text-4); font-size: 12px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.pg-dur { margin-left: auto; color: var(--text-4); font-size: 11px; }
.pg-empty { padding: 48px; text-align: center; color: var(--text-4); }
</style>
