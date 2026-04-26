<template>
  <section class="activity-card">
    <h4>✅ 已部署</h4>
    <p>canonical v{{ canonical.version }} · {{ formatDate(canonical.updated_at) }}</p>
    <details v-if="history.length">
      <summary>近 {{ history.length }} 次 apply</summary>
      <ul>
        <li v-for="h in history" :key="h.id">
          <code>{{ h.title }}</code>
          <span class="muted small">{{ formatDate(h.applied_at) }}</span>
        </li>
      </ul>
    </details>
  </section>
</template>

<script setup lang="ts">
import type { ProposalSummary } from '@/types/proposal'

defineProps<{
  canonical: { id: string; version: number; updated_at: string }
  history: ProposalSummary[]
}>()

function formatDate(s: string | null): string {
  return s ? new Date(s).toLocaleString() : '—'
}
</script>

<style scoped>
.activity-card { padding: 12px; border: 1px solid var(--line); border-radius: 8px; background: var(--bg-panel); }
.activity-card h4 { margin: 0 0 8px; font-size: 14px; color: var(--fg); }
.muted { color: var(--fg-muted); font-size: 11px; }
ul { padding-left: 16px; margin-top: 8px; font-size: 12px; }
li { color: var(--fg); margin-bottom: 4px; }
code { background: var(--bg-inset); padding: 1px 4px; border-radius: 3px; }
</style>
