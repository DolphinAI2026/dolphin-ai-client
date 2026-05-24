<!-- frontend/src/components/v2/config-assistant/ConfigAssistantInput.vue
     2026-05-24 从 ConfigAssistantPanel.vue 拆出 (refactor #9). -->
<script setup lang="ts">
const props = defineProps<{
  modelValue: string
  sending: boolean
}>()

const emit = defineEmits<{
  (e: 'update:modelValue', v: string): void
  (e: 'send'): void
}>()

function onInput(e: Event) {
  emit('update:modelValue', (e.target as HTMLTextAreaElement).value)
}

function onEnter(e: KeyboardEvent) {
  e.preventDefault()
  if (!props.modelValue.trim() || props.sending) return
  emit('send')
}
</script>

<template>
  <footer class="ca-input-area">
    <textarea
      :value="modelValue"
      class="ca-input"
      placeholder="描述你想调整的内容..."
      rows="2"
      :disabled="sending"
      @input="onInput"
      @keydown.enter.exact="onEnter"
      @keydown.enter.meta="onEnter"
    />
    <button
      class="ca-send"
      :disabled="!modelValue.trim() || sending"
      @click="emit('send')"
    >
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
        <path d="m22 2-7 20-4-9-9-4z" />
        <path d="M22 2 11 13" />
      </svg>
      发送
    </button>
  </footer>
</template>

<style scoped>
.ca-input-area {
  border-top: 1px solid var(--line);
  padding: 10px 12px;
  background: var(--surface);
  display: flex;
  gap: 8px;
}

.ca-input {
  flex: 1;
  min-height: 50px;
  max-height: 120px;
  padding: 8px 10px;
  border: 1px solid var(--line);
  border-radius: var(--r-2, 4px);
  font-family: inherit;
  font-size: 12.5px;
  color: var(--text);
  background: var(--surface);
  resize: vertical;
  outline: none;
  transition: border-color 0.12s ease;
}

.ca-input:focus {
  border-color: var(--brand-ring, var(--brand));
}

.ca-input:disabled {
  background: var(--surface-2);
  color: var(--text-3);
  cursor: not-allowed;
}

.ca-send {
  align-self: flex-end;
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 6px 12px;
  border: 0;
  border-radius: var(--r-2, 4px);
  background: var(--brand);
  color: var(--text-inverse, #fff);
  font-family: inherit;
  font-size: 12px;
  font-weight: var(--fw-medium, 500);
  cursor: pointer;
  transition: all 0.12s ease;
}

.ca-send:hover:not(:disabled) {
  background: var(--brand-hover);
}

.ca-send:disabled {
  background: var(--surface-3, var(--surface-2));
  color: var(--text-4);
  cursor: not-allowed;
}
</style>
