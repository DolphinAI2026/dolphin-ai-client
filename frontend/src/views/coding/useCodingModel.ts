/**
 * useCodingModel — 智能开发模型选择相关状态和行为。
 *
 * 职责：
 * - 加载 coding 场景可用模型列表
 * - 维护"会话期持久化"和"当前选中"两个值
 * - 切换模型时调用 conversationApi.updateModel 持久化到会话
 * - 规范化/默认值回落
 */

import { ref, computed } from 'vue'
import { ElMessage } from 'element-plus'

import { useCodingStore } from '@/stores/coding'
import { llmConfigApi, type BuilderModelOption } from '@/api/llmConfig'
import { conversationApi } from '@/api/conversation'

export function useCodingModel() {
  const codingStore = useCodingStore()

  const codingModelOptions = ref<BuilderModelOption[]>([])
  const codingModelLoading = ref(false)
  const updatingCodingModel = ref(false)
  const selectedCodingModelValue = ref<string | null>(null)
  const persistedCodingModelValue = ref<string | null>(null)
  const codingModelPopoverVisible = ref(false)

  const toCodingModelValue = (configId: number | null | undefined) =>
    configId != null ? `llmcfg:${configId}` : null

  const parseCodingModelConfigId = (modelValue?: string | null): number | null => {
    if (!modelValue?.startsWith('llmcfg:')) return null
    const parsed = Number(modelValue.slice('llmcfg:'.length))
    return Number.isFinite(parsed) ? parsed : null
  }

  const defaultCodingModelValue = computed(() =>
    toCodingModelValue(codingModelOptions.value.find(option => option.is_default)?.id)
    ?? toCodingModelValue(codingModelOptions.value[0]?.id)
    ?? null
  )

  const selectedCodingModelOption = computed(() =>
    codingModelOptions.value.find(option => toCodingModelValue(option.id) === selectedCodingModelValue.value) ?? null
  )

  const codingModelHint = computed(() => {
    if (codingModelLoading.value) return '正在加载可用模型...'
    if (codingModelOptions.value.length === 0) return '未配置可用模型，请前往模型配置'
    if (codingStore.conversationId) return '切换后仅影响后续开发与打开 IDE 的默认模型'
    return '首条消息会使用当前选择的模型'
  })

  const normalizeCodingModelValue = (modelValue?: string | null): string | null => {
    const values = new Set(codingModelOptions.value.map(option => toCodingModelValue(option.id)).filter(Boolean) as string[])
    if (modelValue && values.has(modelValue)) return modelValue
    return defaultCodingModelValue.value
  }

  const applyCodingModelSelection = (configId?: number | null) => {
    const normalized = normalizeCodingModelValue(toCodingModelValue(configId))
    selectedCodingModelValue.value = normalized
    persistedCodingModelValue.value = codingStore.conversationId ? normalized : null
  }

  const formatCodingModelProvider = (provider: string): string => {
    const labels: Record<string, string> = {
      minimax: 'MiniMax',
      qwen: 'Qwen',
      gpt: 'GPT',
      codex: 'Codex',
      sonnet: 'Sonnet',
      opus: 'Opus',
      openai: 'OpenAI',
      anthropic: 'Anthropic',
    }
    return labels[provider] || provider
  }

  const codingModelSummary = computed(() => {
    if (codingModelLoading.value) return '正在加载可用模型...'
    if (!selectedCodingModelOption.value) return '请选择开发模型'
    return `${formatCodingModelProvider(selectedCodingModelOption.value.provider)} / ${selectedCodingModelOption.value.model}`
  })

  const loadCodingModelOptions = async () => {
    codingModelLoading.value = true
    try {
      codingModelOptions.value = await llmConfigApi.listOptions('coding')
      selectedCodingModelValue.value = normalizeCodingModelValue(selectedCodingModelValue.value)
      if (codingStore.conversationId) {
        persistedCodingModelValue.value = normalizeCodingModelValue(persistedCodingModelValue.value)
      }
    } catch (e) {
      console.error('获取 coding 模型列表失败:', e)
      codingModelOptions.value = []
      selectedCodingModelValue.value = null
      persistedCodingModelValue.value = null
    } finally {
      codingModelLoading.value = false
    }
  }

  const handleCodingModelChange = async (nextValue: string | null) => {
    selectedCodingModelValue.value = nextValue
    if (!codingStore.conversationId) return

    const previousValue = persistedCodingModelValue.value
    updatingCodingModel.value = true
    try {
      const updated = await conversationApi.updateModel(
        codingStore.conversationId,
        parseCodingModelConfigId(nextValue),
      )
      const normalized = normalizeCodingModelValue(toCodingModelValue(updated.selected_llm_config_id))
      selectedCodingModelValue.value = normalized
      persistedCodingModelValue.value = normalized
    } catch (e: any) {
      selectedCodingModelValue.value = normalizeCodingModelValue(previousValue)
      ElMessage.error(e?.response?.data?.detail || '切换模型失败')
    } finally {
      updatingCodingModel.value = false
    }
  }

  const selectCodingModel = async (option: BuilderModelOption) => {
    codingModelPopoverVisible.value = false
    const nextValue = toCodingModelValue(option.id)
    if (nextValue === selectedCodingModelValue.value) return
    await handleCodingModelChange(nextValue)
  }

  return {
    // state
    codingModelOptions,
    codingModelLoading,
    updatingCodingModel,
    selectedCodingModelValue,
    persistedCodingModelValue,
    codingModelPopoverVisible,
    // computed
    defaultCodingModelValue,
    selectedCodingModelOption,
    codingModelHint,
    codingModelSummary,
    // methods
    toCodingModelValue,
    parseCodingModelConfigId,
    normalizeCodingModelValue,
    applyCodingModelSelection,
    formatCodingModelProvider,
    loadCodingModelOptions,
    handleCodingModelChange,
    selectCodingModel,
  }
}
