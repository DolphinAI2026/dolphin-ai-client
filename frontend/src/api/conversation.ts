import request from '@/utils/request'
import type { Conversation, ConversationCreate, Message } from '@/types'

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

  getMessages(conversationId: number) {
    return request.get<any, Message[]>(`/conversations/${conversationId}/messages`)
  }
}
