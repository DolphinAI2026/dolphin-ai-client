import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { authApi } from '@/api/auth'
import type { User, TenantOption } from '@/types'
import { resetOnboardingCache } from '@/composables/useOnboardingState'
import { MODE_META, modeForRoutePath, useModeStore } from '@/stores/mode'
import { setCommittedAuthToken } from '@/utils/request'

export const useUserStore = defineStore('user', () => {
  const user = ref<User | null>(null)
  const initialToken = localStorage.getItem('token')
  const token = ref<string | null>(initialToken)
  const availableTenants = ref<TenantOption[]>([])
  let storageAlignmentGeneration = 0
  let storageAlignmentAbortController: AbortController | null = null

  setCommittedAuthToken(initialToken)

  const invalidateStorageAlignment = () => {
    storageAlignmentGeneration += 1
    storageAlignmentAbortController?.abort()
    storageAlignmentAbortController = null
  }

  const currentModeTenantHome = (tenantPublicId: string) => {
    const base = import.meta.env.BASE_URL || '/'
    const prefix = base === '/' ? '' : base.replace(/\/$/, '')
    const pathname = typeof window === 'undefined' ? '' : window.location.pathname
    const routePath = (
      base !== '/'
      && pathname.startsWith(base)
    )
      ? `/${pathname.slice(base.length).replace(/^\/+/, '')}`
      : pathname
    const mode = routePath
      ? modeForRoutePath(routePath)
      : useModeStore().mode
    const home = MODE_META[mode].home
    return `${prefix}${home}?tenantId=${encodeURIComponent(tenantPublicId)}`
  }

  const storageAlignmentDestination = (alignedUser: User): string | null => {
    if (alignedUser.tenant_id === null && alignedUser.tenant_public_id === null) {
      return '/platform-admin/'
    }
    if (
      typeof alignedUser.tenant_id !== 'number'
      || typeof alignedUser.tenant_public_id !== 'string'
      || !alignedUser.tenant_public_id
    ) {
      return null
    }
    return currentModeTenantHome(alignedUser.tenant_public_id)
  }

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
    invalidateStorageAlignment()
    token.value = newToken
    setCommittedAuthToken(newToken)
    localStorage.setItem('token', newToken)
  }

  const clearToken = () => {
    invalidateStorageAlignment()
    token.value = null
    user.value = null
    setCommittedAuthToken(null)
    localStorage.removeItem('token')
    localStorage.removeItem('admin_token')
    resetOnboardingCache()
  }

  const fetchUser = async () => {
    const requestToken = token.value
    try {
      const fetchedUser = await authApi.getMe()
      if (
        requestToken === token.value
        && requestToken === localStorage.getItem('token')
      ) {
        user.value = fetchedUser
      }
    } catch (error) {
      if (
        requestToken === token.value
        && requestToken === localStorage.getItem('token')
      ) {
        clearToken()
      }
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

    await switchTenantContext(
      targetTenantId,
      targetTenant.tenant_public_id,
      currentModeTenantHome(targetTenant.tenant_public_id),
    )
  }

  const alignTokenFromStorage = async (eventToken: string) => {
    const generation = ++storageAlignmentGeneration
    storageAlignmentAbortController?.abort()
    const controller = new AbortController()
    storageAlignmentAbortController = controller

    try {
      const alignedUser = await authApi.getMeWithToken(eventToken, controller.signal)
      const destination = storageAlignmentDestination(alignedUser)
      if (
        controller.signal.aborted
        || generation !== storageAlignmentGeneration
        || localStorage.getItem('token') !== eventToken
        || !destination
      ) {
        return
      }

      token.value = eventToken
      user.value = alignedUser
      setCommittedAuthToken(eventToken)
      try { localStorage.removeItem('ai-builder-tabs-v1') } catch { /* ignore */ }
      window.location.replace(destination)
      if (storageAlignmentAbortController === controller) {
        storageAlignmentAbortController = null
      }
    } catch {
      if (storageAlignmentAbortController === controller) {
        storageAlignmentAbortController = null
      }
    }
  }

  if (typeof window !== 'undefined') {
    window.addEventListener('storage', (event) => {
      if (event.key !== 'token') return

      const eventToken = event.newValue
      if (!eventToken) {
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
