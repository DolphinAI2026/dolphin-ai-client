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

vi.mock('vue-router', () => ({
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

describe('TenantSelect pending selection', () => {
  afterEach(() => {
    vi.clearAllMocks()
    document.body.innerHTML = ''
  })

  it('keeps every card disabled until automatic selection navigation settles', async () => {
    const navigation = deferred<void>()
    harness.selectTenant.mockResolvedValue(undefined)
    harness.replace.mockReturnValue(navigation.promise)
    const container = document.createElement('div')
    document.body.appendChild(container)
    const app = createApp(TenantSelect)
    app.component('el-icon', { template: '<span><slot /></span>' })
    app.component('el-button', { template: '<button><slot /></button>' })
    app.mount(container)

    await flushPromises()

    const cards = Array.from(
      container.querySelectorAll<HTMLButtonElement>('button.tenant-card'),
    )
    expect(harness.selectTenant).toHaveBeenCalledTimes(1)
    expect(harness.selectTenant).toHaveBeenCalledWith(
      'selection-token',
      2,
      targetUuid,
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
    app.unmount()
  })
})
