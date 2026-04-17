/**
 * LLM 配置相关纯工具：provider/purpose 枚举 + label 查找。
 *
 * PlatformEnvs.vue 和未来其他设置页面可共享这份清单。
 */

export interface ProviderOption {
  value: string
  label: string
}

export const providerOptions: readonly ProviderOption[] = [
  { value: 'minimax', label: 'MiniMax' },
  { value: 'qwen', label: '通义千问 (Qwen)' },
  { value: 'deepseek', label: 'DeepSeek' },
  { value: 'zhipu', label: '智谱 (Zhipu)' },
  { value: 'moonshot', label: 'Moonshot' },
  { value: 'openai', label: 'OpenAI' },
  { value: 'anthropic', label: 'Anthropic' },
  { value: 'custom', label: '自定义' },
]

export function providerLabel(provider: string): string {
  const opt = providerOptions.find(p => p.value === provider)
  return opt?.label || provider
}

const PURPOSE_LABELS: Record<string, string> = {
  all: '全部场景',
  builder: '应用构建',
  coding: '代码生成',
}

export function purposeLabel(purpose: string): string {
  return PURPOSE_LABELS[purpose] || purpose
}
