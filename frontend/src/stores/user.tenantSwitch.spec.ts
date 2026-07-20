import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

const authMocks = vi.hoisted(() => ({
  getMe: vi.fn(),
  getMeWithToken: vi.fn(),
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
import request, { getAuthSessionState } from '@/utils/request'
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

function installBrowserGlobals(pathname = '/') {
  const storage = new Map<string, string>()
  const sessionStorage = new Map<string, string>()
  const replace = vi.fn()
  const location = {
    pathname,
    search: '',
    hash: '',
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
    localStorage.setItem('token', 'source-token')
    localStorage.setItem('ai-builder-tabs-v1', 'source-tabs')

    await store.switchTenantContext(2, targetUuid, targetPath)

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

  it('ignores a storage event whose token no longer matches localStorage', async () => {
    const { fireStorageEvent } = installBrowserGlobals()
    localStorage.setItem('token', 'token-a')

    setActivePinia(createPinia())
    useUserStore()

    fireStorageEvent('token-b')
    await flushPromises()

    expect(authMocks.getMeWithToken).not.toHaveBeenCalled()
  })

  it('drops a stale event-token response after a newer token wins', async () => {
    const { fireStorageEvent, replace } = installBrowserGlobals()
    const slowB = deferred<User>()
    const userA = makeUser({ tenant_public_id: sourceUuid })
    const userB = makeUser({ tenant_id: 2, tenant_public_id: targetUuid })
    authMocks.getMeWithToken.mockImplementation((candidateToken: string) => {
      if (candidateToken === 'token-b') return slowB.promise
      if (candidateToken === 'token-a') return Promise.resolve(userA)
      throw new Error(`unexpected candidate token: ${candidateToken}`)
    })

    setActivePinia(createPinia())
    const store = useUserStore()

    localStorage.setItem('token', 'token-b')
    fireStorageEvent('token-b')
    const signalForB = authMocks.getMeWithToken.mock.calls[0]?.[1] as AbortSignal

    localStorage.setItem('token', 'token-a')
    fireStorageEvent('token-a')
    slowB.resolve(userB)
    await flushPromises()

    expect(signalForB.aborted).toBe(true)
    expect(store.user).toEqual(userA)
    expect(replace).toHaveBeenCalledWith('/?tenantId=11111111-1111-4111-8111-111111111111')
  })

  it('keeps the current in-memory session and tabs when storage alignment fails', async () => {
    const { fireStorageEvent, replace } = installBrowserGlobals()
    const sourceUser = makeUser({ display_name: 'Source session' })
    localStorage.setItem('token', 'source-token')
    localStorage.setItem('ai-builder-tabs-v1', 'source-tabs')
    authMocks.getMeWithToken.mockRejectedValue(new Error('candidate request failed'))

    setActivePinia(createPinia())
    const store = useUserStore()
    store.user = sourceUser

    localStorage.setItem('token', 'candidate-token')
    fireStorageEvent('candidate-token')
    await flushPromises()

    expect(store.token).toBe('source-token')
    expect(store.user).toEqual(sourceUser)
    expect(localStorage.getItem('ai-builder-tabs-v1')).toBe('source-tabs')
    expect(replace).not.toHaveBeenCalled()
  })

  it('uses the source committed token for normal requests while storage alignment is pending', async () => {
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

    const config = await runRequestInterceptor({ headers: {} })

    expect(config.headers?.Authorization).toBe('Bearer source-token')
  })

  it('keeps using the source committed token for normal requests after storage alignment fails', async () => {
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

    const config = await runRequestInterceptor({ headers: {} })

    expect(config.headers?.Authorization).toBe('Bearer source-token')
  })

  it('uses the source committed token for native fetch and SSE while storage alignment is pending', async () => {
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
    await aiChatApi.sendMessage(1, { message: 'hello' }, { onEvent: vi.fn() })
    extensionApi.openUpdateEventStream(1, {})

    expect(fetch).toHaveBeenCalledWith(
      expect.stringContaining('/ai-chat/sessions/1/send'),
      expect.objectContaining({
        headers: expect.objectContaining({ Authorization: 'Bearer source-token' }),
      }),
    )
    expect(eventSourceUrls[0]).toContain('token=source-token')
    expect(eventSourceUrls[0]).not.toContain('candidate-token')
  })

  it('keeps native fetch on the source token after storage alignment fails', async () => {
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
    await aiChatApi.sendMessage(1, { message: 'hello' }, { onEvent: vi.fn() })

    expect(fetch).toHaveBeenCalledWith(
      expect.any(String),
      expect.objectContaining({
        headers: expect.objectContaining({ Authorization: 'Bearer source-token' }),
      }),
    )
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

  it('uses the aligned token for normal requests after storage alignment succeeds', async () => {
    const { fireStorageEvent } = installBrowserGlobals()
    localStorage.setItem('token', 'source-token')
    authMocks.getMeWithToken.mockResolvedValue(makeUser({
      tenant_id: 2,
      tenant_name: 'Target tenant',
      tenant_public_id: targetUuid,
    }))

    setActivePinia(createPinia())
    const store = useUserStore()
    store.setToken('source-token')
    store.user = makeUser()

    localStorage.setItem('token', 'candidate-token')
    fireStorageEvent('candidate-token')
    await flushPromises()

    const config = await runRequestInterceptor({ headers: {} })

    expect(config.headers?.Authorization).toBe('Bearer candidate-token')
  })

  it.each([
    ['builder', '/?tenantId=22222222-2222-4222-8222-222222222222'],
    ['code', '/code/apps?tenantId=22222222-2222-4222-8222-222222222222'],
  ])('aligns a tenant session to the current %s mode home', async (mode, expectedDestination) => {
    const { fireStorageEvent, replace } = installBrowserGlobals(
      mode === 'code' ? '/code/apps' : '/',
    )
    localStorage.setItem('token', 'source-token')
    localStorage.setItem('apaas-app-mode-v1', mode)
    authMocks.getMeWithToken.mockResolvedValue(makeUser({
      tenant_id: 2,
      tenant_name: 'Target tenant',
      tenant_public_id: targetUuid,
    }))

    setActivePinia(createPinia())
    useUserStore()

    localStorage.setItem('token', 'candidate-token')
    fireStorageEvent('candidate-token')
    await flushPromises()

    expect(replace).toHaveBeenCalledWith(expectedDestination)
  })

  it('uses the initial Code pathname over persisted builder mode during pending user loading', async () => {
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

    expect(replace).toHaveBeenCalledWith('/code/apps?tenantId=22222222-2222-4222-8222-222222222222')

    pendingSourceUser.resolve(makeUser())
    await fetchUserPromise
  })

  it('aligns a no-tenant platform session directly to platform admin', async () => {
    const { fireStorageEvent, replace } = installBrowserGlobals()
    localStorage.setItem('token', 'source-token')
    authMocks.getMeWithToken.mockResolvedValue(makeUser({
      tenant_id: null,
      tenant_public_id: null,
      tenant_name: undefined,
      tenant_role: 'platform_admin',
      is_platform_admin: true,
    }))

    setActivePinia(createPinia())
    useUserStore()

    localStorage.setItem('token', 'platform-token')
    fireStorageEvent('platform-token')
    await flushPromises()

    expect(replace).toHaveBeenCalledWith('/platform-admin/')
  })

  it('drops an ABA storage response after local token commits return to the same value', async () => {
    const { fireStorageEvent, replace } = installBrowserGlobals()
    const slowA = deferred<User>()
    const freshUser = makeUser({ display_name: 'Fresh local session' })
    const staleUser = makeUser({ display_name: 'Stale storage response' })
    localStorage.setItem('token', 'token-a')
    localStorage.setItem('ai-builder-tabs-v1', 'source-tabs')
    authMocks.getMeWithToken.mockImplementation((candidateToken: string) => {
      if (candidateToken === 'token-a') return slowA.promise
      throw new Error(`unexpected candidate token: ${candidateToken}`)
    })

    setActivePinia(createPinia())
    const store = useUserStore()
    store.user = makeUser({ display_name: 'Initial session' })

    fireStorageEvent('token-a')
    store.setToken('token-b')
    store.user = makeUser({ display_name: 'Intermediate local session' })
    store.setToken('token-a')
    store.user = freshUser
    slowA.resolve(staleUser)
    await flushPromises()

    expect(store.user).toEqual(freshUser)
    expect(localStorage.getItem('ai-builder-tabs-v1')).toBe('source-tabs')
    expect(replace).not.toHaveBeenCalled()
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
    expect(replace).not.toHaveBeenCalled()
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

  it('restores a verified session snapshot before aligning a different shared token after store reconstruction', async () => {
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
    await flushPromises()

    const config = await runRequestInterceptor({ headers: {} })
    expect(rebuiltStore.token).toBe('source-token')
    expect(config.headers?.Authorization).toBe('Bearer source-token')
    expect(sessionStorage.get('ai-builder-auth-session-v1')).toContain('source-token')
    expect(authMocks.getMeWithToken).toHaveBeenCalledWith('candidate-token', expect.any(AbortSignal))
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

    expect(authMocks.getMeWithToken).toHaveBeenCalledTimes(1)
  })

  it('cannot commit a storage response after its owner is disposed', async () => {
    const { fireStorageEvent, replace } = installBrowserGlobals()
    const staleCandidate = deferred<User>()
    const sourceUser = makeUser({ display_name: 'Source session' })
    authMocks.getMeWithToken.mockImplementationOnce(() => staleCandidate.promise)
    authMocks.getMeWithToken.mockRejectedValueOnce(new Error('replacement candidate failed'))

    setActivePinia(createPinia())
    const firstStore = useUserStore()
    firstStore.setToken('source-token')
    firstStore.user = sourceUser
    localStorage.setItem('token', 'candidate-token')
    fireStorageEvent('candidate-token')
    firstStore.$dispose()

    setActivePinia(createPinia())
    const replacementStore = useUserStore()
    await flushPromises()
    staleCandidate.resolve(makeUser({
      tenant_id: 2,
      tenant_name: 'Target tenant',
      tenant_public_id: targetUuid,
    }))
    await flushPromises()

    expect(replacementStore.token).toBe('source-token')
    expect(replacementStore.user).toBeNull()
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
    await store.switchTenantContext(3, uuidC, '/?tenantId=tenant-c')
    slowB.resolve(userB)
    await switchB

    expect(store.token).toBe('token-c')
    expect(store.user).toEqual(userC)
    expect(replace).toHaveBeenCalledTimes(1)
    expect(replace).toHaveBeenCalledWith('/?tenantId=tenant-c')
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
    await switchPromise

    expect(store.token).toBe('new-source-token')
    expect(store.user).toEqual(freshUser)
    expect(replace).not.toHaveBeenCalled()
  })
})
