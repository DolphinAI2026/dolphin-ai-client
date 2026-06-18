import { describe, expect, it } from 'vitest'
import { timeGroup, toSessionItems } from './sessionList'

const NOW = new Date('2026-06-19T12:00:00').getTime()

describe('timeGroup', () => {
  it('buckets by recency relative to now', () => {
    expect(timeGroup('2026-06-19T08:00:00', NOW)).toBe('今天')
    expect(timeGroup('2026-06-18T20:00:00', NOW)).toBe('昨天')
    expect(timeGroup('2026-06-15T10:00:00', NOW)).toBe('本周')
    expect(timeGroup(null, NOW)).toBe('更早')
  })
})

describe('toSessionItems', () => {
  it('sorts desc by updated_at, type-prefixes ids, sets badge tone by binding', () => {
    const items = toSessionItems([
      { id: 12, title: '旧对话', binding: { kind: 'none' }, updated_at: '2026-06-10T10:00:00' },
      { id: 7, title: '订单应用', binding: { kind: 'app', appId: 7 }, updated_at: '2026-06-19T09:00:00' },
    ], NOW)
    expect(items.map(i => i.id)).toEqual(['app:7', 'chat:12'])
    expect(items[0]).toMatchObject({ title: '订单应用', badgeTone: 'cowork', badgeLabel: '应用', group: '今天' })
    expect(items[1]).toMatchObject({ id: 'chat:12', badgeTone: 'chat', group: '本月' })
  })
})
