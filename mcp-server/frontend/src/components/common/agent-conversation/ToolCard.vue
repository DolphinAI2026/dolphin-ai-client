<template>
  <!-- dolphin 风格：一行 inline 极简卡片
       已完成 · 调用 list_apaas_apps_in_env · 工具调用 · 3.4s › -->
  <div
    class="tool-card"
    :class="{ expanded, mini, [`status-${tool.status}`]: true }"
  >
    <div class="tc-head" @click="$emit('toggle')">
      <span class="tc-status-label" :class="tool.status">{{ statusLabel }}</span>
      <span class="tc-sep">·</span>
      <span class="tc-verb">{{ verbLabel }}</span>
      <span class="tc-name">{{ tool.name }}</span>
      <span v-if="brief" class="tc-args">{{ brief }}</span>
      <span class="tc-spacer"></span>
      <!-- 结果摘要 chip：父组件按工具名解析 result 后填 tool.resultSummary，
           让一眼能看出工具做成了什么 — 比单看 "0.0s" 直观得多。
           解析失败/老调用方不填时退化为只显 duration。 -->
      <span v-if="resultSummary" class="tc-result-summary" :title="resultSummary">{{ resultSummary }}</span>
      <span v-else class="tc-meta">工具调用</span>
      <!-- 时长 chip：仅当 >= 100ms 时显示。
           - ask_clarifying_question 之类纯 signal 工具的 duration 永远 ~ 0ms，
             显示 "0.0s" 让人误以为工具没真跑（用户实证 2026-05-21）
           - 100ms 以下 toFixed(1) 都是 0.0s，没有信息量 — 去掉减噪音
           - >= 100ms 的工具（aPaaS API / SSE 等）才显示，仍是 "0.1s / 25.0s" 形式 -->
      <span v-if="tool.duration_ms && tool.duration_ms >= 100" class="tc-sep">·</span>
      <span v-if="tool.duration_ms && tool.duration_ms >= 100" class="tc-duration">{{ (tool.duration_ms / 1000).toFixed(1) }}s</span>
      <span class="tc-toggle">›</span>
    </div>
    <div class="tc-body" v-if="expanded">
      <div class="tc-section" v-if="tool.args && !tool.argsBrief">
        <div class="tc-section-label">参数</div>
        <pre>{{ formatArgs(tool.args) }}</pre>
      </div>
      <div class="tc-section" v-if="tool.result">
        <div class="tc-section-label">输出</div>
        <pre>{{ tool.result }}</pre>
      </div>
      <div class="tc-section running-hint" v-else-if="tool.status === 'running'">
        <span class="dots"><span></span><span></span><span></span></span>
        <span>执行中…</span>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import type { AgentToolPayload } from './types'

const props = defineProps<{
  tool: AgentToolPayload
  expanded?: boolean
  mini?: boolean
}>()

defineEmits<{ (e: 'toggle'): void }>()

const icon = computed(() => {
  const n = (props.tool.name || '').toLowerCase()
  if (n.includes('read') || n.includes('cat')) return '📖'
  if (n.includes('write') || n.includes('edit')) return '✏️'
  if (n.includes('bash') || n.includes('exec') || n.includes('run')) return '⚡'
  if (n.includes('search') || n.includes('grep') || n.includes('find')) return '🔍'
  if (n.includes('list') || n.includes('ls')) return '📋'
  if (n.includes('todo')) return '✅'
  if (n.includes('ask')) return '❓'
  return '⚒'
})

const brief = computed(() => {
  if (props.tool.argsBrief) return props.tool.argsBrief
  // 退化：如果 args 是字符串，直接显示；如果是对象，取 path/file/cmd 等常见字段
  const a: any = props.tool.args
  if (!a) return ''
  if (typeof a === 'string') return a
  return a.path || a.file_path || a.filePath || a.cmd || a.command || a.query || ''
})

const resultSummary = computed(() => {
  if (props.tool.resultSummary) return props.tool.resultSummary
  if (props.tool.name === 'ask_clarifying_question' && props.tool.status === 'success') {
    return '✅ 已发出澄清问题'
  }
  return ''
})

const statusGlyph = computed(() => {
  switch (props.tool.status) {
    case 'success': return '✓'
    case 'error': return '✗'
    case 'running': return '◌'
    case 'pending': return '·'
    default: return ''
  }
})

// dolphin 风格状态文字标签（不是图标）
const statusLabel = computed(() => {
  switch (props.tool.status) {
    case 'success': return '已完成'
    case 'error': return '失败'
    case 'running': return '执行中'
    case 'pending': return '准备中'
    default: return ''
  }
})

// 按工具名前缀推断动作动词（"调用 / 读取 / 写入 / 执行"），dolphin 风格"已完成 · 读取 SKILL.md · 文件读取"
const verbLabel = computed(() => {
  const n = (props.tool.name || '').toLowerCase()
  if (props.tool.name === '设计文档') return '生成'
  if (n.startsWith('read') || n.includes('_read')) return '读取'
  if (n.startsWith('write') || n.includes('_write')) return '写入'
  if (n.startsWith('edit') || n.includes('_edit')) return '编辑'
  if (n.startsWith('run') || n.includes('_run') || n.includes('exec') || n.includes('command')) return '执行'
  if (n.startsWith('list') || n.startsWith('query') || n.startsWith('get_') || n.startsWith('search')) return '查询'
  if (n.startsWith('check') || n.startsWith('validate')) return '校验'
  if (n.startsWith('create') || n.startsWith('generate')) return '创建'
  if (n.startsWith('deploy') || n.startsWith('publish') || n.startsWith('upload')) return '发布'
  return '调用'
})

