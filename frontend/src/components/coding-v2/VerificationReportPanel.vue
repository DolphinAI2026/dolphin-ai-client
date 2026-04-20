<template>
  <div class="vr-panel" :class="'status-' + report.overall_status">
    <div class="header">
      <div class="status-row">
        <span class="status-tag">{{ statusLabel }}</span>
        <span class="counts">
          <span class="passed">✅ {{ report.passed_count }}</span>
          <span class="failed">❌ {{ report.failed_count }}</span>
          <span class="total">/ 总 {{ report.items.length }}</span>
        </span>
      </div>
      <div v-if="report.summary" class="summary">{{ report.summary }}</div>
    </div>

    <ul class="items">
      <li v-for="item in report.items" :key="item.index" :class="'item-' + item.status">
        <div class="item-head">
          <span class="idx">#{{ item.index }}</span>
          <span class="icon">{{ iconFor(item.status) }}</span>
          <span class="desc">{{ item.description }}</span>
          <span class="conf">{{ Math.round(item.confidence * 100) }}%</span>
        </div>
        <div v-if="item.evidence" class="evidence">
          <span class="k">证据：</span>{{ item.evidence }}
        </div>
      </li>
    </ul>

    <div v-if="report.overall_status === 'failed'" class="hint hint-retry">
      系统会自动触发 CodingAgent 重新尝试（最多 2 次）。
    </div>
    <div v-else-if="report.overall_status === 'partial'" class="hint hint-review">
      有需要人工确认的项，请查看证据后决定是否接受。
    </div>
    <div v-else-if="report.overall_status === 'passed'" class="hint hint-ok">
      所有验收点通过。可以继续迭代或结束。
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import type { VerificationReport } from '@/stores/codingV2'

const props = defineProps<{
  report: VerificationReport
}>()

const statusLabel = computed(() => {
  const map: Record<string, string> = {
    passed: '✓ 验收通过',
    failed: '✗ 验收失败',
    partial: '⚠️ 部分通过',
    pending: '⏳ 检查中',
  }
  return map[props.report.overall_status] || props.report.overall_status
})

function iconFor(status: string): string {
  switch (status) {
    case 'passed': return '✅'
    case 'failed': return '❌'
    case 'needs_review': return '⚠️'
    default: return '⏳'
  }
}
</script>

<style scoped>
.vr-panel {
  background: white;
  border-radius: 10px;
  padding: 16px 18px;
  border: 1px solid #e5e7eb;
  display: flex;
  flex-direction: column;
  gap: 14px;
}
.status-passed { border-left: 4px solid #10b981; }
.status-failed { border-left: 4px solid #ef4444; }
.status-partial { border-left: 4px solid #f59e0b; }
.status-pending { border-left: 4px solid #9ca3af; }

.header { display: flex; flex-direction: column; gap: 6px; }
.status-row { display: flex; align-items: center; gap: 12px; }
.status-tag { font-size: 15px; font-weight: 600; color: #111827; }
.counts {
  display: flex;
  gap: 8px;
  font-size: 13px;
  font-variant-numeric: tabular-nums;
}
.counts .passed { color: #065f46; }
.counts .failed { color: #b91c1c; }
.counts .total { color: #6b7280; }
.summary { color: #374151; font-size: 13px; }

.items {
  list-style: none;
  padding: 0;
  margin: 0;
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.items li {
  padding: 8px 10px;
  border-radius: 6px;
  background: #f9fafb;
  font-size: 13px;
}
.item-passed { background: #f0fdf4; }
.item-failed { background: #fef2f2; }
.item-needs_review { background: #fffbeb; }
.item-head { display: flex; align-items: center; gap: 8px; }
.idx { color: #6b7280; font-size: 12px; }
.desc { flex: 1; color: #1f2937; }
.conf {
  color: #6b7280;
  font-size: 12px;
  font-variant-numeric: tabular-nums;
}
.evidence {
  margin-top: 6px;
  color: #4b5563;
  font-size: 12px;
  line-height: 1.5;
}
.k { color: #6b7280; font-weight: 500; }
.hint {
  padding: 8px 12px;
  border-radius: 6px;
  font-size: 12px;
}
.hint-retry { background: #fee2e2; color: #991b1b; }
.hint-review { background: #fef3c7; color: #92400e; }
.hint-ok { background: #d1fae5; color: #065f46; }
</style>
