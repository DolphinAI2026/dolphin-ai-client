import { authApi } from '@/api/auth'
import { resolveExternalLoginRedirect } from '@/router/loginRedirect'

export async function recoverWebConsoleRedirect(
  redirect: unknown,
  hasBuilderSession: boolean,
  baseUrl = import.meta.env.BASE_URL || '/',
): Promise<string | null> {
  const target = resolveExternalLoginRedirect(redirect, baseUrl)
  if (!target || !hasBuilderSession) return null

  if (!localStorage.getItem('access_token')?.trim()) {
    const session = await authApi.createWebConsoleSession()
    const accessToken = String(session.access_token || '').trim()
    const tenantId = String(session.tenant_id || '').trim()
    if (!accessToken || !tenantId) {
      throw new Error('Web Console session response is incomplete')
    }
    localStorage.setItem('access_token', accessToken)
    localStorage.setItem('tenant_id', tenantId)
  }

  return target
}
