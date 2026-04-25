export type ProjectRole = 'owner' | 'maintainer' | 'contributor' | 'viewer'

// 兼容老 UI 中可能仍出现的旧名称
export type LegacyProjectRole = 'admin' | 'member' | ProjectRole

export const ROLE_LEVELS: Record<ProjectRole, number> = {
  viewer: 1,
  contributor: 2,
  maintainer: 3,
  owner: 4,
}

export function normalizeRole(role: string | null | undefined): ProjectRole {
  if (!role) return 'viewer'
  if (role === 'admin') return 'maintainer'
  if (role === 'member') return 'contributor'
  if (role in ROLE_LEVELS) return role as ProjectRole
  return 'viewer'
}

export function roleAtLeast(role: string | null | undefined, required: ProjectRole): boolean {
  return ROLE_LEVELS[normalizeRole(role)] >= ROLE_LEVELS[required]
}

export interface ApplicationMember {
  user_id: number
  username: string
  role: ProjectRole
  source: 'creator' | 'inherited' | 'direct'
  created_at: string | null
  id?: number  // optional：仅 direct 类型 member 有 ApplicationMember.id
}

export interface ProjectMemberView {
  id: number
  user_id: number
  username: string
  role: ProjectRole
  created_at: string | null
}

export const ROLE_DISPLAY_NAMES: Record<ProjectRole, string> = {
  owner: '所有者',
  maintainer: '管理员',
  contributor: '协作者',
  viewer: '查看者',
}
