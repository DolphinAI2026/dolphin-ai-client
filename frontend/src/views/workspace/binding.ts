export type BindingKind = 'none' | 'app' | 'workspace'

export type Binding =
  | { kind: 'none' }
  | { kind: 'app'; appId: number }
  | { kind: 'workspace'; workspaceId: string; appId?: number }

// SessionSidebar.badgeTone 内置色: chat=靛蓝 / cowork=橙 / success=绿。复用之。
export function bindingBadge(b: Binding): { tone: string; label: string } {
  if (b.kind === 'app') return { tone: 'cowork', label: '应用' }
  if (b.kind === 'workspace') return { tone: 'success', label: '代码' }
  return { tone: 'chat', label: '对话' }
}

// 统一会话列表混多来源, 用「类型前缀:原始id」防数字 id 撞车。
// 约定前缀: chat(=none 绑定) / app / workspace。
export function prefixedId(kind: BindingKind | 'chat', raw: string | number): string {
  const prefix = kind === 'none' ? 'chat' : kind
  return `${prefix}:${raw}`
}

export function bindingKindFromId(id: string): BindingKind {
  if (id.startsWith('app:')) return 'app'
  if (id.startsWith('workspace:')) return 'workspace'
  return 'none' // chat: 前缀或任何未知形状都按通用对话
}

export function rawId(id: string): string {
  const i = id.indexOf(':')
  return i >= 0 ? id.slice(i + 1) : id
}
