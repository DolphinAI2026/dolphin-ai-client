import request, { API_PREFIX } from '@/utils/request'

export interface RequirementsSession {
  id: number
  title: string
  created_at: string
  updated_at: string
  selected_llm_config_id?: number | null
  has_doc?: boolean
  doc_result?: AnalysisResult | null
  messages?: ChatMessage[]
}

export interface ChatMessage {
  id?: number
  role: 'user' | 'assistant'
  content: string
  created_at?: string
}

export interface AnalysisResult {
  app_info: {
    code: string
    name: string
    description: string
  }
  roles: Array<{
    role_code: string
    role_name: string
    description: string
  }>
  data_dictionary: Array<{
    dict_code: string
    dict_name: string
    items: Array<{ item_code: string; item_name: string }>
  }>
  tables: Array<{
    table_code: string
    table_name: string
    table_type: string
    parent_table: string
    description: string
    fields: Array<{
      field_code: string
      field_name: string
      data_type: string
      length: string
      is_pk: boolean
      is_fk: boolean
      nullable: boolean
      default_value: string
      description: string
    }>
  }>
  role_table_mapping: Array<{
    table_code: string
    table_name: string
    permissions: Array<{
      role_code: string
      role_name: string
      operations: string[]
    }>
  }>
}

const BASE = '/requirements'

export const requirementsApi = {
  createSession: (data?: { selected_llm_config_id?: number | null }): Promise<RequirementsSession> =>
    request.post(`${BASE}/sessions`, data ?? {}),

  listSessions: (): Promise<RequirementsSession[]> =>
    request.get(`${BASE}/sessions`),

  getSession: (id: number): Promise<RequirementsSession> =>
    request.get(`${BASE}/sessions/${id}`),

  deleteSession: (id: number): Promise<{ ok: boolean }> =>
    request.delete(`${BASE}/sessions/${id}`),

  exportMd: (doc_result: AnalysisResult): Promise<{ markdown: string }> =>
    request.post(`${BASE}/export-md`, { doc_result }),

  /** SSE URL for chat */
  chatUrl: (sessionId: number) =>
    `${API_PREFIX}${BASE}/sessions/${sessionId}/chat`,

  /** SSE URL for chat with file */
  chatWithFileUrl: (sessionId: number) =>
    `${API_PREFIX}${BASE}/sessions/${sessionId}/chat-with-file`,

  /** SSE URL for generate-doc */
  generateDocUrl: (sessionId: number) =>
    `${API_PREFIX}${BASE}/sessions/${sessionId}/generate-doc`,

  /** SSE URL for generate-doc-chat (streaming conversation + JSON) */
  generateDocChatUrl: (sessionId: number) =>
    `${API_PREFIX}${BASE}/sessions/${sessionId}/generate-doc-chat`,
}
