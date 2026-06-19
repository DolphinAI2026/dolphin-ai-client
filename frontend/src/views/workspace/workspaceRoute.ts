import type { Binding, BindingKind } from './binding'
import { bindingKindFromId, rawId } from './binding'
import { resolveInitialAppId } from '@/views/chatPageRouteState'

export function routeToBinding(wsId: string | undefined | null, appIdRaw?: any): Binding {
  if (wsId) return { kind: 'workspace', workspaceId: wsId }
  const appId = resolveInitialAppId(appIdRaw)
  if (appId) return { kind: 'app', appId }
  return { kind: 'none' }
}

export function parseSidebarSelect(prefixedId: string): {
  kind: BindingKind
  sessionId: number | null
  workspaceId: string | null
} {
  const kind = bindingKindFromId(prefixedId)
  const raw = rawId(prefixedId)
  if (kind === 'workspace') return { kind, sessionId: null, workspaceId: raw }
  const n = Number(raw)
  return { kind, sessionId: Number.isFinite(n) ? n : null, workspaceId: null }
}
