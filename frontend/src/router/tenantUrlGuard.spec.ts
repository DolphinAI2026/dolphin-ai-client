import { afterEach, describe, expect, it, vi, type Mock } from 'vitest'
import {
  classifyTenantTarget,
  normalizeTenantPublicId,
  resolveTenantUrl,
  type TenantUrlTenant,
  type TenantUrlUserStore,
} from './tenantUrlGuard'

const routerHarness = vi.hoisted(() => ({
  routes: [] as Array<{ path: string; meta: Record<string, unknown> }>,
  guard: null as null | ((to: any, from: any, next: (target?: unknown) => void) => Promise<void>),
  afterGuard: null as null | ((to: any, from: any, failure?: unknown) => void),
}))

const routerGuardState = vi.hoisted(() => ({
  session: { initialized: false, token: null as string | null },
  alignmentPending: false,
  userStore: {} as Record<string, any>,
  modeStore: {} as Record<string, any>,
}))

const requestHarness = vi.hoisted(() => ({
  get: vi.fn(),
}))

vi.mock('vue-router', () => {
  const joinPath = (parentPath: string, childPath: string) => {
    if (childPath.startsWith('/')) return childPath
    if (!parentPath) return `/${childPath}`
    if (!childPath) return parentPath
    return `${parentPath.replace(/\/$/, '')}/${childPath}`
  }
  const flattenRoutes = (
    routes: Array<{ path: string; meta?: Record<string, unknown>; children?: unknown[] }>,
    parentPath = '',
    parentMeta: Record<string, unknown> = {},
  ): Array<{ path: string; meta: Record<string, unknown> }> => routes.flatMap((route) => {
    const path = joinPath(parentPath, route.path)
    const meta = { ...parentMeta, ...route.meta }
    return [
      { path, meta },
      ...flattenRoutes(
        (route.children || []) as Array<{ path: string; meta?: Record<string, unknown>; children?: unknown[] }>,
        path,
        meta,
      ),
    ]
  })

  return {
    createWebHistory: vi.fn(),
    createRouter: (options: { routes: Array<{ path: string; meta?: Record<string, unknown>; children?: unknown[] }> }) => {
      routerHarness.routes = flattenRoutes(options.routes)
      return {
        getRoutes: () => routerHarness.routes,
        beforeEach: (guard: typeof routerHarness.guard) => {
          routerHarness.guard = guard
        },
        afterEach: (guard: typeof routerHarness.afterGuard) => {
          routerHarness.afterGuard = guard
        },
        onError: vi.fn(),
      }
    },
  }
})

vi.mock('@/stores/user', () => ({ useUserStore: () => routerGuardState.userStore }))
vi.mock('@/stores/preview', () => ({ usePreviewStore: vi.fn() }))
vi.mock('@/stores/mode', () => ({
  modeForRoutePath: vi.fn(),
  useModeStore: () => routerGuardState.modeStore,
}))
vi.mock('@/utils/request', () => ({
  default: { get: requestHarness.get },
  getAuthSessionState: () => routerGuardState.session,
  isAuthSessionAlignmentPending: () => routerGuardState.alignmentPending,
}))
vi.mock('@/composables/useOnboardingState', () => ({
  fetchOnboardingState: vi.fn(),
  isOnboardingConfirmed: vi.fn(),
  markOnboardingConfirmed: vi.fn(),
}))

import router, { installRouterGuards, routes } from './index'

const realVueRouter = await vi.importActual<typeof import('vue-router')>('vue-router')

const currentUuid = '11111111-1111-4111-8111-111111111111'
const targetUuid = '22222222-2222-4222-8222-222222222222'
const targetCUuid = '33333333-3333-4333-8333-333333333333'
const unknownUuid = '44444444-4444-4444-8444-444444444444'

const availableTenants = [
  { tenant_id: 1, tenant_public_id: currentUuid },
  { tenant_id: 2, tenant_public_id: targetUuid },
  { tenant_id: 3, tenant_public_id: targetCUuid },
]

describe('tenant URL target classification', () => {
  it.each([
    ['missing', undefined, { kind: 'canonicalize' }],
    ['same', currentUuid, { kind: 'continue' }],
    ['accessible other', targetUuid, { kind: 'switch', tenantId: 2 }],
    ['invalid', '123', { kind: 'reject', reason: 'invalid' }],
    ['unknown', unknownUuid, { kind: 'reject', reason: 'inaccessible' }],
  ])('%s tenant target', (_name, raw, expected) => {
    expect(classifyTenantTarget({
      rawTenantId: raw,
      currentTenantPublicId: currentUuid,
      availableTenants,
    })).toMatchObject(expected)
  })

  it('normalizes a tenant UUID to lowercase', () => {
    expect(normalizeTenantPublicId(' 22222222-2222-4222-8222-222222222222 ')).toBe(targetUuid)
    expect(normalizeTenantPublicId('22222222-2222-4222-8222-222222222222'.toUpperCase())).toBe(targetUuid)
  })
})

describe('tenantContext route classification', () => {
  it('requires every authenticated route to declare tenantContext', () => {
    const missing = router.getRoutes().filter(
      route => route.meta.requiresAuth && !route.meta.tenantContext,
    )

    expect(missing.map(route => route.path)).toEqual([])
  })
})

