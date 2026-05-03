import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { authApi } from '@/api/auth'
import type { User, TenantOption } from '@/types'

export const useUserStore = defineStore('user', () => {
  const user = ref<User | null>(null)
  const token = ref<string | null>(localStorage.getItem('token'))
  const availableTenants = ref<TenantOption[]>([])

  // 多租户状态
  const tenantId = computed(() => user.value?.tenant_id || null)
  const tenantName = computed(() => user.value?.tenant_name || null)
  const tenantRole = computed(() => user.value?.tenant_role || 'member')
  const orgPermissions = computed(() => user.value?.org_permissions || {})

  // 权限判断
  const hasPermission = (code: string): boolean => {
    if (isTenantAdmin.value) return true
    return !!orgPermissions.value[code]
  }

  const isTenantAdmin = computed(() =>
    tenantRole.value === 'platform_admin' || tenantRole.value === 'tenant_admin'
  )

  const setToken = (newToken: string) => {
    token.value = newToken
    localStorage.setItem('token', newToken)
  }

  const clearToken = () => {
    token.value = null
    user.value = null
    localStorage.removeItem('token')
  }

  const fetchUser = async () => {
    try {
      user.value = await authApi.getMe()
    } catch (error) {
      clearToken()
      throw error
    }
  }

  const login = async (username: string, password: string) => {
    const res = await authApi.login({ username, password })

    // 多租户登录处理
    if (res.requires_tenant_selection) {
      // 需要选择租户 — 返回 selection_token 和租户列表
      return {
        requiresSelection: true,
        selectionToken: res.selection_token,
        tenants: res.tenants
      }
    }

    // 单租户或已选择租户 — 直接登录
    setToken(res.access_token!)
    await fetchUser()
    return { requiresSelection: false }
  }

  const selectTenant = async (selectionToken: string, tenantId: number) => {
    const res = await authApi.selectTenant({ selection_token: selectionToken, tenant_id: tenantId })
    setToken(res.access_token)
    await fetchUser()
  }

  const fetchAvailableTenants = async () => {
    try {
      availableTenants.value = await authApi.listMyTenants()
    } catch {
      availableTenants.value = []
    }
    return availableTenants.value
  }

  const switchTenant = async (targetTenantId: number) => {
    if (targetTenantId === tenantId.value) return
    const res = await authApi.switchTenant(targetTenantId)
    setToken(res.access_token)
    await fetchUser()
  }

  const logout = () => {
    clearToken()
  }

  return {
    user,
    token,
    availableTenants,
    tenantId,
    tenantName,
    tenantRole,
    orgPermissions,
    hasPermission,
    isTenantAdmin,
    setToken,
    clearToken,
    fetchUser,
    login,
    selectTenant,
    switchTenant,
    fetchAvailableTenants,
    logout
  }
})
