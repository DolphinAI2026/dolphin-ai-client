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
}

export interface DesktopSetupInput {
  root_dir: string
  login: DesktopLoginConfig
  workspace_entry_scope: DesktopWorkspaceEntryScope
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
  { value: 'apaas', label: '仅 aPaaS' },
  { value: 'ai_platform', label: '仅 AI平台' },
  { value: 'both', label: '两者都有' },
] as const

export function buildDesktopSetupInput(
  rootDir: string,
  mode: DesktopLoginMode,
  baseUrl: string,
  workspaceEntryScope: DesktopWorkspaceEntryScope,
): DesktopSetupInput {
  return {
    root_dir: rootDir,
    login: { mode, base_url: baseUrl },
    workspace_entry_scope: workspaceEntryScope,
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

let cachedDesktopState: DesktopStateSnapshot | null = null

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

export function getDesktopState(): Promise<DesktopStateSnapshot> {
  return invokeDesktopState('desktop_get_state')
}

export function saveDesktopSetup(input: DesktopSetupInput): Promise<DesktopStateSnapshot> {
  return invokeDesktopState('desktop_save_setup', { input })
}

export function testDesktopService(login: DesktopLoginConfig): Promise<void> {
  return invokeDesktop('desktop_test_service', { login })
}

export function enterDesktopLoginSetup(): Promise<void> {
  return invokeDesktop('desktop_enter_login_setup')
}

export function retryDesktopStart(): Promise<DesktopStateSnapshot> {
  return invokeDesktop('desktop_retry_start')
}

export function updateDesktopLogin(login: DesktopLoginConfig): Promise<DesktopStateSnapshot> {
  return invokeDesktopState('desktop_update_login', { login })
}

export function updateDesktopWorkspaceEntryScope(
  scope: DesktopWorkspaceEntryScope,
): Promise<DesktopStateSnapshot> {
  return invokeDesktopState('desktop_update_workspace_entry_scope', { scope })
}

export function openDesktopPath(kind: DesktopPathKind): Promise<void> {
  return invokeDesktop('desktop_open_path', { kind })
}
