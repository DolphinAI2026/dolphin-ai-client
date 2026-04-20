<template>
  <div class="coding-progress">
    <div class="spinner-row">
      <div class="spinner"></div>
      <div class="text">
        <div class="title">🧑‍💻 正在生成代码...</div>
        <div class="subtitle">Coding Agent 正在按 Spec 写入文件</div>
      </div>
    </div>

    <div v-if="files.length" class="files-block">
      <div class="files-header">已写入 {{ files.length }} 个文件</div>
      <ul class="files-list">
        <li v-for="(f, i) in files" :key="i" :class="'action-' + f.action">
          <span class="action-tag">{{ actionLabel(f.action) }}</span>
          <span class="path">{{ f.path }}</span>
        </li>
      </ul>
    </div>

    <div v-if="visibleTraces.length" class="trace-block">
      <div class="trace-header">工具调用（{{ toolTraces.length }}）</div>
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

    <div v-if="streamedText" class="stream-block">
      <div class="stream-header">思考中...</div>
      <pre class="stream-body">{{ streamedText.slice(-600) }}</pre>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import type { FileWriteEntry, ToolTraceEntry } from '@/stores/codingV2'

const props = defineProps<{
  toolTraces: ToolTraceEntry[]
  files: FileWriteEntry[]
  streamedText?: string
}>()

const showAll = ref(false)
const visibleLimit = 8

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

function actionLabel(action: string): string {
  return { create: '✨ 创建', edit: '✏️ 修改', delete: '🗑️ 删除' }[action] || action
}
</script>

<style scoped>
.coding-progress {
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
  border-top-color: #10b981;
  border-radius: 50%;
  animation: spin 900ms linear infinite;
}
@keyframes spin { to { transform: rotate(360deg); } }
.title { font-weight: 500; color: #111827; }
.subtitle { font-size: 12px; color: #6b7280; margin-top: 2px; }
.files-block {
  background: #f0fdf4;
  border-radius: 6px;
  padding: 10px 12px;
}
.files-header {
  color: #065f46;
  font-size: 12px;
  margin-bottom: 6px;
}
.files-list {
  list-style: none;
  padding: 0;
  margin: 0;
  display: flex;
  flex-direction: column;
  gap: 4px;
  font-size: 12px;
}
.files-list li {
  display: flex;
  gap: 8px;
  align-items: center;
}
.action-tag {
  padding: 1px 6px;
  border-radius: 3px;
  font-size: 11px;
  color: white;
}
.action-create .action-tag { background: #10b981; }
.action-edit .action-tag { background: #3b82f6; }
.action-delete .action-tag { background: #ef4444; }
.path {
  font-family: Menlo, Monaco, monospace;
  color: #0f172a;
}
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
.stream-block {
  background: #0f172a;
  border-radius: 6px;
  padding: 10px 12px;
}
.stream-header { color: #94a3b8; font-size: 11px; margin-bottom: 4px; }
.stream-body {
  margin: 0;
  color: #e2e8f0;
  font-size: 11px;
  max-height: 160px;
  overflow: auto;
  white-space: pre-wrap;
  word-break: break-word;
}
</style>
