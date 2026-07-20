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
import request from '@/utils/request'

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
  const promise = new Promise<T>((resolvePromise) => {
    resolve = resolvePromise
  })

  return { promise, resolve }
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

    expect(authMocks.switchTenant).toHaveBeenCalledWith(2)
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
    store.user = makeUser()

    localStorage.setItem('token', 'candidate-token')
    fireStorageEvent('candidate-token')
    await flushPromises()

    const config = await runRequestInterceptor({ headers: {} })

    expect(config.headers?.Authorization).toBe('Bearer source-token')
  })

  it('does not clear the shared candidate token or navigate when a source request returns 401', async () => {
    const { location, replace } = installBrowserGlobals()
    localStorage.setItem('token', 'source-token')

    setActivePinia(createPinia())
    const store = useUserStore()
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
})
