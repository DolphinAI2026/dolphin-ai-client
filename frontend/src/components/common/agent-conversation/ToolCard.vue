<template>
  <div
    class="tool-card"
    :class="{ expanded, mini, [`status-${tool.status}`]: true }"
  >
    <div class="tc-head" @click="$emit('toggle')">
      <span v-if="!mini" class="tc-icon">{{ icon }}</span>
      <span v-if="!mini" class="tc-name">{{ tool.name }}</span>
      <span class="tc-args" v-if="brief">{{ brief }}</span>
      <span v-if="tool.duration_ms" class="tc-duration">{{ (tool.duration_ms / 1000).toFixed(1) }}s</span>
      <span class="tc-status" :class="tool.status">{{ statusGlyph }}</span>
      <span class="tc-toggle">▶</span>
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

const statusGlyph = computed(() => {
  switch (props.tool.status) {
    case 'success': return '✓'
    case 'error': return '✗'
    case 'running': return '◌'
    case 'pending': return '·'
    default: return ''
  }
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
.tool-card {
  border: 1px solid var(--t-border-soft, rgba(116, 128, 171, 0.18));
  border-radius: 10px;
  background: var(--t-bg-elevated, #fff);
  overflow: hidden;
  font-size: 12.5px;
  max-width: 720px;
}
.tool-card.mini {
  border-radius: 6px;
  font-size: 11.5px;
}
.tool-card.status-running {
  border-color: rgba(245, 158, 11, 0.4);
}
.tool-card.status-error {
  border-color: rgba(239, 68, 68, 0.4);
  background: rgba(239, 68, 68, 0.04);
}

.tc-head {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 12px;
  cursor: pointer;
}
.tool-card.mini .tc-head {
  padding: 5px 10px;
}
.tc-head:hover {
  background: rgba(99, 102, 241, 0.05);
}
.tc-name {
  font-weight: 600;
  color: var(--t-text-primary);
}
.tc-args {
  flex: 1;
  color: var(--t-text-muted);
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 11.5px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  min-width: 0;
}
.tc-duration {
  font-size: 10.5px;
  color: var(--t-text-muted);
}
.tc-status {
  font-size: 12px;
  width: 14px;
  text-align: center;
}
.tc-status.success { color: #16a34a; }
.tc-status.error { color: #dc2626; }
.tc-status.running { color: #f59e0b; animation: tc-spin 1s linear infinite; display: inline-block; }
.tc-status.pending { color: var(--t-text-muted); }
.tc-toggle {
  font-size: 9px;
  color: var(--t-text-muted);
  transition: transform 0.18s;
}
.tool-card.expanded .tc-toggle { transform: rotate(90deg); }

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
