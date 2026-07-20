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

function installBrowserGlobals() {
  const storage = new Map<string, string>()
  const replace = vi.fn()
  const storageListeners = new Set<(event: { key: string | null; newValue: string | null }) => void>()

  vi.stubGlobal('localStorage', {
    getItem: (key: string) => storage.get(key) ?? null,
    setItem: (key: string, value: string) => storage.set(key, value),
    removeItem: (key: string) => storage.delete(key),
  })
  vi.stubGlobal('window', {
    location: { replace },
    addEventListener: (type: string, listener: (event: { key: string | null; newValue: string | null }) => void) => {
      if (type === 'storage') storageListeners.add(listener)
    },
    removeEventListener: (type: string, listener: (event: { key: string | null; newValue: string | null }) => void) => {
      if (type === 'storage') storageListeners.delete(listener)
    },
  })

  return {
    replace,
    fireStorageEvent: (token: string | null) => {
      for (const listener of storageListeners) {
        listener({ key: 'token', newValue: token })
      }
    },
  }
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
    expect(replace).toHaveBeenCalledWith('/ai-builder/')
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
    expect(replace).toHaveBeenCalledWith('/ai-builder/')
  })
})
