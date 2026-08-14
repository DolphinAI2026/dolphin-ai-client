import type { CodeExecutionLocation } from '@/api/codeRuntime'

const DURABLE_PREFIX = 'dolphin-code-location-preference-v1'
const PENDING_PREFIX = 'dolphin-code-location-pending-v1'
const PENDING_SHELL_PREFIX = 'dolphin-code-location-pending-shell-v1'

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

function shellKey(shellSessionRef: string): string {
  return `${PENDING_SHELL_PREFIX}:${encodeURIComponent(String(shellSessionRef))}`
}

function commitPendingKey(pendingKey: string, shellSessionRef: string): boolean {
  try {
    if (!pendingKey.startsWith(`${PENDING_PREFIX}:`)) return false
    const raw = sessionStorage.getItem(pendingKey)
    if (!raw) return false
    const pending = JSON.parse(raw) as Partial<PendingLocationPreference>
    if (
      (pending.location !== 'local' && pending.location !== 'remote')
      || pending.shellSessionRef !== String(shellSessionRef)
    ) return false
    const durableKey = pendingKey.replace(`${PENDING_PREFIX}:`, `${DURABLE_PREFIX}:`)
    localStorage.setItem(durableKey, pending.location)
    sessionStorage.removeItem(pendingKey)
    sessionStorage.removeItem(shellKey(shellSessionRef))
    return true
  } catch {
    return false
  }
}

function discardPendingKey(pendingKey: string, shellSessionRef: string): boolean {
  try {
    if (!pendingKey.startsWith(`${PENDING_PREFIX}:`)) return false
    const raw = sessionStorage.getItem(pendingKey)
    if (!raw) return false
    const pending = JSON.parse(raw) as Partial<PendingLocationPreference>
    if (pending.shellSessionRef !== String(shellSessionRef)) return false
    sessionStorage.removeItem(pendingKey)
    sessionStorage.removeItem(shellKey(shellSessionRef))
    return true
  } catch {
    return false
  }
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
  try {
    const pendingKey = key(PENDING_PREFIX, scope)
    const previousPendingKey = sessionStorage.getItem(shellKey(pending.shellSessionRef))
    if (previousPendingKey && previousPendingKey !== pendingKey) {
      discardPendingKey(previousPendingKey, pending.shellSessionRef)
    }
    sessionStorage.setItem(pendingKey, JSON.stringify(pending))
    sessionStorage.setItem(shellKey(pending.shellSessionRef), pendingKey)
  } catch { /* private mode */ }
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
  return commitPendingKey(key(PENDING_PREFIX, scope), shellSessionRef)
}

export function commitPendingCodeApplicationLocationPreferenceByShellSessionRef(
  shellSessionRef: string,
): boolean {
  try {
    const pendingKey = sessionStorage.getItem(shellKey(shellSessionRef))
    return pendingKey ? commitPendingKey(pendingKey, shellSessionRef) : false
  } catch {
    return false
  }
}

export function discardPendingCodeApplicationLocationPreference(
  scope: CodeApplicationLocationPreferenceScope,
  shellSessionRef?: string,
): boolean {
  const pending = pendingPreference(scope)
  if (!pending || (shellSessionRef && pending.shellSessionRef !== String(shellSessionRef))) return false
  return discardPendingKey(key(PENDING_PREFIX, scope), pending.shellSessionRef)
}

export function discardPendingCodeApplicationLocationPreferenceByShellSessionRef(
  shellSessionRef: string,
): boolean {
  try {
    const pendingKey = sessionStorage.getItem(shellKey(shellSessionRef))
    return pendingKey ? discardPendingKey(pendingKey, shellSessionRef) : false
  } catch {
    return false
  }
}
