import request from '@/utils/request'
import type { Conversation, ConversationCreate, Message } from '@/types'

export interface ConversationWithApp {
  id: number
  title: string
  agent_type: string
  status: string
  selected_llm_config_id?: number | null
  created_at: string
  updated_at: string
  app_id?: number
  app_name?: string
  apaas_app_id?: string
  local_status?: string
  message_count?: number
}

export const conversationApi = {
  create(data: ConversationCreate) {
    return request.post<any, Conversation>('/conversations', data)
  },

  list() {
    return request.get<any, Conversation[]>('/conversations')
  },

  get(id: number) {
    return request.get<any, Conversation>(`/conversations/${id}`)
  },

  updateModel(id: number, selected_llm_config_id: number | null) {
    return request.patch<any, Conversation>(`/conversations/${id}/model`, { selected_llm_config_id })
  },

  getMessages(conversationId: number) {
    return request.get<any, Message[]>(`/conversations/${conversationId}/messages`)
  },

  /** 获取带应用信息的对话列表（用于对话历史） */
  listWithApps(params?: { agent_type?: string }) {
    return request.get<any, ConversationWithApp[]>('/conversations/with-apps/list', { params })
  }
}
