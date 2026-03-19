import request from '@/utils/request'
import type { LoginRequest, RegisterRequest, Token, User, LoginResponse, TenantSelectRequest } from '@/types'

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
  }
}
