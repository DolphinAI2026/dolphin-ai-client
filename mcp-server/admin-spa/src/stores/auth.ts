/**
 * Auth store — admin SPA only, platform_admin / superuser 才能进。
 * 本 admin 后台不复用 ai-builder 的多角色多租户登录，纯 admin 维护。
 */
import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { apiPost, apiGet } from '@/api/client'

interface AdminUser {
  id: number
  username: string
  display_name?: string
  is_active?: boolean
  is_superuser?: boolean
  platform_admin?: boolean
  tenant_id?: number
  tenant_name?: string
  tenant_role?: string  // 'platform_admin' / 'tenant_admin' / 'member' / ...
}

export const useAuthStore = defineStore('auth', () => {
  const token = ref<string>(localStorage.getItem('admin_token') || localStorage.getItem('token') || '')
  const user  = ref<AdminUser | null>(null)

  const isAuthenticated = computed(() => Boolean(token.value))
  const isAdmin         = computed(() => {
    const u = user.value
    if (!u) return false
    // 兼容 3 种 backend 返字段方式（按出现顺序优先）
    return !!(u.is_superuser || u.platform_admin || u.tenant_role === 'platform_admin')
  })

  async function login(username: string, password: string) {
    const resp = await apiPost<{ access_token: string }>('/auth/login', { username, password })
    if (!resp?.access_token) throw new Error('登录响应缺 access_token')
    token.value = resp.access_token
    localStorage.setItem('admin_token', resp.access_token)
    await fetchMe()
    if (!isAdmin.value) {
      // 不是 admin —— 拒绝
      logout()
      throw new Error('当前账号无管理员权限')
    }
  }

  async function fetchMe() {
    try {
      const resp = await apiGet<AdminUser>('/auth/me')
      user.value = resp || null
    } catch {
      user.value = null
    }
  }

  function logout() {
    token.value = ''
    user.value = null
    localStorage.removeItem('admin_token')
  }

  return { token, user, isAuthenticated, isAdmin, login, fetchMe, logout }
})
