import { describe, it, expect } from 'vitest'
import src from './CodingPage.vue?raw'
import storeSrc from '../stores/coding?raw'
import pipeSrc from './coding/useCodingPipeline.ts?raw'

describe('CodingPage token 显示接线', () => {
  it('store 有 tokenUsage + contextWarnDismissed', () => {
    expect(storeSrc).toMatch(/tokenUsage/)
    expect(storeSrc).toMatch(/contextWarnDismissed/)
  })
  it('done handler 写 tokenUsage(读 context_budget)', () => {
    expect(pipeSrc).toContain('context_budget')
    expect(pipeSrc).toMatch(/tokenUsage/)
  })
  it('CodingPage import util + footer 显示上下文/累计', () => {
    expect(src).toContain("from './coding/contextUsage'")
    expect(src).toContain('上下文')
    expect(src).toContain('累计')
    expect(src).toMatch(/formatTokenCount/)
  })
})
