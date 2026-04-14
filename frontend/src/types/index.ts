export interface User {
  id: number
  username: string
  is_active: boolean
  created_at: string
  tenant_id?: number
  tenant_name?: string
  tenant_role?: string
  org_permissions?: Record<string, boolean>
}

export interface LoginRequest {
  username: string
  password: string
}

export interface RegisterRequest {
  username: string
  password: string
}

export interface TenantOption {
  tenant_id: number
  tenant_name: string
  tenant_code: string
}

export interface LoginResponse {
  access_token?: string
  token_type: string
  requires_tenant_selection: boolean
  selection_token?: string
  tenants?: TenantOption[]
}

export interface Token {
  access_token: string
  token_type: string
}

export interface TenantSelectRequest {
  selection_token: string
  tenant_id: number
}

export interface Conversation {
  id: number
  title: string
  agent_type: 'builder' | 'assistant' | 'developer' | 'coding' | 'requirements'
  status: string
  selected_llm_config_id?: number | null
  created_at: string
  updated_at: string
}

export interface Message {
  id: number
  role: 'user' | 'assistant' | 'system'
  content: string
  agent?: string
  created_at: string
}

export interface Application {
  id: number
  app_name: string
  app_code: string
  icon_svg?: string | null
  description: string | null
  status: string
  conversation_id?: number | null
  platform_env_id?: number | null
  apaas_app_id?: string | null
  apaas_url?: string | null
  models?: number
  forms?: number
  roles?: number
  dicts?: number
  created_at: string
  updated_at: string
}

export interface MergedApplication {
  id: string
  app_name: string
  app_code?: string
  icon_svg?: string
  description?: string
  source: 'local' | 'remote' | 'linked'
  status: string
  local_status?: string
  remote_status?: string
  apaas_app_id?: string
  apaas_url?: string
  conversation_id?: number
  models: number
  forms: number
  roles: number
  dicts: number
  config_preview?: any
  permissions?: Record<string, boolean>
  env_name?: string
  env_status?: string
  created_at?: string
  updated_at?: string
}

export interface ChatRequest {
  conversation_id: number
  message: string
}

export interface ConversationCreate {
  agent_type: 'builder' | 'assistant' | 'developer' | 'coding'
  selected_llm_config_id?: number | null
}

// Preview types
export interface ModelField {
  name: string
  type: string
  icon: string
  required?: boolean
  dict?: string
  ref?: string | { model: string; field: string }
  sub_fields?: ModelField[]
  sub_code?: string
}

export interface ModelDef {
  name: string
  code: string
  fields: ModelField[]
}

export interface RoleDef {
  code: string
  name: string
}

export interface DictDef {
  name: string
  code: string
  options: (string | { name: string; code: string })[]
}

export interface WorkflowNode {
  name: string
  role: string
  type: 'start' | 'approve' | 'end'
}

export interface WorkflowDef {
  name: string
  form: string
  nodes: WorkflowNode[]
}

export interface PermissionRule {
  role: string
  op: string
  data: string
}

export interface PermissionDef {
  form: string
  rules: PermissionRule[]
}

export interface PreviewData {
  appName: string
  roles: RoleDef[]
  dicts: DictDef[]
  models: ModelDef[]
  forms: any[]
  workflows: WorkflowDef[]
  permissions: PermissionDef[]
}

export interface GenStage {
  name: string
  status: 'done' | 'running' | 'pending' | 'error'
  steps: string[]
}

export interface GenProgress {
  stage: number
  stages: GenStage[]
}
