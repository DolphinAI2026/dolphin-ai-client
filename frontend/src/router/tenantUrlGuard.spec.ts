import { afterEach, describe, expect, it, vi } from 'vitest'
import {
  classifyTenantTarget,
  normalizeTenantPublicId,
  resolveTenantUrl,
} from './tenantUrlGuard'

const routerHarness = vi.hoisted(() => ({
  routes: [] as Array<{ path: string; meta: Record<string, unknown> }>,
  guard: null as null | ((to: any, from: any, next: (target?: unknown) => void) => Promise<void>),
}))

const routerGuardState = vi.hoisted(() => ({
  session: { initialized: false, token: null as string | null },
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
const unknownUuid = '33333333-3333-4333-8333-333333333333'

const availableTenants = [
  { tenant_id: 1, tenant_public_id: currentUuid },
  { tenant_id: 2, tenant_public_id: targetUuid },
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
  it('resolves a required tenant URL before evaluating tenant-admin permission', async () => {
    const setMode = vi.fn()
    routerGuardState.session = { initialized: true, token: 'committed-token' }
    routerGuardState.userStore = {
      user: { tenant_public_id: currentUuid },
      token: 'committed-token',
      tenantId: 1,
      isTenantAdmin: false,
      isPlatformAdmin: false,
      availableTenants,
      fetchAvailableTenants: vi.fn(),
      switchTenantContext: vi.fn(),
    }
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
    const userStore = {
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
      }),
    }
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
})

function createRedirectRouter() {
  installSessionStorage()
  vi.stubGlobal('__DESKTOP__', false)
  const switchTenantContext = vi.fn().mockResolvedValue(undefined)
  routerGuardState.session = { initialized: true, token: 'committed-token' }
  routerGuardState.userStore = {
    user: { tenant_public_id: currentUuid },
    token: 'committed-token',
    tenantId: 1,
    isTenantAdmin: true,
    isPlatformAdmin: false,
    availableTenants,
    fetchUser: vi.fn(),
    fetchAvailableTenants: vi.fn(),
    switchTenantContext,
  }
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
  return { memoryRouter, switchTenantContext }
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

function makeUserStore(overrides: Record<string, unknown> = {}) {
  return {
    user: { tenant_public_id: currentUuid },
    availableTenants,
    fetchAvailableTenants: vi.fn().mockResolvedValue(availableTenants),
    switchTenantContext: vi.fn().mockResolvedValue(undefined),
    ...overrides,
  }
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
    expect(userStore.switchTenantContext).toHaveBeenCalledWith(2, targetUuid, targetFullPath)
    expect(JSON.parse(storage.get('tenant-url-switch') || '')).toEqual({
      targetTenantPublicId: targetUuid,
      targetFullPath,
      startedAt: 1_000,
      attempt: 1,
    })
  })

  it('shares the in-flight switch for repeated navigation to the same full path', async () => {
    const storage = installSessionStorage()
    let completeSwitch: (() => void) | undefined
    const userStore = makeUserStore({
      switchTenantContext: vi.fn(() => new Promise<void>((resolve) => {
        completeSwitch = resolve
      })),
    })
    const route = makeRoute({
      fullPath: `/apps?tenantId=${targetUuid}`,
      query: { tenantId: targetUuid },
    })

    const first = resolveTenantUrl(route, userStore, builderModeStore)
    const second = resolveTenantUrl(route, userStore, builderModeStore)

    expect(userStore.switchTenantContext).toHaveBeenCalledTimes(1)
    completeSwitch?.()

    await expect(first).resolves.toBe(false)
    await expect(second).resolves.toBe(false)
    expect(storage.get('tenant-url-switch')).toBeTruthy()
  })

  it('shares the in-flight switch for the same tenant on a different path', async () => {
    installSessionStorage()
    let completeSwitch: (() => void) | undefined
    const userStore = makeUserStore({
      switchTenantContext: vi.fn(() => new Promise<void>((resolve) => {
        completeSwitch = resolve
      })),
    })
    const first = resolveTenantUrl(makeRoute({
      fullPath: `/apps?tenantId=${targetUuid}&view=one`,
      query: { tenantId: targetUuid, view: 'one' },
    }), userStore, builderModeStore)
    const second = resolveTenantUrl(makeRoute({
      fullPath: `/apps?tenantId=${targetUuid}&view=two`,
      query: { tenantId: targetUuid, view: 'two' },
    }), userStore, builderModeStore)

    expect(userStore.switchTenantContext).toHaveBeenCalledTimes(1)
    completeSwitch?.()

    await expect(first).resolves.toBe(false)
    await expect(second).resolves.toBe(false)
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
