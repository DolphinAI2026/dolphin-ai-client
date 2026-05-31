<template>
  <section class="activity-card">
    <h4>📋 当前草稿</h4>
    <p class="muted">v{{ draft.version }} · 完整度 {{ draft.completeness_confirmed }}/{{ draft.completeness_total }}</p>
    <p class="muted small">最后更新 {{ formatDate(draft.updated_at) }}</p>
    <button v-if="mode === 'pro'" class="builder-btn builder-btn-primary" type="button">Promote to Proposal ↗</button>
  </section>
</template>

<script setup lang="ts">
defineProps<{
  draft: { id: string; version: number; completeness_confirmed: number; completeness_total: number; updated_at: string }
  mode: 'simple' | 'pro'
}>()

function formatDate(s: string): string {
  return new Date(s).toLocaleString()
}
</script>

<style scoped>
.activity-card { padding: 12px; border: 1px solid var(--line); border-radius: 8px; background: var(--bg-panel); }
.activity-card h4 { margin: 0 0 8px; font-size: 14px; color: var(--fg); }
.muted { color: var(--fg-muted); font-size: 12px; margin: 4px 0; }
.small { font-size: 11px; }
</style>
