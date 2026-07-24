import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

const authMocks = vi.hoisted(() => ({
  getMe: vi.fn(),
  getMeWithToken: vi.fn(),
  selectTenant: vi.fn(),
  switchTenant: vi.fn(),
}))

vi.mock('@/api/auth', () => ({
  authApi: authMocks,
}))

vi.mock('@/composables/useOnboardingState', () => ({
  resetOnboardingCache: vi.fn(),
}))

import { useUserStore } from './user'
import type { TenantOption, User } from '@/types'
import request, {
  getAuthSessionBootstrapToken,
  getAuthSessionState,
} from '@/utils/request'
import { aiChatApi } from '@/api/aiChat'
import { extensionApi } from '@/api/extension'

const sourceUuid = '11111111-1111-4111-8111-111111111111'
const targetUuid = '22222222-2222-4222-8222-222222222222'
const targetPath = '/ai-builder/tenants/22222222-2222-4222-8222-222222222222/'

function makeUser(overrides: Partial<User> = {}): User {
  return {
    id: 1,
    username: 'operator',
    is_active: true,
    created_at: '2026-07-20T00:00:00Z',
    tenant_id: 1,
    tenant_name: 'Source tenant',
    tenant_role: 'tenant_admin',
    tenant_public_id: sourceUuid,
    ...overrides,
  }
}

function makeTenantOption(tenantId: number, tenantPublicId: string): TenantOption {
  return {
    tenant_id: tenantId,
    tenant_name: tenantId === 1 ? 'Source tenant' : 'Target tenant',
    tenant_code: tenantId === 1 ? 'source' : 'target',
    tenant_public_id: tenantPublicId,
  }
}

function installBrowserGlobals(pathname = '/', search = '', hash = '') {
  const storage = new Map<string, string>()
  const sessionStorage = new Map<string, string>()
  const replace = vi.fn()
  const location = {
    pathname,
    search,
    hash,
    href: '',
    replace,
  }
  const storageListeners = new Set<(event: { key: string | null; newValue: string | null }) => void>()

  vi.stubGlobal('localStorage', {
    getItem: (key: string) => storage.get(key) ?? null,
    setItem: (key: string, value: string) => storage.set(key, value),
    removeItem: (key: string) => storage.delete(key),
  })
  vi.stubGlobal('sessionStorage', {
    getItem: (key: string) => sessionStorage.get(key) ?? null,
    setItem: (key: string, value: string) => sessionStorage.set(key, value),
    removeItem: (key: string) => sessionStorage.delete(key),
  })
  vi.stubGlobal('window', {
    location,
    addEventListener: (type: string, listener: (event: { key: string | null; newValue: string | null }) => void) => {
      if (type === 'storage') storageListeners.add(listener)
    },
    removeEventListener: (type: string, listener: (event: { key: string | null; newValue: string | null }) => void) => {
      if (type === 'storage') storageListeners.delete(listener)
    },
  })

  return {
    location,
    replace,
    sessionStorage,
    fireStorageEvent: (token: string | null) => {
      for (const listener of storageListeners) {
        listener({ key: 'token', newValue: token })
      }
    },
  }
}

function runRequestInterceptor(config: { headers?: Record<string, string> }) {
  const handler = (
    request.interceptors.request as unknown as {
      handlers: Array<{ fulfilled?: (value: typeof config) => typeof config }>
    }
  ).handlers.find((candidate) => candidate.fulfilled)?.fulfilled

  if (!handler) {
    throw new Error('request interceptor is not registered')
  }

  return handler(config)
}

function runResponseErrorInterceptor(error: {
  response?: { status?: number; data?: { detail?: string } }
  config?: Record<string, unknown>
}) {
  const handler = (
    request.interceptors.response as unknown as {
      handlers: Array<{ rejected?: (reason: typeof error) => Promise<never> }>
    }
  ).handlers.find((candidate) => candidate.rejected)?.rejected

  if (!handler) {
    throw new Error('response interceptor is not registered')
  }

  return handler(error)
}

function deferred<T>() {
  let resolve!: (value: T) => void
  let reject!: (reason?: unknown) => void
  const promise = new Promise<T>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise
    reject = rejectPromise
  })

  return { promise, resolve, reject }
}

function completedSseResponse() {
  return {
    ok: true,
    body: {
      getReader: () => ({
        read: vi.fn().mockResolvedValue({ done: true, value: undefined }),
      }),
    },
  }
}

async function flushPromises() {
  await Promise.resolve()
  await Promise.resolve()
}

