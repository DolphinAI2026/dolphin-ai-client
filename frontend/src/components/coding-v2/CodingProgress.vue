<template>
  <div class="coding-progress">
    <!-- 无内容时的等待提示（活跃卡才转圈；冻结的历史卡不转） -->
    <div v-if="entries.length === 0 && !frozen" class="waiting-row">
      <IconLoading class="status-icon loading" />
      <span class="waiting-text">正在生成代码，请稍候...</span>
    </div>

    <template v-for="entry in entries" :key="entry.id">

      <!-- ── 里程碑 banner ── -->
      <div v-if="entry.kind === 'milestone'" class="milestone-card">
        <IconComplete class="milestone-check" />
        <span>{{ entry.milestoneText }}</span>
      </div>

      <!-- ── 思考过程（可折叠，默认展开当前进行中） ── -->
      <div v-else-if="entry.kind === 'thinking'" class="card thinking-card" :class="{ 'is-collapsed': entry.collapsed }">
        <button class="card-header" @click="entry.collapsed = !entry.collapsed">
          <svg class="header-icon think-icon" viewBox="0 0 16 16" fill="none">
            <circle cx="8" cy="8" r="6.5" stroke="currentColor" stroke-width="1.2" />
            <path d="M8 5v3.5l2 1.5" stroke="currentColor" stroke-width="1.2" stroke-linecap="round" />
          </svg>
          <span class="card-label">思考过程</span>
          <span class="card-meta">{{ (entry.text || '').length }} 字</span>
          <svg class="chevron" :class="{ rotated: !entry.collapsed }" viewBox="0 0 16 16" fill="none">
            <path d="M4 6l4 4 4-4" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" />
          </svg>
        </button>
        <div v-show="!entry.collapsed" class="thinking-body markdown-body"
             v-html="renderMarkdown(preprocessThinking(entry.text || ''))" />
      </div>

      <!-- ── 工具调用行（read/grep/glob/command 等） ── -->
      <div v-else-if="entry.kind === 'tool'" class="card tool-card" :class="'ts-' + (entry.toolStatus || 'running')">
        <div class="card-header tool-header">
          <span class="header-icon tool-icon">{{ toolIcon(entry.toolName) }}</span>
          <span class="tool-label">{{ toolLabel(entry.toolName) }}</span>
          <span class="tool-args">{{ entry.argsPreview }}</span>
          <span class="status-slot">
            <IconLoading v-if="entry.toolStatus === 'running'" class="status-icon loading" />
            <IconComplete v-else-if="entry.toolStatus === 'done'" class="status-icon ok" />
            <IconError v-else class="status-icon err" />
          </span>
        </div>
      </div>

      <!-- ── 文件写入/编辑（可展开看内容） ── -->
      <div v-else-if="entry.kind === 'file'" class="card file-card"
           :class="['fa-' + (entry.fileAction || 'create'), 'ts-' + (entry.toolStatus || 'running')]">
        <button class="card-header file-header" @click="entry.collapsed = !entry.collapsed">
          <span class="file-badge">{{ fileBadge(entry.fileAction) }}</span>
          <span class="file-path">{{ entry.filePath || '?' }}</span>
          <span class="file-action-label">{{ fileActionLabel(entry.fileAction) }}</span>
          <span class="status-slot">
            <IconLoading v-if="entry.toolStatus === 'running'" class="status-icon loading" />
            <IconComplete v-else-if="entry.toolStatus === 'done'" class="status-icon ok" />
            <IconError v-else class="status-icon err" />
          </span>
          <svg v-if="entry.fileContent" class="chevron" :class="{ rotated: !entry.collapsed }" viewBox="0 0 16 16" fill="none">
            <path d="M4 6l4 4 4-4" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" />
          </svg>
        </button>
        <div v-if="entry.fileContent && !entry.collapsed" class="file-body">
          <CodeBlock :code="entry.fileContent" :file-path="entry.filePath" />
        </div>
      </div>

    </template>

    <!-- 底部运行中（只有当前活跃卡才显示） -->
    <div v-if="!frozen && store.isRunning && store.phase === 'generate'" class="running-footer">
      <IconLoading class="status-icon loading" />
      <span>生成中...</span>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import type { CodingLogEntry } from '@/stores/codingV2'
import { useCodingV2Store } from '@/stores/codingV2'
import { renderMarkdown } from '@/views/coding/useStreamMessages'
import CodeBlock from './CodeBlock.vue'
import IconLoading from './icons/IconLoading.vue'
import IconComplete from './icons/IconComplete.vue'
import IconError from './icons/IconError.vue'

