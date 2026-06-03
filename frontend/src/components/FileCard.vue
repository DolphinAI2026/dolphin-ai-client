<template>
  <div class="msg-file-card">
    <div class="file-card-header" @click="$emit('toggle')">
      <span class="file-card-op" :class="opClass">{{ opSymbol }}</span>
      <span class="file-card-name">{{ fileName }}</span>
      <!-- 编辑:显示 +增 -删 统计(对齐 Claude Code) -->
      <span v-if="isDiff && (addCount || delCount)" class="file-card-stat">
        <span v-if="addCount" class="fc-stat-add">+{{ addCount }}</span>
        <span v-if="delCount" class="fc-stat-del">-{{ delCount }}</span>
      </span>
      <span class="file-card-badge" :class="badgeClass">{{ badgeText }}</span>
      <svg class="file-card-chevron" :class="{ rotated: !collapsed }" viewBox="0 0 16 16" fill="none">
        <path d="M4 6l4 4 4-4" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>
      </svg>
    </div>

    <!-- 编辑:红绿 diff -->
    <div v-if="!collapsed && isDiff" class="file-card-code">
      <div class="fc-diff">
        <div v-for="(d, idx) in diffLines" :key="idx" class="fc-diff-line" :class="`fc-${d.t}`">
          <span class="fc-sign">{{ d.t === 'add' ? '+' : d.t === 'del' ? '-' : ' ' }}</span>
          <span class="fc-text">{{ d.text || ' ' }}</span>
        </div>
      </div>
    </div>
    <!-- 新建/无 old:直接展示内容(带行号) -->
    <div v-else-if="!collapsed && fileContent" class="file-card-code">
      <div class="fc-plain">
        <div v-for="(ln, idx) in plainLines" :key="idx" class="fc-plain-line">
          <span class="fc-ln">{{ idx + 1 }}</span>
          <span class="fc-text">{{ ln || ' ' }}</span>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'

const props = defineProps<{
  /** 操作类型：write=新建、edit=修改 */
  action: 'write' | 'edit'
  fileName?: string
  fileContent?: string
  /** 修改前内容(edit 用),有则渲染红绿 diff */
  oldContent?: string
  collapsed?: boolean
}>()

defineEmits<{ toggle: [] }>()

const opSymbol = computed(() => props.action === 'write' ? '+' : '~')
const opClass = computed(() => props.action === 'write' ? 'file-card-op--new' : 'file-card-op--edit')
const badgeText = computed(() => props.action === 'write' ? '新建' : '修改')
const badgeClass = computed(() => props.action === 'write' ? 'file-card-badge--new' : 'file-card-badge--edit')

const isDiff = computed(() => props.action === 'edit' && props.oldContent != null && props.fileContent != null)

type DiffLine = { t: 'ctx' | 'add' | 'del'; text: string }

// LCS 行级 diff —— edit_file 的 old/new 通常是小片段,O(n*m) 足够。
const diffLines = computed<DiffLine[]>(() => {
  if (!isDiff.value) return []
  const a = (props.oldContent || '').split('\n')
  const b = (props.fileContent || '').split('\n')
  const n = a.length, m = b.length
  const dp: number[][] = Array.from({ length: n + 1 }, () => new Array(m + 1).fill(0))
  for (let i = n - 1; i >= 0; i--)
    for (let j = m - 1; j >= 0; j--)
      dp[i]![j] = a[i] === b[j] ? dp[i + 1]![j + 1]! + 1 : Math.max(dp[i + 1]![j]!, dp[i]![j + 1]!)
  const out: DiffLine[] = []
  let i = 0, j = 0
  while (i < n && j < m) {
    if (a[i] === b[j]) { out.push({ t: 'ctx', text: a[i]! }); i++; j++ }
    else if (dp[i + 1]![j]! >= dp[i]![j + 1]!) { out.push({ t: 'del', text: a[i]! }); i++ }
    else { out.push({ t: 'add', text: b[j]! }); j++ }
  }
  while (i < n) { out.push({ t: 'del', text: a[i]! }); i++ }
  while (j < m) { out.push({ t: 'add', text: b[j]! }); j++ }
  return out
})

