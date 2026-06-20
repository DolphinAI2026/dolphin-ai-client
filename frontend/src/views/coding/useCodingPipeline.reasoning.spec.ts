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
  it('agent_thinking_delta: reasoning 和 content 走互斥分支', () => {
    // parsed.reasoning=true → appendToLastReasoning; else → appendToLastThinking
    // 两者必须出现在同一个 if/else 结构里，互不交叉
    expect(pipeSrc).toMatch(/if \(parsed\.reasoning\) appendToLastReasoning/)
    expect(pipeSrc).toMatch(/else appendToLastThinking/)
  })
  it('appendToLastReasoning 反向查找最后一张 reasoning 卡(interleave 防碎片)', () => {
    // 必须用 reverse().find() 而不是只看尾部
    expect(streamSrc).toMatch(/\.reverse\(\)\.find/)
    // 查找条件必须是 type === 'reasoning'
    expect(streamSrc).toMatch(/m\.type === 'reasoning'/)
  })
  it('agent_thinking reasoning 分支也用反向查找', () => {
    expect(pipeSrc).toMatch(/\.reverse\(\)\.find/)
    expect(pipeSrc).toMatch(/m\.type === 'reasoning'/)
  })
})
