/**
 * 配置助手 API — post-deploy chat against a deployed application.
 *
 * Backend route (owned by parallel agent P):
 *   POST /api/applications/:id/config-chat
 *
 * Returns a natural-language reply + an optional ChangePlan that can be
 * previewed / applied via the existing incremental update pipeline.
 */
import request from '@/utils/request'

export interface ConfigChatHistoryItem {
  role: 'user' | 'assistant'
  content: string
}

export interface ConfigChatReq {
  message: string
  history: ConfigChatHistoryItem[]
}

/**
 * ChangePlan preview — loose shape on purpose. Backend may evolve the
 * structure (actions, summary, diff hints, etc); frontend just renders
 * whatever it gets.
 */
export interface ChangePlanPreview {
  summary?: string[]
  actions?: any[]
  [k: string]: any
}

export interface ConfigChatResp {
  reply: string
  change_plan: ChangePlanPreview | null
  requires_confirmation: boolean
  actions_summary: string[]
}

export const configChatApi = {
  chat(applicationId: number, payload: ConfigChatReq) {
    return request.post<any, ConfigChatResp>(
      `/applications/${applicationId}/config-chat`,
      payload
    )
  },
}

export default configChatApi
