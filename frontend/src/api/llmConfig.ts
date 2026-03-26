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
  is_default: boolean
  status: string        // "active" | "inactive" | "error"
  created_at?: string
  updated_at?: string
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
  is_default: boolean
}

export const llmConfigApi = {
  /** 获取所有 LLM 配置 */
  list: () => request.get<any, LlmConfig[]>('/llm-configs'),

  /** 创建 LLM 配置 */
  create: (data: LlmConfigForm) => request.post<any, LlmConfig>('/llm-configs', data),

  /** 更新 LLM 配置 */
  update: (id: number, data: Partial<LlmConfigForm>) => request.put<any, LlmConfig>(`/llm-configs/${id}`, data),

  /** 删除 LLM 配置 */
  delete: (id: number) => request.delete(`/llm-configs/${id}`),

  /** 测试连接 */
  test: (id: number) => request.post<any, { ok: boolean; message: string; error?: string }>(`/llm-configs/${id}/test`),

  /** 设为默认 */
  setDefault: (id: number) => request.post(`/llm-configs/${id}/set-default`),

  /** 获取供应商预设 */
  getPresets: () => request.get<any, ProviderPreset[]>('/llm-configs/presets'),
}
