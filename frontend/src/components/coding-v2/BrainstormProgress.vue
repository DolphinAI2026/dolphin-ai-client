<template>
  <div class="bs-progress">
    <div class="spinner-row">
      <div class="spinner"></div>
      <div class="text">
        <div class="title">🤔 正在理解需求...</div>
        <div class="subtitle">Brainstorm Agent 正在与你对话并产出结构化 Spec</div>
      </div>
    </div>

    <div v-if="pendingBubble" class="waiting">
      <span class="wait-icon">💬</span>
      <span>等待你回答：{{ pendingBubble.question }}</span>
    </div>

    <div v-if="toolTraces.length" class="trace-block">
      <div class="trace-header">思考过程（{{ toolTraces.length }} 步）</div>
      <ol class="trace-list">
        <li v-for="t in visibleTraces" :key="t.id" :class="'st-' + t.status">
          <span class="tool">{{ t.tool }}</span>
          <span v-if="t.args_preview" class="args">{{ t.args_preview }}</span>
          <span class="status-icon">{{ iconFor(t.status) }}</span>
        </li>
      </ol>
      <button
        v-if="toolTraces.length > visibleLimit"
        class="more-btn"
        @click="showAll = !showAll"
      >
        {{ showAll ? '收起' : `查看全部 ${toolTraces.length} 步` }}
      </button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import type { AskUserBubble, ToolTraceEntry } from '@/stores/codingV2'

const props = defineProps<{
  toolTraces: ToolTraceEntry[]
  pendingBubble?: AskUserBubble | null
}>()

const showAll = ref(false)
const visibleLimit = 5

const visibleTraces = computed(() =>
  showAll.value ? props.toolTraces : props.toolTraces.slice(-visibleLimit),
)

function iconFor(status: string): string {
  switch (status) {
    case 'running': return '⏳'
    case 'done': return '✓'
    case 'error': return '✗'
    default: return ''
  }
}
</script>

<style scoped>
.bs-progress {
  background: white;
  border-radius: 10px;
  padding: 16px 18px;
  border: 1px solid #e5e7eb;
  display: flex;
  flex-direction: column;
  gap: 14px;
}
.spinner-row { display: flex; align-items: center; gap: 14px; }
.spinner {
  width: 24px;
  height: 24px;
  border: 3px solid #e5e7eb;
  border-top-color: #3b82f6;
  border-radius: 50%;
  animation: spin 900ms linear infinite;
}
@keyframes spin { to { transform: rotate(360deg); } }
.title { font-weight: 500; color: #111827; }
.subtitle { font-size: 12px; color: #6b7280; margin-top: 2px; }
.waiting {
  padding: 8px 12px;
  background: #fef3c7;
  border-radius: 6px;
  color: #92400e;
  font-size: 13px;
  display: flex;
  gap: 8px;
  align-items: center;
}
.wait-icon { font-size: 14px; }
.trace-block {
  background: #f9fafb;
  border-radius: 6px;
  padding: 10px 12px;
}
.trace-header {
  font-size: 12px;
  color: #6b7280;
  margin-bottom: 6px;
}
.trace-list {
  list-style: none;
  padding: 0;
  margin: 0;
  display: flex;
  flex-direction: column;
  gap: 4px;
  font-size: 12px;
}
.trace-list li {
  display: flex;
  gap: 8px;
  align-items: center;
  color: #4b5563;
}
.tool {
  font-family: Menlo, Monaco, monospace;
  color: #0f172a;
  background: white;
  padding: 1px 6px;
  border-radius: 3px;
}
.args {
  flex: 1;
  color: #6b7280;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.status-icon { font-size: 11px; }
.st-done .status-icon { color: #065f46; }
.st-error .status-icon { color: #b91c1c; }
.more-btn {
  margin-top: 6px;
  background: transparent;
  border: none;
  color: #3b82f6;
  cursor: pointer;
  font-size: 12px;
}
</style>