function formatArgs(args: any): string {
  if (typeof args === 'string') return args
  try {
    return JSON.stringify(args, null, 2)
  } catch {
    return String(args)
  }
}
</script>

<style scoped>
/* dolphin 风格：极简一行 inline 横条卡片 */
.tool-card {
  border: 1px solid rgba(116, 128, 171, 0.14);
  border-radius: 999px;
  background: rgba(116, 128, 171, 0.04);
  overflow: hidden;
  font-size: 12.5px;
  max-width: 100%;
  display: inline-flex;
  flex-direction: column;
  transition: border-color 0.15s, background 0.15s;
}
.tool-card.expanded {
  border-radius: 12px;
  background: rgba(116, 128, 171, 0.06);
}
.tool-card.mini { font-size: 11.5px; }
.tool-card.status-running {
  border-color: rgba(59, 130, 246, 0.28);
  background: rgba(59, 130, 246, 0.05);
}
.tool-card.status-error {
  border-color: rgba(239, 68, 68, 0.32);
  background: rgba(239, 68, 68, 0.04);
}

.tc-head {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 5px 14px;
  cursor: pointer;
  white-space: nowrap;
}
.tc-head:hover { background: rgba(59, 130, 246, 0.05); }

.tc-status-label {
  font-size: 12px;
  font-weight: 600;
}
.tc-status-label.success { color: #16a34a; }
.tc-status-label.error { color: #dc2626; }
.tc-status-label.running { color: #3b82f6; }
.tc-status-label.pending { color: rgba(116, 128, 171, 0.85); }

.tc-sep {
  color: rgba(116, 128, 171, 0.5);
  font-size: 11px;
  margin: 0 2px;
}
.tc-verb {
  color: rgba(31, 41, 55, 0.7);
  font-size: 12px;
}
.tc-name {
  font-weight: 600;
  color: var(--t-text-primary, #1f2937);
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 12px;
}
.tc-args {
  color: rgba(116, 128, 171, 0.85);
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 11px;
  margin-left: 4px;
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: 220px;
}
.tc-spacer { flex: 1; min-width: 8px; }
.tc-meta {
  color: rgba(116, 128, 171, 0.85);
  font-size: 11.5px;
}
/* 结果摘要 chip — 比 .tc-meta 更醒目（深色字 + 浅底）让用户一眼扫到 */
.tc-result-summary {
  color: rgba(31, 41, 55, 0.92);
  font-size: 11.5px;
  font-weight: 500;
  max-width: 360px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.tool-card.status-success .tc-result-summary { color: #15803d; }
.tool-card.status-error .tc-result-summary { color: #b91c1c; }
.tc-duration {
  font-size: 11.5px;
  color: rgba(116, 128, 171, 0.85);
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
}
.tc-toggle {
  font-size: 14px;
  color: rgba(116, 128, 171, 0.7);
  transition: transform 0.18s;
  margin-left: 4px;
}
.tool-card.expanded .tc-toggle { transform: rotate(90deg); }

/* 老的圆点状态 + 黄色 emoji icon 都不再用，但保留 .tc-status 兼容 */
.tc-status {
  font-size: 12px;
  width: 14px;
  text-align: center;
  display: none;
}

.tc-body {
  padding: 0 12px 10px;
  border-top: 1px solid var(--t-border-soft, rgba(116, 128, 171, 0.12));
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding-top: 8px;
}
.tc-section-label {
  font-size: 10.5px;
  font-weight: 700;
  color: var(--t-text-muted);
  letter-spacing: 0.04em;
  text-transform: uppercase;
}
.tc-section pre {
  background: var(--t-bg-soft, rgba(15, 23, 42, 0.06));
  padding: 8px 10px;
  border-radius: 6px;
  font-size: 11.5px;
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  color: var(--t-text-secondary);
  overflow-x: auto;
  white-space: pre-wrap;
  word-break: break-word;
  max-height: 320px;
  overflow-y: auto;
  margin: 0;
}
.running-hint {
  display: flex;
  align-items: center;
  gap: 8px;
  color: var(--t-text-muted);
  font-size: 12px;
}
.running-hint .dots {
  display: inline-flex;
  gap: 3px;
}
.running-hint .dots span {
  width: 5px;
  height: 5px;
  border-radius: 999px;
  background: currentColor;
  opacity: 0.4;
  animation: tc-typing 1.1s infinite;
}
.running-hint .dots span:nth-child(2) { animation-delay: 0.14s; }
.running-hint .dots span:nth-child(3) { animation-delay: 0.28s; }

@keyframes tc-typing {
  0%, 60%, 100% { opacity: 0.3; }
  30% { opacity: 1; }
}
@keyframes tc-spin {
  to { transform: rotate(360deg); }
}
</style>