describe('tenant URL route mount gate', () => {
  function installBootstrapState() {
    vi.stubGlobal('__DESKTOP__', false)
    const userStore = installNavigationCoordinator({
      user: null as { tenant_public_id: string } | null,
      token: 'committed-token',
      tenantId: 1,
      isTenantAdmin: true,
      isPlatformAdmin: false,
      availableTenants,
      fetchUser: vi.fn(async () => {
        userStore.user = { tenant_public_id: currentUuid }
      }),
      fetchAvailableTenants: vi.fn().mockResolvedValue(availableTenants),
      switchTenantContext: vi.fn(),
    })
    routerGuardState.session = { initialized: true, token: 'committed-token' }
    routerGuardState.userStore = userStore
    routerGuardState.modeStore = {
      mode: 'builder',
      meta: builderModeStore.meta,
      setMode: vi.fn(),
    }
    requestHarness.get.mockReset().mockResolvedValue({ connected: true })
    return userStore
  }

  async function runGuard(to: Record<string, any>) {
    if (!routerHarness.guard) throw new Error('router guard was not registered')
    const next = vi.fn()
    await routerHarness.guard(to, {}, next)
    return next
  }

  function commitNavigation(
    to: Record<string, any>,
    failure?: unknown,
  ) {
    if (!routerHarness.afterGuard) throw new Error('router afterEach was not registered')
    routerHarness.afterGuard(to, {}, failure)
  }

  it('resolves a required tenant URL before evaluating tenant-admin permission', async () => {
    const setMode = vi.fn()
    routerGuardState.session = { initialized: true, token: 'committed-token' }
    routerGuardState.userStore = installNavigationCoordinator({
      user: { tenant_public_id: currentUuid },
      token: 'committed-token',
      tenantId: 1,
      isTenantAdmin: false,
      isPlatformAdmin: false,
      availableTenants,
      fetchAvailableTenants: vi.fn(),
      switchTenantContext: vi.fn(),
    })
    routerGuardState.modeStore = {
      mode: 'builder',
      meta: builderModeStore.meta,
      setMode,
    }
    const next = vi.fn()

    if (!routerHarness.guard) throw new Error('router guard was not registered')
    await routerHarness.guard({
      path: '/admin/agent-prompts',
      fullPath: '/admin/agent-prompts?tab=policy#roles',
      query: { tab: 'policy' },
      hash: '#roles',
      meta: {
        requiresAuth: true,
        requiresTenantAdmin: true,
        tenantContext: 'required',
      },
    }, {}, next)

    expect(next).toHaveBeenCalledWith({
      path: '/admin/agent-prompts',
      query: { tab: 'policy', tenantId: currentUuid },
      hash: '#roles',
      replace: true,
    })
    expect(setMode).not.toHaveBeenCalled()
  })

  it('does not read aPaaS state before a cold-start cross-tenant resolution completes', async () => {
    const requestOrder: string[] = []
    const userStore = installNavigationCoordinator({
      user: null as { tenant_public_id: string } | null,
      token: 'committed-token',
      tenantId: 1,
      isTenantAdmin: true,
      isPlatformAdmin: false,
      availableTenants,
      fetchUser: vi.fn(async () => {
        requestOrder.push('/auth/me')
        userStore.user = { tenant_public_id: currentUuid }
      }),
      fetchAvailableTenants: vi.fn(),
      switchTenantContext: vi.fn(async () => {
        requestOrder.push('/auth/switch-tenant')
        userStore.user = { tenant_public_id: targetUuid }
        return 'committed_reload' as const
      }),
    })
    routerGuardState.session = { initialized: true, token: 'committed-token' }
    routerGuardState.userStore = userStore
    routerGuardState.modeStore = {
      mode: 'builder',
      meta: builderModeStore.meta,
      setMode: vi.fn(),
    }
    requestHarness.get.mockImplementation(async (url: string) => {
      requestOrder.push(url)
      return null
    })
    const next = vi.fn()

    if (!routerHarness.guard) throw new Error('router guard was not registered')
    await routerHarness.guard({
      path: '/apps',
      fullPath: `/apps?tenantId=${targetUuid}`,
      query: { tenantId: targetUuid },
      hash: '',
      meta: { requiresAuth: true, tenantContext: 'required' },
    }, {}, next)

    expect(requestOrder).toEqual(['/auth/me', '/auth/switch-tenant'])
    expect(requestHarness.get).not.toHaveBeenCalled()
    expect(next).toHaveBeenCalledWith(false)
  })

  it.each([
    ['rejected', {
      path: '/apps',
      fullPath: `/apps?tenantId=${unknownUuid}`,
      query: { tenantId: unknownUuid },
      hash: '',
      meta: { requiresAuth: true, tenantContext: 'required' },
    }],
    ['canonical', {
      path: '/apps',
      fullPath: '/apps?tab=latest',
      query: { tab: 'latest' },
      hash: '',
      meta: { requiresAuth: true, tenantContext: 'required' },
    }],
  ])(
    'restores preview status only after the bootstrap %s redirect commits an aligned required URL',
    async (_name, initialRoute) => {
      installBootstrapState()
      const initialNext = await runGuard(initialRoute)

      expect(initialNext).toHaveBeenCalledWith(expect.objectContaining({
        query: expect.objectContaining({ tenantId: currentUuid }),
        replace: true,
      }))
      expect(requestHarness.get).not.toHaveBeenCalled()

      commitNavigation(initialRoute)
      expect(requestHarness.get).not.toHaveBeenCalled()

      const finalRoute = {
        path: '/apps',
        fullPath: `/apps?tenantId=${currentUuid}`,
        query: { tenantId: currentUuid },
        hash: '',
        meta: { requiresAuth: true, tenantContext: 'required' },
      }
      const finalNext = await runGuard(finalRoute)
      expect(finalNext).toHaveBeenCalledWith()
      expect(requestHarness.get).not.toHaveBeenCalled()

      commitNavigation(finalRoute)
      expect(requestHarness.get).toHaveBeenCalledOnce()
      expect(requestHarness.get).toHaveBeenCalledWith('/apaas/status')
    },
  )

  it.each([
    ['a navigation failure', {
      path: '/apps',
      fullPath: `/apps?tenantId=${currentUuid}`,
      query: { tenantId: currentUuid },
      hash: '',
      meta: { requiresAuth: true, tenantContext: 'required' },
    }, new Error('cancelled')],
    ['an unauthenticated route', {
      path: '/login',
      fullPath: `/login?tenantId=${currentUuid}`,
      query: { tenantId: currentUuid },
      hash: '',
      meta: { requiresAuth: false, tenantContext: 'required' },
    }, undefined],
    ['a tenantContext none route', {
      path: '/platform-admin/audit',
      fullPath: '/platform-admin/audit',
      query: {},
      hash: '',
      meta: { requiresAuth: true, tenantContext: 'none' },
    }, undefined],
  ])('does not restore pending preview status after %s', async (
    _name,
    committedRoute,
    failure,
  ) => {
    installBootstrapState()
    const canonicalRoute = {
      path: '/apps',
      fullPath: '/apps',
      query: {},
      hash: '',
      meta: { requiresAuth: true, tenantContext: 'required' },
    }
    await runGuard(canonicalRoute)

    commitNavigation(committedRoute, failure)

    expect(requestHarness.get).not.toHaveBeenCalled()
  })

  it('retries preview status on the next aligned navigation after the first request fails', async () => {
    await new Promise((resolve) => setTimeout(resolve, 0))
    installBootstrapState()
    requestHarness.get
      .mockRejectedValueOnce(new Error('temporary failure'))
      .mockResolvedValueOnce({ connected: true })
    const route = {
      path: '/apps',
      fullPath: `/apps?tenantId=${currentUuid}`,
      query: { tenantId: currentUuid },
      hash: '',
      meta: { requiresAuth: true, tenantContext: 'required' },
    }

    await runGuard(route)
    commitNavigation(route)
    await vi.waitFor(() => expect(requestHarness.get).toHaveBeenCalledTimes(1))
    await Promise.resolve()
    await Promise.resolve()

    commitNavigation(route)
    await vi.waitFor(() => expect(requestHarness.get).toHaveBeenCalledTimes(2))

    commitNavigation(route)
    await Promise.resolve()
    expect(requestHarness.get).toHaveBeenCalledTimes(2)
  })
})

