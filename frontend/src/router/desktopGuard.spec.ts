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
    const setupRouteEnd = routerSource.indexOf("path: '/desktop-unavailable'")
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
