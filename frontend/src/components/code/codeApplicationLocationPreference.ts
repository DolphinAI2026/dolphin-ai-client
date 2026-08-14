import type { CodeExecutionLocation } from '@/api/codeRuntime'

const DURABLE_PREFIX = 'dolphin-code-location-preference-v1'
const PENDING_PREFIX = 'dolphin-code-location-pending-v1'

export interface CodeApplicationLocationPreferenceScope {
  deploymentId: string
  userId: string
  logicalApplicationId: string
}

interface PendingLocationPreference {
  location: CodeExecutionLocation
  shellSessionRef: string
}

function key(prefix: string, scope: CodeApplicationLocationPreferenceScope): string {
  return [
    prefix,
    encodeURIComponent(scope.deploymentId),
    encodeURIComponent(scope.userId),
    encodeURIComponent(scope.logicalApplicationId),
  ].join(':')
}

export function loadCodeApplicationLocationPreference(
  scope: CodeApplicationLocationPreferenceScope,
): CodeExecutionLocation | null {
  try {
    const stored = localStorage.getItem(key(DURABLE_PREFIX, scope))
    return stored === 'local' || stored === 'remote' ? stored : null
  } catch {
    return null
  }
}

export function stageCodeApplicationLocationPreference(
  scope: CodeApplicationLocationPreferenceScope,
  location: CodeExecutionLocation,
  shellSessionRef: string,
): void {
  const pending: PendingLocationPreference = { location, shellSessionRef: String(shellSessionRef) }
  try { sessionStorage.setItem(key(PENDING_PREFIX, scope), JSON.stringify(pending)) } catch { /* private mode */ }
}

function pendingPreference(
  scope: CodeApplicationLocationPreferenceScope,
): PendingLocationPreference | null {
  try {
    const raw = sessionStorage.getItem(key(PENDING_PREFIX, scope))
    if (!raw) return null
    const parsed = JSON.parse(raw) as Partial<PendingLocationPreference>
    if ((parsed.location !== 'local' && parsed.location !== 'remote') || !parsed.shellSessionRef) return null
    return parsed as PendingLocationPreference
  } catch {
    return null
  }
}

export function commitCodeApplicationLocationPreference(
  scope: CodeApplicationLocationPreferenceScope,
  shellSessionRef: string,
): boolean {
  const pending = pendingPreference(scope)
  if (!pending || pending.shellSessionRef !== String(shellSessionRef)) return false
  try {
    localStorage.setItem(key(DURABLE_PREFIX, scope), pending.location)
  } catch {
    return false
  }
  try { sessionStorage.removeItem(key(PENDING_PREFIX, scope)) } catch { /* durable value is committed */ }
  return true
}

export function discardPendingCodeApplicationLocationPreference(
  scope: CodeApplicationLocationPreferenceScope,
  shellSessionRef?: string,
): boolean {
  const pending = pendingPreference(scope)
  if (!pending || (shellSessionRef && pending.shellSessionRef !== String(shellSessionRef))) return false
  try {
    sessionStorage.removeItem(key(PENDING_PREFIX, scope))
    return true
  } catch {
    return false
  }
}
