<!-- frontend/src/components/v2/config-assistant/ConfigAssistantHeader.vue
     2026-05-24 #1 从 ConfigAssistantPanel.vue 拆出 (refactor #9).
     2026-05-24 #2 加 model selector dropdown + refresh btn (学 super-agents-dev
                  ai-assistant-sidebar.vue 顶部 model selector 模式).

     职责: 标题 + 副标题 + 模型选择行 (一行 compact 布局).
     不直接持 modelId — 由父容器持 ref + localStorage 持久化, 通过 v-model 传进来.
     Model 列表自己拉 (/llm-configs/options?purpose=builder), 缓存到组件内 ref. -->
<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { llmConfigApi, type BuilderModelOption } from '@/api/llmConfig'

// 2026-05-24: modelId 标 optional 让父容器渐进迁移 — 未传时按 null (后端默认) 处理.
// 用户后续会在 ConfigAssistantPanel.vue 加 modelId ref + localStorage 持久化 +
// v-model:modelId 绑过来. 当前不传也不会报 TS 错.
const props = withDefaults(
  defineProps<{
    appName?: string
    /** 当前选中的 LlmConfig.id; null 表示走后端默认 (gpt-5.5). */
    modelId?: number | null
  }>(),
  { modelId: null },
)

const emit = defineEmits<{
  (e: 'update:modelId', v: number | null): void
}>()

const models = ref<BuilderModelOption[]>([])
const loading = ref(false)
const loadError = ref('')

async function refreshModels(showFeedback = false) {
  loading.value = true
  loadError.value = ''
  try {
    // 复用现有 endpoint: /llm-configs/options?purpose=builder
    // 后端返回的就是 active 的 LlmConfig 列表 (id / config_name / provider / model / is_default)
    const opts = await llmConfigApi.listOptions('builder')
    models.value = (opts || []) as BuilderModelOption[]
    if (showFeedback && models.value.length === 0) {
      loadError.value = '暂无可用模型，请联系管理员在平台管理 → LLM 配置启用'
    }
  } catch (e: any) {
    loadError.value = e?.response?.data?.detail || e?.message || '加载模型列表失败'
    console.error('[ConfigAssistantHeader] refreshModels failed', e)
  } finally {
    loading.value = false
  }
}

onMounted(() => {
  refreshModels(false)
})

function onChange(e: Event) {
  const raw = (e.target as HTMLSelectElement).value
  // 空字符串 → null (走后端默认)
  emit('update:modelId', raw === '' ? null : Number(raw))
}

const selectValue = computed(() => (props.modelId == null ? '' : String(props.modelId)))
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

    <!-- 模型选择行 — 学 super-agents-dev: select + refresh btn 紧凑布局 -->
    <div class="ca-model-row">
      <select
        class="ca-model-select"
        :value="selectValue"
        :disabled="loading"
        :title="loadError || '选择 LLM 模型 (空 = 后端默认)'"
        @change="onChange"
      >
        <option value="">选择模型 (默认 gpt-5.5)</option>
        <option
          v-for="m in models"
          :key="m.id"
          :value="m.id"
        >
          {{ m.config_name }}{{ m.is_default ? ' · 默认' : '' }}
        </option>
      </select>
      <button
        class="ca-model-refresh"
        :disabled="loading"
        :title="loading ? '正在拉取...' : '刷新模型列表'"
        @click="refreshModels(true)"
      >
        <svg
          width="12"
          height="12"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          stroke-width="2"
          stroke-linecap="round"
          stroke-linejoin="round"
          :class="{ spinning: loading }"
        >
          <polyline points="23 4 23 10 17 10" />
          <polyline points="1 20 1 14 7 14" />
          <path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15" />
        </svg>
      </button>
    </div>
    <div v-if="loadError" class="ca-model-error">{{ loadError }}</div>
  </header>
</template>

<style scoped>
.ca-head {
  padding: 12px 14px 10px;
  border-bottom: 1px solid var(--line);
  background: var(--surface-2);
}

.ca-title-row {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 8px;
}

.ca-title {
  font-size: 13px;
  font-weight: var(--fw-semibold, 600);
  color: var(--text);
}

.ca-sub {
  margin-top: 3px;
  font-size: 11.5px;
  color: var(--text-3);
}

.ca-model-row {
  margin-top: 8px;
  display: flex;
  align-items: center;
  gap: 6px;
}

.ca-model-select {
  flex: 1;
  min-width: 0;
  height: 26px;
  padding: 0 6px;
  border: 1px solid var(--line);
  border-radius: var(--r-2, 4px);
  background: var(--surface);
  color: var(--text);
  font-family: inherit;
  font-size: 11.5px;
  cursor: pointer;
  outline: none;
  transition: border-color 0.12s ease;
}

.ca-model-select:hover:not(:disabled) {
  border-color: var(--brand);
}

.ca-model-select:focus {
  border-color: var(--brand-ring, var(--brand));
}

.ca-model-select:disabled {
  background: var(--surface-2);
  color: var(--text-3);
  cursor: not-allowed;
}

.ca-model-refresh {
  flex: 0 0 auto;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 26px;
  height: 26px;
  padding: 0;
  border: 1px solid var(--line);
  border-radius: var(--r-2, 4px);
  background: var(--surface);
  color: var(--text-2, var(--text-3));
  cursor: pointer;
  transition: all 0.12s ease;
}

.ca-model-refresh:hover:not(:disabled) {
  border-color: var(--brand);
  color: var(--brand);
}

.ca-model-refresh:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.ca-model-refresh .spinning {
  animation: ca-model-spin 0.8s linear infinite;
}

@keyframes ca-model-spin {
  to { transform: rotate(360deg); }
}

.ca-model-error {
  margin-top: 4px;
  font-size: 11px;
  color: var(--danger, #d33);
}
</style>
