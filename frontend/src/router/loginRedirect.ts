import type { TenantOption } from '@/types'
import { normalizeTenantPublicId } from './tenantUrlGuard'

const REDIRECT_ORIGIN = 'https://login-redirect.invalid'

function firstQueryValue(raw: unknown): unknown {
  return Array.isArray(raw) ? raw[0] : raw
}

export function safeLoginRedirectPath(raw: unknown): string {
  const value = firstQueryValue(raw)
  const text = typeof value === 'string' ? value.trim() : ''
  if (!text.startsWith('/') || text.startsWith('//')) return ''

  try {
    const parsed = new URL(text, REDIRECT_ORIGIN)
    if (parsed.origin !== REDIRECT_ORIGIN) return ''
    if (
      parsed.pathname === '/login'
      || parsed.pathname.startsWith('/login/')
      || parsed.pathname === '/tenant-select'
      || parsed.pathname.startsWith('/tenant-select/')
    ) {
      return ''
    }
    return `${parsed.pathname}${parsed.search}${parsed.hash}`
  } catch {
    return ''
  }
}

export function resolveExternalLoginRedirect(
  raw: unknown,
  baseUrl = import.meta.env.BASE_URL || '/',
): string {
  const redirect = safeLoginRedirectPath(raw)
  if (!redirect) return ''

  const parsed = new URL(redirect, REDIRECT_ORIGIN)
  if (parsed.pathname !== '/web-console' && parsed.pathname !== '/web-console/') {
    return ''
  }

  const normalizedBase = `/${baseUrl}`.replace(/\/+/g, '/').replace(/\/$/, '')
  return `${normalizedBase}/web-console/${parsed.search}${parsed.hash}`
}

export function tenantIdFromRedirect(raw: unknown): string | null {
  const redirect = safeLoginRedirectPath(raw)
  if (!redirect) return null

  try {
    const parsed = new URL(redirect, REDIRECT_ORIGIN)
    const tenantIds = parsed.searchParams.getAll('tenantId')
    if (tenantIds.length !== 1) return null
    return normalizeTenantPublicId(tenantIds[0])
  } catch {
    return null
  }
}

export function resolveLoginTenant(
  redirect: unknown,
  tenants: TenantOption[] | null | undefined,
): TenantOption | undefined {
  const targetTenantPublicId = tenantIdFromRedirect(redirect)
  if (!targetTenantPublicId) return undefined
  return (tenants || []).find(
    tenant => normalizeTenantPublicId(tenant.tenant_public_id) === targetTenantPublicId,
  )
}
