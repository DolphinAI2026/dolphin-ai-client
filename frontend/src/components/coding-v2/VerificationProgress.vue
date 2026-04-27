<template>
  <div class="verification-progress">
    <!-- ── 运行中的紧凑头部（活跃卡且未出报告时才显示；冻结卡直接跳到下方总结卡） ── -->
    <div v-if="!isFinalized && !frozen" class="card header-card" :class="statusClass">
      <div class="card-header header-row">
        <span class="status-slot status-lg">
          <IconError v-if="isAborted" class="status-icon err" />
          <IconLoading v-else class="status-icon loading" />
        </span>
        <span class="card-label">{{ titleText }}</span>
        <span v-if="liveCheckedCount > 0" class="pill pill-live">
          {{ liveCheckedCount }} 条已核
        </span>
      </div>
    </div>

    <!-- ── 等待态 ── -->
    <div v-if="!isFinalized && !isAborted && !frozen && rawLog.length === 0" class="waiting-row">
      <IconLoading class="status-icon loading" />
      <span class="waiting-text">VerificationAgent 正在启动…</span>
    </div>

    <!-- ── 步骤流水：工具调用 / AC 实时结果（步骤在上，总结在下，就像读书） ── -->
    <template v-for="entry in visibleVerifyLog" :key="entry.id">
      <!-- 工具调用卡 -->
      <div
        v-if="entry.kind === 'tool'"
        class="card tool-card"
        :class="'ts-' + (entry.toolStatus || 'running')"
      >
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

      <!-- AC 结果卡（只在运行中出现） -->
      <div
        v-else-if="entry.kind === 'ac_result'"
        class="card ac-card"
        :class="'ac-' + (entry.acStatus || 'pending')"
      >
        <div class="card-header ac-header">
          <span class="ac-badge">AC #{{ entry.acIndex }}</span>
          <span class="ac-text">{{ acStatusLabel(entry.acStatus) }}</span>
          <span v-if="entry.confidence != null" class="ac-conf">
            {{ Math.round((entry.confidence || 0) * 100) }}%
          </span>
          <span class="status-slot">
            <IconComplete v-if="entry.acStatus === 'passed'" class="status-icon ok" />
            <IconError v-else-if="entry.acStatus === 'failed'" class="status-icon err" />
            <IconWarn v-else-if="entry.acStatus === 'needs_review'" class="status-icon warn" />
          </span>
        </div>
      </div>
    </template>

    <!-- ── 运行中 footer（仅在真·进行中展示） ── -->
    <div v-if="!isFinalized && !isAborted && !frozen && rawLog.length > 0" class="running-footer">
      <IconLoading class="status-icon loading" />
      <span>继续验收…</span>
    </div>

    <!-- ── 终局总结卡：步骤跑完后，合成一张大卡（头部 + AI 总结 + AC 列表） ── -->
    <div v-if="isFinalized" class="card summary-card" :class="statusClass">
      <div class="card-header header-row">
        <span class="status-slot status-lg">
          <IconComplete v-if="overallStatus === 'passed'" class="status-icon ok" />
          <IconError v-else-if="overallStatus === 'failed'" class="status-icon err" />
          <IconWarn v-else class="status-icon warn" />
        </span>
        <span class="card-label">{{ titleText }}</span>
        <span class="pill">{{ passedCount }} / {{ totalCount || '?' }}</span>
        <button
          v-if="report?.summary"
          class="summary-toggle"
          :class="{ open: summaryOpen }"
          @click="summaryOpen = !summaryOpen"
        >
          {{ summaryOpen ? '收起 AI 总结' : '查看 AI 总结' }}
          <svg class="mini-chev" :class="{ rotated: summaryOpen }" viewBox="0 0 16 16" fill="none">
            <path d="M4 6l4 4 4-4" stroke="currentColor" stroke-width="1.5"
                  stroke-linecap="round" stroke-linejoin="round" />
          </svg>
        </button>
      </div>
      <div v-if="report?.summary && summaryOpen" class="summary-body">
        {{ report.summary }}
      </div>

      <div v-if="(report?.items?.length ?? 0) > 0" class="ac-final-list">
        <div
          v-for="item in report!.items"
          :key="`final-${item.index}`"
          :class="['ac-final-row', 'item-' + item.status, { expanded: isExpanded(item.index) }]"
        >
          <button class="ac-final-header" @click="toggle(item.index)">
            <span class="status-slot">
              <IconComplete v-if="item.status === 'passed'" class="status-icon ok" />
              <IconError v-else-if="item.status === 'failed'" class="status-icon err" />
              <IconWarn v-else-if="item.status === 'needs_review'" class="status-icon warn" />
              <IconLoading v-else class="status-icon loading" />
            </span>
            <span class="ac-desc">{{ item.description || '（描述缺失）' }}</span>
            <span v-if="item.confidence != null" class="ac-conf">
              {{ Math.round((item.confidence || 0) * 100) }}%
            </span>
            <svg
              v-if="item.evidence"
              class="chevron"
              :class="{ rotated: isExpanded(item.index) }"
              viewBox="0 0 16 16"
              fill="none"
            >
              <path d="M4 6l4 4 4-4" stroke="currentColor" stroke-width="1.5"
                    stroke-linecap="round" stroke-linejoin="round" />
            </svg>
          </button>
          <div v-if="item.evidence && isExpanded(item.index)" class="ac-evidence">
            {{ item.evidence }}
          </div>
        </div>
      </div>
    </div>

    <!-- ── 底部结果提示卡 ── -->
    <div
      v-if="isFinalized && overallStatus !== 'pending'"
      class="hint-card"
      :class="'hint-' + overallStatus"
    >
      <template v-if="overallStatus === 'passed'">所有验收点通过</template>
      <template v-else-if="overallStatus === 'failed'">
        存在未通过项；系统会自动让 CodingAgent 重跑（最多 2 次）
      </template>
      <template v-else-if="overallStatus === 'partial'">
        部分通过，请人工确认证据后决定
      </template>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue'
