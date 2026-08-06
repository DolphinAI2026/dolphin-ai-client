export interface User {
  id: number
  username: string
  display_name?: string | null
  is_active: boolean
  is_platform_admin?: boolean
  created_at: string
  tenant_id?: number | null
  tenant_public_id?: string | null
  tenant_name?: string
  control_plane_tenant_id?: string | null
  control_plane_tenant_name?: string | null
  account_source?: 'apaas' | 'control_plane' | 'coding' | 'desktop' | string | null
  tenant_authority?: 'builder' | 'control_plane' | string | null
  tenant_role?: string
  org_permissions?: Record<string, boolean>
}

export interface LoginRequest {
  username: string
  password: string
  captcha_id?: string
  captcha_code?: string
}

export interface LoginCaptcha {
  required: boolean
  captcha_id?: string
  image_data?: string
}

export type LoginProvider = 'apaas' | 'platform'

export interface PublicAuthProvider {
  provider: LoginProvider
  label: string
  enabled: boolean
  default: boolean
}

export interface PublicBuilderAuthSettings {
  default_login_provider: LoginProvider
  enabled_login_providers: LoginProvider[]
  products: {
    builder: { enabled: boolean }
    code: { enabled: boolean }
  }
  providers: PublicAuthProvider[]
}

export interface TenantOption {
  tenant_id: number | string
  tenant_public_id?: string | null
  tenant_name: string
  tenant_code: string
}

export interface LoginResponse {
  access_token?: string
  apaas_access_token?: string
  apaas_tenant_id?: string | null
  token_type: string
  requires_tenant_selection: boolean
  selection_token?: string
  tenants?: TenantOption[]
  entry_path?: string
  is_platform_admin?: boolean
  has_tenant_context?: boolean
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
  spec_id?: string | null
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
  // Phase C：project & git
  project_id?: number | null
  git_repo_url?: string | null
  git_provider?: string | null
  git_default_branch?: string | null
  created_at: string
  updated_at: string
}

export interface MergedApplication {
  id: string
  app_name: string
  app_code?: string
  icon_svg?: string
  description?: string
  source: 'local' | 'remote' | 'linked' | 'd-ai-code' | 'desktop-local'
  status: string
  local_status?: string
  remote_status?: string
  apaas_app_id?: string
  apaas_url?: string
  conversation_id?: number
  canonical_spec_id?: string | null
  models: number
  forms: number
  roles: number
  dicts: number
  config_preview?: any
  permissions?: Record<string, boolean>
  env_name?: string
  env_status?: string
  // Phase C：project & git
  project_id?: number | null
  git_repo_url?: string | null
  git_provider?: string | null
  git_default_branch?: string | null
  app_type?: string            // 'low-code' | 'ai-code'
  external_application_id?: string
  source_workspace_id?: string | null
  created_at?: string
  updated_at?: string
}

export interface ChatRequest {
  conversation_id: number
  message: string
}

export interface ConversationCreate {
  agent_type: 'builder' | 'assistant' | 'developer' | 'coding' | 'requirements'
  selected_llm_config_id?: number | null
  initial_message?: string | null
  spec_id?: string | null
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
  flows?: any[]
  workflows: WorkflowDef[]
  permissions: PermissionDef[]
  custom_development?: any[]
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