function createRedirectRouter() {
  installSessionStorage()
  vi.stubGlobal('__DESKTOP__', false)
  const userStore = installNavigationCoordinator({
    user: { tenant_public_id: currentUuid },
    token: 'committed-token',
    tenantId: 1,
    isTenantAdmin: true,
    isPlatformAdmin: false,
    availableTenants,
    fetchUser: vi.fn(),
    fetchAvailableTenants: vi.fn(),
    switchTenantContext: vi.fn(async (
      _tenantId: number,
      tenantPublicId: string,
      _destination: string,
      _navigationEpoch: number,
    ) => {
      userStore.user = { tenant_public_id: tenantPublicId }
      return 'committed_reload' as const
    }),
  })
  routerGuardState.session = { initialized: true, token: 'committed-token' }
  routerGuardState.userStore = userStore
  routerGuardState.modeStore = {
    mode: 'builder',
    meta: builderModeStore.meta,
    setMode: vi.fn(),
  }
  requestHarness.get.mockReset()

  const memoryRouter = realVueRouter.createRouter({
    history: realVueRouter.createMemoryHistory(),
    routes,
  })
  installRouterGuards(memoryRouter)
  return { memoryRouter, switchTenantContext: userStore.switchTenantContext }
}

describe('route redirect tenant context', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it.each([
    ['/skills', '/hub', { tab: 'skills' }],
    ['/settings', '/platform-envs', { tab: 'envs' }],
    ['/work/42', '/chat', { app_id: '42' }],
    ['/knowledge', '/hub', { tab: 'knowledge' }],
    ['/generate/42', '/chat', { deploy_app_id: '42' }],
    ['/code', '/code/apps', {}],
  ])('preserves tenant context through %s redirects', async (sourcePath, targetPath, redirectQuery) => {
    const { memoryRouter, switchTenantContext } = createRedirectRouter()
    const source = `${sourcePath}?tenantId=${targetUuid}&keep=1${sourcePath === '/settings' ? '&tab=envs' : ''}#deep-link`

    await memoryRouter.push(source)

    expect(switchTenantContext).toHaveBeenCalledTimes(1)
    const destination = new URL(
      switchTenantContext.mock.calls[0][2],
      'https://tenant-url-redirect.invalid',
    )
    expect(destination.pathname).toBe(targetPath)
    expect(destination.searchParams.get('tenantId')).toBe(targetUuid)
    expect(destination.searchParams.get('keep')).toBe('1')
    expect(destination.hash).toBe('#deep-link')
    for (const [key, value] of Object.entries(redirectQuery)) {
      expect(destination.searchParams.get(key)).toBe(value)
    }
  })

  it.each([
    ['encoded backslash authority', encodeURIComponent('/\\evil.example/code')],
    ['encoded scheme-relative authority', '%2F%2Fevil.example%2Fcode'],
    ['encoded dot-segment login loop', '/safe/%2e%2e/login'],
  ])('fails closed for %s in the real router', async (_name, unsafe) => {
    const { memoryRouter, switchTenantContext } = createRedirectRouter()

    await expect(memoryRouter.push(`/login?redirect=${unsafe}`)).resolves.toBeUndefined()

    expect(memoryRouter.currentRoute.value.path).toBe('/')
    expect(memoryRouter.currentRoute.value.query.tenantId).toBe(currentUuid)
    expect(switchTenantContext).not.toHaveBeenCalled()
  })
})

