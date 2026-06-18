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
