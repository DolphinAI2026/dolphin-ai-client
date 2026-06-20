import { describe, it, expect } from 'vitest'
import src from './CodingPage.vue?raw'

describe('CodingPage 思维链折叠卡', () => {
  it('reasoning 类型映射成 custom kind', () => {
    expect(src).toMatch(/msg\.type === 'reasoning'/)
    expect(src).toContain("kind: 'custom'")
  })
  it('custom slot 有 reasoning 折叠分支 + 思考过程 文案', () => {
    expect(src).toMatch(/streamCustom\(message\)\.sm\.type === 'reasoning'/)
    expect(src).toContain('思考过程')
  })
})
