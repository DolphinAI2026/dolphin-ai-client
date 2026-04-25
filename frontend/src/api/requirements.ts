import request, { API_PREFIX } from '@/utils/request'

export interface RequirementsSession {
  id: number
  title: string
  created_at: string
  updated_at: string
  selected_llm_config_id?: number | null
  project_id?: number | null
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
  forms?: Array<{
    form_code?: string
    formCode?: string
    form_name?: string
    formName?: string
    model_code?: string
    modelCode?: string
    all_model_codes?: string[]
    allModelCodes?: string[]
    components: Array<{
      field_code?: string
      fieldCode?: string
      field_name?: string
      fieldName?: string
      label?: string
      component_type?: string
      componentType?: string
      section_type?: string
      model_code?: string
      modelCode?: string
      required?: boolean
      hidden?: boolean
      readonly?: boolean
      show_in_list?: boolean
      searchable?: boolean
      dict_code?: string
      description?: string
    }>
  }>
  role_table_mapping: Array<{
    table_code: string
    table_name: string
    permissions: Array<{
      role_code: string
      role_name: string
      operations: string[]
      data_scope?: string
    }>
  }>
  modules?: Array<{
    module_name: string
    module_code: string
    description: string
    features: Array<{
      name: string
      description: string
      roles: string[]
    }>
  }>
  flows?: Array<{
    flow_name: string
    flow_code: string
    description: string
    steps: Array<{
      step: number
      action: string
      role: string
      status: string
    }>
  }>
  custom_development?: Array<{
    type?: string
    scene?: string
    name?: string
    item_name?: string
    trigger?: string
    reason?: string
    scope?: string
    implementation?: string
    deliverables?: string[] | string
    acceptance?: string
    acceptance_criteria?: string
  }>
}

export interface UnifiedPlanResponse {
  session_id: number
  project_id?: number | null
  summary: string
  doc_result: AnalysisResult
  builder_markdown: string
  coding_brief: string
  recommended_scene: string
  used_fallback: boolean
  fallback_reason?: string | null
  source_file_name?: string | null
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

  unifiedPlan: async (payload: {
    business_input: string
    coding_focus?: string
    selected_llm_config_id?: number | null
    project_id?: number | null
    file?: File | null
  }): Promise<UnifiedPlanResponse> => {
    const formData = new FormData()
    formData.append('business_input', payload.business_input ?? '')
    formData.append('coding_focus', payload.coding_focus ?? '')
    if (payload.selected_llm_config_id != null) {
      formData.append('selected_llm_config_id', String(payload.selected_llm_config_id))
    }
    if (payload.project_id != null) {
      formData.append('project_id', String(payload.project_id))
    }
    if (payload.file) {
      formData.append('file', payload.file)
    }
    return request.post(`${BASE}/unified-plan`, formData)
  },

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