function installSessionStorage() {
  const values = new Map<string, string>()
  vi.stubGlobal('sessionStorage', {
    getItem: (key: string) => values.get(key) ?? null,
    setItem: (key: string, value: string) => values.set(key, value),
    removeItem: (key: string) => values.delete(key),
  })
  return values
}

type NavigationCoordinator = Pick<
  TenantUrlUserStore,
  'advanceTenantNavigationEpoch' | 'isTenantNavigationEpochCurrent'
>
type TenantUrlUserStoreHarness = Omit<
  TenantUrlUserStore,
  'fetchAvailableTenants' | 'switchTenantContext'
> & {
  fetchAvailableTenants: Mock<() => Promise<TenantUrlTenant[]>>
  switchTenantContext: Mock<TenantUrlUserStore['switchTenantContext']>
} & Record<string, any>

function installNavigationCoordinator<T extends Record<string, any>>(
  userStore: T,
): T & NavigationCoordinator {
  let epoch = 0
  Object.assign(userStore, {
    advanceTenantNavigationEpoch: vi.fn(() => ++epoch),
    isTenantNavigationEpochCurrent: vi.fn((candidate: number) => candidate === epoch),
  })
  return userStore as T & NavigationCoordinator
}

function makeUserStore(
  overrides: Record<string, unknown> = {},
): TenantUrlUserStoreHarness {
  const userStore = {
    user: { tenant_public_id: currentUuid },
    availableTenants,
    fetchAvailableTenants: vi.fn().mockResolvedValue(availableTenants),
    switchTenantContext: vi.fn(async (
      _tenantId: number,
      tenantPublicId: string,
      _destination: string,
      _navigationEpoch: number,
    ) => {
      userStore.user = { tenant_public_id: tenantPublicId }
      return 'committed_reload' as const
    }),
  }
  Object.assign(userStore, overrides)
  return installNavigationCoordinator(userStore) as TenantUrlUserStoreHarness
}

function makeRoute(overrides: Record<string, unknown> = {}) {
  return {
    path: '/apps',
    fullPath: `/apps?tenantId=${currentUuid}`,
    query: { tenantId: currentUuid },
    hash: '',
    meta: { requiresAuth: true, tenantContext: 'required' as const },
    ...overrides,
  }
}

const builderModeStore = { meta: { home: '/' } }
const codeModeStore = { meta: { home: '/code/apps' } }
type TenantSwitchOutcome = 'committed_reload' | 'stale_cancelled'

function deferred<T>() {
  let resolve: (value: T) => void = () => undefined
  let reject: (reason?: unknown) => void = () => undefined
  const promise = new Promise<T>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise
    reject = rejectPromise
  })
  return { promise, resolve, reject }
}

