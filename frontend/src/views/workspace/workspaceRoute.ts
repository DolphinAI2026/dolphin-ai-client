import type { Binding, BindingKind } from './binding'
import { bindingKindFromId, rawId } from './binding'

export function routeToBinding(id: string | undefined | null): Binding {
  if (!id) return { kind: 'none' }
  return { kind: 'workspace', workspaceId: id }
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
