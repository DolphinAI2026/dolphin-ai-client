<!-- frontend/src/components/BaseTag.vue
     中性标签（非状态）。替代 低代码 / PC页面 等。
     用法：<BaseTag>低代码</BaseTag> / <BaseTag tone="brand">PC页面</BaseTag> -->
<template>
  <span class="base-tag" :class="`tone-${tone}`"><slot /></span>
</template>

<script setup lang="ts">
withDefaults(defineProps<{ tone?: 'neutral' | 'brand' }>(), { tone: 'neutral' })
</script>

<style scoped>
.base-tag {
  display: inline-flex; align-items: center;
  font-size: 11px; font-weight: var(--fw-medium, 500); line-height: 1.5;
  padding: 1px 7px; border-radius: var(--r-1, 4px); white-space: nowrap;
}
.tone-neutral { background: var(--surface-3);  color: var(--text-3); }
.tone-brand   { background: var(--brand-soft);  color: var(--brand); }
</style>