import type { VerifyLogEntry, VerificationReport } from '@/stores/codingV2'
import { useCodingV2Store } from '@/stores/codingV2'
import IconLoading from './icons/IconLoading.vue'
import IconComplete from './icons/IconComplete.vue'
import IconError from './icons/IconError.vue'
import IconWarn from './icons/IconWarn.vue'

const props = defineProps<{
  /** autofix 多轮场景下，历史 verify-active 卡把自己的日志 + 报告塞进来 */
  frozenLog?: VerifyLogEntry[]
  frozenReport?: VerificationReport | null
}>()

const store = useCodingV2Store()
const frozen = computed(() => Array.isArray(props.frozenLog))

const report = computed<VerificationReport | null>(
  () => (frozen.value ? (props.frozenReport ?? null) : store.lastVerificationReport),
)
const rawLog = computed<VerifyLogEntry[]>(() => props.frozenLog ?? store.verifyLog)

const isFinalized = computed(() => !!report.value)
const overallStatus = computed(() => report.value?.overall_status || 'pending')
// 冻结卡不跑活动态；只有当前活跃卡才会出现 aborted
const isAborted = computed(() =>
  !frozen.value && !isFinalized.value && store.phase === 'failed',
)

const statusClass = computed(() => {
  if (isAborted.value) return 'status-aborted'
  if (!isFinalized.value) return 'status-running'
  return 'status-' + overallStatus.value
})
const titleText = computed(() => {
  if (isAborted.value) return '验收未完成'
  if (!isFinalized.value) return '验收中…'
  if (overallStatus.value === 'passed') return '验收通过'
  if (overallStatus.value === 'failed') return '验收失败'
  if (overallStatus.value === 'partial') return '部分通过'
  return '验收完成'
})

const liveCheckedCount = computed(() =>
  frozen.value ? (rawLog.value.filter(e => e.kind === 'ac_result').length) : store.liveVerifyItems.length,
)
const passedCount = computed(() => report.value?.passed_count ?? 0)
const totalCount = computed(() => report.value?.items?.length ?? 0)

// 筛选规则：
// - check_ac / emit_report 工具行恒隐藏
// - ac_result 卡只在运行中保留；终局后和底部最终 AC 列表重复，隐掉
// - 其它（代码搜索 / 读取文件 等真实轨迹）永远保留
const visibleVerifyLog = computed(() =>
  rawLog.value.filter((e) => {
    if (e.kind === 'tool' && (e.toolName === 'emit_report' || e.toolName === 'check_ac')) {
      return false
    }
    if (e.kind === 'ac_result' && isFinalized.value) return false
    return true
  }),
)

const summaryOpen = ref(false)
const expandedSet = reactive(new Set<number>())

function toggle(idx: number) {
  if (expandedSet.has(idx)) expandedSet.delete(idx)
  else expandedSet.add(idx)
}
function isExpanded(idx: number): boolean {
  return expandedSet.has(idx)
}

// 失败 / 待核项默认展开
watch(report, (r) => {
  if (!r) return
  for (const it of r.items) {
    if (it.status === 'failed' || it.status === 'needs_review') {
      expandedSet.add(it.index)
    }
  }
}, { immediate: true })

function toolIcon(name?: string): string {
  switch (name) {
    case 'grep_code': return '🔍'
    case 'read_file': return '📄'
    case 'check_ac': return '✅'
    case 'emit_report': return '📋'
    default: return '🔧'
  }
}
function toolLabel(name?: string): string {
  switch (name) {
    case 'grep_code': return '代码搜索'
    case 'read_file': return '读取文件'
    case 'check_ac': return '核验 AC'
    case 'emit_report': return '汇总报告'
    default: return name || '工具'
  }
}
function acStatusLabel(s?: string): string {
  switch (s) {
    case 'passed': return '通过'
    case 'failed': return '未通过'
    case 'needs_review': return '待人工核对'
    case 'pending': return '等待'
    default: return ''
  }
}
</script>

<style scoped>
/* ══════════════════════════════════════════════════════════════
 * 与 CodingProgress 一致的分块卡片布局
 * ══════════════════════════════════════════════════════════════ */