const addCount = computed(() => diffLines.value.filter(d => d.t === 'add').length)
const delCount = computed(() => diffLines.value.filter(d => d.t === 'del').length)

const plainLines = computed(() => (props.fileContent || '').split('\n'))
</script>

<style scoped>
.msg-file-card {
  border: 1px solid var(--t-border-subtle);
  border-radius: var(--t-radius-sm);
  overflow: hidden;
  margin: 4px 0;
  background: var(--t-bg-panel);
  box-shadow: var(--t-shadow-sm);
}

.file-card-header {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 7px 12px;
  cursor: pointer;
  font-size: 12px;
  font-family: 'SF Mono', 'Monaco', 'Menlo', monospace;
  transition: background 0.15s;
  background: var(--t-bg-panel);
}
.file-card-header:hover { background: var(--t-bg-panel-hover); }

.file-card-op {
  font-weight: 700;
  font-size: 13px;
  width: 14px;
  text-align: center;
  flex-shrink: 0;
}
.file-card-op--new { color: var(--t-success); }
.file-card-op--edit { color: var(--t-warning); }

.file-card-name {
  flex: 1;
  color: var(--t-text-primary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.file-card-stat {
  display: inline-flex;
  gap: 6px;
  font-size: 11px;
  font-weight: 600;
  flex-shrink: 0;
}
.fc-stat-add { color: var(--t-success); }
.fc-stat-del { color: var(--t-danger, #e5484d); }

.file-card-badge {
  font-size: 10px;
  font-weight: 500;
  padding: 2px 7px;
  border-radius: 10px;
  flex-shrink: 0;
}
.file-card-badge--new { background: var(--t-success-subtle); color: var(--t-success); }
.file-card-badge--edit { background: var(--t-warning-subtle); color: var(--t-warning); }

.file-card-chevron {
  width: 14px;
  height: 14px;
  color: var(--t-text-muted);
  flex-shrink: 0;
  transition: transform 0.2s;
}
.file-card-chevron.rotated { transform: rotate(180deg); }

.file-card-code {
  border-top: 1px solid var(--t-border-subtle);
  max-height: 320px;
  overflow: auto;
  background: var(--t-bg-code);
  font-size: 12px;
  line-height: 1.55;
  font-family: 'SF Mono', 'Monaco', 'Menlo', monospace;
  padding: 6px 0;
}

/* ── diff ── */
.fc-diff-line {
  display: flex;
  align-items: flex-start;
  padding: 0 12px;
  white-space: pre;
}
.fc-diff-line .fc-sign {
  width: 12px;
  flex-shrink: 0;
  color: var(--t-text-muted);
  user-select: none;
}
.fc-diff-line .fc-text { flex: 1; }
.fc-diff-line.fc-add { background: color-mix(in srgb, var(--t-success) 16%, transparent); }
.fc-diff-line.fc-add .fc-sign,
.fc-diff-line.fc-add .fc-text { color: var(--t-success); }
.fc-diff-line.fc-del { background: color-mix(in srgb, var(--t-danger, #e5484d) 14%, transparent); }
.fc-diff-line.fc-del .fc-sign,
.fc-diff-line.fc-del .fc-text { color: var(--t-danger, #e5484d); }
.fc-diff-line.fc-ctx .fc-text { color: var(--t-text-primary); }

/* ── 新建(带行号) ── */
.fc-plain-line {
  display: flex;
  align-items: flex-start;
  padding: 0 12px;
  white-space: pre;
}
.fc-plain-line .fc-ln {
  width: 30px;
  flex-shrink: 0;
  text-align: right;
  margin-right: 12px;
  color: var(--t-text-muted);
  user-select: none;
}
.fc-plain-line .fc-text { flex: 1; color: var(--t-text-primary); }
</style>
