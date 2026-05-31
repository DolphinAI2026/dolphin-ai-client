<template>
  <section class="activity-card proposal-card" @click="$emit('click')">
    <h4>🔍 {{ proposal.title }}</h4>
    <span class="status-badge" :class="`status-${proposal.status}`">{{ STATUS_DISPLAY_NAMES[proposal.status] || proposal.status }}</span>
    <p class="muted small">提案者：用户 {{ proposal.created_by }} · {{ formatDate(proposal.created_at) }}</p>
    <button v-if="canApprove" class="builder-btn builder-btn-primary" type="button" @click.stop="$emit('approve')">
      Approve ✓
    </button>
  </section>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { type ProposalSummary, STATUS_DISPLAY_NAMES } from '@/types/proposal'
import { type ProjectRole, roleAtLeast } from '@/types/collaboration'

const props = defineProps<{
  proposal: ProposalSummary
  mode: 'simple' | 'pro'
  role: ProjectRole
}>()

defineEmits<{ click: []; approve: [] }>()

const canApprove = computed(() =>
  props.proposal.status === 'open' && roleAtLeast(props.role, 'maintainer')
)

function formatDate(s: string | null): string {
  return s ? new Date(s).toLocaleString() : '—'
}
</script>

<style scoped>
.activity-card { padding: 12px; border: 1px solid var(--line); border-radius: 8px; background: var(--bg-panel); cursor: pointer; }
.activity-card:hover { background: var(--bg-hover); }
.activity-card h4 { margin: 0 0 8px; font-size: 14px; color: var(--fg); }
.status-badge { padding: 2px 8px; border-radius: 8px; font-size: 11px; }
.status-open { background: var(--brand-soft); color: var(--brand); }
.status-changes_requested { background: var(--t-warning-subtle); color: var(--t-warning); }
.status-approved { background: var(--t-success-subtle); color: var(--t-success); }
.muted { color: var(--fg-muted); font-size: 12px; margin: 4px 0; }
.small { font-size: 11px; }
</style>
