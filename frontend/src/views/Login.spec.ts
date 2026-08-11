// @vitest-environment happy-dom
import { createApp, defineComponent, h, nextTick } from 'vue'
import { afterEach, describe, expect, it, vi } from 'vitest'
import loginSource from './Login.vue?raw'
import tenantSelectSource from './TenantSelect.vue?raw'
import userStoreSource from '@/stores/user.ts?raw'
import {
  resolveLoginTenant,
  safeLoginRedirectPath,
  tenantIdFromRedirect,
} from '@/router/loginRedirect'

const loginHarness = vi.hoisted(() => ({
  createWebConsoleSession: vi.fn(),
  error: vi.fn(),
  getCaptcha: vi.fn(),
  login: vi.fn(),
  logout: vi.fn(),
  push: vi.fn(),
  routeQuery: {} as Record<string, unknown>,
  replace: vi.fn(),
  token: null as string | null,
  toggleTheme: vi.fn(),
}))

vi.mock('vue-router', async importOriginal => ({
  ...await importOriginal<typeof import('vue-router')>(),
  useRoute: () => ({ query: loginHarness.routeQuery }),
  useRouter: () => ({
    push: loginHarness.push,
    replace: loginHarness.replace,
    resolve: (path: string) => ({ path }),
  }),
}))

vi.mock('@/api/auth', () => ({
  authApi: {
    createWebConsoleSession: loginHarness.createWebConsoleSession,
    getCaptcha: loginHarness.getCaptcha,
  },
}))

vi.mock('@/stores/user', () => ({
  useUserStore: () => ({
    login: loginHarness.login,
    logout: loginHarness.logout,
    token: loginHarness.token,
  }),
}))

vi.mock('@/stores/theme', () => ({
  useThemeStore: () => ({ isDark: false, toggle: loginHarness.toggleTheme }),
}))

vi.mock('@/stores/productAvailability', () => ({
  defaultProductHome: () => '/code/apps',
  loadProductAvailability: vi.fn(),
  productForRoute: vi.fn(),
  redirectForDisabledProduct: vi.fn(),
}))

vi.mock('@/utils/desktop', () => ({
  enterDesktopLoginSetup: vi.fn(),
  getDesktopState: vi.fn(),
  isDesktop: false,
}))

vi.mock('element-plus', () => ({
  ElMessage: { error: loginHarness.error, success: vi.fn() },
}))

vi.mock('@element-plus/icons-vue', () => ({
  Lock: { template: '<span />' },
  Moon: { template: '<span />' },
  Setting: { template: '<span />' },
  Sunny: { template: '<span />' },
  User: { template: '<span />' },
}))

import Login from './Login.vue'

const ElForm = defineComponent({
  inheritAttrs: false,
  setup(_props, { attrs, expose, slots }) {
    expose({ validate: () => Promise.resolve(true) })
    return () => h('form', attrs, slots.default?.())
  },
})

const ElInput = defineComponent({
  inheritAttrs: false,
  props: { modelValue: { type: String, default: '' } },
  emits: ['update:modelValue'],
  setup(props, { attrs, emit }) {
    return () => h('input', {
      ...attrs,
      value: props.modelValue,
      onInput: (event: Event) => emit(
        'update:modelValue',
        (event.target as HTMLInputElement).value,
      ),
    })
  },
})

const Passthrough = defineComponent({
  inheritAttrs: false,
  setup(_props, { attrs, slots }) {
    return () => h('div', attrs, slots.default?.())
  },
})

const ElButton = defineComponent({
  inheritAttrs: false,
  setup(_props, { attrs, slots }) {
    return () => h('button', attrs, slots.default?.())
  },
})

function mountLogin() {
  const container = document.createElement('div')
  document.body.appendChild(container)
  const app = createApp(Login)
  app.component('el-form', ElForm)
  app.component('el-form-item', Passthrough)
  app.component('el-input', ElInput)
  app.component('el-button', ElButton)
  app.component('el-icon', Passthrough)
  app.component('el-tooltip', Passthrough)
  app.mount(container)
  return { app, container }
}

