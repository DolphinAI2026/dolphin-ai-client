import { describe, expect, it } from 'vitest'
import {
  normalizeAiSessions,
  normalizeCodingSessions,
  railSessionTarget,
  isRailSessionActive,
  railSessionFallback,
} from './railSessions'

describe('rail session normalization', () => {
  it('maps AI Builder sessions to the common rail shape with app name', () => {
    const out = normalizeAiSessions([
      { id: 7, title: '配置 CRM', updated_at: '2026-06-21T10:00:00Z', generation: { app_name: '销售管理' } } as any,
      { id: 8, title: '', updated_at: '2026-06-20T10:00:00Z' } as any,
    ])
    expect(out).toEqual([
      { id: 7, title: '配置 CRM', updatedAt: '2026-06-21T10:00:00Z', appName: '销售管理' },
      { id: 8, title: '未命名会话', updatedAt: '2026-06-20T10:00:00Z', appName: undefined },
    ])
  })

  it('maps coding conversations, falling back updatedAt to created_at and titling empties', () => {
    const out = normalizeCodingSessions([
      { id: 3, title: '招聘后台', updated_at: '2026-06-21T09:00:00Z', created_at: '2026-06-19T09:00:00Z' } as any,
      { id: 4, title: '', created_at: '2026-06-18T09:00:00Z' } as any,
    ])
    expect(out).toEqual([
      { id: 3, title: '招聘后台', updatedAt: '2026-06-21T09:00:00Z', appName: undefined },
      { id: 4, title: '开发会话 #4', updatedAt: '2026-06-18T09:00:00Z', appName: undefined },
    ])
  })

  it('tolerates null/undefined input lists', () => {
    expect(normalizeAiSessions(undefined as any)).toEqual([])
    expect(normalizeCodingSessions(null as any)).toEqual([])
  })
})

describe('rail session navigation target', () => {
  it('routes builder/agent sessions to the /ai-chat/:id page', () => {
    expect(railSessionTarget('builder', 42)).toEqual({ path: '/ai-chat/42' })
    expect(railSessionTarget('agent', 42)).toEqual({ path: '/ai-chat/42' })
  })

  it('routes code sessions to /ai-chat/:id too (统一外壳,AIChatPage 按 mode 挂 CodexPanelHost)', () => {
    expect(railSessionTarget('code', 42)).toEqual({ path: '/ai-chat/42' })
  })
})

describe('rail session active state', () => {
  it('highlights the builder/agent session by path', () => {
    expect(isRailSessionActive('builder', 9, { path: '/ai-chat/9', query: {} })).toBe(true)
    expect(isRailSessionActive('builder', 9, { path: '/ai-chat/10', query: {} })).toBe(false)
  })

  it('highlights the code session by /ai-chat/:id path too', () => {
    expect(isRailSessionActive('code', 9, { path: '/ai-chat/9', query: {} })).toBe(true)
    expect(isRailSessionActive('code', 9, { path: '/ai-chat/10', query: {} })).toBe(false)
    expect(isRailSessionActive('code', 9, { path: '/coding', query: {} })).toBe(false)
  })
})

describe('rail session fallback after delete', () => {
  it('falls back to home for all modes (统一外壳)', () => {
    expect(railSessionFallback('builder')).toBe('/')
    expect(railSessionFallback('agent')).toBe('/')
    expect(railSessionFallback('code')).toBe('/')
  })
})
