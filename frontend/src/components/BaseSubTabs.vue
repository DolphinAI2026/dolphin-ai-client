<!-- frontend/src/components/BaseSubTabs.vue
     下划线二级 tab。统一权限（胶囊→下划线）与日志的二级导航。
     用法：<BaseSubTabs :tabs="[{key:'role',label:'角色'},...]" v-model="active" /> -->
<template>
  <div class="base-subtabs" role="tablist">
    <button
      v-for="t in tabs" :key="t.key"
      type="button" role="tab"
      class="bst-tab" :class="{ 'is-active': t.key === modelValue }"
      :disabled="t.disabled" :aria-selected="t.key === modelValue"
      @click="t.disabled || $emit('update:modelValue', t.key)"
    >{{ t.label }}</button>
  </div>
</template>

<script setup lang="ts">
defineProps<{
  tabs: { key: string; label: string; disabled?: boolean }[]
  modelValue: string
}>()
defineEmits<{ 'update:modelValue': [key: string] }>()
</script>

<style scoped>
.base-subtabs { display: flex; align-items: center; gap: var(--s-1, 4px); border-bottom: 1px solid var(--line); }
.bst-tab {
  position: relative; padding: var(--s-2, 8px) var(--s-3, 12px);
  background: transparent; border: none; border-bottom: 2px solid transparent; margin-bottom: -1px;
  color: var(--text-3); font-size: 13px; font-weight: var(--fw-medium, 500); line-height: 1.4;
  font-family: inherit; cursor: pointer;
  transition: color .14s var(--ease, cubic-bezier(.2,.8,.2,1));
}
.bst-tab:hover:not(:disabled) { color: var(--text); }
.bst-tab.is-active { color: var(--brand); border-bottom-color: var(--brand); font-weight: var(--fw-semibold, 600); }
.bst-tab:disabled { opacity: .45; cursor: not-allowed; }
.bst-tab:focus-visible { outline: 2px solid var(--line-focus, var(--brand-ring)); outline-offset: -2px; border-radius: var(--r-1, 4px); }
</style>
