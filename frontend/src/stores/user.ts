import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { authApi } from '@/api/auth'
import { useTabsStore } from '@/stores/tabs'
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
    isPlatformAdmin.value || tenantRole.value === 'tenant_admin'
  )

  const isPlatformAdmin = computed(() =>
    tenantRole.value === 'platform_admin' || user.value?.is_platform_admin === true
  )

  const setToken = (newToken: string) => {
    token.value = newToken
    localStorage.setItem('token', newToken)
  }

  const clearToken = () => {
    token.value = null
    user.value = null
    localStorage.removeItem('token')
    localStorage.removeItem('admin_token')
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

    // 2026-05-22 修"切租户数据不刷新"用户痛点 — 整页 reload 让所有 store / 组件
    // state 重拉新租户数据. 反模式: 只更新 user.tenant_id 不动其他 store 导致
    // applications / SPEC / workspace / artifact 等列表全部 stale (上一个租户残留).
    // 整页 reload 避免漏 invalidate 某些 store 缓存. 切租户本来就是 disruptive
    // 重置工作环境的行为, 副作用 (in-flight SSE 断 / 填一半表单丢) 可接受.
    if (typeof window !== 'undefined') {
      useTabsStore().resetTabs()
      try { localStorage.removeItem('ai-builder-tabs-v1') } catch { /* ignore */ }
      // 切到首页再 reload 防止用户停在 /chat?app_id=N 那种含其他租户 app id 的 url
      window.location.href = '/ai-builder/'
    }
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
    isPlatformAdmin,
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
