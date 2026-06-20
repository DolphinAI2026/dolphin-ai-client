import { describe, it, expect } from 'vitest'
import { formatTokenCount, contextRatio, contextLevel } from './contextUsage'

describe('formatTokenCount', () => {
  it('小于 1000 原样', () => { expect(formatTokenCount(0)).toBe('0'); expect(formatTokenCount(999)).toBe('999') })
  it('千位带 k 一位小数、去 .0', () => {
    expect(formatTokenCount(1234)).toBe('1.2k')
    expect(formatTokenCount(128000)).toBe('128k')
    expect(formatTokenCount(12345)).toBe('12.3k')
  })
})

describe('contextRatio', () => {
  it('正常比值', () => { expect(contextRatio(45000, 90000)).toBeCloseTo(0.5) })
  it('除零安全', () => { expect(contextRatio(100, 0)).toBe(0) })
})

describe('contextLevel', () => {
  it('分档边界', () => {
    expect(contextLevel(0.5)).toBe('ok')
    expect(contextLevel(0.79)).toBe('ok')
    expect(contextLevel(0.8)).toBe('warn')
    expect(contextLevel(0.99)).toBe('warn')
    expect(contextLevel(1.0)).toBe('danger')
    expect(contextLevel(1.5)).toBe('danger')
  })
})
