/**
 * Resolve the remote management console for tenant-owned AI resources.
 *
 * Desktop uses the discovery URL as the console origin; Web deployments can
 * override it with VITE_CONTROL_PLANE_CONSOLE_URL or use the same-origin
 * /web-console mount. Authentication is handed over with a one-time message,
 * never in the URL.
 */
export function controlPlaneConsoleUrl(path = '/capabilities', baseUrl = ''): string {
  const configured = String(import.meta.env.VITE_CONTROL_PLANE_CONSOLE_URL || '').trim()
  const base = configured || baseUrl.trim() || '/web-console/'
  let normalized = base.replace(/\/+$/, '')
  try {
    const parsed = new URL(normalized, typeof window === 'undefined' ? 'https://control-plane.invalid' : window.location.href)
    if (!/\/web-console(?:\/|$)/.test(parsed.pathname)) {
      parsed.pathname = `${parsed.pathname.replace(/\/$/, '')}/web-console`
      normalized = parsed.toString().replace(/\/+$/, '')
    }
  } catch {
    if (!/\/web-console(?:\/|$)/.test(normalized)) normalized = `${normalized}/web-console`
  }
  const suffix = path.startsWith('/') ? path : `/${path}`
  return `${normalized}${suffix}`
}

const HANDOFF_QUERY_KEY = 'cp_handoff'

function createHandoffId(): string {
  try {
    if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
      return crypto.randomUUID()
    }
  } catch { /* restricted browser context */ }
  return `${Date.now()}-${Math.random().toString(36).slice(2)}`
}

function openWindow(url: string): Window | null {
  const opened = window.open(url, '_blank', 'noopener,noreferrer')
  if (!opened) window.location.assign(url)
  return opened
}

export function openControlPlaneConsole(
  path = '/capabilities',
  auth?: { accessToken?: string | null; tenantId?: string | null },
  baseUrl = '',
): void {
  if (typeof window === 'undefined') return
  const resolved = new URL(controlPlaneConsoleUrl(path, baseUrl), window.location.href)
  const sameOrigin = resolved.origin === window.location.origin

  if (sameOrigin) {
    if (auth?.accessToken) window.localStorage.setItem('access_token', auth.accessToken)
    if (auth?.tenantId) window.localStorage.setItem('tenant_id', auth.tenantId)
    openWindow(resolved.toString())
    return
  }

  if (!auth?.accessToken) {
    openWindow(resolved.toString())
    return
  }

  const handoffId = createHandoffId()
  resolved.searchParams.set(HANDOFF_QUERY_KEY, handoffId)
  const targetOrigin = resolved.origin
  const popup = window.open(resolved.toString(), '_blank')
  if (!popup) {
    window.location.assign(resolved.toString())
    return
  }

  let timer: number | undefined
  const cleanup = () => {
    window.removeEventListener('message', onMessage)
    if (timer !== undefined) window.clearTimeout(timer)
  }
  const onMessage = (event: MessageEvent) => {
    if (event.source !== popup || event.origin !== targetOrigin) return
    const data = event.data as { type?: unknown; handoffId?: unknown } | null
    if (data?.type !== 'control-plane-console-ready' || data.handoffId !== handoffId) return
    popup.postMessage({
      type: 'control-plane-console-auth',
      handoffId,
      accessToken: auth.accessToken,
      tenantId: auth.tenantId || null,
    }, targetOrigin)
    cleanup()
  }
  window.addEventListener('message', onMessage)
  timer = window.setTimeout(cleanup, 30_000)
}
