<template>
  <div class="coding-progress">
    <!-- 无内容时的等待提示 -->
    <div v-if="store.codingLog.length === 0" class="waiting-row">
      <div class="mini-spinner" />
      <span class="waiting-text">正在生成代码，请稍候...</span>
    </div>

    <template v-for="entry in store.codingLog" :key="entry.id">

      <!-- ── 里程碑 banner ── -->
      <div v-if="entry.kind === 'milestone'" class="milestone-banner">
        <span class="milestone-check">✓</span>
        <span>{{ entry.milestoneText }}</span>
      </div>

      <!-- ── 思考过程（可折叠） ── -->
      <div v-else-if="entry.kind === 'thinking'" class="entry thinking-entry">
        <button
          class="entry-header"
          @click="toggleThinking(entry.id)"
        >
          <span class="entry-icon think-icon">⏱</span>
          <span class="entry-title">思考过程</span>
          <span class="entry-meta">{{ charCount(entry.text) }} 字</span>
          <span class="chevron">{{ expanded.has(entry.id) ? '∧' : '∨' }}</span>
        </button>
        <div v-if="expanded.has(entry.id)" class="thinking-body">
          {{ entry.text }}
        </div>
      </div>

      <!-- ── 工具调用行 ── -->
      <div
        v-else-if="entry.kind === 'tool'"
        class="entry tool-entry"
        :class="'ts-' + (entry.toolStatus || 'running')"
      >
        <span class="entry-icon">{{ toolIcon(entry.toolName) }}</span>
        <span class="tool-label">{{ toolLabel(entry.toolName) }}</span>
        <span class="tool-args">{{ entry.argsPreview }}</span>
        <span class="tool-status-icon">
          <span v-if="entry.toolStatus === 'running'" class="inline-spin" />
          <span v-else-if="entry.toolStatus === 'done'" class="done-dot">✓</span>
          <span v-else class="err-dot">✗</span>
        </span>
        <span class="chevron-expand">∨</span>
      </div>

      <!-- ── 文件写入行 ── -->
      <div
        v-else-if="entry.kind === 'file'"
        class="entry file-entry"
        :class="'fa-' + (entry.fileAction || 'create')"
      >
        <span class="file-badge">{{ fileBadge(entry.fileAction) }}</span>
        <span class="file-path">{{ shortPath(entry.filePath) }}</span>
        <span class="file-action-label">{{ fileActionLabel(entry.fileAction) }}</span>
        <span class="chevron-expand">∨</span>
      </div>

    </template>

    <!-- 运行中：底部 loading 行 -->
    <div v-if="store.isRunning && store.phase === 'generate'" class="running-footer">
      <div class="mini-spinner" />
      <span>生成中...</span>
    </div>
  </div>
</template>

<script setup lang="ts">
import { reactive } from 'vue'
import { useCodingV2Store } from '@/stores/codingV2'

const store = useCodingV2Store()

// 展开的思考 entry id 集合
const expanded = reactive(new Set<string>())

function toggleThinking(id: string) {
  if (expanded.has(id)) expanded.delete(id)
  else expanded.add(id)
}

function charCount(text?: string): number {
  return text?.length ?? 0
}

// ── 工具图标 / 标签 ──
function toolIcon(name?: string): string {
  switch (name) {
    case 'read_file':   return '📄'
    case 'write_file':  return '✏️'
    case 'edit_file':   return '✏️'
    case 'glob_files':  return '📁'
    case 'grep_search': return '🔍'
    case 'run_command': return '⚡'
    default:            return '🔧'
  }
}

function toolLabel(name?: string): string {
  switch (name) {
    case 'read_file':   return '读取'
    case 'write_file':  return '写入'
    case 'edit_file':   return '编辑'
    case 'glob_files':  return '扫描'
    case 'grep_search': return '搜索'
    case 'run_command': return '执行'
    default:            return name || '工具'
  }
}

// ── 文件写入 badge / 标签 ──
function fileBadge(action?: string): string {
  switch (action) {
    case 'create': return '+'
    case 'edit':   return '~'
    case 'delete': return '-'
    default:       return '+'
  }
}

function fileActionLabel(action?: string): string {
  switch (action) {
    case 'create': return '新建'
    case 'edit':   return '修改'
    case 'delete': return '删除'
    default:       return ''
  }
}

function shortPath(p?: string): string {
  if (!p) return '?'
  // 显示最后两段路径，避免过长
  const parts = p.split('/')
  return parts.length > 2 ? parts.slice(-2).join('/') : p
}
</script>

