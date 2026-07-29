export type DesktopLoginMode = 'control_plane' | 'apaas'
export type DesktopLoginServiceMode = DesktopLoginMode | 'public_account' | 'trial_account'

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
}

export interface DesktopSetupInput {
  root_dir: string
  login: DesktopLoginConfig
}

export interface DesktopStateSnapshot {
  phase: DesktopPhase
  setup_scope: DesktopSetupScope
  config: DesktopConfig | null
  default_root_dir: string
  error: { code: string; message: string } | null
}

export const DESKTOP_LOGIN_SERVICES: readonly DesktopLoginServiceOption[] = [
  { mode: 'control_plane', label: 'AI中台', defaultUrl: 'https://om-demo.dfy.definesys.cn', enabled: true },
  { mode: 'apaas', label: 'aPaaS平台', defaultUrl: 'https://apaas-trial.definesys.cn/backend', enabled: true },
  { mode: 'public_account', label: '公开账号', defaultUrl: '', enabled: false },
  { mode: 'trial_account', label: '试用账号', defaultUrl: '', enabled: false },
]

export function buildDesktopSetupInput(
  rootDir: string,
  mode: DesktopLoginMode,
  baseUrl: string,
): DesktopSetupInput {
  return { root_dir: rootDir, login: { mode, base_url: baseUrl } }
}

async function invokeDesktop<T>(
  command: string,
  args?: Record<string, unknown>,
): Promise<T> {
  if (!__DESKTOP__) throw new Error('Desktop capability is unavailable')
  const { invoke } = await import('@tauri-apps/api/core')
  return invoke<T>(command, args)
}

export function getDesktopState(): Promise<DesktopStateSnapshot> {
  return invokeDesktop('desktop_get_state')
}

export function saveDesktopSetup(input: DesktopSetupInput): Promise<DesktopStateSnapshot> {
  return invokeDesktop('desktop_save_setup', { input })
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
  return invokeDesktop('desktop_update_login', { login })
}

export function openDesktopPath(kind: DesktopPathKind): Promise<void> {
  return invokeDesktop('desktop_open_path', { kind })
}
