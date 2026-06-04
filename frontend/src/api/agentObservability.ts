import request from '@/utils/request'

export interface AgentRunSummary {
  run_id: string
  agent_type: string
  status: string
  model: string | null
  session_id: string | null
  app_id: string | null
  started_at: string | null
  ended_at: string | null
  duration_ms: number | null
  total_prompt_tokens: number
  total_completion_tokens: number
  total_tokens: number
  turn_count: number
  error_message: string | null
  created_at: string | null
}

export interface AgentStep {
  seq: number
  step_type: 'llm' | 'tool' | 'error' | 'artifact'
  tool_name: string | null
  args_json: Record<string, any> | null
  result_text: string | null
  status: string | null
  duration_ms: number | null
  prompt_tokens: number | null
  completion_tokens: number | null
  ts: string | null
}

export interface AgentRunDetail {
  run: AgentRunSummary
  steps: AgentStep[]
}

export const agentObservabilityApi = {
  listRuns(params: { session_id?: string; agent_type?: string; limit?: number } = {}): Promise<{ runs: AgentRunSummary[] }> {
    return request({ url: '/agent-runs', method: 'get', params }) as unknown as Promise<{ runs: AgentRunSummary[] }>
  },
  getRunDetail(runId: string): Promise<AgentRunDetail> {
    return request({ url: `/agent-runs/${runId}`, method: 'get' }) as unknown as Promise<AgentRunDetail>
  },
}
