import request from '@/utils/request'
import type { LoginRequest, Token, User, LoginResponse, TenantSelectRequest, TenantOption } from '@/types'

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
}

export const authApi = {
  login(data: LoginRequest) {
    return request.post<any, LoginResponse>('/auth/login', data)
  },

  selectTenant(data: TenantSelectRequest) {
    return request.post<any, Token>('/auth/select-tenant', data)
  },

  switchTenant(tenantId: number) {
    return request.post<any, Token>('/auth/switch-tenant', { tenant_id: tenantId })
  },

  listMyTenants() {
    return request.get<any, TenantOption[]>('/auth/me/tenants')
  },

  getMe() {
    return request.get<any, User>('/auth/me')
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

  inviteTenantUser(data: { username: string; password?: string; role_code?: string }) {
    return request.post<any, TenantUser>('/auth/tenant-users/invite', data)
  }
}