async function flushPromises() {
  await Promise.resolve()
  await Promise.resolve()
  await nextTick()
}

const currentUuid = '11111111-1111-4111-8111-111111111111'
const targetUuid = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa'
const tenants = [
  {
    tenant_id: 1,
    tenant_public_id: currentUuid,
    tenant_name: 'Current',
    tenant_code: 'current',
  },
  {
    tenant_id: 2,
    tenant_public_id: targetUuid,
    tenant_name: 'Target',
    tenant_code: 'target',
  },
]

describe('Login page brand layout', () => {
  it('uses the Ruijing whale identity with a right-side auth panel', () => {
    expect(loginSource).toContain('ruijing-whale-mark.svg')
    expect(loginSource).toContain('login-brand-stage')
    expect(loginSource).toContain('login-auth-panel')
    expect(loginSource).not.toContain('brand-features')
    expect(loginSource).not.toContain('需求沉淀为设计文档')
  })
})

// 桌面端和 Web 共用同一认证与租户选择协议。
describe('Login page reuses web auth on desktop', () => {
  it('does not branch to the legacy desktop account login', () => {
    expect(loginSource).not.toContain('desktopLogin')
  })

  it('keeps tenant selection for every client', () => {
    expect(loginSource).toContain('requiresSelection')
    expect(loginSource).toContain('/tenant-select')
  })

  it('honors the Control Plane server entry path after a direct login', () => {
    expect(userStoreSource).toContain('entryPath: safeLoginRedirectPath(res.entry_path)')
    expect(loginSource).toContain('result.entryPath')
  })

  it('uses the Code home when neither login entry source is valid for Code-only', () => {
    expect(loginSource).toContain("from '@/stores/productAvailability'")
    expect(loginSource).toContain('await loadProductAvailability()')
    expect(loginSource).toContain('redirectForDisabledProduct(')
    expect(loginSource).toContain('defaultProductHome(productAvailability)')
  })

  it('collects the configured captcha for every client', () => {
    expect(loginSource).toContain('captcha_code')
    expect(loginSource).toContain('captchaImage')
    expect(loginSource).toContain('refreshCaptcha')
  })
})

describe('Login captcha fallback', () => {
  afterEach(() => {
    vi.clearAllMocks()
    loginHarness.routeQuery = {}
    loginHarness.token = null
    localStorage.clear()
    document.body.innerHTML = ''
  })

  it('restores the captcha input after a failed probe and the first login failure', async () => {
    loginHarness.getCaptcha.mockRejectedValueOnce(new Error('captcha unavailable'))
    loginHarness.getCaptcha.mockResolvedValueOnce({
      required: true,
      captcha_id: 'captcha-2',
      image_data: 'data:image/png;base64,captcha-2',
    })
    loginHarness.login.mockRejectedValueOnce({
      response: { data: { detail: '账号或密码不正确' } },
    })
    const { app, container } = mountLogin()

    await flushPromises()

    expect(container.querySelector('input[placeholder="验证码"]')).toBeNull()

    const username = container.querySelector<HTMLInputElement>('input[placeholder="账号"]')
    const password = container.querySelector<HTMLInputElement>('input[placeholder="密码"]')
    username!.value = 'alice'
    username!.dispatchEvent(new Event('input'))
    password!.value = 'secret'
    password!.dispatchEvent(new Event('input'))
    container.querySelector<HTMLButtonElement>('button.submit-btn')!.click()

    await flushPromises()
    await flushPromises()

    expect(loginHarness.login).toHaveBeenCalledWith('alice', 'secret', '', '')
    expect(loginHarness.error).toHaveBeenCalledWith('账号或密码不正确')
    expect(loginHarness.getCaptcha).toHaveBeenCalledTimes(2)
    expect(container.querySelector('input[placeholder="验证码"]')).not.toBeNull()
    app.unmount()
  })

  it('does not retry captcha discovery after the one recovery attempt also fails', async () => {
    loginHarness.getCaptcha
      .mockRejectedValueOnce(new Error('captcha unavailable'))
      .mockRejectedValueOnce(new Error('captcha still unavailable'))
    loginHarness.login.mockRejectedValue({
      response: { data: { detail: '账号或密码不正确' } },
    })
    const { app, container } = mountLogin()

    await flushPromises()

    const username = container.querySelector<HTMLInputElement>('input[placeholder="账号"]')
    const password = container.querySelector<HTMLInputElement>('input[placeholder="密码"]')
    const submit = container.querySelector<HTMLButtonElement>('button.submit-btn')
    username!.value = 'alice'
    username!.dispatchEvent(new Event('input'))
    password!.value = 'secret'
    password!.dispatchEvent(new Event('input'))

    submit!.click()
    await flushPromises()
    await flushPromises()
    submit!.click()
    await flushPromises()
    await flushPromises()

    expect(loginHarness.login).toHaveBeenCalledTimes(2)
    expect(loginHarness.getCaptcha).toHaveBeenCalledTimes(2)
    expect(loginHarness.error).toHaveBeenCalledTimes(2)
    expect(container.querySelector('input[placeholder="验证码"]')).toBeNull()
    app.unmount()
  })
})

