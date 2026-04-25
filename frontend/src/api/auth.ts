import request from '@/utils/request'
import type { LoginRequest, RegisterRequest, Token, User, LoginResponse, TenantSelectRequest } from '@/types'

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
  tenant_status: number
  tenant_role: 'tenant_admin' | 'developer' | 'viewer' | 'member'
  role_code?: string | null
  role_name?: string | null
  org_permissions?: Record<string, boolean>
  joined_at?: string | null
  created_at?: string | null
}

export const authApi = {
  login(data: LoginRequest) {
    return request.post<any, LoginResponse>('/auth/login', data)
  },

  register(data: RegisterRequest) {
    return request.post<any, Token>('/auth/register', data)
  },

  selectTenant(data: TenantSelectRequest) {
    return request.post<any, Token>('/auth/select-tenant', data)
  },

  getMe() {
    return request.get<any, User>('/auth/me')
  },

  listTenantUsers() {
    return request.get<any, TenantUser[]>('/auth/tenant-users')
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
