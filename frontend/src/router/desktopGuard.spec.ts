import { describe, it, expect } from 'vitest'
import {
  resolveDesktopBootstrapRedirect,
  resolveDesktopRedirect,
} from './desktopGuard'
import routerSource from './index.ts?raw'

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
})
