export type RoutePathMatch = string | string[] | undefined

export function resolvePlatformAdminPath(raw: RoutePathMatch): string {
  const parts = Array.isArray(raw) ? raw : raw ? [raw] : []
  const path = `/${parts.map(part => String(part).trim()).filter(Boolean).join('/')}`.replace(/\/+/g, '/')
  return path === '/' ? '/status' : path
}

export function buildPlatformAdminIframeSrc(options: {
  origin: string
  baseUrl: string
  adminPath: string
  token?: string | null
}): string {
  const params = new URLSearchParams({ embed: '1' })
  if (options.token) params.set('handoff_token', options.token)

  const base = (options.baseUrl || '/').replace(/\/$/, '')
  const adminBase = `${options.origin}${base}/admin`.replace(/([^:]\/)\/+/g, '$1')
  return `${adminBase}${options.adminPath}?${params.toString()}`
}