const props = defineProps<{
  /** 如果传入，就走只读快照模式（autofix 多轮时历史 coding-active 卡用） */
  frozenLog?: CodingLogEntry[]
}>()

const store = useCodingV2Store()
const frozen = computed(() => Array.isArray(props.frozenLog))
const entries = computed(() => props.frozenLog ?? store.codingLog)

/**
 * 把 LLM 输出的内联数字序号（比如 "xxx.vue 8. xxx 9. xxx"）拆成独立行，
 * 让 marked 能正确渲染为列表。
 * 命中时机保守，避免误伤普通段落里的数字。
 */
function preprocessThinking(text: string): string {
  if (!text) return ''
  let t = text
  // 中文全角冒号后紧跟数字序号 → 多加一个空行，强制独立成列表块
  t = t.replace(/(：)\s*(\d+\.\s)/g, '$1\n\n$2')
  // markdown 加粗/斜体收尾后紧跟数字序号
  t = t.replace(/(\*\*|\*)\s+(\d+\.\s)/g, '$1\n$2')
  // 通用兜底：用 lookahead 不把列表项 body 吃进匹配里，否则连续两条只会隔一条切一次。
  // 命中 "xxx>  9. mobile/src/..."、"IDENT 16. web/src/..."、".vue 2. web/..." 等
  // LLM 把多条路径写成一行的场景。要求后续 token 是 "N.+路径形/标识形"（含 / 或 . 或 _ 的多字符），
  // 避免误伤普通句子里的数字（比如 "at 8. am"）。
  t = t.replace(/([^\s\n])[ \t]+(?=\d+\.\s+[\w-]+[\/._])/g, '$1\n')
  return t
}

function toolIcon(name?: string): string {
  switch (name) {
    case 'read_file':   return '📄'
    case 'glob_files':  return '📁'
    case 'grep_search': return '🔍'
    case 'run_command': return '⚡'
    default:            return '🔧'
  }
}

function toolLabel(name?: string): string {
  switch (name) {
    case 'read_file':   return '读取'
    case 'glob_files':  return '扫描'
    case 'grep_search': return '搜索'
    case 'run_command': return '执行'
    default:            return name || '工具'
  }
}

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
</script>

<style scoped>
.coding-progress {
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding: 4px 0;
}

