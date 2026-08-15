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

async function invokeDesktop<T>(
  command: string,
  args?: Record<string, unknown>,
): Promise<T> {
  if (!__DESKTOP__) throw new Error('Desktop capability is unavailable')
  const { invoke } = await import('@tauri-apps/api/core')
  return invoke<T>(command, args)
}

function normalizeSensitiveKey(key: string): string {
  return key.replace(/[^A-Za-z0-9]/g, '').toLowerCase()
}

function isSensitiveKey(key: string): boolean {
  const normalized = normalizeSensitiveKey(key)
  return normalized === 'authorization'
    || normalized.endsWith('password')
    || normalized.endsWith('token')
    || normalized.endsWith('apikey')
    || normalized.endsWith('secret')
    || normalized.endsWith('encryptionkey')
    || normalized.endsWith('privatekey')
    || normalized.endsWith('authenticationresponse')
}

function containsSensitiveText(value: string): boolean {
  if (/traceback/i.test(value) || /\bbearer\s+\S+/i.test(value)) return true
  if (value.split(/[\s"'(),;[\]{}]+/).some((candidate) => {
    const parts = candidate.split('.')
    return parts.length === 3
      && parts[0].startsWith('eyJ')
      && parts.every(part => part.length > 0 && /^[A-Za-z0-9_-]+$/.test(part))
  })) return true
  for (let index = 0; index < value.length; index += 1) {
    const match = value.slice(index).match(/^["']?([A-Za-z0-9 _-]{1,80})["']?\s*[:=]/)
    if (match && isSensitiveKey(match[1])) return true
  }
  for (const match of value.matchAll(/https?:\/\/[^\s"'<>]+/gi)) {
    try {
      const url = new URL(match[0].replace(/[,;\)\]\}]+$/, ''))
      if (url.username || url.password) return true
      if ([...url.searchParams.keys()].some(isSensitiveKey)) return true
    } catch {
      // Malformed URLs remain ordinary error text.
    }
  }
  return false
}

function containsSensitiveValue(value: unknown): boolean {
  if (Array.isArray(value)) return value.some(containsSensitiveValue)
  if (value && typeof value === 'object') {
    return Object.entries(value).some(([key, item]) => (
      isSensitiveKey(key) || containsSensitiveValue(item)
    ))
  }
  return typeof value === 'string' && containsSensitiveText(value)
}

export function desktopErrorMessage(error: unknown, fallback: string): string {
  const raw = error instanceof Error
    ? error.message
    : error && typeof error === 'object' && 'message' in error
      ? String((error as { message?: unknown }).message ?? '')
      : typeof error === 'string'
        ? error
        : ''
  if (!raw.trim()) {
    const code = error && typeof error === 'object' && 'code' in error
      ? String((error as { code?: unknown }).code ?? '').trim()
      : ''
    return code && !containsSensitiveText(code) ? code.slice(0, 240) : fallback
  }
  let parsed: unknown = raw
  try { parsed = JSON.parse(raw) } catch { /* Plain text is checked below. */ }
  if (containsSensitiveValue(parsed)) return fallback
  return raw.split(/\r?\n/).find(line => line.trim())?.trim().slice(0, 240) || fallback
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
