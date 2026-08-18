import { getCommittedAuthToken } from '@/utils/request'

const STORAGE_KEY = 'ai-builder-control-plane-code-session-v1'

interface ExplicitControlPlaneCodeSessionRecord {
  version: 1
  token: string
  sourceToken: string
}

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

function explicitRecord(value: string | null): ExplicitControlPlaneCodeSessionRecord | null {
  if (!value?.startsWith('{')) return null
  try {
    const parsed = JSON.parse(value) as Partial<ExplicitControlPlaneCodeSessionRecord>
    if (
      parsed.version !== 1
      || typeof parsed.token !== 'string'
      || typeof parsed.sourceToken !== 'string'
      || !fromToken(parsed.token)
    ) {
      return null
    }
    return {
      version: 1,
      token: parsed.token,
      sourceToken: parsed.sourceToken,
    }
  } catch {
    return null
  }
}

export function getControlPlaneCodeSession(): ControlPlaneCodeSession | null {
  const committedToken = getCommittedAuthToken()
  try {
    const storedValue = sessionStorage.getItem(STORAGE_KEY)
    const record = explicitRecord(storedValue)
    if (record?.sourceToken === committedToken) return fromToken(record.token)
    if (!record && !committedToken) return fromToken(storedValue)
  } catch {
    // Fall through to the committed login ticket when storage is unavailable.
  }
  const committed = fromToken(committedToken)
  if (committed) setControlPlaneCodeSession(committed.token)
  return committed
}

export function setControlPlaneCodeSession(token: string): ControlPlaneCodeSession | null {
  const session = fromToken(token)
  if (!session) return null
  try { sessionStorage.setItem(STORAGE_KEY, token) } catch { /* private mode */ }
  return session
}

export function setExplicitControlPlaneCodeSession(
  token: string,
  sourceToken: string,
  expectedTenantId: string,
): ControlPlaneCodeSession | null {
  const session = fromToken(token)
  if (!session || session.tenantId !== expectedTenantId) return null
  try {
    sessionStorage.setItem(STORAGE_KEY, JSON.stringify({
      version: 1,
      token,
      sourceToken,
    } satisfies ExplicitControlPlaneCodeSessionRecord))
  } catch {
    return null
  }
  return session
}

export function clearControlPlaneCodeSession() {
  try { sessionStorage.removeItem(STORAGE_KEY) } catch { /* private mode */ }
}

export function controlPlaneCodeAuthorization() {
  const session = getControlPlaneCodeSession()
  return session ? { Authorization: `Bearer ${session.token}` } : undefined
}
