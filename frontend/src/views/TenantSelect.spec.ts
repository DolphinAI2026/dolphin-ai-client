// @vitest-environment happy-dom
import { createApp, nextTick } from 'vue'
import { afterEach, describe, expect, it, vi } from 'vitest'

const harness = vi.hoisted(() => ({
  replace: vi.fn(),
  push: vi.fn(),
  selectTenant: vi.fn(),
  success: vi.fn(),
  error: vi.fn(),
  route: {
    query: {
      token: 'selection-token',
      redirect: '/code/apps?tenantId=22222222-2222-4222-8222-222222222222',
      tenants: JSON.stringify([
        {
          tenant_id: 2,
          tenant_public_id: '22222222-2222-4222-8222-222222222222',
          tenant_name: 'Target',
          tenant_code: 'target',
        },
        {
          tenant_id: 3,
          tenant_public_id: '33333333-3333-4333-8333-333333333333',
          tenant_name: 'Other',
          tenant_code: 'other',
        },
      ]),
    },
  },
}))

const targetUuid = '22222222-2222-4222-8222-222222222222'

vi.mock('vue-router', async importOriginal => ({
  ...await importOriginal<typeof import('vue-router')>(),
  useRoute: () => harness.route,
  useRouter: () => ({
    replace: harness.replace,
    push: harness.push,
  }),
}))

vi.mock('@/stores/user', () => ({
  useUserStore: () => ({
    selectTenant: harness.selectTenant,
  }),
}))

vi.mock('element-plus', () => ({
  ElMessage: {
    success: harness.success,
    error: harness.error,
  },
}))

vi.mock('@element-plus/icons-vue', () => ({
  ArrowRight: { template: '<span />' },
}))

import TenantSelect from './TenantSelect.vue'

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
  await nextTick()
}

function selectionCommit(onRollback?: () => void) {
  return {
    rollback: vi.fn(() => {
      onRollback?.()
      return true
    }),
    finalize: vi.fn(),
  }
}

function mountTenantSelect() {
  const container = document.createElement('div')
  document.body.appendChild(container)
  const app = createApp(TenantSelect)
  app.component('el-icon', { template: '<span><slot /></span>' })
  app.component('el-button', {
    inheritAttrs: false,
    template: '<button v-bind="$attrs"><slot /></button>',
  })
  app.mount(container)
  return { app, container }
}

async function createAbortedNavigationFailure() {
  const {
    createMemoryHistory,
    createRouter,
    isNavigationFailure,
  } = await vi.importActual<typeof import('vue-router')>('vue-router')
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/tenant-select', component: { template: '<div />' } },
      {
        path: '/target',
        component: { template: '<div />' },
        beforeEnter: () => false,
      },
    ],
  })
  await router.push('/tenant-select')
  const failure = await router.replace('/target')
  expect(isNavigationFailure(failure)).toBe(true)
  return failure
}

describe('TenantSelect pending selection', () => {
  afterEach(() => {
    vi.clearAllMocks()
    document.body.innerHTML = ''
  })

  it('keeps every card disabled until automatic selection navigation settles', async () => {
    const navigation = deferred<void>()
    const commit = selectionCommit()
    harness.selectTenant.mockResolvedValue(commit)
    harness.replace.mockReturnValue(navigation.promise)
    const { app, container } = mountTenantSelect()

    await flushPromises()

    const cards = Array.from(
      container.querySelectorAll<HTMLButtonElement>('button.tenant-card'),
    )
    expect(harness.selectTenant).toHaveBeenCalledTimes(1)
    expect(harness.selectTenant).toHaveBeenCalledWith(
      'selection-token',
      2,
      targetUuid,
      expect.any(AbortSignal),
    )
    expect(harness.replace).toHaveBeenCalledTimes(1)
    expect(cards).toHaveLength(2)
    expect(cards.every(card => card.disabled)).toBe(true)

    cards[1].click()
    await flushPromises()

    expect(harness.selectTenant).toHaveBeenCalledTimes(1)

    navigation.resolve()
    await flushPromises()

    expect(cards.every(card => card.disabled)).toBe(false)
    expect(commit.finalize).toHaveBeenCalledTimes(1)
    app.unmount()
  })

  it('disables and fail-closes return-to-login while selection is pending', async () => {
    const selection = deferred<ReturnType<typeof selectionCommit>>()
    harness.selectTenant.mockReturnValue(selection.promise)
    const { app, container } = mountTenantSelect()

    await flushPromises()

    const logout = container.querySelector<HTMLButtonElement>('.select-footer button')
    expect(logout?.disabled).toBe(true)
    logout?.click()
    await flushPromises()

    expect(harness.push).not.toHaveBeenCalled()
    selection.resolve(selectionCommit())
    await flushPromises()
    app.unmount()
  })

  it('aborts an unmounted selection and rolls back any late commit handle', async () => {
    const selection = deferred<ReturnType<typeof selectionCommit>>()
    const commit = selectionCommit()
    let signal: AbortSignal | undefined
    harness.selectTenant.mockImplementation((
      _selectionToken: string,
      _tenantId: number,
      _tenantPublicId: string,
      candidateSignal: AbortSignal,
    ) => {
      signal = candidateSignal
      return selection.promise
    })
    const { app } = mountTenantSelect()

    await flushPromises()
    app.unmount()

    expect(signal?.aborted).toBe(true)
    selection.resolve(commit)
    await flushPromises()

    expect(commit.rollback).toHaveBeenCalledTimes(1)
    expect(harness.replace).not.toHaveBeenCalled()
    expect(harness.success).not.toHaveBeenCalled()
  })

  it('rolls back a committed candidate when replace resolves a navigation failure', async () => {
    let session = 'candidate'
    const commit = selectionCommit(() => {
      session = 'source'
    })
    harness.selectTenant.mockResolvedValue(commit)
    harness.replace.mockResolvedValue(await createAbortedNavigationFailure())
    const { app } = mountTenantSelect()

    await flushPromises()
    await flushPromises()

    expect(commit.rollback).toHaveBeenCalledTimes(1)
    expect(commit.finalize).not.toHaveBeenCalled()
    expect(session).toBe('source')
    expect(harness.success).not.toHaveBeenCalled()
    app.unmount()
  })
})
