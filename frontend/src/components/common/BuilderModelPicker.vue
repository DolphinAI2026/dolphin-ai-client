<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import type { BuilderModelOption } from '@/api/llmConfig'

const props = withDefaults(defineProps<{
  modelValue: number | null
  options: BuilderModelOption[]
  disabled?: boolean
  title?: string
  defaultLabel?: string
  showDefaultConfigName?: boolean
}>(), {
  options: () => [],
  disabled: false,
  title: '切换模型',
  defaultLabel: '默认模型',
  showDefaultConfigName: false,
})

const emit = defineEmits<{
  (e: 'update:modelValue', value: number | null): void
  (e: 'change', value: number | null): void
}>()

const open = ref(false)
const rootRef = ref<HTMLElement | null>(null)

const selectedOption = computed(() =>
  props.options.find(option => option.id === props.modelValue) ?? null,
)
const selectedLabel = computed(() =>
  selectedOption.value?.is_default && !props.showDefaultConfigName
    ? props.defaultLabel
    : selectedOption.value?.config_name || props.defaultLabel,
)

function optionLabel(option: BuilderModelOption): string {
  if (option.is_default && !props.showDefaultConfigName) return props.defaultLabel
  return option.config_name || option.model || props.defaultLabel
}

function toggle() {
  if (props.disabled) return
  open.value = !open.value
}

function choose(value: number | null) {
  open.value = false
  if (value === props.modelValue) return
  emit('update:modelValue', value)
  emit('change', value)
}

function closeOnOutside(event: MouseEvent) {
  const root = rootRef.value
  if (!root || !open.value) return
  if (event.target instanceof Node && root.contains(event.target)) return
  open.value = false
}

onMounted(() => document.addEventListener('click', closeOnOutside))
onUnmounted(() => document.removeEventListener('click', closeOnOutside))
</script>

<template>
  <div ref="rootRef" class="builder-model-picker" :class="{ 'is-disabled': disabled }">
    <button
      type="button"
      class="bmp-trigger"
      :class="{ 'is-open': open }"
      :disabled="disabled"
      :title="title"
      aria-haspopup="listbox"
      :aria-expanded="open"
      @click.stop="toggle"
      @keydown.esc.stop="open = false"
    >
      <span class="bmp-trigger-text">{{ selectedLabel }}</span>
      <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.1" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
        <path d="m6 9 6 6 6-6" />
      </svg>
    </button>

    <div v-if="open" class="bmp-menu" role="listbox" aria-label="选择模型">
      <button
        type="button"
        class="bmp-option"
        :class="{ 'is-selected': modelValue === null }"
        role="option"
        :aria-selected="modelValue === null"
        @click.stop="choose(null)"
      >
        <span class="bmp-option-name">默认模型</span>
        <span class="bmp-option-meta">使用当前默认配置</span>
      </button>
      <button
        v-for="option in options"
        :key="option.id"
        type="button"
        class="bmp-option"
        :class="{ 'is-selected': modelValue === option.id }"
        role="option"
        :aria-selected="modelValue === option.id"
        @click.stop="choose(option.id)"
      >
        <span class="bmp-option-name">{{ optionLabel(option) }}</span>
        <span class="bmp-option-meta">{{ option.is_default ? '当前默认配置' : `${option.provider} / ${option.model}` }}</span>
      </button>
    </div>
  </div>
</template>

<style scoped>
.builder-model-picker {
  position: relative;
  flex: 0 0 auto;
  /* 2026-06-25: 贴合内容宽度(原来固定 clamp 142-220px, 短标签如「Dolphin-默认」也撑很宽,
     在窄的配置助手面板里显得过长)。max-content 让框子随标签收窄, 长名 168px 封顶 + 省略号。 */
  width: max-content;
  min-width: 0;
  max-width: 168px;
  z-index: 14;
}

.builder-model-picker.is-disabled {
  opacity: 0.6;
}

.bmp-trigger {
  display: inline-flex;
  align-items: center;
  justify-content: space-between;
  gap: 7px;
  width: 100%;
  height: 32px;
  padding: 0 9px 0 10px;
  border: 1px solid var(--line, var(--ac-border, var(--t-border-subtle, rgba(116, 128, 171, 0.22))));
  border-radius: 8px;
  background: color-mix(in srgb, var(--surface, var(--ac-surface, var(--t-bg-panel, #fff))) 86%, transparent);
  color: var(--text-3, var(--ac-text-mute, var(--t-text-secondary, #64748b)));
  font: inherit;
  font-size: 12px;
  line-height: 1;
  cursor: pointer;
  outline: none;
  transition: border-color 0.15s ease, color 0.15s ease, background 0.15s ease;
}

.bmp-trigger:hover,
.bmp-trigger.is-open {
  border-color: var(--brand, var(--ac-brand, var(--t-brand, #4f6ef7)));
  background: color-mix(in srgb, var(--brand, var(--ac-brand, var(--t-brand, #4f6ef7))) 10%, transparent);
  color: var(--text, var(--ac-text, var(--t-text-primary, #172033)));
}

.bmp-trigger:disabled {
  cursor: not-allowed;
}

.bmp-trigger-text {
  min-width: 0;
  flex: 1 1 auto;
  overflow: hidden;
  text-align: left;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.bmp-trigger svg {
  flex: 0 0 auto;
  opacity: 0.82;
  transition: transform 0.15s ease;
}

.bmp-trigger.is-open svg {
  transform: rotate(180deg);
}

.bmp-menu {
  position: absolute;
  left: 0;
  bottom: calc(100% + 7px);
  width: max(100%, 240px);
  max-width: min(320px, calc(100vw - 32px));
  max-height: min(280px, calc(100vh - 160px));
  overflow: auto;
  padding: 5px;
  border: 1px solid var(--line, var(--ac-border, var(--t-border-subtle, rgba(116, 128, 171, 0.22))));
  border-radius: 10px;
  background: color-mix(in srgb, var(--surface, var(--ac-surface, var(--t-bg-panel, #fff))) 94%, #050b18);
  box-shadow: 0 18px 44px rgba(0, 0, 0, 0.34);
}

.bmp-option {
  display: flex;
  width: 100%;
  min-height: 42px;
  flex-direction: column;
  align-items: flex-start;
  justify-content: center;
  gap: 3px;
  padding: 7px 9px;
  border: 0;
  border-radius: 8px;
  background: transparent;
  color: var(--text-3, var(--ac-text-mute, var(--t-text-secondary, #64748b)));
  font: inherit;
  text-align: left;
  cursor: pointer;
}

.bmp-option:hover {
  background: color-mix(in srgb, var(--brand, var(--ac-brand, var(--t-brand, #4f6ef7))) 13%, transparent);
  color: var(--text, var(--ac-text, var(--t-text-primary, #172033)));
}

.bmp-option.is-selected {
  background: color-mix(in srgb, var(--brand, var(--ac-brand, var(--t-brand, #4f6ef7))) 18%, transparent);
  color: var(--brand, var(--ac-brand, var(--t-brand, #4f6ef7)));
}

.bmp-option-name,
.bmp-option-meta {
  max-width: 100%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.bmp-option-name {
  font-size: 12.5px;
  font-weight: 650;
}

.bmp-option-meta {
  color: var(--text-4, var(--ac-text-faint, var(--t-text-muted, #94a3b8)));
  font-size: 11px;
}
</style>
