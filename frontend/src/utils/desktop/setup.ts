export type DesktopLoginMode = 'control_plane' | 'apaas'
export type DesktopLoginServiceMode = DesktopLoginMode | 'public_account' | 'trial_account'
export type DesktopWorkspaceEntryScope = 'apaas' | 'ai_platform' | 'both'

export type DesktopPhase =
  | 'needs_setup'
  | 'saving_config'
  | 'starting_runtime'
  | 'starting_sidecar'
  | 'ready'
  | 'failed'

export type DesktopSetupScope = 'full' | 'login_only'
export type DesktopPathKind = 'root' | 'logs'

export interface DesktopLoginConfig {
  mode: DesktopLoginMode
  base_url: string
}

export interface DesktopLoginServiceOption {
  mode: DesktopLoginServiceMode
  label: string
  defaultUrl: string
  enabled: boolean
}

export interface DesktopConfig {
  schema_version: number
  root_dir: string
  login: DesktopLoginConfig
  workspace_entry_scope: DesktopWorkspaceEntryScope
  discovery_url?: string
  discovery?: DesktopDiscoveryDocument | null
  local_ai_enabled?: boolean
}

export interface DesktopDiscoveryDocument {
  schema_version: number
  deployment_id: string
  platform: { type: string; name: string }
  auth: { provider: DesktopLoginMode; login_url: string; api_base_url?: string | null; logout_url?: string | null }
  products: {
    builder: { enabled: boolean; base_url?: string | null }
    code: { enabled: boolean; base_url?: string | null }
  }
  remote_capabilities: {
    models: boolean
    mcp: boolean
    skills: boolean
    knowledge_bases: boolean
  }
  local_ai: { enabled: boolean; allowed_kinds: string[]; bridge_protocol_version: number }
}

export interface DesktopSetupInput {
  root_dir: string
  login: DesktopLoginConfig
  workspace_entry_scope: DesktopWorkspaceEntryScope
  discovery_url?: string | null
  discovery?: DesktopDiscoveryDocument | null
  local_ai_enabled?: boolean
}

export interface DesktopStateSnapshot {
  phase: DesktopPhase
  setup_scope: DesktopSetupScope
  config: DesktopConfig | null
  default_root_dir: string
  error: { code: string; message: string } | null
}

export type DesktopSetupStep = 'login_service' | 'local_storage'
export type DesktopSetupRecovery = 'none' | 'edit_config' | 'retry_start'
export type DesktopSetupEvent = 'next' | 'back' | 'pick_directory' | 'poll_tick' | 'ready'

export interface DesktopSetupViewDecision {
  rootDir: string
  directoryEditable: boolean
  recovery: DesktopSetupRecovery
}

export interface DesktopSetupMachineState {
  scope: DesktopSetupScope
  step: DesktopSetupStep
}

export interface DesktopSetupTransition {
  step: DesktopSetupStep
  pickerRequests: 0 | 1
  pollAfterMs: number | null
  stopPolling: boolean
  navigation: null
}

export const DESKTOP_LOGIN_SERVICES: readonly DesktopLoginServiceOption[] = [
  { mode: 'control_plane', label: 'AI中台', defaultUrl: 'https://om-demo.dfy.definesys.cn', enabled: true },
  { mode: 'apaas', label: 'aPaaS平台', defaultUrl: 'https://apaas-trial.definesys.cn/backend', enabled: true },
  { mode: 'public_account', label: '公开账号', defaultUrl: '', enabled: false },
  { mode: 'trial_account', label: '试用账号', defaultUrl: '', enabled: false },
]

export const DESKTOP_WORKSPACE_ENTRY_OPTIONS = [
  { value: 'apaas', label: '仅 Builder' },
  { value: 'ai_platform', label: '仅 Code' },
  { value: 'both', label: '两者都有' },
] as const

export function buildDesktopSetupInput(
  rootDir: string,
  mode: DesktopLoginMode,
  baseUrl: string,
  workspaceEntryScope: DesktopWorkspaceEntryScope,
  discoveryUrl?: string,
  discovery?: DesktopDiscoveryDocument | null,
  localAiEnabled = true,
): DesktopSetupInput {
  return {
    root_dir: rootDir,
    login: { mode, base_url: baseUrl },
    workspace_entry_scope: workspaceEntryScope,
    discovery_url: discoveryUrl || baseUrl,
    discovery: discovery || null,
    local_ai_enabled: localAiEnabled,
  }
}

