import request from '@/utils/request'
import type {
  LoginCaptcha,
  LoginRequest,
  Token,
  User,
  LoginResponse,
  TenantSelectRequest,
  TenantOption,
} from '@/types'

export interface TenantRoleOption {
  id: number
  role_code: string
  role_name: string
  is_system: boolean
  permissions: Record<string, boolean>
}

export interface TenantUser {
  id: number
  username: string
  display_name?: string | null
  is_active: boolean
  is_platform_admin?: boolean
  tenant_id?: number | null
  tenant_name?: string | null
  tenant_summary?: string | null
  tenant_status: number
  tenant_role: 'platform_admin' | 'tenant_admin' | 'developer' | 'viewer' | 'member'
  role_code?: string | null
  role_name?: string | null
  org_permissions?: Record<string, boolean>
  joined_at?: string | null
  created_at?: string | null
}

export interface ActiveTenantUser {
  id: number
  username: string
  display_name?: string | null
}

export interface TenantAdminItem {
  id: number
  tenant_name: string
  tenant_code: string
  max_applications: number
  max_workspaces: number
  max_components: number
  status: number
  contact_name?: string | null
  contact_email?: string | null
  member_count: number
  created_at?: string | null
}

export interface TenantCreatePayload {
  tenant_name: string
  tenant_code: string
  max_applications?: number
  max_workspaces?: number
  max_components?: number
  contact_name?: string | null
  contact_email?: string | null
}

export interface TenantUsageQuota {
  used: number
  max: number
}

export interface TenantUsage {
  applications: TenantUsageQuota
  workspaces: TenantUsageQuota
  components: TenantUsageQuota
  members: number
}

export interface TenantDashboardNearLimit {
  tenant_id: number
  tenant_name: string
  resource: 'applications' | 'workspaces' | 'components'
  used: number
  max: number
  ratio: number
}

export interface TenantDashboard {
  tenants_active: number
  totals: {
    applications: TenantUsageQuota
    workspaces: TenantUsageQuota
    components: TenantUsageQuota
    members: number
  }
  near_limit: TenantDashboardNearLimit[]
}

export interface TenantMemberItem {
  user_id: number
  username: string
  display_name?: string | null
  is_active: boolean
  is_platform_admin: boolean
  tenant_role: string
  role_code?: string | null
  role_name?: string | null
  joined_at?: string | null
  is_default: boolean
}

export interface TenantMemberAddPayload {
  username: string
  password?: string
  role_code?: string
}

export interface PlatformUserItem {
  id: number
  username: string
  is_platform_admin: boolean
}

export interface TenantUpdatePayload {
  tenant_name?: string
  max_applications?: number
  max_workspaces?: number
  max_components?: number
  contact_name?: string | null
  contact_email?: string | null
}

export const authApi = {
  getCaptcha() {
    return request.get<any, LoginCaptcha>('/auth/captcha', { authPolicy: 'public' })
  },

  login(data: LoginRequest) {
    return request.post<any, LoginResponse>('/auth/login', data, { authPolicy: 'public' })
  },

  selectTenant(data: TenantSelectRequest, signal?: AbortSignal) {
    return request.post<any, Token>(
      '/auth/select-tenant',
      data,
      signal ? { authPolicy: 'public', signal } : { authPolicy: 'public' },
    )
  },

  switchTenant(tenantId: number, signal?: AbortSignal) {
    return request.post<any, Token>('/auth/switch-tenant', { tenant_id: tenantId }, { signal })
  },

  listMyTenants() {
    return request.get<any, TenantOption[]>('/auth/me/tenants')
  },

  listAllTenants(params?: { q?: string; status?: 0 | 1 }) {
    return request.get<any, TenantAdminItem[]>('/auth/tenants', { params })
  },

  listPlatformUsers() {
    return request.get<any, PlatformUserItem[]>('/auth/platform-users')
  },

  getTenantDashboard() {
    return request.get<any, TenantDashboard>('/auth/tenants/dashboard')
  },

  setMyDefaultTenant(tenantId: number) {
    return request.put<any, { ok: boolean; tenant_id: number; stored: boolean }>(
      '/auth/me/default-tenant',
      { tenant_id: tenantId },
    )
  },

  createTenant(data: TenantCreatePayload) {
    return request.post<any, TenantAdminItem>('/auth/tenants', data)
  },

  updateTenantStatus(tenantId: number, status: 0 | 1) {
    return request.put<any, TenantAdminItem>(`/auth/tenants/${tenantId}/status`, { status })
  },

  updateTenant(tenantId: number, data: TenantUpdatePayload) {
    return request.put<any, TenantAdminItem>(`/auth/tenants/${tenantId}`, data)
  },

  deleteTenant(tenantId: number, force = false) {
    return request.delete<any, { ok: boolean; deleted_tenant_id: number; residual: Record<string, number> }>(
      `/auth/tenants/${tenantId}${force ? '?force=true' : ''}`,
    )
  },

  getTenantUsage(tenantId: number) {
    return request.get<any, TenantUsage>(`/auth/tenants/${tenantId}/usage`)
  },

  listTenantMembers(tenantId: number) {
    return request.get<any, TenantMemberItem[]>(`/auth/tenants/${tenantId}/members`)
  },

  addTenantMember(tenantId: number, data: TenantMemberAddPayload) {
    return request.post<any, TenantMemberItem>(`/auth/tenants/${tenantId}/members`, data)
  },

  removeTenantMember(tenantId: number, userId: number) {
    return request.delete<any, { ok: boolean }>(`/auth/tenants/${tenantId}/members/${userId}`)
  },

  updateTenantMemberRole(tenantId: number, userId: number, roleCode: string) {
    return request.put<any, TenantMemberItem>(
      `/auth/tenants/${tenantId}/members/${userId}/role`,
      { role_code: roleCode },
    )
  },

  getMe() {
    return request.get<any, User>('/auth/me')
  },

  getMeWithToken(candidateToken: string, signal?: AbortSignal) {
    return request.get<any, User>('/auth/me', {
      headers: { Authorization: `Bearer ${candidateToken}` },
      signal,
      authFailurePolicy: 'preserve-source-session',
    })
  },

  listTenantUsers() {
    return request.get<any, TenantUser[]>('/auth/tenant-users')
  },

  listActiveUsers() {
    return request.get<any, ActiveTenantUser[]>('/auth/users')
  },

  listTenantRoles() {
    return request.get<any, TenantRoleOption[]>('/auth/tenant-roles')
  },

  updateTenantUserStatus(userId: number, status: number) {
    return request.put<any, TenantUser>(`/auth/tenant-users/${userId}/status`, { status })
  },

  updateTenantUserRole(userId: number, roleCode: string) {
    return request.put<any, TenantUser>(`/auth/tenant-users/${userId}/role`, { role_code: roleCode })
  },

  inviteTenantUser(data: { username: string; password?: string; role_code?: string; tenant_id?: number }) {
    return request.post<any, TenantUser>('/auth/tenant-users/invite', data)
  },

  resetUserPassword(userId: number, newPassword: string) {
    return request.post<any, { ok: boolean; user_id: number; username: string }>(
      `/auth/users/${userId}/reset-password`,
      { new_password: newPassword },
    )
  }
}