/* ── 状态图标（4 种 SVG） ── */
.status-icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  font-size: 16px;
  flex-shrink: 0;
}
.status-icon.loading { color: #7c3aed; }
.status-icon.ok      { color: #10b981; }
.status-icon.err     { color: #ef4444; }
.status-icon.warn    { color: #f59e0b; }

/* ── 等待提示 ── */
.waiting-row {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 14px 18px;
  color: #6b7280;
  font-size: 13px;
  background: white;
  border: 1px solid #e5e7eb;
  border-radius: 10px;
}

/* ── 里程碑（工程脚手架已初始化 等） ── */
.milestone-card {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 12px 16px;
  background: #f0fdf4;
  border: 1px solid #d1fae5;
  border-radius: 10px;
  font-size: 13px;
  font-weight: 500;
  color: #065f46;
}
.milestone-check { color: #10b981; font-size: 18px; }

/* ── 通用卡片容器 ── */
.card {
  background: white;
  border: 1px solid #e5e7eb;
  border-radius: 10px;
  overflow: hidden;
  box-shadow: 0 1px 2px rgba(0, 0, 0, 0.03);
  transition: box-shadow 0.12s;
}
.card-header {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 14px;
  width: 100%;
  background: none;
  border: none;
  text-align: left;
  color: inherit;
  min-height: 40px;
}
button.card-header { cursor: pointer; }
button.card-header:hover { background: #fafafa; }

.header-icon {
  width: 16px;
  height: 16px;
  color: #9ca3af;
  flex-shrink: 0;
}
.card-label {
  font-size: 13px;
  color: #4b5563;
  font-weight: 500;
}
.card-meta {
  font-size: 12px;
  color: #9ca3af;
  margin-left: 2px;
}

/* ── 下拉箭头（复用老 coding 页样式） ── */
.chevron {
  margin-left: auto;
  width: 14px;
  height: 14px;
  color: #9ca3af;
  transition: transform 0.2s;
  flex-shrink: 0;
}
.chevron.rotated { transform: rotate(180deg); }

/* ── 思考过程 ── */
.thinking-card .think-icon { color: #a78bfa; }
.thinking-body {
  padding: 12px 18px 14px;
  font-size: 13px;
  color: #374151;
  line-height: 1.75;
  border-top: 1px solid #f3f4f6;
  background: #fafafa;
  word-break: break-word;
}

/* ── 工具条目 ── */
.tool-header {
  gap: 8px;
}
.tool-icon { font-size: 14px; width: 20px; text-align: center; color: inherit; }
.tool-label {
  font-size: 13px;
  color: #374151;
  font-weight: 500;
  flex-shrink: 0;
}
.tool-args {
  font-size: 12px;
  color: #6b7280;
  flex: 1;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  font-family: 'SF Mono', 'Menlo', 'Monaco', monospace;
}
.status-slot {
  flex-shrink: 0;
  display: inline-flex;
  width: 20px;
  height: 20px;
  align-items: center;
  justify-content: center;
  margin-left: 8px;
}

/* ── 文件卡片 ── */
.file-header { gap: 10px; padding: 10px 14px; }
.file-badge {
  width: 22px;
  height: 22px;
  border-radius: 5px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 14px;
  font-weight: 700;
  flex-shrink: 0;
  font-family: 'SF Mono', 'Menlo', monospace;
}
.fa-create .file-badge { background: #dcfce7; color: #15803d; }
.fa-edit   .file-badge { background: #fef3c7; color: #b45309; }
.fa-delete .file-badge { background: #fee2e2; color: #b91c1c; }

.file-path {
  font-size: 12.5px;
  color: #111827;
  font-family: 'SF Mono', 'Menlo', 'Monaco', monospace;
  flex: 1;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.file-action-label {
  font-size: 11px;
  color: #9ca3af;
  flex-shrink: 0;
  padding: 2px 8px;
  border-radius: 999px;
  background: #f3f4f6;
}
.fa-create .file-action-label { color: #15803d; background: #f0fdf4; }
.fa-edit   .file-action-label { color: #b45309; background: #fffbeb; }
.fa-delete .file-action-label { color: #b91c1c; background: #fef2f2; }

.file-body {
  border-top: 1px solid #f3f4f6;
  max-height: 420px;
  overflow: auto;
}

/* ── 底部运行中 ── */
.running-footer {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 16px;
  font-size: 12px;
  color: #9ca3af;
  background: white;
  border: 1px solid #e5e7eb;
  border-radius: 10px;
}

/* ══════════════════════════════════════════════════════════════
 * Markdown body 样式（思考过程 / 未来复用）
 * ══════════════════════════════════════════════════════════════ */
.markdown-body :deep(h1),
.markdown-body :deep(h2),
.markdown-body :deep(h3),
.markdown-body :deep(h4) {
  font-weight: 600;
  color: #111827;
  margin: 12px 0 6px;
  line-height: 1.4;
}
.markdown-body :deep(h1) { font-size: 16px; }
.markdown-body :deep(h2) { font-size: 14.5px; }
.markdown-body :deep(h3),
.markdown-body :deep(h4) { font-size: 13.5px; }
.markdown-body :deep(p) { margin: 6px 0; }
.markdown-body :deep(strong) { font-weight: 600; color: #111827; }
.markdown-body :deep(em) { font-style: italic; color: #374151; }
.markdown-body :deep(ul),
.markdown-body :deep(ol) { padding-left: 22px; margin: 6px 0; }
.markdown-body :deep(li) { margin: 3px 0; }
.markdown-body :deep(table) {
  border-collapse: collapse;
  width: 100%;
  margin: 10px 0;
  font-size: 12.5px;
}
.markdown-body :deep(th),
.markdown-body :deep(td) {
  border: 1px solid #e5e7eb;
  padding: 6px 10px;
  text-align: left;
  word-break: break-word;
}
.markdown-body :deep(th) { background: #f9fafb; font-weight: 600; color: #111827; }
.markdown-body :deep(code) {
  background: #f3f4f6;
  border-radius: 4px;
  padding: 1px 5px;
  font-family: 'SF Mono', 'Menlo', 'Monaco', monospace;
  font-size: 12px;
  color: #7c3aed;
  word-break: break-word;
}
.markdown-body :deep(pre) {
  background: #f3f4f6;
  border-radius: 6px;
  padding: 10px 12px;
  overflow-x: auto;
  margin: 8px 0;
  border: 1px solid #e5e7eb;
}
.markdown-body :deep(pre code) { background: none; padding: 0; color: #111827; }
.markdown-body :deep(a) { color: #2563eb; text-decoration: none; word-break: break-all; }
.markdown-body :deep(a:hover) { text-decoration: underline; }
.markdown-body :deep(hr) { border: none; border-top: 1px solid #e5e7eb; margin: 12px 0; }
.markdown-body :deep(blockquote) {
  border-left: 3px solid #a78bfa;
  padding-left: 12px;
  margin: 6px 0;
  color: #6b7280;
}
</style>