export function resolveDesktopSetupView(state: DesktopStateSnapshot): DesktopSetupViewDecision {
  const directoryEditable = state.setup_scope === 'full'
  const recovery = state.error?.code === 'DESKTOP_SETUP_CONFIG_INVALID'
    ? 'edit_config'
    : state.phase === 'failed'
      ? 'retry_start'
      : 'none'

  return {
    rootDir: state.config?.root_dir || state.default_root_dir,
    directoryEditable,
    recovery,
  }
}

export function transitionDesktopSetup(
  state: DesktopSetupMachineState,
  event: DesktopSetupEvent,
): DesktopSetupTransition {
  const step = event === 'next' && state.scope === 'full'
    ? 'local_storage'
    : event === 'back'
      ? 'login_service'
      : state.step
  const pickerRequests = event === 'pick_directory'
    && state.scope === 'full'
    && state.step === 'local_storage'
    ? 1
    : 0

  return {
    step,
    pickerRequests,
    pollAfterMs: event === 'poll_tick' ? 300 : null,
    stopPolling: event === 'ready',
    navigation: null,
  }
}

async function invokeDesktop<T>(
  command: string,
  args?: Record<string, unknown>,
): Promise<T> {
  if (!__DESKTOP__) throw new Error('Desktop capability is unavailable')
  const { invoke } = await import('@tauri-apps/api/core')
  return invoke<T>(command, args)
}

export function desktopErrorMessage(error: unknown, fallback: string): string {
  if (error instanceof Error && error.message.trim()) return error.message
  if (error && typeof error === 'object') {
    const message = 'message' in error ? String((error as { message?: unknown }).message ?? '') : ''
    if (message.trim()) return message
    const code = 'code' in error ? String((error as { code?: unknown }).code ?? '') : ''
    if (code.trim()) return code
  }
  if (typeof error === 'string' && error.trim()) return error
  return fallback
}

let cachedDesktopState: DesktopStateSnapshot | null = null

const PREVIEW_CONFIG_KEY = 'dolphin.desktop.web-preview.config'

function desktopWebPreviewEnabled(): boolean {
  return typeof __DESKTOP_WEB_PREVIEW__ !== 'undefined' && __DESKTOP_WEB_PREVIEW__
}

function previewState(config: DesktopConfig | null = null): DesktopStateSnapshot {
  return {
    phase: config ? 'ready' : 'needs_setup',
    setup_scope: 'full',
    config,
    default_root_dir: '/tmp/dolphin-code-workspace',
    error: null,
  }
}

function readPreviewConfig(): DesktopConfig | null {
  if (!desktopWebPreviewEnabled() || typeof localStorage === 'undefined') return null
  try {
    const raw = localStorage.getItem(PREVIEW_CONFIG_KEY)
    return raw ? JSON.parse(raw) as DesktopConfig : null
  } catch {
    return null
  }
}

function writePreviewConfig(config: DesktopConfig): DesktopStateSnapshot {
  if (desktopWebPreviewEnabled() && typeof localStorage !== 'undefined') {
    localStorage.setItem(PREVIEW_CONFIG_KEY, JSON.stringify(config))
  }
  cachedDesktopState = previewState(config)
  return cachedDesktopState
}

function previewDiscovery(url: string): DesktopDiscoveryDocument {
  const baseUrl = url.replace(/\/$/, '')
  const standaloneBuilder = new URL(baseUrl).pathname.replace(/\/$/, '').endsWith('/builder-standalone')
  return {
    schema_version: 1,
    deployment_id: standaloneBuilder ? 'builder-standalone' : 'control-plane',
    platform: standaloneBuilder
      ? { type: 'apaas_builder', name: 'aPaaS Builder' }
      : { type: 'control_plane', name: 'Dolphin Control Plane' },
    auth: {
      provider: standaloneBuilder ? 'apaas' : 'control_plane',
      login_url: baseUrl,
      api_base_url: baseUrl,
    },
    products: {
      builder: { enabled: true, base_url: baseUrl },
      code: { enabled: !standaloneBuilder, base_url: standaloneBuilder ? null : baseUrl },
    },
    remote_capabilities: { models: true, mcp: true, skills: true, knowledge_bases: true },
    local_ai: {
      enabled: true,
      allowed_kinds: ['models', 'mcp', 'skills', 'knowledge_bases'],
      bridge_protocol_version: 1,
    },
  }
}