<style scoped>
.coding-progress {
  background: white;
  border-radius: 10px;
  border: 1px solid #e5e7eb;
  overflow: hidden;
  display: flex;
  flex-direction: column;
}

/* ── 等待提示 ── */
.waiting-row {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 14px 16px;
  color: #6b7280;
  font-size: 13px;
}

/* ── 里程碑 banner ── */
.milestone-banner {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 16px;
  background: #f0fdf4;
  border-bottom: 1px solid #d1fae5;
  font-size: 13px;
  font-weight: 500;
  color: #065f46;
}
.milestone-check {
  color: #10b981;
  font-size: 14px;
}

/* ── 通用条目 ── */
.entry {
  border-bottom: 1px solid #f3f4f6;
  display: flex;
  align-items: center;
  min-height: 38px;
}
.entry:last-child { border-bottom: none; }

.entry-icon {
  width: 28px;
  text-align: center;
  font-size: 13px;
  flex-shrink: 0;
}
.entry-header {
  display: flex;
  align-items: center;
  width: 100%;
  background: none;
  border: none;
  cursor: pointer;
  padding: 0 12px 0 8px;
  min-height: 38px;
  text-align: left;
  gap: 6px;
  color: inherit;
}
.entry-header:hover { background: #f9fafb; }

/* ── 思考条目 ── */
.thinking-entry { flex-direction: column; align-items: stretch; }
.think-icon { color: #9ca3af; }
.entry-title {
  font-size: 13px;
  color: #6b7280;
}
.entry-meta {
  font-size: 12px;
  color: #9ca3af;
  margin-left: 4px;
}
.chevron {
  margin-left: auto;
  font-size: 11px;
  color: #9ca3af;
}
.thinking-body {
  padding: 10px 16px 12px 16px;
  font-size: 13px;
  color: #374151;
  line-height: 1.65;
  white-space: pre-wrap;
  border-top: 1px solid #f3f4f6;
  background: #fafafa;
}

/* ── 工具条目 ── */
.tool-entry {
  padding: 0 12px 0 8px;
  gap: 6px;
  cursor: default;
}
.tool-label {
  font-size: 13px;
  color: #374151;
  flex-shrink: 0;
}
.tool-args {
  font-size: 12px;
  color: #6b7280;
  flex: 1;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  font-family: 'Menlo', 'Monaco', monospace;
}
.tool-status-icon { flex-shrink: 0; margin-left: 8px; }
.inline-spin {
  display: inline-block;
  width: 12px;
  height: 12px;
  border: 1.5px solid #e5e7eb;
  border-top-color: #6b7280;
  border-radius: 50%;
  animation: spin 800ms linear infinite;
}
.done-dot { color: #10b981; font-size: 12px; }
.err-dot  { color: #ef4444; font-size: 12px; }
.chevron-expand {
  color: #d1d5db;
  font-size: 10px;
  margin-left: auto;
}

/* ── 文件写入行 ── */
.file-entry {
  padding: 0 12px 0 8px;
  gap: 8px;
  cursor: default;
}
.file-badge {
  width: 20px;
  height: 20px;
  border-radius: 4px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 13px;
  font-weight: 700;
  flex-shrink: 0;
  font-family: monospace;
}
.fa-create .file-badge { background: #dcfce7; color: #15803d; }
.fa-edit   .file-badge { background: #fef3c7; color: #b45309; }
.fa-delete .file-badge { background: #fee2e2; color: #b91c1c; }

.file-path {
  font-size: 12px;
  color: #111827;
  font-family: 'Menlo', 'Monaco', monospace;
  flex: 1;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.file-action-label {
  font-size: 11px;
  color: #9ca3af;
  flex-shrink: 0;
}
.fa-create .file-action-label { color: #15803d; }
.fa-edit   .file-action-label { color: #b45309; }
.fa-delete .file-action-label { color: #b91c1c; }

/* ── 底部运行中 ── */
.running-footer {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 16px;
  border-top: 1px solid #f3f4f6;
  font-size: 12px;
  color: #9ca3af;
}

/* ── 通用 spinner ── */
.mini-spinner {
  width: 14px;
  height: 14px;
  border: 1.5px solid #e5e7eb;
  border-top-color: #6b7280;
  border-radius: 50%;
  animation: spin 800ms linear infinite;
  flex-shrink: 0;
}
@keyframes spin { to { transform: rotate(360deg); } }
</style>