describe('resolveTenantUrl', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
    vi.restoreAllMocks()
  })

  it('removes tenantId from a tenantContext none route', async () => {
    installSessionStorage()
    const resolution = await resolveTenantUrl(
      makeRoute({
        path: '/platform-admin/audit',
        fullPath: `/platform-admin/audit?tenantId=${currentUuid}&tab=security#events`,
        query: { tenantId: currentUuid, tab: 'security' },
        hash: '#events',
        meta: { requiresAuth: true, tenantContext: 'none' },
      }),
      makeUserStore(),
      builderModeStore,
    )

    expect(resolution).toEqual({
      path: '/platform-admin/audit',
      query: { tab: 'security' },
      hash: '#events',
      replace: true,
    })
  })

  it('canonicalizes a missing tenantId without losing path, query, or hash', async () => {
    installSessionStorage()
    const resolution = await resolveTenantUrl(
      makeRoute({
        path: '/project/42',
        fullPath: '/project/42?tab=deploy#logs',
        query: { tab: 'deploy' },
        hash: '#logs',
      }),
      makeUserStore(),
      builderModeStore,
    )

    expect(resolution).toEqual({
      path: '/project/42',
      query: { tab: 'deploy', tenantId: currentUuid },
      hash: '#logs',
      replace: true,
    })
  })

  it('continues for the current tenant without loading tenants or switching', async () => {
    installSessionStorage()
    const userStore = makeUserStore()

    await expect(resolveTenantUrl(makeRoute(), userStore, builderModeStore)).resolves.toBe(true)
    expect(userStore.fetchAvailableTenants).not.toHaveBeenCalled()
    expect(userStore.switchTenantContext).not.toHaveBeenCalled()
  })

  it('rejects duplicate tenantId values on required routes', () => {
    expect(classifyTenantTarget({
      rawTenantId: [currentUuid, targetUuid],
      currentTenantPublicId: currentUuid,
      availableTenants,
    })).toEqual({ kind: 'reject', reason: 'invalid' })
  })

  it('removes tenantId from a none route whenever the query key is an array', async () => {
    installSessionStorage()

    await expect(resolveTenantUrl(
      makeRoute({
        path: '/platform-admin/audit',
        fullPath: `/platform-admin/audit?tenantId&tenantId=${currentUuid}`,
        query: { tenantId: [null, currentUuid] },
        meta: { requiresAuth: true, tenantContext: 'none' },
      }),
      makeUserStore(),
      builderModeStore,
    )).resolves.toEqual({
      path: '/platform-admin/audit',
      query: {},
      replace: true,
    })
  })

  it('loads the authorized tenant list and switches only to a listed target', async () => {
    const storage = installSessionStorage()
    vi.spyOn(Date, 'now').mockReturnValue(1_000)
    const userStore = makeUserStore({
      availableTenants: [],
      fetchAvailableTenants: vi.fn().mockResolvedValue(availableTenants),
    })
    const targetFullPath = `/code/apps?tenantId=${targetUuid}&tab=recent#builds`

    await expect(resolveTenantUrl(
      makeRoute({
        path: '/code/apps',
        fullPath: targetFullPath,
        query: { tenantId: targetUuid, tab: 'recent' },
        hash: '#builds',
      }),
      userStore,
      codeModeStore,
    )).resolves.toBe(false)

    expect(userStore.fetchAvailableTenants).toHaveBeenCalledTimes(1)
    expect(userStore.switchTenantContext).toHaveBeenCalledWith(
      2,
      targetUuid,
      targetFullPath,
      expect.any(Number),
    )
    expect(JSON.parse(storage.get('tenant-url-switch') || '')).toEqual({
      targetTenantPublicId: targetUuid,
      targetFullPath,
      startedAt: 1_000,
      attempt: 1,
      ownerId: expect.any(Number),
    })
  })

  it('restarts the same full path under the latest resolver epoch', async () => {
    const storage = installSessionStorage()
    const firstSwitch = deferred<TenantSwitchOutcome>()
    const latestSwitch = deferred<TenantSwitchOutcome>()
    let switchCall = 0
    const userStore = makeUserStore({
      switchTenantContext: vi.fn(() => {
        switchCall += 1
        return switchCall === 1 ? firstSwitch.promise : latestSwitch.promise
      }),
    })
    const route = makeRoute({
      fullPath: `/apps?tenantId=${targetUuid}`,
      query: { tenantId: targetUuid },
    })

    const first = resolveTenantUrl(route, userStore, builderModeStore)
    const second = resolveTenantUrl(route, userStore, builderModeStore)

    userStore.user = { tenant_public_id: targetUuid }
    latestSwitch.resolve('committed_reload')
    firstSwitch.resolve('stale_cancelled')

    await expect(second).resolves.toBe(false)
    await expect(first).resolves.toEqual({
      path: '/',
      query: { tenantId: targetUuid },
      replace: true,
    })
    expect(userStore.switchTenantContext).toHaveBeenCalledTimes(2)
    expect(storage.get('tenant-url-switch')).toBeTruthy()
  })

  it('supersedes a same-target flight when a newer full path needs a different reload destination', async () => {
    installSessionStorage()
    const firstSwitch = deferred<TenantSwitchOutcome>()
    const latestSwitch = deferred<TenantSwitchOutcome>()
    let switchCall = 0
    const userStore = makeUserStore({
      switchTenantContext: vi.fn(() => {
        switchCall += 1
        return switchCall === 1 ? firstSwitch.promise : latestSwitch.promise
      }),
    })
    const first = resolveTenantUrl(makeRoute({
      fullPath: `/apps?tenantId=${targetUuid}&view=one`,
      query: { tenantId: targetUuid, view: 'one' },
    }), userStore, builderModeStore)
    const second = resolveTenantUrl(makeRoute({
      fullPath: `/apps?tenantId=${targetUuid}&view=two`,
      query: { tenantId: targetUuid, view: 'two' },
    }), userStore, builderModeStore)

    userStore.user = { tenant_public_id: targetUuid }
    latestSwitch.resolve('committed_reload')
    firstSwitch.resolve('stale_cancelled')

    await expect(second).resolves.toBe(false)
    await expect(first).resolves.toEqual({
      path: '/',
      query: { tenantId: targetUuid },
      replace: true,
    })
    expect(userStore.switchTenantContext).toHaveBeenCalledTimes(2)
    expect(userStore.switchTenantContext.mock.calls.map((call: unknown[]) => call[2])).toEqual([
      `/apps?tenantId=${targetUuid}&view=one`,
      `/apps?tenantId=${targetUuid}&view=two`,
    ])
  })

  it('starts the latest cross-target switch instead of sharing a different target flight', async () => {
    const storage = installSessionStorage()
    const switchB = deferred<TenantSwitchOutcome>()
    const switchC = deferred<TenantSwitchOutcome>()
    const userStore = makeUserStore({
      switchTenantContext: vi.fn((tenantId: number) => (
        tenantId === 2 ? switchB.promise : switchC.promise
      )),
    })
    const builderB = resolveTenantUrl(makeRoute({
      fullPath: `/apps?tenantId=${targetUuid}`,
      query: { tenantId: targetUuid },
    }), userStore, builderModeStore)
    const codeC = resolveTenantUrl(makeRoute({
      path: '/code/apps',
      fullPath: `/code/apps?tenantId=${targetCUuid}`,
      query: { tenantId: targetCUuid },
    }), userStore, codeModeStore)

    userStore.user = { tenant_public_id: targetCUuid }
    switchC.resolve('committed_reload')
    switchB.resolve('stale_cancelled')

    await expect(codeC).resolves.toBe(false)
    await expect(builderB).resolves.toEqual({
      path: '/',
      query: { tenantId: targetCUuid },
      replace: true,
    })
    expect(userStore.switchTenantContext).toHaveBeenCalledTimes(2)
    expect(JSON.parse(storage.get('tenant-url-switch') || '')).toMatchObject({
      targetTenantPublicId: targetCUuid,
    })
  })

  it('maps a cross-target failure to each waiter mode instead of the first waiter fallback', async () => {
    installSessionStorage()
    const switchB = deferred<TenantSwitchOutcome>()
    const switchC = deferred<TenantSwitchOutcome>()
    const userStore = makeUserStore({
      switchTenantContext: vi.fn((tenantId: number) => (
        tenantId === 2 ? switchB.promise : switchC.promise
      )),
    })
    const builderB = resolveTenantUrl(makeRoute({
      fullPath: `/apps?tenantId=${targetUuid}`,
      query: { tenantId: targetUuid },
    }), userStore, builderModeStore)
    const codeC = resolveTenantUrl(makeRoute({
      path: '/code/apps',
      fullPath: `/code/apps?tenantId=${targetCUuid}`,
      query: { tenantId: targetCUuid },
    }), userStore, codeModeStore)

    switchC.reject(new Error('tenant C switch failed'))
    switchB.resolve('stale_cancelled')

    await expect(builderB).resolves.toEqual({
      path: '/',
      query: { tenantId: currentUuid },
      replace: true,
    })
    expect(userStore.switchTenantContext).toHaveBeenCalledTimes(2)
    await expect(codeC).resolves.toEqual({
      path: '/code/apps',
      query: { tenantId: currentUuid },
      replace: true,
    })
  })

  it('uses each same-target waiter mode when each latest-epoch operation fails', async () => {
    installSessionStorage()
    const builderSwitch = deferred<TenantSwitchOutcome>()
    const codeSwitch = deferred<TenantSwitchOutcome>()
    let switchCall = 0
    const userStore = makeUserStore({
      switchTenantContext: vi.fn(() => {
        switchCall += 1
        return switchCall === 1 ? builderSwitch.promise : codeSwitch.promise
      }),
    })
    const builder = resolveTenantUrl(makeRoute({
      fullPath: `/apps?tenantId=${targetUuid}`,
      query: { tenantId: targetUuid },
    }), userStore, builderModeStore)
    const code = resolveTenantUrl(makeRoute({
      fullPath: `/apps?tenantId=${targetUuid}`,
      query: { tenantId: targetUuid },
    }), userStore, codeModeStore)

    expect(userStore.switchTenantContext).toHaveBeenCalledTimes(2)
    builderSwitch.reject(new Error('builder tenant switch failed'))
    codeSwitch.reject(new Error('code tenant switch failed'))

    await expect(builder).resolves.toEqual({
      path: '/',
      query: { tenantId: currentUuid },
      replace: true,
    })
    await expect(code).resolves.toEqual({
      path: '/code/apps',
      query: { tenantId: currentUuid },
      replace: true,
    })
  })

  it('fails closed and removes its marker when Task 3 reports a stale source revision', async () => {
    const storage = installSessionStorage()
    const userStore = makeUserStore({
      switchTenantContext: vi.fn().mockResolvedValue('stale_cancelled'),
    })

    await expect(resolveTenantUrl(makeRoute({
      fullPath: `/apps?tenantId=${targetUuid}`,
      query: { tenantId: targetUuid },
    }), userStore, builderModeStore)).resolves.toEqual({
      path: '/',
      query: { tenantId: currentUuid },
      replace: true,
    })

    expect(storage.get('tenant-url-switch')).toBeUndefined()
  })

  it('fails closed to the live tenant home when a sidebar switch supersedes the resolver', async () => {
    installSessionStorage()
    const switchFlight = deferred<TenantSwitchOutcome>()
    const userStore = makeUserStore({
      switchTenantContext: vi.fn(() => switchFlight.promise),
    })
    const resolution = resolveTenantUrl(makeRoute({
      fullPath: `/apps?tenantId=${targetUuid}`,
      query: { tenantId: targetUuid },
    }), userStore, builderModeStore)

    userStore.user = { tenant_public_id: targetCUuid }
    switchFlight.resolve('stale_cancelled')

    await expect(resolution).resolves.toEqual({
      path: '/',
      query: { tenantId: targetCUuid },
      replace: true,
    })
  })

  it('cancels a slow B preflight when a current-tenant route is newer', async () => {
    installSessionStorage()
    const fetchB = deferred<typeof availableTenants>()
    const userStore = makeUserStore({
      availableTenants: [],
      fetchAvailableTenants: vi.fn(() => fetchB.promise),
    })
    const oldB = resolveTenantUrl(makeRoute({
      fullPath: `/apps?tenantId=${targetUuid}`,
      query: { tenantId: targetUuid },
    }), userStore, builderModeStore)

    await expect(resolveTenantUrl(makeRoute(), userStore, builderModeStore)).resolves.toBe(true)
    fetchB.resolve(availableTenants)

    await expect(oldB).resolves.toEqual({
      path: '/',
      query: { tenantId: currentUuid },
      replace: true,
    })
    expect(userStore.switchTenantContext).not.toHaveBeenCalled()
    expect(userStore.advanceTenantNavigationEpoch).toHaveBeenCalledTimes(2)
  })

  it('cancels a slow B preflight when a tenantContext none route is newer', async () => {
    installSessionStorage()
    const fetchB = deferred<typeof availableTenants>()
    const userStore = makeUserStore({
      availableTenants: [],
      fetchAvailableTenants: vi.fn(() => fetchB.promise),
    })
    const oldB = resolveTenantUrl(makeRoute({
      fullPath: `/apps?tenantId=${targetUuid}`,
      query: { tenantId: targetUuid },
    }), userStore, builderModeStore)

    await expect(resolveTenantUrl(makeRoute({
      path: '/platform-admin/audit',
      fullPath: `/platform-admin/audit?tenantId=${currentUuid}`,
      query: { tenantId: currentUuid },
      meta: { requiresAuth: true, tenantContext: 'none' },
    }), userStore, builderModeStore)).resolves.toEqual({
      path: '/platform-admin/audit',
      query: {},
      replace: true,
    })
    fetchB.resolve(availableTenants)

    await expect(oldB).resolves.toEqual({
      path: '/',
      query: { tenantId: currentUuid },
      replace: true,
    })
    expect(userStore.switchTenantContext).not.toHaveBeenCalled()
  })

  it.each([
    ['invalid UUID', {
      fullPath: '/apps?tenantId=123',
      query: { tenantId: '123' },
    }],
    ['missing UUID', {
      fullPath: '/apps?tab=latest',
      query: { tab: 'latest' },
    }],
  ])('cancels a slow B preflight when a newer %s route does not switch', async (_name, route) => {
    installSessionStorage()
    const fetchB = deferred<typeof availableTenants>()
    const userStore = makeUserStore({
      availableTenants: [],
      fetchAvailableTenants: vi.fn(() => fetchB.promise),
    })
    const oldB = resolveTenantUrl(makeRoute({
      fullPath: `/apps?tenantId=${targetUuid}`,
      query: { tenantId: targetUuid },
    }), userStore, builderModeStore)

    await resolveTenantUrl(makeRoute(route), userStore, builderModeStore)
    fetchB.resolve(availableTenants)

    await expect(oldB).resolves.toEqual({
      path: '/',
      query: { tenantId: currentUuid },
      replace: true,
    })
    expect(userStore.switchTenantContext).not.toHaveBeenCalled()
  })

  it('cancels a slow B preflight when sidebar C advances the shared epoch', async () => {
    installSessionStorage()
    const fetchB = deferred<typeof availableTenants>()
    const userStore = makeUserStore({
      availableTenants: [],
      fetchAvailableTenants: vi.fn(() => fetchB.promise),
    })
    const oldB = resolveTenantUrl(makeRoute({
      fullPath: `/apps?tenantId=${targetUuid}`,
      query: { tenantId: targetUuid },
    }), userStore, builderModeStore)
    const sidebarEpoch = userStore.advanceTenantNavigationEpoch()

    await expect(userStore.switchTenantContext(
      3,
      targetCUuid,
      `/?tenantId=${targetCUuid}`,
      sidebarEpoch,
    )).resolves.toBe('committed_reload')
    fetchB.resolve(availableTenants)

    await expect(oldB).resolves.toEqual({
      path: '/',
      query: { tenantId: targetCUuid },
      replace: true,
    })
    expect(userStore.switchTenantContext).toHaveBeenCalledTimes(1)
    expect(userStore.switchTenantContext).toHaveBeenCalledWith(
      3,
      targetCUuid,
      `/?tenantId=${targetCUuid}`,
      sidebarEpoch,
    )
  })

  it('cancels an active B Task 3 flight when a current-tenant route is newer', async () => {
    installSessionStorage()
    const switchB = deferred<TenantSwitchOutcome>()
    const userStore = makeUserStore({
      switchTenantContext: vi.fn(() => switchB.promise),
    })
    const oldB = resolveTenantUrl(makeRoute({
      fullPath: `/apps?tenantId=${targetUuid}`,
      query: { tenantId: targetUuid },
    }), userStore, builderModeStore)

    await expect(resolveTenantUrl(makeRoute(), userStore, builderModeStore)).resolves.toBe(true)
    switchB.resolve('stale_cancelled')

    await expect(oldB).resolves.toEqual({
      path: '/',
      query: { tenantId: currentUuid },
      replace: true,
    })
    expect(userStore.switchTenantContext).toHaveBeenCalledTimes(1)
    expect(userStore.advanceTenantNavigationEpoch).toHaveBeenCalledTimes(2)
  })

  it('does not let a slow B tenant-list recovery supersede a newer C navigation', async () => {
    installSessionStorage()
    const fetchB = deferred<typeof availableTenants>()
    const fetchC = deferred<typeof availableTenants>()
    const userStore = makeUserStore({
      availableTenants: [],
      fetchAvailableTenants: vi.fn()
        .mockImplementationOnce(() => fetchB.promise)
        .mockImplementationOnce(() => fetchC.promise),
    })
    userStore.switchTenantContext.mockImplementation(async (
      _tenantId: number,
      tenantPublicId: string,
    ) => {
      userStore.user = { tenant_public_id: tenantPublicId }
      return 'committed_reload' as const
    })
    const builderB = resolveTenantUrl(makeRoute({
      fullPath: `/apps?tenantId=${targetUuid}`,
      query: { tenantId: targetUuid },
    }), userStore, builderModeStore)
    const codeC = resolveTenantUrl(makeRoute({
      path: '/code/apps',
      fullPath: `/code/apps?tenantId=${targetCUuid}`,
      query: { tenantId: targetCUuid },
    }), userStore, codeModeStore)

    fetchC.resolve(availableTenants)
    await expect(codeC).resolves.toBe(false)
    fetchB.resolve(availableTenants)

    await expect(builderB).resolves.toEqual({
      path: '/',
      query: { tenantId: targetCUuid },
      replace: true,
    })
    expect(userStore.switchTenantContext).toHaveBeenCalledTimes(1)
    expect(userStore.switchTenantContext).toHaveBeenCalledWith(
      3,
      targetCUuid,
      `/code/apps?tenantId=${targetCUuid}`,
      expect.any(Number),
    )
  })

  it('does not let a slow C tenant-list recovery supersede a newer B navigation', async () => {
    installSessionStorage()
    const fetchC = deferred<typeof availableTenants>()
    const fetchB = deferred<typeof availableTenants>()
    const userStore = makeUserStore({
      availableTenants: [],
      fetchAvailableTenants: vi.fn()
        .mockImplementationOnce(() => fetchC.promise)
        .mockImplementationOnce(() => fetchB.promise),
    })
    userStore.switchTenantContext.mockImplementation(async (
      _tenantId: number,
      tenantPublicId: string,
    ) => {
      userStore.user = { tenant_public_id: tenantPublicId }
      return 'committed_reload' as const
    })
    const codeC = resolveTenantUrl(makeRoute({
      path: '/code/apps',
      fullPath: `/code/apps?tenantId=${targetCUuid}`,
      query: { tenantId: targetCUuid },
    }), userStore, codeModeStore)
    const builderB = resolveTenantUrl(makeRoute({
      fullPath: `/apps?tenantId=${targetUuid}`,
      query: { tenantId: targetUuid },
    }), userStore, builderModeStore)

    fetchB.resolve(availableTenants)
    await expect(builderB).resolves.toBe(false)
    fetchC.resolve(availableTenants)

    await expect(codeC).resolves.toEqual({
      path: '/code/apps',
      query: { tenantId: targetUuid },
      replace: true,
    })
    expect(userStore.switchTenantContext).toHaveBeenCalledTimes(1)
    expect(userStore.switchTenantContext).toHaveBeenCalledWith(
      2,
      targetUuid,
      `/apps?tenantId=${targetUuid}`,
      expect.any(Number),
    )
  })

  it('keeps the newest same-millisecond B marker when B-C-B flights settle out of order', async () => {
    const storage = installSessionStorage()
    vi.spyOn(Date, 'now').mockReturnValue(1_000)
    const firstB = deferred<TenantSwitchOutcome>()
    const middleC = deferred<TenantSwitchOutcome>()
    const latestB = deferred<TenantSwitchOutcome>()
    const userStore = makeUserStore({
      switchTenantContext: vi.fn()
        .mockImplementationOnce(() => firstB.promise)
        .mockImplementationOnce(() => middleC.promise)
        .mockImplementationOnce(() => latestB.promise),
    })
    const oldB = resolveTenantUrl(makeRoute({
      fullPath: `/apps?tenantId=${targetUuid}`,
      query: { tenantId: targetUuid },
    }), userStore, builderModeStore)
    const middle = resolveTenantUrl(makeRoute({
      path: '/code/apps',
      fullPath: `/code/apps?tenantId=${targetCUuid}`,
      query: { tenantId: targetCUuid },
    }), userStore, codeModeStore)
    const newestB = resolveTenantUrl(makeRoute({
      fullPath: `/apps?tenantId=${targetUuid}`,
      query: { tenantId: targetUuid },
    }), userStore, builderModeStore)
    const newestMarker = JSON.parse(storage.get('tenant-url-switch') || '')

    firstB.resolve('stale_cancelled')
    await expect(oldB).resolves.toEqual({
      path: '/',
      query: { tenantId: currentUuid },
      replace: true,
    })
    expect(JSON.parse(storage.get('tenant-url-switch') || '')).toMatchObject({
      targetTenantPublicId: targetUuid,
      ownerId: newestMarker.ownerId,
    })

    middleC.resolve('stale_cancelled')
    userStore.user = { tenant_public_id: targetUuid }
    latestB.resolve('committed_reload')
    await expect(middle).resolves.toEqual({
      path: '/code/apps',
      query: { tenantId: targetUuid },
      replace: true,
    })
    await expect(newestB).resolves.toBe(false)
  })

  it.each([
    ['invalid', '123'],
    ['inaccessible', unknownUuid],
  ])('fails closed for an %s tenant target', async (_name, tenantId) => {
    installSessionStorage()
    const userStore = makeUserStore()

    await expect(resolveTenantUrl(
      makeRoute({
        fullPath: `/apps?tenantId=${tenantId}`,
        query: { tenantId },
      }),
      userStore,
      builderModeStore,
    )).resolves.toEqual({
      path: '/',
      query: { tenantId: currentUuid },
      replace: true,
    })
    expect(userStore.switchTenantContext).not.toHaveBeenCalled()
  })

  it('returns a tenantless platform administrator to platform admin', async () => {
    installSessionStorage()

    await expect(resolveTenantUrl(
      makeRoute({
        fullPath: '/apps',
        query: {},
      }),
      makeUserStore({
        user: { tenant_public_id: null },
        isPlatformAdmin: true,
      }),
      builderModeStore,
    )).resolves.toEqual({
      path: '/platform-admin',
      replace: true,
    })
  })

  it('stops a repeated tenant switch within the 30 second marker window', async () => {
    const storage = installSessionStorage()
    vi.spyOn(Date, 'now').mockReturnValue(10_000)
    const targetFullPath = `/apps?tenantId=${targetUuid}`
    storage.set('tenant-url-switch', JSON.stringify({
      targetTenantPublicId: targetUuid,
      targetFullPath,
      startedAt: 5_000,
      attempt: 1,
      ownerId: 1,
    }))
    const userStore = makeUserStore()

    await expect(resolveTenantUrl(
      makeRoute({
        fullPath: targetFullPath,
        query: { tenantId: targetUuid },
      }),
      userStore,
      builderModeStore,
    )).resolves.toEqual({
      path: '/',
      query: { tenantId: currentUuid },
      replace: true,
    })
    expect(userStore.switchTenantContext).not.toHaveBeenCalled()
    expect(sessionStorage.getItem('tenant-url-switch')).toBeNull()
  })
})