describe('standalone Web Console redirect recovery', () => {
  afterEach(() => {
    vi.clearAllMocks()
    loginHarness.routeQuery = {}
    loginHarness.token = null
    localStorage.clear()
    document.body.innerHTML = ''
  })

  it('restores a failed management-session handoff without asking for credentials again', async () => {
    loginHarness.routeQuery = { redirect: '/web-console/' }
    loginHarness.token = 'committed-builder-token'
    loginHarness.getCaptcha.mockResolvedValue({ required: false })
    loginHarness.createWebConsoleSession.mockResolvedValue({
      access_token: 'web-console-token',
      tenant_id: '840289793437859841',
    })

    const { app } = mountLogin()
    await flushPromises()
    await flushPromises()

    expect(localStorage.getItem('access_token')).toBe('web-console-token')
    expect(localStorage.getItem('tenant_id')).toBe('840289793437859841')
    app.unmount()
  })
})

describe('tenant-aware login redirects', () => {
  it('auto-selects only the tenant whose public UUID matches the redirect', () => {
    expect(resolveLoginTenant(
      `/code/session?tenantId=${targetUuid}&agent=runtime-1#activity`,
      tenants,
    )).toEqual(tenants[1])
  })

  it('keeps invalid or inaccessible tenant targets on the manual selection path', () => {
    expect(resolveLoginTenant('/code/session?tenantId=2', tenants)).toBeUndefined()
    expect(resolveLoginTenant(
      '/code/session?tenantId=bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb',
      tenants,
    )).toBeUndefined()
  })

  it('extracts a canonical tenant UUID without trusting an external redirect', () => {
    expect(tenantIdFromRedirect(`/code/session?tenantId=${targetUuid}`)).toBe(targetUuid)
    expect(tenantIdFromRedirect('https://evil.example/code?tenantId=' + targetUuid)).toBeNull()
    expect(safeLoginRedirectPath('/\\evil.example/code')).toBe('')
  })

  it('wires the server-returned tenant list into TenantSelect auto-selection', () => {
    expect(loginSource).toContain('safeLoginRedirectPath')
    expect(tenantSelectSource).toContain('resolveLoginTenant')
    expect(tenantSelectSource).toContain('handleSelect(targetTenant)')
  })

  it('never submits tenant_public_id in TenantSelectRequest', () => {
    expect(userStoreSource).toContain(
      '{ selection_token: selectionToken, tenant_id: tenantId }',
    )
    expect(userStoreSource).not.toContain('tenant_public_id:')
  })
})
