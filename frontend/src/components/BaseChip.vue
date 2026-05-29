<!-- frontend/src/components/BaseChip.vue
     可点击建议/动作 chip。统一 配置助手 / 首页 / Coding 三处建议 chip。
     用法：<BaseChip @click="send('...')">开发一个头像上传组件</BaseChip> -->
<template>
  <button type="button" class="base-chip" :disabled="disabled" @click="$emit('click', $event)">
    <slot />
  </button>
</template>

<script setup lang="ts">
withDefaults(defineProps<{ disabled?: boolean }>(), { disabled: false })
defineEmits<{ click: [e: MouseEvent] }>()
</script>

<style scoped>
.base-chip {
  display: inline-flex; align-items: center; gap: var(--s-2, 8px); max-width: 100%;
  padding: var(--s-2, 8px) var(--s-3, 12px);
  background: var(--surface); border: 1px solid var(--line);
  border-radius: var(--r-full, 999px);
  color: var(--text-2); font-size: 12.5px; font-weight: var(--fw-medium, 500);
  font-family: inherit; cursor: pointer; text-align: left;
  transition: background .14s var(--ease, cubic-bezier(.2,.8,.2,1)),
              border-color .14s var(--ease, cubic-bezier(.2,.8,.2,1)),
              color .14s var(--ease, cubic-bezier(.2,.8,.2,1));
}
.base-chip:hover:not(:disabled) {
  background: var(--brand-soft); border-color: var(--brand-ring, var(--brand)); color: var(--brand);
}
.base-chip:disabled { opacity: .5; cursor: not-allowed; }
.base-chip:focus-visible { outline: 2px solid var(--line-focus, var(--brand-ring)); outline-offset: 2px; }
</style>
