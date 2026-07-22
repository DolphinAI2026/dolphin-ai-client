import { describe, it, expect } from 'vitest'
import { resolveDesktopRedirect } from './desktopGuard'
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

  it('桌面端废弃的配置向导入口重定向到 Code 应用页', () => {
    expect(routerSource).toContain("path: '/desktop-setup'")
    expect(routerSource).toContain("redirect: () => ({ path: '/code/apps' })")
  })

  it('桌面端不会因隐藏的本地 tenant_id 把平台管理员导向平台管理', () => {
    expect(routerSource).toContain('&& !__DESKTOP__')
  })

  it('桌面端根入口进入 Code 应用页，不启动 Builder 模型流程', () => {
    expect(routerSource).toContain("beforeEnter: () => __DESKTOP__ ? { path: '/code/apps' } : true")
  })
})
