import { describe, it, expect } from 'vitest'
import {
  loadDesktopBootstrapDecision,
  resolveDesktopBootstrapRedirect,
  resolveDesktopRedirect,
  resolveDesktopSettingsRedirect,
  resolveDesktopWorkspaceRedirect,
} from './desktopGuard'
import {
  DESKTOP_LOGIN_SERVICES,
  buildDesktopSetupInput,
  desktopErrorMessage,
} from '@/utils/desktop/setup'
import routerSource from './index.ts?raw'
import setupWizardSource from '@/views/DesktopSetupWizard.vue?raw'
import loginSource from '@/views/Login.vue?raw'
import * as loginModule from '@/views/Login.vue'
import desktopSettingsSource from '@/views/DesktopSettings.vue?raw'
import aboutDialogSource from '@/components/desktop/DesktopAboutDialog.vue?raw'
import railSidebarSource from '@/components/v2/RailSidebar.vue?raw'

function deferred<T>() {
  let resolve!: (value: T | PromiseLike<T>) => void
  let reject!: (reason?: unknown) => void
  const promise = new Promise<T>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise
    reject = rejectPromise
  })
  return { promise, resolve, reject }
}

describe('resolveDesktopRedirect', () => {
  it('在线版不拦截 hidden 路由', () => {
    expect(resolveDesktopRedirect(false, { desktop: 'hidden' }, '/platform-admin')).toBeNull()
  })
  it('桌面版 hidden 路由 → /desktop-unavailable', () => {
    expect(resolveDesktopRedirect(true, { desktop: 'hidden' }, '/platform-admin'))
      .toBe('/desktop-unavailable')
  })
  it('桌面版普通路由放行', () => {
    expect(resolveDesktopRedirect(true, {}, '/apps')).toBeNull()
  })
  it('已在 unavailable 页不再重定向(防环)', () => {
    expect(resolveDesktopRedirect(true, { desktop: 'hidden' }, '/desktop-unavailable')).toBeNull()
  })

  it('未初始化和启动失败都在认证前进入桌面初始化页', () => {
    expect(resolveDesktopBootstrapRedirect('needs_setup', '/login')).toBe('/desktop-setup')
    expect(resolveDesktopBootstrapRedirect('starting_runtime', '/')).toBe('/desktop-setup')
    expect(resolveDesktopBootstrapRedirect('failed', '/code/apps')).toBe('/desktop-setup')
  })

  it('ready 后放行业务路由，初始化页自身防环', () => {
    expect(resolveDesktopBootstrapRedirect('ready', '/login')).toBeNull()
    expect(resolveDesktopBootstrapRedirect('needs_setup', '/desktop-setup')).toBeNull()
  })

  it('IPC 失败可进入初始化页，且后续 ready 不受失败状态阻塞', async () => {
    let attempt = 0
    const loadState = async () => {
      attempt += 1
      if (attempt < 3) throw new Error('desktop bridge unavailable')
      return { phase: 'ready' as const }
    }

    await expect(loadDesktopBootstrapDecision(loadState, '/login')).resolves.toEqual({
      readyForDocument: false,
      redirect: '/desktop-setup',
    })
    await expect(loadDesktopBootstrapDecision(loadState, '/desktop-setup')).resolves.toEqual({
      readyForDocument: false,
      redirect: null,
    })
    await expect(loadDesktopBootstrapDecision(loadState, '/code/apps')).resolves.toEqual({
      readyForDocument: true,
      redirect: null,
    })
  })

  it('旧 aPaaS 和 LLM onboarding 守卫已退役', () => {
    const setupRouteStart = routerSource.indexOf("path: '/desktop-setup'")
    const setupRouteEnd = routerSource.indexOf("path: '/desktop-settings'")
    const setupRouteSource = routerSource.slice(setupRouteStart, setupRouteEnd)

    expect(routerSource).not.toContain('fetchOnboardingState')
    expect(routerSource).not.toContain('isOnboardingConfirmed')
    expect(setupRouteSource).not.toContain('redirect:')
    expect(setupRouteSource).not.toContain('requiresAuth')
    expect(setupRouteSource).toContain("meta: { tenantContext: 'none' }")
  })

  it('桌面专用路由只在 desktop build 中注册', () => {
    const desktopRoutesStart = routerSource.indexOf('const desktopRoutes: RouteRecordRaw[] = __DESKTOP__ ? [')
    const routesStart = routerSource.indexOf('export const routes: RouteRecordRaw[] = [')
    const spreadIndex = routerSource.indexOf('...desktopRoutes', routesStart)

    expect(desktopRoutesStart).toBeGreaterThan(-1)
    expect(routesStart).toBeGreaterThan(desktopRoutesStart)
    expect(spreadIndex).toBeGreaterThan(routesStart)
    expect(routerSource.slice(desktopRoutesStart, routesStart)).toContain("path: '/desktop-setup'")
    expect(routerSource.slice(desktopRoutesStart, routesStart)).toContain("path: '/desktop-settings'")
  })

  it('桌面 bootstrap 在用户 store 和认证恢复前执行', () => {
    const bootstrapGuardIndex = routerSource.indexOf("if (typeof __DESKTOP__ !== 'undefined' && __DESKTOP__) {")
    const userStoreIndex = routerSource.indexOf('const userStore = useUserStore()')

    expect(bootstrapGuardIndex).toBeGreaterThan(-1)
    expect(bootstrapGuardIndex).toBeLessThan(userStoreIndex)
  })

  it('桌面设置路由需要认证且不依赖租户上下文', () => {
    const settingsRouteStart = routerSource.indexOf("path: '/desktop-settings'")
    const settingsRouteEnd = routerSource.indexOf("path: '/desktop-unavailable'")
    const settingsRouteSource = routerSource.slice(settingsRouteStart, settingsRouteEnd)

    expect(settingsRouteStart).toBeGreaterThan(-1)
    expect(settingsRouteSource).toContain("name: 'DesktopSettings'")
    expect(settingsRouteSource).toContain("component: () => import('@/views/DesktopSettings.vue')")
    expect(settingsRouteSource).not.toContain("path: '/settings'")
    expect(settingsRouteSource).not.toContain("section: 'desktop'")
    expect(settingsRouteSource).toContain("meta: { requiresAuth: true, tenantContext: 'none' }")
  })

  it('桌面设置通过关于弹窗提供版本与手动更新入口', () => {
    expect(desktopSettingsSource).toContain("label: '关于与更新'")
    expect(desktopSettingsSource).toContain('<DesktopAboutDialog')
    expect(aboutDialogSource).toContain('DolphinAI')
    expect(aboutDialogSource).toContain('__APP_VERSION__')
    expect(aboutDialogSource).toContain('__BUILD_REVISION__')
    expect(aboutDialogSource).toContain('__BUILD_TARGET__')
    expect(aboutDialogSource).toContain('checkAndPromptUpdate({ silentIfNone: false })')
  })

  it('核心桌面入口使用 DolphinAI 品牌', () => {
    for (const source of [loginSource, setupWizardSource, railSidebarSource]) {
      expect(source).toContain('DolphinAI')
      expect(source).not.toContain('Dolphin Code')
      expect(source).not.toContain('睿鲸')
    }
  })

  it('登录页显示桌面服务摘要并通过 packaged setup 更改服务', () => {
    expect(loginSource).toContain('desktopService.label')
    expect(loginSource).toContain('desktopService.host')
    expect(loginSource).toContain('更改登录服务')
    expect(loginSource).toContain('const loginUrl = discovery?.auth.login_url || config.login.base_url')
    expect(loginSource).toContain('host: new URL(loginUrl).host')
    const logoutIndex = loginSource.indexOf('userStore.logout()')
    const setupIndex = loginSource.indexOf('await enterDesktopLoginSetup()')
    expect(logoutIndex).toBeGreaterThan(-1)
    expect(setupIndex).toBeGreaterThan(logoutIndex)
  })

  it('桌面设置重新发现远程能力并保持本地根目录只读', () => {
    expect(desktopSettingsSource).toContain('<BuilderFrame')
    expect(desktopSettingsSource).toContain('服务地址')
    expect(desktopSettingsSource).toContain('readonly')
    expect(desktopSettingsSource).toContain("@click=\"openPath('root')\"")
    expect(desktopSettingsSource).toContain("@click=\"openPath('logs')\"")
    expect(desktopSettingsSource).toContain('await openDesktopPath(kind)')
    expect(desktopSettingsSource).not.toContain('pickDirectory')
    expect(desktopSettingsSource).toContain('await discoverDesktopService(serviceUrl.value.trim())')
    expect(desktopSettingsSource).toContain('await saveDesktopSetup(buildDesktopSetupInput(')
    expect(desktopSettingsSource).toContain("rootDir.value || snapshot.value?.default_root_dir || ''")
    expect(desktopSettingsSource).toContain('new URL(value.trim())')
    expect(desktopSettingsSource).toContain("['http:', 'https:'].includes(url.protocol)")
  })

  it('桌面设置原生重连期间保持锁定，ready 或失败后解锁', () => {
    const handlerStart = desktopSettingsSource.indexOf('async function saveConnection()')
    const handlerEnd = desktopSettingsSource.indexOf('onMounted(() =>', handlerStart)
    const handlerSource = desktopSettingsSource.slice(handlerStart, handlerEnd)

    expect(handlerStart).toBeGreaterThan(-1)
    expect(handlerSource).toContain('saving.value = true')
    expect(handlerSource).toContain("if (__DESKTOP_WEB_PREVIEW__ || snapshot.value?.phase === 'ready'")
    expect(handlerSource.match(/saving\.value = false/g)).toHaveLength(2)
    expect(desktopSettingsSource).toContain(':disabled="!discovery || Boolean(urlError)"')
  })

  it('登录服务切换成功保持锁定且旧 sidecar 登录入口全部停用', () => {
    const changeStart = loginSource.indexOf('async function changeDesktopService()')
    const changeEnd = loginSource.indexOf('onMounted(() =>', changeStart)
    const changeSource = loginSource.slice(changeStart, changeEnd)
    const catchIndex = changeSource.indexOf('} catch {')
    const unlockIndex = changeSource.indexOf('changingDesktopService.value = false')
    const formStart = loginSource.indexOf('<el-form')
    const formEnd = loginSource.indexOf('</el-form>', formStart)
    const formSource = loginSource.slice(formStart, formEnd)
    const refreshStart = loginSource.indexOf('const refreshCaptcha = async')
    const refreshEnd = loginSource.indexOf('async function loadDesktopService()', refreshStart)
    const refreshSource = loginSource.slice(refreshStart, refreshEnd)
    const loginHandlerStart = loginSource.indexOf('const handleLogin = async () =>')
    const loginHandlerSource = loginSource.slice(loginHandlerStart)

    expect(changeStart).toBeGreaterThan(-1)
    expect(changeSource).not.toContain('finally')
    expect(catchIndex).toBeGreaterThan(-1)
    expect(unlockIndex).toBeGreaterThan(catchIndex)
    expect(changeSource.match(/changingDesktopService\.value = false/g)).toHaveLength(1)
    expect(refreshSource).toContain('if (changingDesktopService.value) return')
    expect(loginHandlerSource).toContain('changingDesktopService.value,')
    expect(formSource.match(/:disabled="changingDesktopService"/g)).toHaveLength(2)
    expect(formSource.match(/:disabled="loginLoading \|\| changingDesktopService"/g))
      .toHaveLength(3)
  })

  it('登录 pending、settled 与 transition pending 共用服务切换 gate', async () => {
    const canChangeDesktopService = (
      loginModule as typeof loginModule & {
        canChangeDesktopService?: (loginPending: boolean, transitionPending: boolean) => boolean
      }
    ).canChangeDesktopService

    expect(canChangeDesktopService).toBeTypeOf('function')
    if (!canChangeDesktopService) return

    let loginPending = true
    let transitionPending = false
    const loginRequest = deferred<void>()
    const loginLifecycle = loginRequest.promise.finally(() => {
      loginPending = false
    })

    expect(canChangeDesktopService(loginPending, transitionPending)).toBe(false)
    loginRequest.resolve()
    await loginLifecycle
    expect(canChangeDesktopService(loginPending, transitionPending)).toBe(true)

    transitionPending = true
    const transitionRequest = deferred<void>()
    expect(canChangeDesktopService(loginPending, transitionPending)).toBe(false)
    transitionRequest.resolve()
    await transitionRequest.promise
    expect(canChangeDesktopService(loginPending, transitionPending)).toBe(false)
  })

  it('登录提交 single-flight 在 pending settle 前只启动一次 action', async () => {
    const tryStartLogin = (
      loginModule as typeof loginModule & {
        tryStartLogin?: (
          loginPending: boolean,
          transitionPending: boolean,
          start: () => void,
        ) => boolean
      }
    ).tryStartLogin

    expect(tryStartLogin).toBeTypeOf('function')
    if (!tryStartLogin) return

    let loginPending = false
    let transitionPending = false
    let loginCalls = 0
    const submit = async (request: Promise<void>) => {
      const started = tryStartLogin(loginPending, transitionPending, () => {
        loginPending = true
      })
      if (!started) return

      loginCalls += 1
      try {
        await request
      } finally {
        loginPending = false
      }
    }

    const firstLogin = deferred<void>()
    const firstSubmission = submit(firstLogin.promise)
    await submit(Promise.resolve())
    expect(loginCalls).toBe(1)
    expect(loginPending).toBe(true)

    firstLogin.resolve()
    await firstSubmission
    expect(loginPending).toBe(false)

    const nextLogin = deferred<void>()
    const nextSubmission = submit(nextLogin.promise)
    expect(loginCalls).toBe(2)
    expect(loginPending).toBe(true)
    nextLogin.resolve()
    await nextSubmission

    transitionPending = true
    await submit(Promise.resolve())
    expect(loginCalls).toBe(2)
  })

  it('handleLogin 在异步校验前同步获取 single-flight latch', () => {
    const handlerStart = loginSource.indexOf('const handleLogin = async () =>')
    const handlerEnd = loginSource.indexOf('</script>', handlerStart)
    const handlerSource = loginSource.slice(handlerStart, handlerEnd)
    const gateIndex = handlerSource.indexOf('!tryStartLogin(')
    const latchIndex = handlerSource.indexOf('loginLoading.value = true')
    const validateIndex = handlerSource.indexOf('await form.validate()')
    const loginIndex = handlerSource.indexOf('await userStore.login(')

    expect(gateIndex).toBeGreaterThan(-1)
    expect(latchIndex).toBeGreaterThan(gateIndex)
    expect(validateIndex).toBeGreaterThan(latchIndex)
    expect(loginIndex).toBeGreaterThan(validateIndex)
    expect(handlerSource).toContain('loginLoading.value,')
    expect(handlerSource).toContain('changingDesktopService.value,')
    expect(handlerSource).toContain('loginLoading.value = false')
  })

  it('更改服务按钮和 handler 消费同一 gate', () => {
    const buttonStart = loginSource.lastIndexOf(
      '<button',
      loginSource.indexOf('class="login-service-settings"'),
    )
    const buttonEnd = loginSource.indexOf('</button>', buttonStart)
    const buttonSource = loginSource.slice(buttonStart, buttonEnd)
    const handlerStart = loginSource.indexOf('async function changeDesktopService()')
    const handlerEnd = loginSource.indexOf('onMounted(() =>', handlerStart)
    const handlerSource = loginSource.slice(handlerStart, handlerEnd)

    expect(loginSource).toContain(
      'const desktopServiceChangeAllowed = computed(() => canChangeDesktopService(',
    )
    expect(buttonSource).toContain(':disabled="!desktopServiceChangeAllowed"')
    expect(buttonSource).toContain('aria-label="更改登录服务"')
    expect(handlerSource).toContain(
      'if (!isDesktop || !desktopServiceChangeAllowed.value) return',
    )
    expect(handlerSource).toContain("await router.replace('/desktop-setup')")
  })

  it('桌面登录服务只启用 AI中台和 aPaaS平台', () => {
    expect(DESKTOP_LOGIN_SERVICES).toEqual([
      { mode: 'control_plane', label: 'AI中台', defaultUrl: 'https://om-demo.dfy.definesys.cn', enabled: true },
      { mode: 'apaas', label: 'aPaaS平台', defaultUrl: 'https://apaas-trial.definesys.cn/backend', enabled: true },
      { mode: 'public_account', label: '公开账号', defaultUrl: '', enabled: false },
      { mode: 'trial_account', label: '试用账号', defaultUrl: '', enabled: false },
    ])
  })

  it('桌面入口范围约束业务路由并写入初始化配置', () => {
    expect(resolveDesktopWorkspaceRedirect('apaas', '/code/apps')).toBe('/')
    expect(resolveDesktopWorkspaceRedirect('ai_platform', '/apps')).toBe('/code/apps')
    expect(resolveDesktopWorkspaceRedirect('ai_platform', '/login')).toBeNull()
    expect(resolveDesktopWorkspaceRedirect('ai_platform', '/desktop-settings')).toBeNull()
    expect(resolveDesktopWorkspaceRedirect('both', '/apps')).toBeNull()

    expect(buildDesktopSetupInput(
      'C:\\Users\\Administrator\\DolphinCode',
      'control_plane',
      'https://example.com',
      'ai_platform',
    ))
      .toEqual({
        root_dir: 'C:\\Users\\Administrator\\DolphinCode',
        login: { mode: 'control_plane', base_url: 'https://example.com' },
        workspace_entry_scope: 'ai_platform',
        discovery_url: 'https://example.com',
        discovery: null,
        local_ai_enabled: true,
      })
  })

  it('初始化页只输入远程地址并消费服务发现结果', () => {
    expect(setupWizardSource).toContain('await discoverDesktopService(serviceUrl.value.trim())')
    expect(setupWizardSource).toContain('discovery.value.auth.provider')
    expect(setupWizardSource).toContain('discovery.value.auth.login_url')
    expect(setupWizardSource).toContain('saveDesktopSetup(buildDesktopSetupInput(')
    expect(setupWizardSource).not.toContain('pickDirectory')
  })

  it('初始化轮询使用 single-flight 且卸载后不再调度', () => {
    expect(setupWizardSource).toContain('if (polling || disposed.value) return')
    expect(setupWizardSource).toContain('polling = true')
    expect(setupWizardSource).toContain('polling = false')
    expect(setupWizardSource).toContain('if (!disposed.value) scheduleRefresh(')
    expect(setupWizardSource).toContain('onBeforeUnmount(disposePolling)')
  })

  it('失败页拒绝展示各种凭据语法、URL secret、JWT 和 traceback', () => {
    const fallback = '本地环境未能启动，请重试或查看日志'
    for (const sensitive of [
      'Authorization : Bearer auth-space',
      'Authorization=auth-equals',
      '{\n  "nested": {"token" : "json-token"},\n  "ok": "visible"\n}',
      'password : password-colon',
      'apiKey=camel-key',
      'Bearer bearer-only',
      'urls https://safe.example/path https://user:url-pass@example.test/path?x=1',
      'queries https://safe.example/?x=1 https://example.test/?apiKey=query-key',
      'secret=secret-value',
      'eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjMifQ.signature',
      'Traceback (most recent call last):\n  File "app.py", line 1',
    ]) {
      expect(desktopErrorMessage(sensitive, fallback)).toBe(fallback)
    }
    expect(desktopErrorMessage('sidecar 健康检查超时\nignored detail', fallback))
      .toBe('sidecar 健康检查超时')
    expect(setupWizardSource).toContain('const stateErrorMessage = computed(() => desktopErrorMessage(')
    expect(setupWizardSource).toContain('state.value?.error,')
  })
})

describe('resolveDesktopSettingsRedirect', () => {
  it('桌面端将旧设置入口统一收口到桌面设置', () => {
    for (const path of ['/settings', '/platform-envs', '/skills', '/skills/example/workspace', '/knowledge', '/admin/mcp', '/hub']) {
      expect(resolveDesktopSettingsRedirect(true, path)).toBe('/desktop-settings')
    }
  })

  it('桌面端保留工作区目录入口，Web 端不拦截旧设置路径', () => {
    expect(resolveDesktopSettingsRedirect(true, '/workspace-catalog')).toBeNull()
    expect(resolveDesktopSettingsRedirect(false, '/settings')).toBeNull()
  })
})
