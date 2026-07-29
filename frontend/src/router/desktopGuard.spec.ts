import { describe, it, expect } from 'vitest'
import {
  loadDesktopBootstrapDecision,
  resolveDesktopBootstrapRedirect,
  resolveDesktopRedirect,
} from './desktopGuard'
import {
  DESKTOP_LOGIN_SERVICES,
  buildDesktopSetupInput,
  resolveDesktopSetupView,
  transitionDesktopSetup,
  type DesktopSetupMachineState,
} from '@/utils/desktop/setup'
import routerSource from './index.ts?raw'
import setupWizardSource from '@/views/DesktopSetupWizard.vue?raw'
import loginSource from '@/views/Login.vue?raw'
import * as loginModule from '@/views/Login.vue'
import desktopSettingsSource from '@/views/DesktopSettings.vue?raw'

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
    expect(settingsRouteSource).toContain("meta: { requiresAuth: true, tenantContext: 'none' }")
  })

  it('登录页显示桌面服务摘要并通过 packaged setup 更改服务', () => {
    expect(loginSource).toContain('desktopService.label')
    expect(loginSource).toContain('desktopService.host')
    expect(loginSource).toContain('更改登录服务')
    expect(loginSource).toContain('new URL(snapshot.config.login.base_url).host')
    const logoutIndex = loginSource.indexOf('userStore.logout()')
    const setupIndex = loginSource.indexOf('await enterDesktopLoginSetup()')
    expect(logoutIndex).toBeGreaterThan(-1)
    expect(setupIndex).toBeGreaterThan(logoutIndex)
  })

  it('桌面设置只修改登录服务且本地根目录保持只读', () => {
    expect(desktopSettingsSource).toContain('<BuilderFrame')
    expect(desktopSettingsSource).toContain('DESKTOP_LOGIN_SERVICES')
    expect(desktopSettingsSource).toContain('service.label')
    expect(desktopSettingsSource).toContain('服务地址')
    expect(desktopSettingsSource).toContain('readonly')
    expect(desktopSettingsSource).toContain('不提供编辑或迁移操作')
    expect(desktopSettingsSource).toContain("@click=\"openPath('root')\"")
    expect(desktopSettingsSource).toContain("@click=\"openPath('logs')\"")
    expect(desktopSettingsSource).toContain('await openDesktopPath(kind)')
    expect(desktopSettingsSource).not.toContain('pickDirectory')
    expect(desktopSettingsSource).not.toContain('saveDesktopSetup')
    expect(desktopSettingsSource).not.toContain('root_dir:')
    expect(desktopSettingsSource).toContain('new URL(value.trim())')
    expect(desktopSettingsSource).toContain("['http:', 'https:'].includes(url.protocol)")

    const logoutIndex = desktopSettingsSource.indexOf('user.logout()')
    const updateIndex = desktopSettingsSource.indexOf('await updateDesktopLogin({')
    expect(logoutIndex).toBeGreaterThan(-1)
    expect(updateIndex).toBeGreaterThan(logoutIndex)
  })

  it('桌面设置入队成功保持锁定且仅 invoke 失败解锁', () => {
    const handlerStart = desktopSettingsSource.indexOf('async function saveLoginSettings()')
    const handlerEnd = desktopSettingsSource.indexOf('onMounted(() =>', handlerStart)
    const handlerSource = desktopSettingsSource.slice(handlerStart, handlerEnd)
    const catchIndex = handlerSource.indexOf('} catch {')
    const unlockIndex = handlerSource.indexOf('saving.value = false')

    expect(handlerStart).toBeGreaterThan(-1)
    expect(handlerSource).toContain('saving.value = true')
    expect(handlerSource).not.toContain('finally')
    expect(catchIndex).toBeGreaterThan(-1)
    expect(unlockIndex).toBeGreaterThan(catchIndex)
    expect(handlerSource.match(/saving\.value = false/g)).toHaveLength(1)
    expect(desktopSettingsSource).toContain(':disabled="saving || Boolean(urlError)"')
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
    const refreshStart = loginSource.indexOf('const refreshCaptcha = async () =>')
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
    expect(loginHandlerSource).toContain(
      'if (changingDesktopService.value || !loginFormRef.value) return',
    )
    expect(formSource.match(/:disabled="changingDesktopService"/g)).toHaveLength(5)
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

  it('更改服务按钮和 handler 消费同一 gate', () => {
    const buttonStart = loginSource.lastIndexOf(
      '<button',
      loginSource.indexOf('class="login-service-change"'),
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
    expect(handlerSource).toContain(
      'if (!isDesktop || !desktopServiceChangeAllowed.value) return',
    )
  })

  it('桌面登录服务只启用 AI中台和 aPaaS平台', () => {
    expect(DESKTOP_LOGIN_SERVICES).toEqual([
      { mode: 'control_plane', label: 'AI中台', defaultUrl: 'https://om-demo.dfy.definesys.cn', enabled: true },
      { mode: 'apaas', label: 'aPaaS平台', defaultUrl: 'https://apaas-trial.definesys.cn/backend', enabled: true },
      { mode: 'public_account', label: '公开账号', defaultUrl: '', enabled: false },
      { mode: 'trial_account', label: '试用账号', defaultUrl: '', enabled: false },
    ])
  })

  it('初始化提交不包含账号、密码、租户或模型字段', () => {
    expect(buildDesktopSetupInput('C:\\Users\\Administrator\\DolphinCode', 'control_plane', 'https://example.com'))
      .toEqual({
        root_dir: 'C:\\Users\\Administrator\\DolphinCode',
        login: { mode: 'control_plane', base_url: 'https://example.com' },
      })
  })

  it('full scope 固定为两步并开放本地目录字段', () => {
    expect(resolveDesktopSetupView({
      phase: 'needs_setup',
      setup_scope: 'full',
      config: null,
      default_root_dir: 'C:\\Users\\Administrator\\DolphinCode',
      error: null,
    })).toEqual({
      rootDir: 'C:\\Users\\Administrator\\DolphinCode',
      directoryEditable: true,
      recovery: 'none',
    })
  })

  it('login_only 只显示登录服务并保留已保存 root', () => {
    expect(resolveDesktopSetupView({
      phase: 'needs_setup',
      setup_scope: 'login_only',
      config: {
        schema_version: 1,
        root_dir: 'D:\\DolphinCode',
        login: { mode: 'apaas', base_url: 'https://apaas.example.com/backend' },
      },
      default_root_dir: 'C:\\Users\\Administrator\\DolphinCode',
      error: null,
    })).toEqual({
      rootDir: 'D:\\DolphinCode',
      directoryEditable: false,
      recovery: 'none',
    })
  })

  it('启动失败进入重试恢复，配置无效直接回到编辑表单', () => {
    const baseState = {
      setup_scope: 'full' as const,
      config: null,
      default_root_dir: 'C:\\Users\\Administrator\\DolphinCode',
    }

    expect(resolveDesktopSetupView({
      ...baseState,
      phase: 'failed',
      error: { code: 'DESKTOP_SETUP_RUNTIME_START_FAILED', message: '启动失败' },
    }).recovery).toBe('retry_start')
    expect(resolveDesktopSetupView({
      ...baseState,
      phase: 'failed',
      error: { code: 'DESKTOP_SETUP_CONFIG_INVALID', message: '目录无效' },
    }).recovery).toBe('edit_config')
  })

  it('full setup 连续执行 next/back 驱动真实两步切换', () => {
    let machine: DesktopSetupMachineState = { scope: 'full', step: 'login_service' }

    const next = transitionDesktopSetup(machine, 'next')
    expect(next.step).toBe('local_storage')
    machine = { ...machine, step: next.step }

    expect(transitionDesktopSetup(machine, 'back').step).toBe('login_service')
  })

  it('login_only 无 storage 且拒绝目录选择 effect', () => {
    const machine = { scope: 'login_only' as const, step: 'login_service' as const }

    expect(transitionDesktopSetup(machine, 'next').step).toBe('login_service')
    expect(transitionDesktopSetup(machine, 'pick_directory').pickerRequests).toBe(0)
  })

  it('full 每次目录选择 event 只产生一次 picker effect', () => {
    const machine = { scope: 'full' as const, step: 'local_storage' as const }

    expect(transitionDesktopSetup(machine, 'pick_directory').pickerRequests).toBe(1)
    expect(transitionDesktopSetup(machine, 'pick_directory').pickerRequests).toBe(1)
  })

  it('poll_tick 延迟 300ms，ready 停止并等待 Tauri 导航', () => {
    const machine = { scope: 'full' as const, step: 'local_storage' as const }

    expect(transitionDesktopSetup(machine, 'poll_tick')).toEqual({
      step: 'local_storage',
      pickerRequests: 0,
      pollAfterMs: 300,
      stopPolling: false,
      navigation: null,
    })
    expect(transitionDesktopSetup(machine, 'ready')).toEqual({
      step: 'local_storage',
      pickerRequests: 0,
      pollAfterMs: null,
      stopPolling: true,
      navigation: null,
    })
  })

  it('向导真实交互消费统一 transition/effect', () => {
    expect(setupWizardSource).toContain("transitionDesktopSetup(machineState(), 'next')")
    expect(setupWizardSource).toContain("transitionDesktopSetup(machineState(), 'back')")
    expect(setupWizardSource).toContain("transitionDesktopSetup(machineState(), 'pick_directory')")
    expect(setupWizardSource).toContain("snapshot.phase === 'ready' ? 'ready' : 'poll_tick'")
    expect(setupWizardSource).not.toContain('useRouter')
  })

  it('卸载后阻止 in-flight polling 重新调度', () => {
    expect(setupWizardSource).toContain('if (polling || disposed) return')
    expect(setupWizardSource).toContain('if (disposed) return')
    expect(setupWizardSource).toContain('disposed = true')
    expect(setupWizardSource).toContain('onBeforeUnmount(disposePolling)')
  })
})
