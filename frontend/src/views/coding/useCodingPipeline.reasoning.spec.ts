import { describe, it, expect } from 'vitest'
import pipeSrc from './useCodingPipeline.ts?raw'
import streamSrc from './useStreamMessages.ts?raw'

describe('reasoning 分流', () => {
  it('useStreamMessages 有 appendToLastReasoning(找/建 reasoning 卡)', () => {
    expect(streamSrc).toMatch(/appendToLastReasoning/)
    expect(streamSrc).toContain("'reasoning'")
  })
  it('useCodingPipeline 按 parsed.reasoning 分流', () => {
    expect(pipeSrc).toMatch(/parsed\.reasoning/)
    expect(pipeSrc).toMatch(/appendToLastReasoning/)
  })
})
