import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const routerHarness = vi.hoisted(() => ({
  guard: null as null | ((to: any, from: any, next: (target?: unknown) => void) => Promise<void>),
}))
const userStore = vi.hoisted(() => ({
  token: null as string | null,
  user: null as unknown,
  fetchUser: vi.fn(),
  isTenantAdmin: true,
  isPlatformAdmin: false,
  tenantId: 1 as number | null,
}))
const modeStore = vi.hoisted(() => ({
  mode: 'builder',
  setMode: vi.fn(),
}))
const tenantUrlMocks = vi.hoisted(() => ({
  resolveTenantUrl: vi.fn().mockResolvedValue(true),
}))

vi.mock('vue-router', () => ({
  createWebHistory: vi.fn(),
  createRouter: () => ({
    beforeEach: (guard: typeof routerHarness.guard) => {
      routerHarness.guard = guard
    },
    afterEach: vi.fn(),
    onError: vi.fn(),
  }),
}))

vi.mock('@/stores/user', () => ({
  useUserStore: () => userStore,
}))

vi.mock('@/stores/preview', () => ({
  usePreviewStore: () => ({ connected: false }),
}))

vi.mock('@/stores/mode', () => ({
  modeForRoutePath: () => 'builder',
  useModeStore: () => modeStore,
}))

vi.mock('./tenantUrlGuard', () => ({
  normalizeTenantPublicId: vi.fn(() => null),
  resolveTenantUrl: tenantUrlMocks.resolveTenantUrl,
}))

vi.mock('@/utils/request', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/utils/request')>()
  return {
    ...actual,
    default: { get: vi.fn().mockResolvedValue(null) },
  }
})

vi.mock('@/composables/useOnboardingState', () => ({
  fetchOnboardingState: vi.fn(),
  isOnboardingConfirmed: vi.fn(() => true),
  markOnboardingConfirmed: vi.fn(),
}))

import {
  beginAuthSessionAlignment,
  beginAuthSessionBootstrap,
  commitAuthSession,
} from '@/utils/request'
import './index'

function installStorage() {
  const local = new Map<string, string>()
  const session = new Map<string, string>()
  vi.stubGlobal('localStorage', {
    getItem: (key: string) => local.get(key) ?? null,
    setItem: (key: string, value: string) => local.set(key, value),
    removeItem: (key: string) => local.delete(key),
  })
  vi.stubGlobal('sessionStorage', {
    getItem: (key: string) => session.get(key) ?? null,
    setItem: (key: string, value: string) => session.set(key, value),
    removeItem: (key: string) => session.delete(key),
  })
}

async function runGuard(to: Record<string, unknown>) {
  if (!routerHarness.guard) throw new Error('router guard was not registered')
  const next = vi.fn()
  await routerHarness.guard(to, {}, next)
  return next
}

describe('router auth session guard', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    installStorage()
    vi.stubGlobal('__DESKTOP__', false)
    userStore.token = null
    userStore.user = null
    userStore.fetchUser.mockResolvedValue(undefined)
    userStore.isTenantAdmin = true
    userStore.isPlatformAdmin = false
    userStore.tenantId = 1
    modeStore.mode = 'builder'
    tenantUrlMocks.resolveTenantUrl.mockResolvedValue(true)
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('keeps /login after a bootstrap candidate transient failure', async () => {
    beginAuthSessionBootstrap('bootstrap-token')
    userStore.token = 'bootstrap-token'

    const next = await runGuard({
      path: '/login',
      fullPath: '/login',
      query: {},
      meta: {},
    })

    expect(userStore.fetchUser).toHaveBeenCalledTimes(1)
    expect(next).toHaveBeenCalledWith()
  })

  it('redirects /login only for a committed session', async () => {
    commitAuthSession('committed-token')
    userStore.user = { id: 1 }

    const next = await runGuard({
      path: '/login',
      fullPath: '/login',
      query: { redirect: '/apps' },
      meta: {},
    })

    expect(next).toHaveBeenCalledWith('/apps')
  })

  it('keeps the standalone login page when a legacy Builder session has no aPaaS token', async () => {
    commitAuthSession('committed-token')
    userStore.user = { id: 1 }

    const next = await runGuard({
      path: '/login',
      fullPath: '/login?redirect=%2Fweb-console%2F',
      query: { redirect: '/web-console/' },
      meta: {},
    })

    expect(next).toHaveBeenCalledWith()
  })

  it('refreshes a live user before resolving the canonical tenant route', async () => {
    commitAuthSession('live-token')
    userStore.token = 'live-token'
    userStore.user = { id: 1, tenant_public_id: 'source-tenant' }

    const next = await runGuard({
      path: '/apps',
      fullPath: '/apps',
      query: {},
      meta: { requiresAuth: true, tenantContext: 'required' },
    })

    expect(userStore.fetchUser).toHaveBeenCalledTimes(1)
    expect(tenantUrlMocks.resolveTenantUrl).toHaveBeenCalledTimes(1)
    expect(next).toHaveBeenCalledWith()
  })

  it('does not resolve tenant URLs while cross-tab auth alignment is pending', async () => {
    commitAuthSession('source-token')
    beginAuthSessionAlignment('candidate-token')
    userStore.token = 'source-token'
    userStore.user = { id: 1 }

    const next = await runGuard({
      path: '/code/session-42',
      fullPath: '/code/session-42?agent=codex',
      query: { agent: 'codex' },
      meta: { requiresAuth: true, tenantContext: 'required' },
    })

    expect(tenantUrlMocks.resolveTenantUrl).not.toHaveBeenCalled()
    expect(next).toHaveBeenCalledWith(false)
  })

  it.each(['/apps', '/code/apps'])(
    'keeps a platform administrator on %s when no local tenant is present',
    async (path) => {
      commitAuthSession('platform-token')
      userStore.token = 'platform-token'
      userStore.user = { id: 1 }
      userStore.isPlatformAdmin = true
      userStore.tenantId = null

      const next = await runGuard({
        path,
        fullPath: path,
        query: {},
        meta: { requiresAuth: true, tenantContext: 'none' },
      })

      expect(next).toHaveBeenCalledWith()
    },
  )

  it('keeps a protected route blocked when reloaded alignment validation has a transient failure', async () => {
    commitAuthSession('source-token')
    beginAuthSessionAlignment('candidate-token')
    userStore.token = 'source-token'
    userStore.user = null
    userStore.fetchUser.mockResolvedValue(undefined)

    const next = await runGuard({
      path: '/code/session-42',
      fullPath: '/code/session-42?agent=codex',
      query: { agent: 'codex' },
      meta: { requiresAuth: true, tenantContext: 'required' },
    })

    expect(userStore.fetchUser).toHaveBeenCalledTimes(1)
    expect(tenantUrlMocks.resolveTenantUrl).not.toHaveBeenCalled()
    expect(next).toHaveBeenCalledWith(false)
  })

  it('sends an unresolved bootstrap candidate from a protected route to login', async () => {
    beginAuthSessionBootstrap('bootstrap-token')
    userStore.token = 'bootstrap-token'

    const next = await runGuard({
      path: '/apps',
      fullPath: '/apps',
      query: {},
      meta: { requiresAuth: true },
    })

    expect(next).toHaveBeenCalledWith({
      path: '/login',
      query: { redirect: '/apps' },
    })
  })
})
