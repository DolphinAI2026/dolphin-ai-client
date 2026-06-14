export function shouldLoadAiChatAuthenticatedResource(
  token: string | null | undefined,
): boolean {
  return typeof token === 'string' && token.trim().length > 0
}

export function shouldReloadAiChatForTenantChange(
  nextTenantId: number | string | null | undefined,
  previousTenantId: number | string | null | undefined,
  token: string | null | undefined,
): boolean {
  if (!token) return false
  if (nextTenantId == null || previousTenantId == null) return false
  return String(nextTenantId) !== String(previousTenantId)
}
