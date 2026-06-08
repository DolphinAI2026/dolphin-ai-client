/**
 * Auth store — admin SPA uses the Builder login token passed from the host app.
 */
import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { apiGet } from '@/api/client'

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
    localStorage.removeItem('token')
  }

  return { token, user, isAuthenticated, isAdmin, fetchMe, logout }
})
