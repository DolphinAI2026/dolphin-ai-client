import request from '@/utils/request'

export type EnterpriseAuthProvider = 'apaas' | 'control_plane'

export interface EnterpriseAuthStatus {
  auth_provider: string
  binding_enabled: boolean
}

export interface EnterpriseAuthAccountSummary {
  id: number
  provider: EnterpriseAuthProvider
  base_url: string
  tenant_ref: string
  tenant_name: string | null
  account: string
  status: string
}

export interface EnterpriseAuthAccount extends EnterpriseAuthAccountSummary {
  has_password: boolean
  has_access_token: boolean
  last_verified_at: string | null
  last_error: string | null
  created_at: string
  updated_at: string
}

export interface EnterpriseAuthAccountCreatePayload {
  provider: EnterpriseAuthProvider
  base_url: string
  tenant_ref: string
  tenant_name?: string | null
  account: string
  password: string
  enabled: boolean
}

export interface EnterpriseAuthAccountUpdatePayload {
  provider?: EnterpriseAuthProvider
  base_url?: string
  tenant_ref?: string
  tenant_name?: string | null
  account?: string
  password?: string
  enabled?: boolean
}

export interface EnterpriseAuthAccountFormValue {
  provider: EnterpriseAuthProvider
  base_url: string
  tenant_ref: string
  tenant_name: string
  account: string
  password: string
  enabled: boolean
}

export interface EnterpriseAuthBinding {
  id: number
  left_account_id: number
  right_account_id: number
  priority: number
  enabled: boolean
  left_account: EnterpriseAuthAccountSummary
  right_account: EnterpriseAuthAccountSummary
  created_at: string
  updated_at: string
}

export interface EnterpriseAuthBindingCreatePayload {
  left_account_id: number
  right_account_id: number
  priority: number
  enabled: boolean
}

export interface EnterpriseAuthBindingUpdatePayload {
  left_account_id?: number
  right_account_id?: number
  priority?: number
  enabled?: boolean
}

export interface EnterpriseAuthDeleteResult {
  ok: boolean
  deleted_id: number
}

export type EnterpriseAuthIdentitySource = Pick<
  EnterpriseAuthAccountFormValue,
  'provider' | 'base_url' | 'account'
>

export function isEnterpriseAuthBindingPairAllowed(
  left: Pick<EnterpriseAuthAccountSummary, 'id' | 'provider'> | null | undefined,
  right: Pick<EnterpriseAuthAccountSummary, 'id' | 'provider'> | null | undefined,
): boolean {
  return Boolean(
    left
    && right
    && left.id !== right.id
    && left.provider !== right.provider,
  )
}

function baseUrlOrigin(value: string): string {
  try {
    return new URL(value.trim()).origin
  } catch {
    return value.trim().replace(/\/+$/, '')
  }
}

export function hasEnterpriseAuthIdentitySourceChanged(
  original: EnterpriseAuthIdentitySource,
  current: EnterpriseAuthIdentitySource,
): boolean {
  return (
    original.provider !== current.provider
    || original.account.trim() !== current.account.trim()
    || baseUrlOrigin(original.base_url) !== baseUrlOrigin(current.base_url)
  )
}

export function sanitizeEnterpriseAuthLastError(
  value: string | null | undefined,
  maxLength = 96,
): string {
  const redacted = String(value || '')
    .replace(/\bBearer\s+\S+/gi, 'Bearer ***')
    .replace(
      /\b(password|access[_-]?token|refresh[_-]?token|token)\s*[:=]\s*[^\s,;]+/gi,
      '$1=***',
    )
  if (redacted.length <= maxLength) return redacted
  return `${redacted.slice(0, Math.max(0, maxLength - 1))}…`
}

export function buildEnterpriseAuthAccountUpdatePayload(
  value: EnterpriseAuthAccountFormValue,
): EnterpriseAuthAccountUpdatePayload {
  const payload: EnterpriseAuthAccountUpdatePayload = {
    provider: value.provider,
    base_url: value.base_url.trim(),
    tenant_ref: value.tenant_ref.trim(),
    tenant_name: value.tenant_name.trim() || null,
    account: value.account.trim(),
    enabled: value.enabled,
  }
  if (value.password.trim()) payload.password = value.password
  return payload
}

export const enterpriseAuthApi = {
  getStatus: () =>
    request.get<unknown, EnterpriseAuthStatus>('/enterprise-auth/status'),
  listAccounts: () =>
    request.get<unknown, EnterpriseAuthAccount[]>('/enterprise-auth/accounts'),
  createAccount: (payload: EnterpriseAuthAccountCreatePayload) =>
    request.post<unknown, EnterpriseAuthAccount>('/enterprise-auth/accounts', payload),
  updateAccount: (accountId: number, payload: EnterpriseAuthAccountUpdatePayload) =>
    request.put<unknown, EnterpriseAuthAccount>(
      `/enterprise-auth/accounts/${accountId}`,
      payload,
    ),
  testAccount: (accountId: number) =>
    request.post<unknown, EnterpriseAuthAccount>(
      `/enterprise-auth/accounts/${accountId}/test`,
    ),
  deleteAccount: (accountId: number) =>
    request.delete<unknown, EnterpriseAuthDeleteResult>(
      `/enterprise-auth/accounts/${accountId}`,
    ),
  listBindings: () =>
    request.get<unknown, EnterpriseAuthBinding[]>('/enterprise-auth/bindings'),
  createBinding: (payload: EnterpriseAuthBindingCreatePayload) =>
    request.post<unknown, EnterpriseAuthBinding>('/enterprise-auth/bindings', payload),
  updateBinding: (bindingId: number, payload: EnterpriseAuthBindingUpdatePayload) =>
    request.put<unknown, EnterpriseAuthBinding>(
      `/enterprise-auth/bindings/${bindingId}`,
      payload,
    ),
  deleteBinding: (bindingId: number) =>
    request.delete<unknown, EnterpriseAuthDeleteResult>(
      `/enterprise-auth/bindings/${bindingId}`,
    ),
}
