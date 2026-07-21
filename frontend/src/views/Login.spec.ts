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

// 桌面端和 Web 共用同一认证与租户选择协议。
describe('Login page reuses web auth on desktop', () => {
  it('does not branch to the legacy desktop account login', () => {
    expect(loginSource).not.toContain("from '@/utils/desktop'")
    expect(loginSource).not.toContain('desktopLogin')
  })

  it('keeps tenant selection for every client', () => {
    expect(loginSource).toContain('requiresSelection')
    expect(loginSource).toContain('/tenant-select')
  })

  it('collects the configured captcha for every client', () => {
    expect(loginSource).toContain('captcha_code')
    expect(loginSource).toContain('captchaImage')
    expect(loginSource).toContain('refreshCaptcha')
  })
})
