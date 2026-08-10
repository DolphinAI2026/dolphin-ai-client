import { defineStore } from 'pinia'
import { ref, computed, onScopeDispose } from 'vue'
import { authApi } from '@/api/auth'
import type { User, TenantOption } from '@/types'
import { MODE_META, modeForRoutePath, useModeStore } from '@/stores/mode'
import { safeLoginRedirectPath } from '@/router/loginRedirect'
import {
  beginAuthSessionAlignment,
  beginAuthSessionBootstrap,
  clearAuthSession,
  commitAuthSession,
  getAuthSessionBootstrapToken,
  getAuthSessionState,
  subscribeToAuthSessionClear,
} from '@/utils/request'
import {
  clearControlPlaneCodeSession,
  setExplicitControlPlaneCodeSession,
  setControlPlaneCodeSession,
} from '@/utils/controlPlaneCodeSession'

let activeSessionOwnerCleanup: (() => void) | null = null
let activeSessionOwner: symbol | null = null

export type TenantSwitchContextOutcome = 'committed_reload' | 'stale_cancelled'

export interface TenantSelectionCommit {
  rollback: () => boolean
  finalize: () => void
}

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
  const initialAlignmentToken = (
    initialSession.initialized
    && typeof sharedInitialToken === 'string'
    && sharedInitialToken
    && sharedInitialToken !== initialSession.token
  )
    ? sharedInitialToken
    : null
  const token = ref<string | null>(
    initialSession.initialized ? initialSession.token : initialBootstrapToken,
  )
  const availableTenants = ref<TenantOption[]>([])
  let tenantSwitchGeneration = 0
  let tenantSwitchAbortController: AbortController | null = null
  let tenantSelectionGeneration = 0
  let tenantSelectionAbortController: AbortController | null = null
  let controlPlaneCodeTenantSwitchGeneration = 0
  let tenantNavigationEpoch = 0
  let sessionOwner: symbol | null = null
  let sessionOwnerReleased = false

  if (initialAlignmentToken) {
    beginAuthSessionAlignment(initialAlignmentToken)
  } else if (initialBootstrapToken) {
    beginAuthSessionBootstrap(initialBootstrapToken)
  }

  const invalidateTenantSwitch = () => {
    tenantSwitchGeneration += 1
    tenantSwitchAbortController?.abort()
    tenantSwitchAbortController = null
  }

  const advanceTenantNavigationEpoch = () => {
    tenantNavigationEpoch += 1
    invalidateTenantSwitch()
    return tenantNavigationEpoch
  }

  const isTenantNavigationEpochCurrent = (epoch: number) => (
    epoch === tenantNavigationEpoch
  )

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

  const storageAlignmentReloadDestination = (): string | null => {
    if (typeof window === 'undefined') return null
    const basePath = currentAppBasePath()
    const prefix = basePath === '/' ? '' : basePath
    const pathname = window.location.pathname
    const routePath = (
      basePath !== '/'
      && (pathname === basePath || pathname.startsWith(`${basePath}/`))
    )
      ? `/${pathname.slice(basePath.length).replace(/^\/+/, '')}`
      : pathname
    return normalizeTenantDestination(`${prefix}${MODE_META[modeForRoutePath(routePath)].home}`)
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
    advanceTenantNavigationEpoch()
    token.value = newToken
    commitAuthSession(newToken)
    localStorage.setItem('token', newToken)
    if (!setControlPlaneCodeSession(newToken)) clearControlPlaneCodeSession()
  }

  const setToken = (newToken: string) => {
    commitLocalToken(newToken)
  }

  const commitTenantSwitch = (
    newToken: string,
    nextUser: User,
    destination: string,
  ) => {
    // A reload must see the candidate in both shared and per-tab storage. If
    // sessionStorage is updated after location.replace(), the next page can
    // revive the previous token and send Code requests to the old tenant.
    const sourceSession = getAuthSessionState()
    const sourceSharedToken = localStorage.getItem('token')
    const sourceUser = user.value
    let candidateCommitted = false
    try {
      localStorage.setItem('token', newToken)
      commitAuthSession(newToken)
      if (!setControlPlaneCodeSession(newToken)) clearControlPlaneCodeSession()
      candidateCommitted = true
      token.value = newToken
      user.value = nextUser
      window.location.replace(destination)
    } catch (error) {
      try {
        if (sourceSharedToken === null) {
          localStorage.removeItem('token')
        } else {
          localStorage.setItem('token', sourceSharedToken)
        }
        if (candidateCommitted) {
          if (sourceSession.token) {
            commitAuthSession(sourceSession.token)
            token.value = sourceSession.token
          } else {
            clearAuthSession()
            token.value = null
          }
          user.value = sourceUser
        }
      } catch {
        // Preserve the navigation error; a browser storage failure is not
        // recoverable here.
      }
      throw error
    }

    try { localStorage.removeItem('ai-builder-tabs-v1') } catch { /* ignore */ }
  }

  const commitVerifiedSession = (newToken: string, nextUser: User) => {
    localStorage.setItem('token', newToken)
    advanceTenantNavigationEpoch()
    const committedSession = commitAuthSession(newToken)
    if (!setControlPlaneCodeSession(newToken)) clearControlPlaneCodeSession()
    token.value = newToken
    user.value = nextUser
    return committedSession
  }

  const tenantSelectionAbortError = () => {
    const error = new Error('Tenant selection aborted')
    error.name = 'AbortError'
    return error
  }

  const clearSessionMemory = () => {
    advanceTenantNavigationEpoch()
    token.value = null
    user.value = null
    localStorage.removeItem('admin_token')
  }

  const clearToken = () => {
    advanceTenantNavigationEpoch()
    clearAuthSession()
    localStorage.removeItem('token')
    localStorage.removeItem('access_token')
    localStorage.removeItem('tenant_id')
    clearControlPlaneCodeSession()
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
    if (res.web_console_access_token) {
      localStorage.setItem('access_token', res.web_console_access_token)
      if (res.web_console_tenant_id) {
        localStorage.setItem('tenant_id', res.web_console_tenant_id)
      } else {
        localStorage.removeItem('tenant_id')
      }
    } else {
      localStorage.removeItem('access_token')
      localStorage.removeItem('tenant_id')
    }
    await fetchUser()
    return {
      requiresSelection: false,
      // Control Plane login selects the Code shell explicitly. Do not discard
      // the server-directed internal entry route and fall back to Builder home.
      entryPath: safeLoginRedirectPath(res.entry_path) || '/',
    }
  }

  const selectTenant = async (
    selectionToken: string,
    tenantId: number,
    tenantPublicId: string,
    externalSignal?: AbortSignal,
  ): Promise<TenantSelectionCommit> => {
    const sourceSession = getAuthSessionState()
    const sourceUser = user.value
    const generation = ++tenantSelectionGeneration
    tenantSelectionAbortController?.abort()
    const controller = new AbortController()
    tenantSelectionAbortController = controller
    const abortFromExternal = () => controller.abort(externalSignal?.reason)
    if (externalSignal?.aborted) {
      abortFromExternal()
    } else {
      externalSignal?.addEventListener('abort', abortFromExternal, { once: true })
    }
    const isCurrentOperation = () => (
      !controller.signal.aborted
      && generation === tenantSelectionGeneration
      && getAuthSessionState().revision === sourceSession.revision
    )
    const requireCurrentOperation = () => {
      if (!isCurrentOperation()) throw tenantSelectionAbortError()
    }

    try {
      requireCurrentOperation()
      const res = await authApi.selectTenant(
        { selection_token: selectionToken, tenant_id: tenantId },
        controller.signal,
      )
      requireCurrentOperation()
      const candidateUser = await authApi.getMeWithToken(
        res.access_token,
        controller.signal,
      )
      requireCurrentOperation()
      if (
        candidateUser.tenant_id !== tenantId
        || candidateUser.tenant_public_id !== tenantPublicId
      ) {
        throw new Error('tenant candidate mismatch')
      }
      requireCurrentOperation()

      const committedSession = commitVerifiedSession(res.access_token, candidateUser)
      let active = true
      return {
        rollback: () => {
          if (!active) return false
          active = false
          const currentSession = getAuthSessionState()
          if (
            currentSession.revision !== committedSession.revision
            || currentSession.token !== res.access_token
            || token.value !== res.access_token
            || localStorage.getItem('token') !== res.access_token
          ) {
            return false
          }

          const sourceToken = sourceSession.initialized ? sourceSession.token : null
          if (sourceToken) {
            localStorage.setItem('token', sourceToken)
            commitAuthSession(sourceToken)
            token.value = sourceToken
            user.value = sourceUser
          } else {
            localStorage.removeItem('token')
            clearAuthSession()
            token.value = null
            user.value = null
          }
          advanceTenantNavigationEpoch()
          return true
        },
        finalize: () => {
          active = false
        },
      }
    } finally {
      externalSignal?.removeEventListener('abort', abortFromExternal)
      if (tenantSelectionAbortController === controller) {
        tenantSelectionAbortController = null
      }
    }
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
    navigationEpoch?: number,
  ) => {
    const epoch = navigationEpoch ?? advanceTenantNavigationEpoch()
    if (!isTenantNavigationEpochCurrent(epoch)) {
      return 'stale_cancelled' as const
    }

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
      && isTenantNavigationEpochCurrent(epoch)
      && getAuthSessionState().revision === sourceRevision
    )

    try {
      const candidate = await authApi.switchTenant(targetTenantId, controller.signal)
      if (!isCurrentOperation()) return 'stale_cancelled' as const

      const candidateUser = await authApi.getMeWithToken(candidate.access_token, controller.signal)
      if (!isCurrentOperation()) return 'stale_cancelled' as const
      if (
        candidateUser.tenant_id !== targetTenantId
        || candidateUser.tenant_public_id !== targetTenantPublicId
      ) {
        throw new Error('tenant candidate mismatch')
      }

      commitStarted = true
      commitTenantSwitch(candidate.access_token, candidateUser, normalizedDestination)
      return 'committed_reload' as const
    } catch (error) {
      if (!commitStarted && !isCurrentOperation()) return 'stale_cancelled' as const
      throw error
    } finally {
      if (tenantSwitchAbortController === controller) {
        tenantSwitchAbortController = null
      }
    }
  }

  const switchControlPlaneCodeTenant = async (
    targetTenantId: string,
    authToken: string,
  ) => {
    const sourceSession = getAuthSessionState()
    const generation = ++controlPlaneCodeTenantSwitchGeneration
    const candidate = await authApi.switchControlPlaneCodeTenant(targetTenantId, authToken)
    const currentSession = getAuthSessionState()
    if (
      generation !== controlPlaneCodeTenantSwitchGeneration
      || currentSession.revision !== sourceSession.revision
      || currentSession.token !== sourceSession.token
    ) {
      return 'stale_cancelled' as const
    }
    if (
      !sourceSession.token
      || !setExplicitControlPlaneCodeSession(
        candidate.access_token,
        sourceSession.token,
        targetTenantId,
      )
    ) {
      throw new Error('control-plane tenant candidate mismatch')
    }
    return 'committed' as const
  }

  const switchTenant = async (targetTenantId: number | string) => {
    const navigationEpoch = advanceTenantNavigationEpoch()
    if (String(targetTenantId) === String(tenantId.value || '')) return
    if (typeof targetTenantId === 'string') {
      const candidate = await authApi.switchTenant(targetTenantId)
      setToken(candidate.access_token)
      await fetchUser()
      if (typeof window !== 'undefined') {
        try { localStorage.removeItem('ai-builder-tabs-v1') } catch { /* ignore */ }
        window.location.href = import.meta.env.BASE_URL
      }
      return
    }
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
      navigationEpoch,
    )
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
    if (!ownsSessionOwner()) return
    beginAuthSessionAlignment(eventToken)
    advanceTenantNavigationEpoch()
    const destination = storageAlignmentReloadDestination()
    if (destination) {
      try {
        window.location.replace(destination)
      } catch {
        // The old page remains auth-pending if browser navigation is blocked.
      }
    }
  }
  if (typeof window !== 'undefined') {
    window.addEventListener('storage', storageListener)
  }

  const releaseSessionOwner = () => {
    if (sessionOwnerReleased) return
    sessionOwnerReleased = true
    tenantSelectionGeneration += 1
    tenantSelectionAbortController?.abort()
    tenantSelectionAbortController = null
    advanceTenantNavigationEpoch()
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
    switchTenantContext,
    switchControlPlaneCodeTenant,
    switchTenant,
    fetchAvailableTenants,
    advanceTenantNavigationEpoch,
    isTenantNavigationEpochCurrent,
    logout
  }
})
