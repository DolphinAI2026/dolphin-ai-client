<template>
  <div :class="['mode-toggle', { disabled }]" :title="disabled ? '需 maintainer+ 权限' : ''">
    <button
      type="button"
      :class="{ active: mode === 'simple' }"
      :disabled="disabled"
      @click="onClick('simple')"
    >简单</button>
    <button
      type="button"
      :class="{ active: mode === 'pro' }"
      :disabled="disabled"
      @click="onClick('pro')"
    >专业</button>
  </div>
</template>

<script setup lang="ts">
const props = defineProps<{
  mode: 'simple' | 'pro'
  disabled?: boolean
}>()

const emit = defineEmits<{
  change: [mode: 'simple' | 'pro']
}>()

function onClick(target: 'simple' | 'pro') {
  if (props.disabled || target === props.mode) return
  emit('change', target)
}
</script>

<style scoped>
.mode-toggle { display: inline-flex; background: var(--bg-inset); border-radius: 16px; padding: 2px; }
.mode-toggle button { padding: 4px 12px; background: transparent; border: 0; color: var(--fg-muted); cursor: pointer; border-radius: 14px; font-size: 12px; }
.mode-toggle button.active { background: var(--brand); color: var(--fg-on-ink); }
.mode-toggle.disabled { opacity: 0.6; cursor: not-allowed; }
.mode-toggle button:disabled { cursor: not-allowed; }
</style>
