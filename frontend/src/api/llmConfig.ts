import request from '@/utils/request'

export interface LlmConfig {
  id: number
  config_name: string
  provider: string
  base_url: string
  model: string
  purpose: string       // "all" | "builder" | "coding"
  max_tokens: number
  temperature: number
  codex_wire_api: 'responses' | 'chat'
  is_default: boolean
  status: string        // "active" | "inactive" | "error"
  created_at?: string
  updated_at?: string
}

export interface BuilderModelOption {
  id: number
  config_name: string
  provider: string
  model: string
  purpose: string
  is_default: boolean
}

/**
 * Normalize Builder/Control Plane adapters to the array shape used by pickers.
 * Remote adapters may wrap the list in items, options, data or models.
 */
export function normalizeLlmOptions(payload: unknown): BuilderModelOption[] {
  if (Array.isArray(payload)) return payload as BuilderModelOption[]
  if (!payload || typeof payload !== 'object') return []

  const body = payload as Record<string, unknown>
  for (const key of ['items', 'options', 'data', 'models']) {
    if (Array.isArray(body[key])) return body[key] as BuilderModelOption[]
  }
  return []
}

export interface ProviderPreset {
  provider: string
  label: string
  base_url: string
  models: string[]
}

export interface LlmConfigForm {
  config_name: string
  provider: string
  base_url: string
  api_key?: string
  model: string
  purpose: string
  max_tokens: number
  temperature: number
  codex_wire_api: 'responses' | 'chat'
  is_default: boolean
  status?: string
}

export const llmConfigApi = {
  /** 获取所有 LLM 配置 */
  list: () => request.get<any, LlmConfig[]>('/llm-configs'),

  /** 获取指定用途可选模型列表 */
  listOptions: async (purpose = 'builder') => {
    const payload = await request.get<any, unknown>('/llm-configs/options', { params: { purpose } })
    return normalizeLlmOptions(payload)
  },

  /** 创建 LLM 配置 */
  create: (data: LlmConfigForm) => request.post<any, LlmConfig>('/llm-configs', data),

  /** 更新 LLM 配置 */
  update: (id: number, data: Partial<LlmConfigForm>) => request.put<any, LlmConfig>(`/llm-configs/${id}`, data),

  /** 删除 LLM 配置 */
  delete: (id: number) => request.delete(`/llm-configs/${id}`),

  /** 测试连接 */
  test: (id: number) => request.post<any, {
    ok?: boolean
    success?: boolean
    message?: string
    reply?: string
    error?: string
  }>(`/llm-configs/${id}/test`),

  /** 设为默认 */
  setDefault: (id: number) => request.post(`/llm-configs/${id}/set-default`),

  /** 全局启用/禁用 */
  updateStatus: (id: number, status: 'active' | 'inactive') =>
    request.post<any, LlmConfig>(`/llm-configs/${id}/status`, { status }),

  /** 获取供应商预设 */
  getPresets: () => request.get<any, ProviderPreset[]>('/llm-configs/presets'),

  /** 使用填写的地址和 Key 从 OpenAI 兼容的 /models 接口拉取模型 */
  fetchModels: (data: Pick<LlmConfigForm, 'provider' | 'base_url' | 'api_key'>) =>
    request.post<any, { models: string[] }>('/llm-configs/models', data),
}
