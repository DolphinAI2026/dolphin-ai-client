import { describe, expect, it } from 'vitest'
import {
  appendLogLine,
  nextAfterSeq,
  mergeBySeq,
  isErrorLog,
  type LogLine,
} from './runDebugState'

describe('appendLogLine', () => {
  it('appends in order and dedupes by seq', () => {
    let ring: LogLine[] = []
    ring = appendLogLine(ring, { seq: 1, stream: 'stdout', line: 'a' })
    ring = appendLogLine(ring, { seq: 2, stream: 'stderr', line: 'b' })
    ring = appendLogLine(ring, { seq: 2, stream: 'stderr', line: 'b' }) // dup seq ignored
    expect(ring.map(l => l.seq)).toEqual([1, 2])
  })

  it('trims to the most recent maxLines', () => {
    let ring: LogLine[] = []
    for (let i = 1; i <= 5; i++) ring = appendLogLine(ring, { seq: i, stream: 'stdout', line: `l${i}` }, 3)
    expect(ring.map(l => l.seq)).toEqual([3, 4, 5])
  })
})

describe('nextAfterSeq', () => {
  it('returns the max seq seen, else the current cursor', () => {
    expect(nextAfterSeq([{ seq: 3 }, { seq: 7 }, { seq: 5 }], 0)).toBe(7)
    expect(nextAfterSeq([], 4)).toBe(4)
  })
})

describe('mergeBySeq', () => {
  it('concatenates only strictly-newer entries by seq', () => {
    const existing = [{ seq: 1 }, { seq: 2 }]
    const incoming = [{ seq: 2 }, { seq: 3 }]
    expect(mergeBySeq(existing, incoming).map(e => e.seq)).toEqual([1, 2, 3])
  })
})

describe('isErrorLog', () => {
  it('flags stderr and error-like text', () => {
    expect(isErrorLog({ seq: 1, stream: 'stderr', line: 'whatever' })).toBe(true)
    expect(isErrorLog({ seq: 2, stream: 'stdout', line: 'Module build failed' })).toBe(true)
    expect(isErrorLog({ seq: 3, stream: 'stdout', line: 'Compiled successfully' })).toBe(false)
  })
})
