import request from '@/utils/request'

/** 一个 agent 在某个 phase 下的提示词模板（对应后端 agent_prompts 行）。 */
export interface AgentPromptItem {
  phase: string
  template: string
  notes?: string | null
  version: number
}

export interface AgentPromptListResp {
  agent_id: string
  prompts: AgentPromptItem[]
}

/** 管理页展示的 agent 列表。后端 GET 对 builder / whale / unified 会 lazy seed。 */
export interface AgentDescriptor {
  id: string
  label: string
  desc: string
}

export const AGENT_DESCRIPTORS: AgentDescriptor[] = [
  { id: 'unified', label: '全栈助手 (Unified)', desc: 'AIChat 主链路系统提示，最大流量入口' },
  { id: 'builder', label: 'Builder', desc: '应用搭建 SpecAgent，多 phase（gathering / drafting / …）' },
  { id: 'whale', label: '二次开发 (Whale)', desc: 'Coding / 代码工作区 codegen agent' },
]

export const agentPromptsApi = {
  /** 列出某 agent 各 phase 的提示词（首次访问 builder/whale/unified 会自动 seed 默认值）。 */
  list: (agentId: string) =>
    request.get<any, AgentPromptListResp>(`/agent-prompts/${agentId}`),

  /** 更新某 agent 某 phase 的模板 / 备注，version 自动 +1。 */
  update: (agentId: string, phase: string, data: { template: string; notes?: string | null }) =>
    request.put<any, AgentPromptItem>(`/agent-prompts/${agentId}/${phase}`, data),
}
