import type { TenantOption } from '@/types'
import { normalizeTenantPublicId } from '@/router/tenantUrlGuard'

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
