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

export class EnterpriseAuthApiError extends Error {
  code?: string
  detail?: unknown

  constructor(message: string, code?: string, detail?: unknown) {
    super(message)
    this.name = 'EnterpriseAuthApiError'
    this.code = code
    this.detail = detail
  }
}

export function canonicalizeEnterpriseAuthPair(
  firstAccountId: number,
  secondAccountId: number,
): [number, number] {
  return firstAccountId <= secondAccountId
    ? [firstAccountId, secondAccountId]
    : [secondAccountId, firstAccountId]
}

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
  if (value.password.trim()) {
    payload.password = value.password
  }
  return payload
}

function detailMessage(detail: unknown): string | undefined {
  if (typeof detail === 'string' && detail.trim()) return detail
  if (Array.isArray(detail)) {
    const first = detail.find((item) => item && typeof item === 'object') as
      | { msg?: unknown; message?: unknown }
      | undefined
    const message = first?.message ?? first?.msg
    return typeof message === 'string' && message.trim() ? message : undefined
  }
  if (detail && typeof detail === 'object') {
    const message = (detail as { message?: unknown }).message
    return typeof message === 'string' && message.trim() ? message : undefined
  }
  return undefined
}

function normalizeEnterpriseAuthError(error: unknown): EnterpriseAuthApiError {
  if (error instanceof EnterpriseAuthApiError) return error
  const responseData = (
    error as { response?: { data?: unknown } } | null | undefined
  )?.response?.data
  const data = responseData && typeof responseData === 'object'
    ? responseData as Record<string, unknown>
    : {}
  const detail = data.detail
  const detailRecord = detail && typeof detail === 'object' && !Array.isArray(detail)
    ? detail as Record<string, unknown>
    : {}
  const topLevelCode = typeof data.code === 'string' ? data.code : undefined
  const detailCode = typeof detailRecord.code === 'string' ? detailRecord.code : undefined
  const topLevelMessage = typeof data.message === 'string' && data.message.trim()
    ? data.message
    : undefined
  const fallbackMessage = (
    error as { message?: unknown } | null | undefined
  )?.message
  const message = topLevelMessage
    || detailMessage(detail)
    || (typeof fallbackMessage === 'string' && fallbackMessage.trim()
      ? fallbackMessage
      : '企业认证请求失败')
  return new EnterpriseAuthApiError(message, topLevelCode || detailCode, detail)
}

async function enterpriseAuthRequest<T>(operation: () => Promise<T>): Promise<T> {
  try {
    return await operation()
  } catch (error) {
    throw normalizeEnterpriseAuthError(error)
  }
}

function canonicalBindingCreatePayload(
  payload: EnterpriseAuthBindingCreatePayload,
): EnterpriseAuthBindingCreatePayload {
  const [leftAccountId, rightAccountId] = canonicalizeEnterpriseAuthPair(
    payload.left_account_id,
    payload.right_account_id,
  )
  return {
    ...payload,
    left_account_id: leftAccountId,
    right_account_id: rightAccountId,
  }
}

function canonicalBindingUpdatePayload(
  payload: EnterpriseAuthBindingUpdatePayload,
): EnterpriseAuthBindingUpdatePayload {
  if (
    payload.left_account_id === undefined
    || payload.right_account_id === undefined
  ) {
    return payload
  }
  const [leftAccountId, rightAccountId] = canonicalizeEnterpriseAuthPair(
    payload.left_account_id,
    payload.right_account_id,
  )
  return {
    ...payload,
    left_account_id: leftAccountId,
    right_account_id: rightAccountId,
  }
}

export const enterpriseAuthApi = {
  getStatus(): Promise<EnterpriseAuthStatus> {
    return enterpriseAuthRequest(() =>
      request.get<unknown, EnterpriseAuthStatus>('/enterprise-auth/status'))
  },

  listAccounts(): Promise<EnterpriseAuthAccount[]> {
    return enterpriseAuthRequest(() =>
      request.get<unknown, EnterpriseAuthAccount[]>('/enterprise-auth/accounts'))
  },

  createAccount(
    payload: EnterpriseAuthAccountCreatePayload,
  ): Promise<EnterpriseAuthAccount> {
    return enterpriseAuthRequest(() =>
      request.post<unknown, EnterpriseAuthAccount>('/enterprise-auth/accounts', payload))
  },

  updateAccount(
    accountId: number,
    payload: EnterpriseAuthAccountUpdatePayload,
  ): Promise<EnterpriseAuthAccount> {
    return enterpriseAuthRequest(() =>
      request.put<unknown, EnterpriseAuthAccount>(
        `/enterprise-auth/accounts/${accountId}`,
        payload,
      ))
  },

  testAccount(accountId: number): Promise<EnterpriseAuthAccount> {
    return enterpriseAuthRequest(() =>
      request.post<unknown, EnterpriseAuthAccount>(
        `/enterprise-auth/accounts/${accountId}/test`,
      ))
  },

  deleteAccount(accountId: number): Promise<EnterpriseAuthDeleteResult> {
    return enterpriseAuthRequest(() =>
      request.delete<unknown, EnterpriseAuthDeleteResult>(
        `/enterprise-auth/accounts/${accountId}`,
      ))
  },

  listBindings(): Promise<EnterpriseAuthBinding[]> {
    return enterpriseAuthRequest(() =>
      request.get<unknown, EnterpriseAuthBinding[]>('/enterprise-auth/bindings'))
  },

  createBinding(
    payload: EnterpriseAuthBindingCreatePayload,
  ): Promise<EnterpriseAuthBinding> {
    return enterpriseAuthRequest(() =>
      request.post<unknown, EnterpriseAuthBinding>(
        '/enterprise-auth/bindings',
        canonicalBindingCreatePayload(payload),
      ))
  },

  updateBinding(
    bindingId: number,
    payload: EnterpriseAuthBindingUpdatePayload,
  ): Promise<EnterpriseAuthBinding> {
    return enterpriseAuthRequest(() =>
      request.put<unknown, EnterpriseAuthBinding>(
        `/enterprise-auth/bindings/${bindingId}`,
        canonicalBindingUpdatePayload(payload),
      ))
  },

  deleteBinding(bindingId: number): Promise<EnterpriseAuthDeleteResult> {
    return enterpriseAuthRequest(() =>
      request.delete<unknown, EnterpriseAuthDeleteResult>(
        `/enterprise-auth/bindings/${bindingId}`,
      ))
  },
}