async function invokeDesktopState(
  command: string,
  args?: Record<string, unknown>,
): Promise<DesktopStateSnapshot> {
  const state = await invokeDesktop<DesktopStateSnapshot>(command, args)
  cachedDesktopState = state
  return state
}

export function getCachedDesktopState(): DesktopStateSnapshot | null {
  return cachedDesktopState
}

export function resolveDesktopProductScope(config?: DesktopConfig | null): DesktopWorkspaceEntryScope {
  const products = config?.discovery?.products
  if (products) {
    if (products.builder.enabled && !products.code.enabled) return 'apaas'
    if (!products.builder.enabled && products.code.enabled) return 'ai_platform'
    return 'both'
  }
  return config?.workspace_entry_scope || 'both'
}

export function getDesktopState(): Promise<DesktopStateSnapshot> {
  if (desktopWebPreviewEnabled()) {
    const state = previewState(readPreviewConfig())
    cachedDesktopState = state
    return Promise.resolve(state)
  }
  return invokeDesktopState('desktop_get_state')
}

export function saveDesktopSetup(input: DesktopSetupInput): Promise<DesktopStateSnapshot> {
  if (desktopWebPreviewEnabled()) {
    const discovery = input.discovery || previewDiscovery(input.discovery_url || input.login.base_url)
    return Promise.resolve(writePreviewConfig({
      schema_version: 2,
      root_dir: input.root_dir || '/tmp/dolphin-code-workspace',
      login: input.login,
      workspace_entry_scope: input.workspace_entry_scope,
      discovery_url: input.discovery_url || input.login.base_url,
      discovery,
      local_ai_enabled: input.local_ai_enabled ?? true,
    }))
  }
  return invokeDesktopState('desktop_save_setup', { input })
}

export function testDesktopService(login: DesktopLoginConfig): Promise<void> {
  if (desktopWebPreviewEnabled()) return Promise.resolve()
  return invokeDesktop('desktop_test_service', { login })
}

export function discoverDesktopService(url: string): Promise<DesktopDiscoveryDocument> {
  if (desktopWebPreviewEnabled()) return Promise.resolve(previewDiscovery(url))
  return invokeDesktop('desktop_discover_service', { url })
}

export function enterDesktopLoginSetup(): Promise<void> {
  if (desktopWebPreviewEnabled()) return Promise.resolve()
  return invokeDesktop('desktop_enter_login_setup')
}

export function retryDesktopStart(): Promise<DesktopStateSnapshot> {
  if (desktopWebPreviewEnabled()) return Promise.resolve(previewState(readPreviewConfig()))
  return invokeDesktop('desktop_retry_start')
}

export function updateDesktopLogin(login: DesktopLoginConfig): Promise<DesktopStateSnapshot> {
  if (desktopWebPreviewEnabled()) {
    const current = readPreviewConfig()
    return Promise.resolve(current ? writePreviewConfig({ ...current, login }) : previewState())
  }
  return invokeDesktopState('desktop_update_login', { login })
}

export function updateDesktopWorkspaceEntryScope(
  scope: DesktopWorkspaceEntryScope,
): Promise<DesktopStateSnapshot> {
  if (desktopWebPreviewEnabled()) {
    const current = readPreviewConfig()
    return Promise.resolve(current ? writePreviewConfig({ ...current, workspace_entry_scope: scope }) : previewState())
  }
  return invokeDesktopState('desktop_update_workspace_entry_scope', { scope })
}

export function openDesktopPath(kind: DesktopPathKind): Promise<void> {
  if (desktopWebPreviewEnabled()) return Promise.resolve()
  return invokeDesktop('desktop_open_path', { kind })
}