describe('user tenant switching', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.unstubAllGlobals()
  })

  it('fails closed for ordinary requests until a cold-start token passes explicit validation', async () => {
    installBrowserGlobals()
    const pendingCandidate = deferred<User>()
    localStorage.setItem('token', 'boot-token')
    authMocks.getMeWithToken.mockReturnValue(pendingCandidate.promise)

    setActivePinia(createPinia())
    const store = useUserStore()

    await expect(
      Promise.resolve().then(() => runRequestInterceptor({ headers: {} })),
    ).rejects.toMatchObject({ code: 'AUTH_SESSION_PENDING' })

    const fetchUserPromise = store.fetchUser()
    expect(authMocks.getMeWithToken).toHaveBeenCalledWith('boot-token')

    pendingCandidate.resolve(makeUser())
    await fetchUserPromise

    const config = await runRequestInterceptor({ headers: {} })
    expect(config.headers?.Authorization).toBe('Bearer boot-token')
  })

  it('keeps the source session when selected-tenant candidate validation fails', async () => {
    installBrowserGlobals()
    const sourceUser = makeUser({ display_name: 'Source session' })
    const forbidden = Object.assign(new Error('inactive tenant'), {
      response: { status: 403 },
    })
    authMocks.selectTenant.mockResolvedValue({ access_token: 'candidate-token' })
    authMocks.getMeWithToken.mockRejectedValue(forbidden)

    setActivePinia(createPinia())
    const store = useUserStore()
    store.setToken('source-token')
    store.user = sourceUser
    const sourceRevision = getAuthSessionState().revision

    await expect(
      store.selectTenant('selection-token', 2, targetUuid),
    ).rejects.toBe(forbidden)

    expect(authMocks.selectTenant).toHaveBeenCalledWith({
      selection_token: 'selection-token',
      tenant_id: 2,
    }, expect.any(AbortSignal))
    expect(authMocks.getMeWithToken).toHaveBeenCalledWith(
      'candidate-token',
      expect.any(AbortSignal),
    )
    expect(getAuthSessionState().revision).toBe(sourceRevision)
    expect(localStorage.getItem('token')).toBe('source-token')
    expect(store.token).toBe('source-token')
    expect(store.user).toEqual(sourceUser)
  })

  it('commits a selected tenant only after numeric ID and public UUID validation', async () => {
    installBrowserGlobals()
    const targetUser = makeUser({
      tenant_id: 2,
      tenant_name: 'Target tenant',
      tenant_public_id: targetUuid,
    })
    authMocks.selectTenant.mockResolvedValue({ access_token: 'candidate-token' })
    authMocks.getMeWithToken.mockResolvedValue(targetUser)

    setActivePinia(createPinia())
    const store = useUserStore()
    store.setToken('source-token')
    store.user = makeUser()

    const commit = await store.selectTenant('selection-token', 2, targetUuid)

    expect(localStorage.getItem('token')).toBe('candidate-token')
    expect(store.token).toBe('candidate-token')
    expect(store.user).toEqual(targetUser)
    commit.finalize()
  })

  it('does not commit when selection is aborted after candidate user validation starts', async () => {
    installBrowserGlobals()
    const sourceUser = makeUser({ display_name: 'Source session' })
    const pendingCandidate = deferred<User>()
    const controller = new AbortController()
    authMocks.selectTenant.mockResolvedValue({ access_token: 'candidate-token' })
    authMocks.getMeWithToken.mockReturnValue(pendingCandidate.promise)

    setActivePinia(createPinia())
    const store = useUserStore()
    store.setToken('source-token')
    store.user = sourceUser
    const sourceRevision = getAuthSessionState().revision

    const selection = store.selectTenant(
      'selection-token',
      2,
      targetUuid,
      controller.signal,
    )
    await flushPromises()
    controller.abort()
    pendingCandidate.resolve(makeUser({
      tenant_id: 2,
      tenant_name: 'Target tenant',
      tenant_public_id: targetUuid,
    }))

    await expect(selection).rejects.toMatchObject({ name: 'AbortError' })
    expect(getAuthSessionState().revision).toBe(sourceRevision)
    expect(localStorage.getItem('token')).toBe('source-token')
    expect(store.token).toBe('source-token')
    expect(store.user).toEqual(sourceUser)
  })

  it('aborts an older selection intent before it can commit', async () => {
    installBrowserGlobals()
    const firstToken = deferred<{ access_token: string }>()
    authMocks.selectTenant
      .mockReturnValueOnce(firstToken.promise)
      .mockRejectedValueOnce(new Error('replacement failed'))

    setActivePinia(createPinia())
    const store = useUserStore()
    store.setToken('source-token')
    store.user = makeUser()
    const first = store.selectTenant('selection-one', 2, targetUuid)
    await flushPromises()
    const second = store.selectTenant('selection-two', 3, '33333333-3333-4333-8333-333333333333')
    const secondExpectation = expect(second).rejects.toThrow('replacement failed')
    firstToken.resolve({ access_token: 'stale-token' })

    await expect(first).rejects.toMatchObject({ name: 'AbortError' })
    await secondExpectation
    expect(authMocks.getMeWithToken).not.toHaveBeenCalled()
    expect(localStorage.getItem('token')).toBe('source-token')
    expect(store.token).toBe('source-token')
  })

  it('rolls back only the currently committed selected-tenant candidate', async () => {
    installBrowserGlobals()
    const sourceUser = makeUser({ display_name: 'Source session' })
    const targetUser = makeUser({
      tenant_id: 2,
      tenant_name: 'Target tenant',
      tenant_public_id: targetUuid,
    })
    authMocks.selectTenant.mockResolvedValue({ access_token: 'candidate-token' })
    authMocks.getMeWithToken.mockResolvedValue(targetUser)

    setActivePinia(createPinia())
    const store = useUserStore()
    store.setToken('source-token')
    store.user = sourceUser

    const commit = await store.selectTenant('selection-token', 2, targetUuid)
    expect(commit.rollback()).toBe(true)

    expect(localStorage.getItem('token')).toBe('source-token')
    expect(store.token).toBe('source-token')
    expect(store.user).toEqual(sourceUser)
    expect(commit.rollback()).toBe(false)
  })

  it('does not roll back an initialized source after shared storage moves to a newer token', async () => {
    const { fireStorageEvent, replace } = installBrowserGlobals()
    const sourceUser = makeUser({ display_name: 'Source session' })
    const targetUser = makeUser({
      tenant_id: 2,
      tenant_name: 'Target tenant',
      tenant_public_id: targetUuid,
    })
    authMocks.selectTenant.mockResolvedValue({ access_token: 'candidate-token' })
    authMocks.getMeWithToken.mockResolvedValue(targetUser)

    setActivePinia(createPinia())
    const store = useUserStore()
    store.setToken('source-token')
    store.user = sourceUser

    const commit = await store.selectTenant('selection-token', 2, targetUuid)
    const candidateSession = getAuthSessionState()
    localStorage.setItem('token', 'newer-shared-token')
    fireStorageEvent('newer-shared-token')
    await flushPromises()
    const setItem = vi.spyOn(localStorage, 'setItem')
    const removeItem = vi.spyOn(localStorage, 'removeItem')

    expect(commit.rollback()).toBe(false)

    expect(authMocks.getMeWithToken).toHaveBeenCalledTimes(1)
    expect(getAuthSessionState()).toMatchObject({
      token: candidateSession.token,
      revision: candidateSession.revision + 1,
    })
    expect(getAuthSessionBootstrapToken()).toBe('newer-shared-token')
    expect(store.token).toBe('candidate-token')
    expect(store.user).toEqual(targetUser)
    expect(localStorage.getItem('token')).toBe('newer-shared-token')
    expect(replace).toHaveBeenCalledWith('/')
    expect(setItem).not.toHaveBeenCalled()
    expect(removeItem).not.toHaveBeenCalled()
  })

  it('does not clear a newer shared token when the selected-tenant source was uninitialized', async () => {
    const { fireStorageEvent, replace } = installBrowserGlobals()
    const targetUser = makeUser({
      tenant_id: 2,
      tenant_name: 'Target tenant',
      tenant_public_id: targetUuid,
    })
    authMocks.selectTenant.mockResolvedValue({ access_token: 'candidate-token' })
    authMocks.getMeWithToken.mockResolvedValue(targetUser)

    setActivePinia(createPinia())
    const store = useUserStore()
    expect(getAuthSessionState()).toMatchObject({
      token: null,
      initialized: false,
    })

    const commit = await store.selectTenant('selection-token', 2, targetUuid)
    const candidateSession = getAuthSessionState()
    localStorage.setItem('token', 'newer-shared-token')
    fireStorageEvent('newer-shared-token')
    await flushPromises()
    const setItem = vi.spyOn(localStorage, 'setItem')
    const removeItem = vi.spyOn(localStorage, 'removeItem')

    expect(commit.rollback()).toBe(false)

    expect(authMocks.getMeWithToken).toHaveBeenCalledTimes(1)
    expect(getAuthSessionState()).toMatchObject({
      token: candidateSession.token,
      revision: candidateSession.revision + 1,
    })
    expect(getAuthSessionBootstrapToken()).toBe('newer-shared-token')
    expect(store.token).toBe('candidate-token')
    expect(store.user).toEqual(targetUser)
    expect(localStorage.getItem('token')).toBe('newer-shared-token')
    expect(replace).toHaveBeenCalledWith('/')
    expect(setItem).not.toHaveBeenCalled()
    expect(removeItem).not.toHaveBeenCalled()
  })

  it('keeps source state when candidate /auth/me UUID mismatches', async () => {
    const { replace } = installBrowserGlobals()
    const sourceUser = makeUser()
    const targetUser = makeUser({
      tenant_id: 2,
      tenant_name: 'Target tenant',
      tenant_public_id: 'wrong-uuid',
    })
    localStorage.setItem('token', 'source-token')
    localStorage.setItem('ai-builder-tabs-v1', 'source-tabs')
    authMocks.switchTenant.mockResolvedValue({ access_token: 'candidate-token' })
    authMocks.getMeWithToken.mockResolvedValue(targetUser)

    setActivePinia(createPinia())
    const store = useUserStore()
    store.user = sourceUser

    await expect(
      store.switchTenantContext(2, targetUuid, targetPath),
    ).rejects.toThrow()

    expect(localStorage.getItem('token')).toBe('source-token')
    expect(localStorage.getItem('ai-builder-tabs-v1')).toBe('source-tabs')
    expect(store.user).toEqual(sourceUser)
    expect(replace).not.toHaveBeenCalled()
  })

  it('commits token and user only after candidate numeric ID and UUID match', async () => {
    const { replace, sessionStorage } = installBrowserGlobals()
    const targetUser = makeUser({
      tenant_id: 2,
      tenant_name: 'Target tenant',
      tenant_public_id: targetUuid,
    })
    authMocks.switchTenant.mockResolvedValue({ access_token: 'candidate-token' })
    authMocks.getMeWithToken.mockResolvedValue(targetUser)

    setActivePinia(createPinia())
    const store = useUserStore()
    store.user = makeUser()
    localStorage.setItem('token', 'source-token')
    localStorage.setItem('ai-builder-tabs-v1', 'source-tabs')
    replace.mockImplementation(() => {
      expect(sessionStorage.get('ai-builder-auth-session-v1')).toContain('candidate-token')
    })

    await expect(store.switchTenantContext(2, targetUuid, targetPath))
      .resolves.toBe('committed_reload')

    expect(localStorage.getItem('token')).toBe('candidate-token')
    expect(localStorage.getItem('ai-builder-tabs-v1')).toBeNull()
    expect(store.user?.tenant_public_id).toBe(targetUuid)
    expect(replace).toHaveBeenCalledWith(targetPath)
  })

  it.each(['SecurityError', 'QuotaExceededError'])(
    'keeps the source session intact and rejects when active switch shared storage write throws %s',
    async (errorName) => {
      const { replace } = installBrowserGlobals()
      const sourceUser = makeUser({ display_name: 'Source session' })
      const targetUser = makeUser({
        tenant_id: 2,
        tenant_name: 'Target tenant',
        tenant_public_id: targetUuid,
      })
      authMocks.switchTenant.mockResolvedValue({ access_token: 'candidate-token' })
      authMocks.getMeWithToken.mockResolvedValue(targetUser)

      setActivePinia(createPinia())
      const store = useUserStore()
      store.setToken('source-token')
      store.user = sourceUser
      localStorage.setItem('ai-builder-tabs-v1', 'source-tabs')
      const sourceRevision = getAuthSessionState().revision
      const originalSetItem = localStorage.setItem
      vi.spyOn(localStorage, 'setItem').mockImplementation((key: string, value: string) => {
        if (key === 'token' && value === 'candidate-token') {
          const error = new Error(`blocked ${errorName}`)
          error.name = errorName
          throw error
        }
        originalSetItem.call(localStorage, key, value)
      })

      await expect(
        store.switchTenantContext(2, targetUuid, targetPath),
      ).rejects.toMatchObject({ name: errorName })

      expect(getAuthSessionState().revision).toBe(sourceRevision)
      expect(store.token).toBe('source-token')
      expect(store.user).toEqual(sourceUser)
      expect(localStorage.getItem('token')).toBe('source-token')
      expect(localStorage.getItem('ai-builder-tabs-v1')).toBe('source-tabs')
      expect(replace).not.toHaveBeenCalled()
    },
  )

  it('restores the source session and shared token when active switch navigation throws', async () => {
    const { location, replace } = installBrowserGlobals()
    const sourceUser = makeUser({ display_name: 'Source session' })
    const targetUser = makeUser({
      tenant_id: 2,
      tenant_name: 'Target tenant',
      tenant_public_id: targetUuid,
    })
    const navigationError = Object.assign(new Error('navigation blocked'), {
      name: 'SecurityError',
    })
    authMocks.switchTenant.mockResolvedValue({ access_token: 'candidate-token' })
    authMocks.getMeWithToken.mockResolvedValue(targetUser)
    replace.mockImplementation(() => {
      throw navigationError
    })

    setActivePinia(createPinia())
    const store = useUserStore()
    store.setToken('source-token')
    store.user = sourceUser
    localStorage.setItem('ai-builder-tabs-v1', 'source-tabs')
    const sourceRevision = getAuthSessionState().revision

    await expect(
      store.switchTenantContext(2, targetUuid, targetPath),
    ).rejects.toBe(navigationError)

    expect(getAuthSessionState().revision).toBeGreaterThan(sourceRevision)
    expect(getAuthSessionState().token).toBe('source-token')
    expect(store.token).toBe('source-token')
    expect(store.user).toEqual(sourceUser)
    expect(localStorage.getItem('token')).toBe('source-token')
    expect(localStorage.getItem('ai-builder-tabs-v1')).toBe('source-tabs')
    expect(location.href).toBe('')
    expect(replace).toHaveBeenCalledWith(targetPath)
  })

  it.each([
    'https://untrusted.example/tenant',
    '//untrusted.example/tenant',
    'javascript:alert(1)',
    'data:text/html,tenant',
  ])('rejects an unsafe active switch destination before candidate requests: %s', async (destination) => {
    const { replace } = installBrowserGlobals()
    const sourceUser = makeUser({ display_name: 'Source session' })

    setActivePinia(createPinia())
    const store = useUserStore()
    store.setToken('source-token')
    store.user = sourceUser
    localStorage.setItem('ai-builder-tabs-v1', 'source-tabs')
    const sourceRevision = getAuthSessionState().revision

    await expect(
      store.switchTenantContext(2, targetUuid, destination),
    ).rejects.toThrow('invalid tenant switch destination')

    expect(authMocks.switchTenant).not.toHaveBeenCalled()
    expect(authMocks.getMeWithToken).not.toHaveBeenCalled()
    expect(getAuthSessionState().revision).toBe(sourceRevision)
    expect(store.token).toBe('source-token')
    expect(store.user).toEqual(sourceUser)
    expect(localStorage.getItem('token')).toBe('source-token')
    expect(localStorage.getItem('ai-builder-tabs-v1')).toBe('source-tabs')
    expect(replace).not.toHaveBeenCalled()
  })

  it('uses the authorized available tenant UUID in the switchTenant compatibility wrapper', async () => {
    const { replace } = installBrowserGlobals()
    const targetUser = makeUser({
      tenant_id: 2,
      tenant_name: 'Target tenant',
      tenant_public_id: targetUuid,
    })
    authMocks.switchTenant.mockResolvedValue({ access_token: 'candidate-token' })
    authMocks.getMeWithToken.mockResolvedValue(targetUser)

    setActivePinia(createPinia())
    const store = useUserStore()
    store.user = makeUser()
    store.availableTenants = [
      makeTenantOption(1, sourceUuid),
      makeTenantOption(2, targetUuid),
    ]

    await store.switchTenant(2)

    expect(authMocks.switchTenant).toHaveBeenCalledWith(2, expect.any(AbortSignal))
    expect(replace).toHaveBeenCalledWith('/?tenantId=22222222-2222-4222-8222-222222222222')
  })

  it('uses the shared navigation epoch to cancel an active tenant switch', async () => {
    const { replace } = installBrowserGlobals()
    const slowCandidate = deferred<User>()
    authMocks.switchTenant.mockResolvedValue({ access_token: 'candidate-token' })
    authMocks.getMeWithToken.mockReturnValue(slowCandidate.promise)

    setActivePinia(createPinia())
    const store = useUserStore()
    store.setToken('source-token')
    store.user = makeUser()

    expect(store.advanceTenantNavigationEpoch).toBeTypeOf('function')
    const resolverEpoch = store.advanceTenantNavigationEpoch()
    const switchB = store.switchTenantContext(2, targetUuid, targetPath, resolverEpoch)
    await flushPromises()
    store.advanceTenantNavigationEpoch()
    slowCandidate.resolve(makeUser({
      tenant_id: 2,
      tenant_name: 'Target tenant',
      tenant_public_id: targetUuid,
    }))

    await expect(switchB).resolves.toBe('stale_cancelled')
    expect(replace).not.toHaveBeenCalled()
  })

  it('advances the shared navigation epoch before sidebar switchTenant starts Task 3', async () => {
    const { replace } = installBrowserGlobals()
    const slowB = deferred<User>()
    const userC = makeUser({
      tenant_id: 3,
      tenant_name: 'Tenant C',
      tenant_public_id: '33333333-3333-4333-8333-333333333333',
    })
    authMocks.switchTenant.mockImplementation((tenantId: number) => Promise.resolve({
      access_token: tenantId === 2 ? 'token-b' : 'token-c',
    }))
    authMocks.getMeWithToken.mockImplementation((candidateToken: string) => {
      if (candidateToken === 'token-b') return slowB.promise
      if (candidateToken === 'token-c') return Promise.resolve(userC)
      throw new Error(`unexpected token ${candidateToken}`)
    })

    setActivePinia(createPinia())
    const store = useUserStore()
    store.setToken('source-token')
    store.user = makeUser()
    store.availableTenants = [
      makeTenantOption(1, sourceUuid),
      makeTenantOption(2, targetUuid),
      makeTenantOption(3, userC.tenant_public_id!),
    ]

    expect(store.advanceTenantNavigationEpoch).toBeTypeOf('function')
    const resolverEpoch = store.advanceTenantNavigationEpoch()
    const switchB = store.switchTenantContext(2, targetUuid, '/?tenantId=tenant-b', resolverEpoch)
    await flushPromises()
    await store.switchTenant(3)
    slowB.resolve(makeUser({
      tenant_id: 2,
      tenant_name: 'Tenant B',
      tenant_public_id: targetUuid,
    }))

    await expect(switchB).resolves.toBe('stale_cancelled')
    expect(replace).toHaveBeenCalledTimes(1)
  })

  it('ignores a storage event whose token no longer matches localStorage', async () => {
    const { fireStorageEvent } = installBrowserGlobals()
    localStorage.setItem('token', 'token-a')

    setActivePinia(createPinia())
    useUserStore()

    fireStorageEvent('token-b')
    await flushPromises()

    expect(authMocks.getMeWithToken).not.toHaveBeenCalled()
  })

  it('keeps only the latest storage token pending across rapid token changes', async () => {
    const { fireStorageEvent, replace } = installBrowserGlobals()

    setActivePinia(createPinia())
    const store = useUserStore()
    store.setToken('token-a')
    const sourceUser = makeUser()
    store.user = sourceUser
    const sourceRevision = getAuthSessionState().revision

    localStorage.setItem('token', 'token-b')
    fireStorageEvent('token-b')

    localStorage.setItem('token', 'token-a')
    fireStorageEvent('token-a')

    expect(authMocks.getMeWithToken).not.toHaveBeenCalled()
    expect(getAuthSessionBootstrapToken()).toBe('token-a')
    expect(getAuthSessionState()).toMatchObject({
      token: 'token-a',
      revision: sourceRevision + 2,
    })
    expect(store.user).toEqual(sourceUser)
    expect(replace).toHaveBeenNthCalledWith(1, '/')
    expect(replace).toHaveBeenNthCalledWith(2, '/')
  })

  it('keeps the current in-memory session and tabs while reloading for storage alignment', async () => {
    const { fireStorageEvent, replace } = installBrowserGlobals()
    const sourceUser = makeUser({ display_name: 'Source session' })
    localStorage.setItem('token', 'source-token')
    localStorage.setItem('ai-builder-tabs-v1', 'source-tabs')

    setActivePinia(createPinia())
    const store = useUserStore()
    store.user = sourceUser

    localStorage.setItem('token', 'candidate-token')
    fireStorageEvent('candidate-token')
    await flushPromises()

    expect(store.token).toBe('source-token')
    expect(store.user).toEqual(sourceUser)
    expect(localStorage.getItem('ai-builder-tabs-v1')).toBe('source-tabs')
    expect(authMocks.getMeWithToken).not.toHaveBeenCalled()
    expect(replace).toHaveBeenCalledWith('/')
  })

  it('fails closed and reloads the Code tenant home without retaining source resource IDs', async () => {
    const { fireStorageEvent, replace } = installBrowserGlobals(
      '/code/session-42',
      `?tenantId=${sourceUuid}&agent=codex&view=diff`,
      '#latest',
    )
    localStorage.setItem('token', 'source-token')

    setActivePinia(createPinia())
    const store = useUserStore()
    store.setToken('source-token')
    store.user = makeUser()

    localStorage.setItem('token', 'candidate-token')
    fireStorageEvent('candidate-token')

    expect(getAuthSessionBootstrapToken()).toBe('candidate-token')
    await expect(
      Promise.resolve().then(() => runRequestInterceptor({ headers: {} })),
    ).rejects.toMatchObject({ code: 'AUTH_SESSION_PENDING' })
    expect(authMocks.getMeWithToken).not.toHaveBeenCalled()
    expect(replace).toHaveBeenCalledWith('/code/apps')
  })

  it('keeps storage alignment fail-closed when controlled navigation throws', async () => {
    const { location, fireStorageEvent, replace } = installBrowserGlobals()
    const sourceUser = makeUser({ display_name: 'Source session' })
    replace.mockImplementation(() => {
      throw Object.assign(new Error('navigation blocked'), { name: 'SecurityError' })
    })

    setActivePinia(createPinia())
    const store = useUserStore()
    store.setToken('source-token')
    store.user = sourceUser
    localStorage.setItem('ai-builder-tabs-v1', 'source-tabs')
    const sourceRevision = getAuthSessionState().revision

    localStorage.setItem('token', 'candidate-token')
    expect(() => fireStorageEvent('candidate-token')).not.toThrow()

    expect(getAuthSessionState().revision).toBe(sourceRevision + 1)
    expect(getAuthSessionBootstrapToken()).toBe('candidate-token')
    expect(store.token).toBe('source-token')
    expect(store.user).toEqual(sourceUser)
    expect(localStorage.getItem('token')).toBe('candidate-token')
    expect(localStorage.getItem('ai-builder-tabs-v1')).toBe('source-tabs')
    expect(location.href).toBe('')
    expect(replace).toHaveBeenCalledWith('/')
  })

  it('fails closed for normal requests while storage alignment is pending', async () => {
    const { fireStorageEvent } = installBrowserGlobals()
    const pendingCandidate = deferred<User>()
    localStorage.setItem('token', 'source-token')
    authMocks.getMeWithToken.mockReturnValue(pendingCandidate.promise)

    setActivePinia(createPinia())
    const store = useUserStore()
    store.setToken('source-token')
    store.user = makeUser()

    localStorage.setItem('token', 'candidate-token')
    fireStorageEvent('candidate-token')

    await expect(
      Promise.resolve().then(() => runRequestInterceptor({ headers: {} })),
    ).rejects.toMatchObject({ code: 'AUTH_SESSION_PENDING' })
  })

  it('keeps normal requests fail-closed after storage alignment fails', async () => {
    const { fireStorageEvent } = installBrowserGlobals()
    localStorage.setItem('token', 'source-token')
    authMocks.getMeWithToken.mockRejectedValue(new Error('candidate request failed'))

    setActivePinia(createPinia())
    const store = useUserStore()
    store.setToken('source-token')
    store.user = makeUser()

    localStorage.setItem('token', 'candidate-token')
    fireStorageEvent('candidate-token')
    await flushPromises()

    await expect(
      Promise.resolve().then(() => runRequestInterceptor({ headers: {} })),
    ).rejects.toMatchObject({ code: 'AUTH_SESSION_PENDING' })
  })

  it('fails closed for native fetch and SSE while storage alignment is pending', async () => {
    const { fireStorageEvent } = installBrowserGlobals()
    const pendingCandidate = deferred<User>()
    const fetch = vi.fn().mockResolvedValue(completedSseResponse())
    const eventSourceUrls: string[] = []
    class FakeEventSource {
      onerror: ((event: Event) => void) | null = null
      constructor(url: string) {
        eventSourceUrls.push(url)
      }
      addEventListener() {}
      close() {}
    }
    vi.stubGlobal('fetch', fetch)
    vi.stubGlobal('EventSource', FakeEventSource)
    localStorage.setItem('token', 'source-token')
    authMocks.getMeWithToken.mockReturnValue(pendingCandidate.promise)

    setActivePinia(createPinia())
    const store = useUserStore()
    store.setToken('source-token')
    store.user = makeUser()

    localStorage.setItem('token', 'candidate-token')
    fireStorageEvent('candidate-token')

    await expect(
      aiChatApi.sendMessage(1, { message: 'hello' }, { onEvent: vi.fn() }),
    ).rejects.toMatchObject({ code: 'AUTH_SESSION_PENDING' })
    expect(() => extensionApi.openUpdateEventStream(1, {}))
      .toThrow(expect.objectContaining({ code: 'AUTH_SESSION_PENDING' }))
    expect(fetch).not.toHaveBeenCalled()
    expect(eventSourceUrls).toEqual([])
  })

  it('keeps native fetch fail-closed after storage alignment fails', async () => {
    const { fireStorageEvent } = installBrowserGlobals()
    const fetch = vi.fn().mockResolvedValue(completedSseResponse())
    vi.stubGlobal('fetch', fetch)
    localStorage.setItem('token', 'source-token')
    authMocks.getMeWithToken.mockRejectedValue(new Error('candidate failed'))

    setActivePinia(createPinia())
    const store = useUserStore()
    store.setToken('source-token')
    store.user = makeUser()

    localStorage.setItem('token', 'candidate-token')
    fireStorageEvent('candidate-token')
    await flushPromises()

    await expect(
      aiChatApi.sendMessage(1, { message: 'hello' }, { onEvent: vi.fn() }),
    ).rejects.toMatchObject({ code: 'AUTH_SESSION_PENDING' })
    expect(fetch).not.toHaveBeenCalled()
  })

  it('fails closed for native fetch before a cold-start token is verified', async () => {
    installBrowserGlobals()
    const fetch = vi.fn()
    vi.stubGlobal('fetch', fetch)
    localStorage.setItem('token', 'boot-token')

    setActivePinia(createPinia())
    useUserStore()

    await expect(
      aiChatApi.sendMessage(1, { message: 'hello' }, { onEvent: vi.fn() }),
    ).rejects.toMatchObject({ code: 'AUTH_SESSION_PENDING' })
    expect(fetch).not.toHaveBeenCalled()
  })

  it('does not clear the shared candidate token or navigate when a source request returns 401', async () => {
    const { location, replace } = installBrowserGlobals()
    localStorage.setItem('token', 'source-token')

    setActivePinia(createPinia())
    const store = useUserStore()
    store.setToken('source-token')
    store.user = makeUser()
    localStorage.setItem('token', 'candidate-token')

    const config = await runRequestInterceptor({ headers: {} })
    const error = {
      response: { status: 401, data: { detail: 'source request expired' } },
      config: { url: '/applications', ...config },
    }

    await expect(runResponseErrorInterceptor(error)).rejects.toBe(error)

    expect(config.headers?.Authorization).toBe('Bearer source-token')
    expect(localStorage.getItem('token')).toBe('candidate-token')
    expect(location.href).toBe('')
    expect(replace).not.toHaveBeenCalled()
  })

  it('uses the shared token after the reloaded page validates its bootstrap candidate', async () => {
    installBrowserGlobals()
    authMocks.getMeWithToken.mockResolvedValue(makeUser({
      tenant_id: 2,
      tenant_name: 'Target tenant',
      tenant_public_id: targetUuid,
    }))

    setActivePinia(createPinia())
    const sourceStore = useUserStore()
    sourceStore.setToken('source-token')
    sourceStore.user = makeUser()
    sourceStore.$dispose()

    localStorage.setItem('token', 'candidate-token')
    setActivePinia(createPinia())
    const reloadedStore = useUserStore()
    await reloadedStore.fetchUser()

    const config = await runRequestInterceptor({ headers: {} })

    expect(authMocks.getMeWithToken).toHaveBeenCalledWith('candidate-token')
    expect(config.headers?.Authorization).toBe('Bearer candidate-token')
  })

  it.each([
    ['builder', '/'],
    ['code', '/code/apps'],
  ])('reloads the current %s path without resolving the target tenant in the old page', async (mode, expectedDestination) => {
    const { fireStorageEvent, replace } = installBrowserGlobals(
      mode === 'code' ? '/code/apps' : '/',
    )
    localStorage.setItem('token', 'source-token')
    localStorage.setItem('apaas-app-mode-v1', mode)

    setActivePinia(createPinia())
    useUserStore()

    localStorage.setItem('token', 'candidate-token')
    fireStorageEvent('candidate-token')

    expect(authMocks.getMeWithToken).not.toHaveBeenCalled()
    expect(replace).toHaveBeenCalledWith(expectedDestination)
  })

  it('uses the initial Code pathname to select the safe Code home during pending user loading', async () => {
    const { fireStorageEvent, replace } = installBrowserGlobals('/code/projects/42')
    const pendingSourceUser = deferred<User>()
    localStorage.setItem('token', 'source-token')
    localStorage.setItem('apaas-app-mode-v1', 'builder')
    authMocks.getMe.mockReturnValue(pendingSourceUser.promise)
    authMocks.getMeWithToken.mockResolvedValue(makeUser({
      tenant_id: 2,
      tenant_name: 'Target tenant',
      tenant_public_id: targetUuid,
    }))

    setActivePinia(createPinia())
    const store = useUserStore()
    store.setToken('source-token')
    const fetchUserPromise = store.fetchUser()

    localStorage.setItem('token', 'candidate-token')
    fireStorageEvent('candidate-token')
    await flushPromises()

    expect(replace).toHaveBeenCalledWith('/code/apps')
    expect(authMocks.getMeWithToken).not.toHaveBeenCalled()

    pendingSourceUser.resolve(makeUser())
    await fetchUserPromise
  })

  it('lets the reloaded bootstrap commit a no-tenant platform session', async () => {
    const { replace } = installBrowserGlobals()
    authMocks.getMeWithToken.mockResolvedValue(makeUser({
      tenant_id: null,
      tenant_public_id: null,
      tenant_name: undefined,
      tenant_role: 'platform_admin',
      is_platform_admin: true,
    }))

    setActivePinia(createPinia())
    const sourceStore = useUserStore()
    sourceStore.setToken('source-token')
    sourceStore.$dispose()

    localStorage.setItem('token', 'platform-token')
    setActivePinia(createPinia())
    const reloadedStore = useUserStore()
    await reloadedStore.fetchUser()

    expect(reloadedStore.user).toMatchObject({
      tenant_id: null,
      tenant_public_id: null,
      is_platform_admin: true,
    })
    expect(getAuthSessionState().token).toBe('platform-token')
    expect(replace).not.toHaveBeenCalled()
  })

  it('drops an ABA bootstrap response after storage alignment revisions move A to B to A', async () => {
    const { fireStorageEvent, replace } = installBrowserGlobals()
    const slowA = deferred<User>()
    const staleUser = makeUser({ display_name: 'Stale storage response' })
    localStorage.setItem('ai-builder-tabs-v1', 'source-tabs')
    authMocks.getMeWithToken.mockReturnValue(slowA.promise)

    setActivePinia(createPinia())
    const sourceStore = useUserStore()
    sourceStore.setToken('source-token')
    sourceStore.user = makeUser()
    sourceStore.$dispose()

    localStorage.setItem('token', 'token-a')
    setActivePinia(createPinia())
    const reloadedStore = useUserStore()
    const fetchUserPromise = reloadedStore.fetchUser()
    const requestRevision = getAuthSessionState().revision

    localStorage.setItem('token', 'token-b')
    fireStorageEvent('token-b')
    localStorage.setItem('token', 'token-a')
    fireStorageEvent('token-a')
    slowA.resolve(staleUser)
    await fetchUserPromise

    expect(getAuthSessionState()).toMatchObject({
      token: 'source-token',
      revision: requestRevision + 2,
    })
    expect(getAuthSessionBootstrapToken()).toBe('token-a')
    expect(reloadedStore.user).toBeNull()
    expect(localStorage.getItem('ai-builder-tabs-v1')).toBe('source-tabs')
    expect(replace).toHaveBeenCalledTimes(2)
  })

  it('drops an old fetchUser success after local session A to B to A', async () => {
    installBrowserGlobals()
    const slowSourceUser = deferred<User>()
    const freshUser = makeUser({ display_name: 'Fresh session A' })
    const staleUser = makeUser({ display_name: 'Stale session A' })
    authMocks.getMe.mockReturnValue(slowSourceUser.promise)

    setActivePinia(createPinia())
    const store = useUserStore()
    store.setToken('token-a')

    const fetchUserPromise = store.fetchUser()
    store.setToken('token-b')
    store.user = makeUser({ display_name: 'Session B' })
    store.setToken('token-a')
    store.user = freshUser
    slowSourceUser.resolve(staleUser)
    await fetchUserPromise

    expect(store.user).toEqual(freshUser)
  })

  it('silently drops a split-state fetchUser 401 instead of exposing it to the router', async () => {
    const { fireStorageEvent, location, replace } = installBrowserGlobals()
    const slowSourceUser = deferred<User>()
    const pendingCandidate = deferred<User>()
    localStorage.setItem('token', 'source-token')
    authMocks.getMe.mockReturnValue(slowSourceUser.promise)
    authMocks.getMeWithToken.mockReturnValue(pendingCandidate.promise)

    setActivePinia(createPinia())
    const store = useUserStore()
    store.setToken('source-token')
    store.user = makeUser()

    const fetchUserPromise = store.fetchUser()
    localStorage.setItem('token', 'candidate-token')
    fireStorageEvent('candidate-token')
    slowSourceUser.reject({
      response: { status: 401, data: { detail: 'source token expired' } },
    })

    await expect(fetchUserPromise).resolves.toBeUndefined()
    expect(localStorage.getItem('token')).toBe('candidate-token')
    expect(location.href).toBe('')
    expect(getAuthSessionBootstrapToken()).toBe('candidate-token')
    expect(replace).toHaveBeenCalledWith('/')
  })

  it('clears the committed session and user memory before requests after an authoritative 401', async () => {
    const { location } = installBrowserGlobals()

    setActivePinia(createPinia())
    const store = useUserStore()
    store.setToken('source-token')
    store.user = makeUser()

    const sourceRequest = await runRequestInterceptor({ headers: {} })
    const error = {
      response: { status: 401, data: { detail: 'Not authenticated' } },
      config: { url: '/applications', ...sourceRequest },
    }

    await expect(runResponseErrorInterceptor(error)).rejects.toBe(error)

    const afterInvalidation = await runRequestInterceptor({ headers: {} })
    expect(afterInvalidation.headers?.Authorization).toBeUndefined()
    expect(store.token).toBeNull()
    expect(store.user).toBeNull()
    expect(localStorage.getItem('token')).toBeNull()
    expect(location.href).toContain('login?redirect=')
  })

  it('restores a verified session snapshot and validates a different shared token after reload', async () => {
    const { sessionStorage } = installBrowserGlobals()
    const pendingCandidate = deferred<User>()
    authMocks.getMeWithToken.mockReturnValue(pendingCandidate.promise)

    setActivePinia(createPinia())
    const firstStore = useUserStore()
    firstStore.setToken('source-token')
    firstStore.user = makeUser()
    firstStore.$dispose()

    localStorage.setItem('token', 'candidate-token')
    setActivePinia(createPinia())
    const rebuiltStore = useUserStore()
    await expect(
      Promise.resolve().then(() => runRequestInterceptor({ headers: {} })),
    ).rejects.toMatchObject({ code: 'AUTH_SESSION_PENDING' })
    pendingCandidate.resolve(makeUser({
      tenant_id: 2,
      tenant_name: 'Target tenant',
      tenant_public_id: targetUuid,
    }))
    await rebuiltStore.fetchUser()
    const config = await runRequestInterceptor({ headers: {} })

    expect(rebuiltStore.token).toBe('candidate-token')
    expect(config.headers?.Authorization).toBe('Bearer candidate-token')
    expect(sessionStorage.get('ai-builder-auth-session-v1')).toContain('candidate-token')
    expect(authMocks.getMeWithToken).toHaveBeenCalledWith('candidate-token')
  })

  it('removes the disposed store storage listener before a replacement store handles an event', async () => {
    const { fireStorageEvent } = installBrowserGlobals()
    const pendingCandidate = deferred<User>()
    authMocks.getMeWithToken.mockReturnValue(pendingCandidate.promise)

    setActivePinia(createPinia())
    const firstStore = useUserStore()
    firstStore.setToken('source-token')
    firstStore.$dispose()

    setActivePinia(createPinia())
    useUserStore()
    localStorage.setItem('token', 'candidate-token')
    fireStorageEvent('candidate-token')
    await flushPromises()

    expect(authMocks.getMeWithToken).not.toHaveBeenCalled()
    expect(getAuthSessionBootstrapToken()).toBe('candidate-token')
  })

  it('cannot commit a pending bootstrap response after logout advances the auth revision', async () => {
    const { replace } = installBrowserGlobals()
    const staleCandidate = deferred<User>()
    authMocks.getMeWithToken.mockReturnValue(staleCandidate.promise)

    setActivePinia(createPinia())
    const sourceStore = useUserStore()
    sourceStore.setToken('source-token')
    sourceStore.user = makeUser()
    sourceStore.$dispose()

    localStorage.setItem('token', 'candidate-token')
    setActivePinia(createPinia())
    const reloadedStore = useUserStore()
    const fetchUserPromise = reloadedStore.fetchUser()
    reloadedStore.logout()
    staleCandidate.resolve(makeUser({
      tenant_id: 2,
      tenant_name: 'Target tenant',
      tenant_public_id: targetUuid,
    }))
    await fetchUserPromise

    expect(getAuthSessionState()).toMatchObject({
      token: null,
      initialized: true,
    })
    expect(getAuthSessionBootstrapToken()).toBeNull()
    expect(reloadedStore.token).toBeNull()
    expect(reloadedStore.user).toBeNull()
    expect(localStorage.getItem('token')).toBeNull()
    expect(replace).not.toHaveBeenCalled()
  })

  it('keeps the latest tenant switch when an earlier candidate completes last', async () => {
    const { replace } = installBrowserGlobals()
    const slowB = deferred<User>()
    const userB = makeUser({ tenant_id: 2, tenant_name: 'Tenant B', tenant_public_id: targetUuid })
    const uuidC = '33333333-3333-4333-8333-333333333333'
    const userC = makeUser({ tenant_id: 3, tenant_name: 'Tenant C', tenant_public_id: uuidC })
    authMocks.switchTenant.mockImplementation((tenantId: number) => Promise.resolve({
      access_token: tenantId === 2 ? 'token-b' : 'token-c',
    }))
    authMocks.getMeWithToken.mockImplementation((candidateToken: string) => {
      if (candidateToken === 'token-b') return slowB.promise
      if (candidateToken === 'token-c') return Promise.resolve(userC)
      throw new Error(`unexpected token ${candidateToken}`)
    })

    setActivePinia(createPinia())
    const store = useUserStore()
    store.setToken('source-token')
    store.user = makeUser()

    const switchB = store.switchTenantContext(2, targetUuid, '/?tenantId=tenant-b')
    await flushPromises()
    await expect(store.switchTenantContext(3, uuidC, '/?tenantId=tenant-c'))
      .resolves.toBe('committed_reload')
    slowB.resolve(userB)
    await expect(switchB).resolves.toBe('stale_cancelled')

    expect(store.token).toBe('token-c')
    expect(store.user).toEqual(userC)
    expect(replace).toHaveBeenCalledTimes(1)
    expect(replace).toHaveBeenCalledWith('/?tenantId=tenant-c')
  })

  it('cancels an in-flight local switch before reloading for a cross-tab token', async () => {
    const { fireStorageEvent, replace } = installBrowserGlobals()
    const slowB = deferred<User>()
    const userB = makeUser({
      tenant_id: 2,
      tenant_name: 'Tenant B',
      tenant_public_id: targetUuid,
    })
    const uuidC = '33333333-3333-4333-8333-333333333333'
    authMocks.switchTenant.mockResolvedValue({ access_token: 'token-b' })
    authMocks.getMeWithToken.mockImplementation((candidateToken: string) => {
      if (candidateToken === 'token-b') return slowB.promise
      throw new Error(`unexpected token ${candidateToken}`)
    })

    setActivePinia(createPinia())
    const store = useUserStore()
    store.setToken('source-token')
    store.user = makeUser()
    const setItem = vi.spyOn(localStorage, 'setItem')

    const switchB = store.switchTenantContext(
      2,
      targetUuid,
      '/?tenantId=tenant-b',
    )
    await flushPromises()

    localStorage.setItem('token', 'token-c')
    fireStorageEvent('token-c')
    expect(getAuthSessionBootstrapToken()).toBe('token-c')
    expect(replace).toHaveBeenCalledWith('/')

    slowB.resolve(userB)
    await expect(switchB).resolves.toBe('stale_cancelled')
    expect(setItem).not.toHaveBeenCalledWith('token', 'token-b')
    expect(localStorage.getItem('token')).toBe('token-c')
    expect(store.token).toBe('source-token')
    expect(store.user?.tenant_public_id).toBe(sourceUuid)
    expect(replace).toHaveBeenCalledTimes(1)
  })

  it('drops a tenant switch when its source auth revision changes', async () => {
    const { replace } = installBrowserGlobals()
    const slowCandidate = deferred<User>()
    authMocks.switchTenant.mockResolvedValue({ access_token: 'candidate-token' })
    authMocks.getMeWithToken.mockReturnValue(slowCandidate.promise)

    setActivePinia(createPinia())
    const store = useUserStore()
    store.setToken('source-token')
    store.user = makeUser()

    const switchPromise = store.switchTenantContext(2, targetUuid, '/?tenantId=target')
    await flushPromises()
    store.setToken('new-source-token')
    const freshUser = makeUser({ display_name: 'Fresh source session' })
    store.user = freshUser
    slowCandidate.resolve(makeUser({
      tenant_id: 2,
      tenant_name: 'Target tenant',
      tenant_public_id: targetUuid,
    }))
    await expect(switchPromise).resolves.toBe('stale_cancelled')

    expect(store.token).toBe('new-source-token')
    expect(store.user).toEqual(freshUser)
    expect(replace).not.toHaveBeenCalled()
  })
})
