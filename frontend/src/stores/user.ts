import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { authApi } from '@/api/auth'
import type { User, TenantOption } from '@/types'
import { resetOnboardingCache } from '@/composables/useOnboardingState'

export const useUserStore = defineStore('user', () => {
  const user = ref<User | null>(null)
  const token = ref<string | null>(localStorage.getItem('token'))
  const availableTenants = ref<TenantOption[]>([])
  let storageAlignmentGeneration = 0
  let storageAlignmentAbortController: AbortController | null = null

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
    resetOnboardingCache()
  }

  const fetchUser = async () => {
    try {
      user.value = await authApi.getMe()
    } catch (error) {
      clearToken()
      throw error
    }
  }

  const login = async (
    username: string,
    password: string,
    captchaId?: string,
    captchaCode?: string,
  ) => {
    const res = await authApi.login({
      username,
      password,
      captcha_id: captchaId,
      captcha_code: captchaCode,
    })

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

  const desktopLogin = async (username: string, password: string) => {
    const { desktopLogin: api } = await import('@/api/desktopAuth')
    const res: any = await api({ username, password })
    setToken(res.access_token)
    await fetchUser()
    return { ok: true }
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

  const switchTenantContext = async (
    targetTenantId: number,
    targetTenantPublicId: string,
    destination: string,
  ) => {
    const candidate = await authApi.switchTenant(targetTenantId)
    const candidateUser = await authApi.getMeWithToken(candidate.access_token)
    if (
      candidateUser.tenant_id !== targetTenantId
      || candidateUser.tenant_public_id !== targetTenantPublicId
    ) {
      throw new Error('tenant candidate mismatch')
    }

    setToken(candidate.access_token)
    user.value = candidateUser

    if (typeof window !== 'undefined') {
      try { localStorage.removeItem('ai-builder-tabs-v1') } catch { /* ignore */ }
      window.location.replace(destination)
    }
  }

  const switchTenant = async (targetTenantId: number) => {
    if (targetTenantId === tenantId.value) return
    const targetTenant = availableTenants.value.find(
      (tenant) => tenant.tenant_id === targetTenantId,
    )
    if (!targetTenant?.tenant_public_id) {
      throw new Error('target tenant is not authorized')
    }

    await switchTenantContext(targetTenantId, targetTenant.tenant_public_id, '/ai-builder/')
  }

  const alignTokenFromStorage = async (eventToken: string) => {
    const generation = ++storageAlignmentGeneration
    storageAlignmentAbortController?.abort()
    const controller = new AbortController()
    storageAlignmentAbortController = controller

    try {
      const alignedUser = await authApi.getMeWithToken(eventToken, controller.signal)
      if (
        controller.signal.aborted
        || generation !== storageAlignmentGeneration
        || localStorage.getItem('token') !== eventToken
      ) {
        return
      }

      token.value = eventToken
      user.value = alignedUser
      try { localStorage.removeItem('ai-builder-tabs-v1') } catch { /* ignore */ }
      window.location.replace('/ai-builder/')
    } catch {
      if (
        !controller.signal.aborted
        && generation === storageAlignmentGeneration
        && localStorage.getItem('token') === eventToken
      ) {
        clearToken()
      }
    }
  }

  if (typeof window !== 'undefined') {
    window.addEventListener('storage', (event) => {
      if (event.key !== 'token') return

      const eventToken = event.newValue
      if (!eventToken) {
        storageAlignmentGeneration += 1
        storageAlignmentAbortController?.abort()
        storageAlignmentAbortController = null
        clearToken()
        return
      }

      if (localStorage.getItem('token') !== eventToken) return
      void alignTokenFromStorage(eventToken)
    })
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
    desktopLogin,
    selectTenant,
    switchTenantContext,
    switchTenant,
    fetchAvailableTenants,
    logout
  }
})
