import request from '@/utils/request'

export interface AgentSkillItem {
  code: string
  name: string
  desc: string
}

export interface AgentConfig {
  id: string
  name: string
  role: string
  desc: string
  tone: 'ai' | 'brand' | 'emerald'
  icon: string
  model: string
  model_options: string[]
  system_prompt: string
  context_window: number
  max_output: number
  active_calls: number
  today_calls: number
  skills: AgentSkillItem[]
  mcps: string[]
  knowledge: { industry_packs: string[]; spec_templates: string[] }
}

export interface AgentListResponse {
  agents: AgentConfig[]
}

export const agentsApi = {
  /** 列出当前租户的全部 agent 配置（首次访问会自动 seed 默认 3 个） */
  list(): Promise<AgentListResponse> {
    return request({ url: '/agents', method: 'get' }) as unknown as Promise<AgentListResponse>
  },
  /** 更新指定 agent 的 model / system_prompt */
  update(agentId: string, payload: { model?: string; system_prompt?: string }): Promise<AgentConfig> {
    return request({ url: `/agents/${agentId}`, method: 'put', data: payload }) as unknown as Promise<AgentConfig>
  },
}
