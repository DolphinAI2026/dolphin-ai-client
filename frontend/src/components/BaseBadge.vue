<!-- frontend/src/components/BaseBadge.vue
     语义状态徽章。替代散落的 成功/失败、部署/待部署、已发布 等胶囊。
     用法：<BaseBadge variant="success">成功</BaseBadge> / <BaseBadge variant="warn" size="sm">待部署</BaseBadge>
     token 全程 var() — 浅/暗自适配。 -->
<template>
  <span class="base-badge" :class="[`is-${variant}`, `sz-${size}`]"><slot /></span>
</template>

<script setup lang="ts">
withDefaults(defineProps<{
  variant?: 'success' | 'warn' | 'error' | 'info' | 'neutral'
  size?: 'sm' | 'md'
}>(), { variant: 'neutral', size: 'md' })
</script>

<style scoped>
.base-badge {
  display: inline-flex; align-items: center; gap: var(--s-1, 4px);
  font-weight: var(--fw-medium, 500); line-height: 1.4;
  border-radius: var(--r-full, 999px); white-space: nowrap;
  border: 1px solid transparent;
}
.sz-md { font-size: 12px; padding: 2px var(--s-3, 12px); }
.sz-sm { font-size: 11px; padding: 1px var(--s-2, 8px); }
.is-success { background: var(--ok-soft);    color: var(--ok); }
.is-warn    { background: var(--warn-soft);  color: var(--warn); }
.is-error   { background: var(--err-soft);   color: var(--err); }
.is-info    { background: var(--brand-soft); color: var(--brand); }
.is-neutral { background: var(--surface-3);  color: var(--text-3); }
</style>
