<!-- frontend/src/components/v2/config-assistant/ConfigAssistantHeader.vue
     2026-05-24 #1 从 ConfigAssistantPanel.vue 拆出 (refactor #9).
     2026-06-04: 恢复 builder 模型选择，避免有模型但未设默认时走空配置。 -->
<script setup lang="ts">
import { computed } from 'vue'
import type { BuilderModelOption } from '@/api/llmConfig'

const props = defineProps<{
  appName?: string
  modelId?: number | null
  modelOptions?: BuilderModelOption[]
  modelLoading?: boolean
  modelError?: string
}>()

const emit = defineEmits<{
  (e: 'update:modelId', value: number | null): void
}>()

const options = computed(() => props.modelOptions ?? [])

const selectedModelLabel = computed(() => {
  const selected = options.value.find((option) => option.id === props.modelId)
  if (!selected) return props.modelLoading ? '加载模型...' : '未配置可用模型'
  return `${selected.config_name} / ${selected.model}`
})

function onModelChange(value: string | number | null) {
  const parsed = Number(value)
  emit('update:modelId', Number.isFinite(parsed) && parsed > 0 ? parsed : null)
}

function onModelChangeEvent(event: Event) {
  onModelChange((event.target as HTMLSelectElement | null)?.value ?? null)
}
</script>

<template>
  <header class="ca-head">
    <div class="ca-title-row">
      <div>
        <div class="ca-title">配置助手</div>
        <div class="ca-sub">
          {{ appName ? `调整「${appName}」` : '调整已部署应用' }}
        </div>
      </div>
    </div>

    <div class="ca-model-row" aria-label="配置助手模型选择">
      <span class="ca-model-label">模型</span>
      <select
        class="ca-model-select"
        :value="modelId ?? ''"
        :title="selectedModelLabel"
        :disabled="modelLoading || options.length === 0"
        @change="onModelChangeEvent"
      >
        <option value="" disabled>
          {{ modelLoading ? '加载模型...' : '未配置可用模型' }}
        </option>
        <option
          v-for="option in options"
          :key="option.id"
          :value="option.id"
        >
          {{ option.config_name }} / {{ option.model }}{{ option.is_default ? '（默认）' : '' }}
        </option>
      </select>
    </div>
    <div v-if="modelError" class="ca-model-error">{{ modelError }}</div>
  </header>
</template>

<style scoped>
.ca-head {
  padding: 16px 132px 14px 14px;
  border-bottom: 1px solid var(--line);
  background: linear-gradient(135deg, var(--surface) 0%, var(--brand-soft, #eef4ff) 100%);
}

.ca-title-row {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 8px;
}

.ca-title {
  font-size: 18px;
  font-weight: var(--fw-bold, 700);
  color: var(--text);
}

.ca-sub {
  margin-top: 6px;
  font-size: 12.5px;
  color: var(--text-3);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.ca-model-row {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 12px;
  max-width: 100%;
}

.ca-model-label {
  flex: 0 0 auto;
  font-size: 12px;
  font-weight: var(--fw-semibold, 600);
  color: var(--text-3);
}

.ca-model-select {
  width: min(100%, 238px);
  min-width: 0;
  height: 30px;
  padding: 0 28px 0 10px;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: var(--surface);
  color: var(--text);
  font: inherit;
  font-size: 12.5px;
  line-height: 30px;
  cursor: pointer;
  outline: none;
}

.ca-model-select:disabled {
  color: var(--text-3);
  cursor: not-allowed;
  opacity: 0.72;
}

.ca-model-select:focus-visible {
  border-color: var(--brand);
  box-shadow: 0 0 0 2px var(--brand-ring, rgba(37, 99, 235, 0.16));
}

.ca-model-error {
  margin-top: 6px;
  font-size: 11.5px;
  line-height: 1.35;
  color: var(--danger, #dc2626);
}
</style>
