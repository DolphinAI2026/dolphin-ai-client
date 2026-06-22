import { describe, expect, it } from 'vitest'
import loginSource from './Login.vue?raw'

describe('Login page brand layout', () => {
  it('uses the Ruijing whale identity with a right-side auth panel', () => {
    expect(loginSource).toContain('ruijing-whale-mark.svg')
    expect(loginSource).toContain('login-brand-stage')
    expect(loginSource).toContain('login-auth-panel')
    expect(loginSource).not.toContain('brand-features')
    expect(loginSource).not.toContain('需求沉淀为设计文档')
  })
})

// 2026-06-22: 桌面登录页统一用 Login.vue(和 web 同一套 UI), 删 DesktopLogin.vue。
// 桌面端登录走 desktopLogin(account-service); web 端走 login(可能要选租户)。
describe('Login page handles both web and desktop auth', () => {
  it('branches the auth call on isDesktop (desktopLogin on desktop)', () => {
    expect(loginSource).toContain("from '@/utils/desktop'")
    expect(loginSource).toContain('isDesktop')
    expect(loginSource).toContain('desktopLogin')
  })

  it('keeps the web tenant-selection path', () => {
    expect(loginSource).toContain('requiresSelection')
    expect(loginSource).toContain('/tenant-select')
  })
})
