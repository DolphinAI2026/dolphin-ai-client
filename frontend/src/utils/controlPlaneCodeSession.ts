import { getCommittedAuthToken } from '@/utils/request'

const STORAGE_KEY = 'ai-builder-control-plane-code-session-v1'

export interface ControlPlaneCodeSession {
  token: string
  tenantId: string
  tenantName: string
}

function claims(token: string): Record<string, unknown> {
  try {
    const payload = token.split('.')[1]
    return JSON.parse(atob(payload.replace(/-/g, '+').replace(/_/g, '/')))
  } catch {
    return {}
  }
}

function fromToken(token: string | null): ControlPlaneCodeSession | null {
  if (!token) return null
  const payload = claims(token)
  const tenantId = String(payload.cp_tid || '').trim()
  if (!tenantId) return null
  return {
    token,
    tenantId,
    tenantName: String(payload.cp_tname || tenantId).trim() || tenantId,
  }
}

export function getControlPlaneCodeSession(): ControlPlaneCodeSession | null {
  const initial = fromToken(getCommittedAuthToken())
  if (initial) {
    setControlPlaneCodeSession(initial.token)
    return initial
  }
  try {
    const stored = fromToken(sessionStorage.getItem(STORAGE_KEY))
    if (stored) return stored
  } catch {
    // Fall through to the initial login ticket when storage is unavailable.
  }
  return null
}

export function setControlPlaneCodeSession(token: string): ControlPlaneCodeSession | null {
  const session = fromToken(token)
  if (!session) return null
  try { sessionStorage.setItem(STORAGE_KEY, token) } catch { /* private mode */ }
  return session
}

export function clearControlPlaneCodeSession() {
  try { sessionStorage.removeItem(STORAGE_KEY) } catch { /* private mode */ }
}

export function controlPlaneCodeAuthorization() {
  const session = getControlPlaneCodeSession()
  return session ? { Authorization: `Bearer ${session.token}` } : undefined
}
