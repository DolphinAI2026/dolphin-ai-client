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
  default: { get: vi.fn() },
  getAuthSessionState: () => routerGuardState.session,
}))
vi.mock('@/composables/useOnboardingState', () => ({
  fetchOnboardingState: vi.fn(),
  isOnboardingConfirmed: vi.fn(),
  markOnboardingConfirmed: vi.fn(),
}))

import router from './index'

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