.verification-progress {
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding: 4px 0;
}

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

/* ── 通用卡片 ── */
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
  font-size: 13.5px;
  color: #111827;
  font-weight: 600;
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
.status-slot.status-lg {
  width: 22px;
  height: 22px;
  margin-left: 0;
}

/* ── 头部卡 / 总结卡共用样式 ── */
.header-card .header-row,
.summary-card .header-row {
  gap: 10px;
  padding: 12px 16px;
  min-height: 44px;
}
.summary-card.status-passed { border-color: #bbf7d0; }
.summary-card.status-failed { border-color: #fecaca; }
.summary-card.status-partial { border-color: #fed7aa; }
.pill {
  font-size: 12px;
  color: #6b7280;
  padding: 2px 10px;
  background: #f3f4f6;
  border-radius: 999px;
  font-variant-numeric: tabular-nums;
}
.pill-live { background: #ede9fe; color: #6d28d9; }
.status-passed .pill { background: #dcfce7; color: #15803d; }
.status-failed .pill { background: #fee2e2; color: #b91c1c; }
.status-partial .pill { background: #fef3c7; color: #b45309; }
.status-aborted { border-color: #fecaca; }
.status-aborted .card-label { color: #b91c1c; }

.summary-toggle {
  margin-left: auto;
  background: transparent;
  border: 1px solid #e5e7eb;
  color: #6b7280;
  font-size: 12px;
  padding: 4px 10px;
  border-radius: 6px;
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  gap: 4px;
  transition: background 0.12s, color 0.12s;
}
.summary-toggle:hover { background: #f9fafb; color: #111827; }
.summary-toggle.open { background: #f3f4f6; color: #111827; }
.mini-chev {
  width: 11px;
  height: 11px;
  transition: transform 0.2s;
}
.mini-chev.rotated { transform: rotate(180deg); }

.summary-body {
  padding: 10px 16px 12px;
  font-size: 12.5px;
  color: #4b5563;
  background: #fafafa;
  border-top: 1px solid #f3f4f6;
  line-height: 1.65;
}

/* ── 等待态 ── */
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

/* ── 工具卡 ── */
.tool-header { gap: 8px; }
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

/* ── AC 结果卡（进行中） ── */
.ac-header { gap: 10px; }
.ac-badge {
  font-family: 'SF Mono', 'Menlo', monospace;
  font-size: 11px;
  padding: 2px 8px;
  border-radius: 4px;
  background: #f3f4f6;
  color: #6b7280;
  flex-shrink: 0;
}
.ac-text {
  flex: 1;
  font-size: 13px;
  color: #111827;
}
.ac-card.ac-passed .ac-text { color: #065f46; }
.ac-card.ac-failed .ac-text { color: #b91c1c; }
.ac-card.ac-needs_review .ac-text { color: #92400e; }
.ac-card.ac-passed { border-color: #bbf7d0; }
.ac-card.ac-failed { border-color: #fecaca; }
.ac-card.ac-needs_review { border-color: #fed7aa; }

.ac-conf {
  font-size: 11px;
  color: #9ca3af;
  flex-shrink: 0;
  font-variant-numeric: tabular-nums;
}

/* ── 运行中 footer ── */
.running-footer {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 16px;
  font-size: 12px;
  color: #7c3aed;
  background: white;
  border: 1px solid #e5e7eb;
  border-radius: 10px;
}

/* ── 终局 AC 详情：合成一张卡，行分割线隔开 ── */
.chevron {
  margin-left: auto;
  width: 14px;
  height: 14px;
  color: #9ca3af;
  transition: transform 0.2s;
  flex-shrink: 0;
}
.chevron.rotated { transform: rotate(180deg); }

.ac-final-list {
  display: flex;
  flex-direction: column;
  border-top: 1px solid #f3f4f6;
}
.ac-final-row + .ac-final-row {
  border-top: 1px solid #f3f4f6;
}
.ac-final-header {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 12px 14px;
  width: 100%;
  background: transparent;
  border: none;
  text-align: left;
  color: inherit;
  cursor: pointer;
  transition: background 0.12s;
}
.ac-final-header:hover { background: #fafafa; }
.ac-desc {
  flex: 1;
  font-size: 13.5px;
  color: #111827;
  line-height: 1.55;
  word-break: break-word;
}

.ac-evidence {
  padding: 10px 16px 14px 50px;
  font-size: 12.5px;
  color: #4b5563;
  line-height: 1.7;
  word-break: break-word;
  background: #fafafa;
  border-top: 1px dashed #e5e7eb;
}
.ac-final-row.item-failed .ac-evidence { background: #fef7f7; }

/* ── 结果提示卡 ── */
.hint-card {
  padding: 10px 16px;
  font-size: 12.5px;
  border-radius: 10px;
  line-height: 1.55;
  border: 1px solid transparent;
}
.hint-passed { color: #065f46; background: #f0fdf4; border-color: #d1fae5; }
.hint-failed { color: #991b1b; background: #fef2f2; border-color: #fecaca; }
.hint-partial { color: #92400e; background: #fffbeb; border-color: #fed7aa; }
</style>
