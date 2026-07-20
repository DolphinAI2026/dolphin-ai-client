import { defineStore } from 'pinia'
import { ref, computed, onScopeDispose } from 'vue'
import { authApi } from '@/api/auth'
import type { User, TenantOption } from '@/types'
import { resetOnboardingCache } from '@/composables/useOnboardingState'
import { MODE_META, modeForRoutePath, useModeStore } from '@/stores/mode'
import {
  beginAuthSessionBootstrap,
  clearAuthSession,
  commitAuthSession,
  getAuthSessionBootstrapToken,
  getAuthSessionState,
  subscribeToAuthSessionClear,
} from '@/utils/request'

let activeSessionOwnerCleanup: (() => void) | null = null
let activeSessionOwner: symbol | null = null

if (import.meta.hot) {
  import.meta.hot.dispose(() => {
    activeSessionOwnerCleanup?.()
    activeSessionOwnerCleanup = null
    activeSessionOwner = null
  })
}

export const useUserStore = defineStore('user', () => {
  const user = ref<User | null>(null)
  const initialSession = getAuthSessionState()
  const sharedInitialToken = localStorage.getItem('token')
  const initialBootstrapToken = (
    !initialSession.initialized
    && typeof sharedInitialToken === 'string'
    && sharedInitialToken
  )
    ? sharedInitialToken
    : null
  const token = ref<string | null>(
    initialSession.initialized ? initialSession.token : initialBootstrapToken,
  )
  const availableTenants = ref<TenantOption[]>([])
  let storageAlignmentGeneration = 0
  let storageAlignmentAbortController: AbortController | null = null
  let tenantSwitchGeneration = 0
  let tenantSwitchAbortController: AbortController | null = null
  let sessionOwner: symbol | null = null
  let sessionOwnerReleased = false

  if (initialBootstrapToken) {
    beginAuthSessionBootstrap(initialBootstrapToken)
  }

  const invalidateStorageAlignment = () => {
    storageAlignmentGeneration += 1
    storageAlignmentAbortController?.abort()
    storageAlignmentAbortController = null
  }

  const invalidateTenantSwitch = () => {
    tenantSwitchGeneration += 1
    tenantSwitchAbortController?.abort()
    tenantSwitchAbortController = null
  }

  const ownsSessionOwner = () => (
    !sessionOwnerReleased
    && sessionOwner !== null
    && activeSessionOwner === sessionOwner
  )

  const currentAppBasePath = () => {
    const base = import.meta.env.BASE_URL || '/'
    const path = `/${base.replace(/^\/+|\/+$/g, '')}`
    return path === '/' ? '/' : path
  }

  const normalizeTenantDestination = (destination: string): string | null => {
    if (
      typeof destination !== 'string'
      || !destination.startsWith('/')
      || destination.startsWith('//')
    ) {
      return null
    }

    try {
      const origin = 'https://tenant-switch.invalid'
      const parsed = new URL(destination, origin)
      const basePath = currentAppBasePath()
      const isWithinBase = (
        basePath === '/'
        || parsed.pathname === basePath
        || parsed.pathname.startsWith(`${basePath}/`)
      )
      if (parsed.origin !== origin || !isWithinBase) return null
      return `${parsed.pathname}${parsed.search}${parsed.hash}`
    } catch {
      return null
    }
  }

  const currentModeTenantHome = (tenantPublicId: string) => {
    const basePath = currentAppBasePath()
    const prefix = basePath === '/' ? '' : basePath
    const pathname = typeof window === 'undefined' ? '' : window.location.pathname
    const routePath = (
      basePath !== '/'
      && (pathname === basePath || pathname.startsWith(`${basePath}/`))
    )
      ? `/${pathname.slice(basePath.length).replace(/^\/+/, '')}`
      : pathname
    const mode = routePath
      ? modeForRoutePath(routePath)
      : useModeStore().mode
    const home = MODE_META[mode].home
    return `${prefix}${home}?tenantId=${encodeURIComponent(tenantPublicId)}`
  }

  const storageAlignmentDestination = (alignedUser: User): string | null => {
    if (alignedUser.tenant_id === null && alignedUser.tenant_public_id === null) {
      const basePath = currentAppBasePath()
      const prefix = basePath === '/' ? '' : basePath
      return `${prefix}/platform-admin/`
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

  const commitLocalToken = (newToken: string) => {
    invalidateStorageAlignment()
    invalidateTenantSwitch()
    token.value = newToken
    commitAuthSession(newToken)
    localStorage.setItem('token', newToken)
  }

  const setToken = (newToken: string) => {
    commitLocalToken(newToken)
  }

  const commitTenantSwitch = (
    newToken: string,
    nextUser: User,
    destination: string,
  ) => {
    // Shared storage and navigation may throw. Keep both ahead of all per-tab
    // adapter, Pinia, and tab mutations so failure preserves the source session.
    const sourceSharedToken = localStorage.getItem('token')
    localStorage.setItem('token', newToken)
    try {
      window.location.replace(destination)
    } catch (error) {
      try {
        if (sourceSharedToken === null) {
          localStorage.removeItem('token')
        } else {
          localStorage.setItem('token', sourceSharedToken)
        }
      } catch {
        // The per-tab session remains untouched even if storage rollback fails.
      }
      throw error
    }

    invalidateStorageAlignment()
    commitAuthSession(newToken)
    token.value = newToken
    user.value = nextUser

    try { localStorage.removeItem('ai-builder-tabs-v1') } catch { /* ignore */ }
  }

  const clearSessionMemory = () => {
    invalidateStorageAlignment()
    invalidateTenantSwitch()
    token.value = null
    user.value = null
    localStorage.removeItem('admin_token')
    resetOnboardingCache()
  }

  const clearToken = () => {
    invalidateStorageAlignment()
    invalidateTenantSwitch()
    clearAuthSession()
    localStorage.removeItem('token')
  }

  const ownsCurrentSession = (requestToken: string, requestRevision: number) => {
    const session = getAuthSessionState()
    return (
      session.token === requestToken
      && session.revision === requestRevision
      && requestToken === localStorage.getItem('token')
    )
  }

  const ownsCurrentBootstrap = (requestToken: string, requestRevision: number) => {
    const session = getAuthSessionState()
    return (
      getAuthSessionBootstrapToken() === requestToken
      && session.revision === requestRevision
      && requestToken === localStorage.getItem('token')
    )
  }

  const isUnauthorized = (error: unknown) => (
    (error as { response?: { status?: number } })?.response?.status === 401
  )

  const fetchUser = async () => {
    const session = getAuthSessionState()
    const bootstrapToken = getAuthSessionBootstrapToken()
    const requestToken = bootstrapToken || session.token
    const requestRevision = session.revision
    const isBootstrap = bootstrapToken === requestToken && Boolean(requestToken)
    if (!requestToken) return

    try {
      const fetchedUser = isBootstrap
        ? await authApi.getMeWithToken(requestToken)
        : await authApi.getMe()
      if (isBootstrap) {
        if (!ownsCurrentBootstrap(requestToken, requestRevision)) return
        commitAuthSession(requestToken)
        token.value = requestToken
        user.value = fetchedUser
        return
      }
      if (ownsCurrentSession(requestToken, requestRevision)) {
        user.value = fetchedUser
      }
    } catch (error) {
      if (isBootstrap) {
        if (!ownsCurrentBootstrap(requestToken, requestRevision)) return
        if (!isUnauthorized(error)) return
        clearToken()
        throw error
      }
      if (
        (error as { config?: { authSessionFailure?: string } })?.config?.authSessionFailure
        === 'authoritative'
      ) {
        throw error
      }
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
    const normalizedDestination = normalizeTenantDestination(destination)
    if (!normalizedDestination) {
      throw new Error('invalid tenant switch destination')
    }

    const sourceRevision = getAuthSessionState().revision
    const generation = ++tenantSwitchGeneration
    tenantSwitchAbortController?.abort()
    const controller = new AbortController()
    tenantSwitchAbortController = controller
    let commitStarted = false
    const isCurrentOperation = () => (
      !controller.signal.aborted
      && generation === tenantSwitchGeneration
      && getAuthSessionState().revision === sourceRevision
    )

    try {
      const candidate = await authApi.switchTenant(targetTenantId, controller.signal)
      if (!isCurrentOperation()) return

      const candidateUser = await authApi.getMeWithToken(candidate.access_token, controller.signal)
      if (!isCurrentOperation()) return
      if (
        candidateUser.tenant_id !== targetTenantId
        || candidateUser.tenant_public_id !== targetTenantPublicId
      ) {
        throw new Error('tenant candidate mismatch')
      }

      commitStarted = true
      commitTenantSwitch(candidate.access_token, candidateUser, normalizedDestination)
    } catch (error) {
      if (!commitStarted && !isCurrentOperation()) return
      throw error
    } finally {
      if (tenantSwitchAbortController === controller) {
        tenantSwitchAbortController = null
      }
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
      const normalizedDestination = destination
        ? normalizeTenantDestination(destination)
        : null
      if (
        controller.signal.aborted
        || generation !== storageAlignmentGeneration
        || !ownsSessionOwner()
        || localStorage.getItem('token') !== eventToken
        || !normalizedDestination
      ) {
        return
      }

      window.location.replace(normalizedDestination)
      commitAuthSession(eventToken)
      token.value = eventToken
      user.value = alignedUser
      try { localStorage.removeItem('ai-builder-tabs-v1') } catch { /* ignore */ }
      if (storageAlignmentAbortController === controller) {
        storageAlignmentAbortController = null
      }
    } catch {
      if (storageAlignmentAbortController === controller) {
        storageAlignmentAbortController = null
      }
    }
  }

  activeSessionOwnerCleanup?.()
  sessionOwner = Symbol('auth-session-owner')
  activeSessionOwner = sessionOwner

  const unsubscribeFromSessionClear = subscribeToAuthSessionClear(clearSessionMemory)
  const storageListener = (event: StorageEvent) => {
    if (event.key !== 'token') return

    const eventToken = event.newValue
    if (!eventToken) {
      clearToken()
      return
    }

    if (localStorage.getItem('token') !== eventToken) return
    void alignTokenFromStorage(eventToken)
  }
  if (typeof window !== 'undefined') {
    window.addEventListener('storage', storageListener)
  }

  const releaseSessionOwner = () => {
    if (sessionOwnerReleased) return
    sessionOwnerReleased = true
    invalidateStorageAlignment()
    invalidateTenantSwitch()
    unsubscribeFromSessionClear()
    if (typeof window !== 'undefined') {
      window.removeEventListener('storage', storageListener)
    }
    if (activeSessionOwner === sessionOwner) {
      activeSessionOwner = null
    }
    if (activeSessionOwnerCleanup === releaseSessionOwner) {
      activeSessionOwnerCleanup = null
    }
  }
  activeSessionOwnerCleanup = releaseSessionOwner
  onScopeDispose(releaseSessionOwner)

  const currentSession = getAuthSessionState()
  const sharedToken = localStorage.getItem('token')
  if (
    currentSession.initialized
    && typeof sharedToken === 'string'
    && sharedToken
    && sharedToken !== currentSession.token
  ) {
    void alignTokenFromStorage(sharedToken)
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
