import { describe, expect, it } from 'vitest'
import type { LocationQueryRaw } from 'vue-router'
import {
  normalizeAiSessions,
  normalizeCodeRailHistory,
  normalizeCodingSessions,
  nextAgentQuery,
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

  it('keeps the local application id for Builder application-group actions', () => {
    const out = normalizeAiSessions([
      { id: 17, title: '继续配置', app_id: 49, generation: { app_name: '客户管理' } } as any,
    ])
    expect(out[0]).toMatchObject({ id: 17, appId: 49, appName: '客户管理' })
  })

  it('derives the Builder application id from generation metadata for legacy sessions', () => {
    const out = normalizeAiSessions([
      { id: 18, title: '历史会话', generation: { app_id: 51, app_name: '采购管理' } } as any,
    ])
    expect(out[0]).toMatchObject({ appId: 51, appName: '采购管理' })
  })

  it('groups Code sessions by the external d-ai-code application name', () => {
    const out = normalizeAiSessions([
      {
        id: 9,
        title: '客户门户 Code',
        updated_at: '2026-06-30T10:00:00Z',
        mode: 'code',
        app_id: null,
        external_application_id: 'code-app-1',
        external_app_name: '客户门户',
        external_app_code: 'crm_portal',
      } as any,
    ])

    expect(out).toEqual([
      { id: 9, title: '客户门户 Code', updatedAt: '2026-06-30T10:00:00Z', appName: '客户门户' },
    ])
  })

  it('keeps one Code rail session per external application using the newest shell session', () => {
    const out = normalizeAiSessions([
      {
        id: 9,
        title: 'CRM Code',
        updated_at: '2026-06-30T10:00:00Z',
        mode: 'code',
        external_application_id: 'crm',
        external_app_name: 'CRM',
      } as any,
      {
        id: 12,
        title: 'CRM Code',
        updated_at: '2026-07-01T10:00:00Z',
        mode: 'code',
        external_application_id: 'crm',
        external_app_name: 'CRM',
      } as any,
      {
        id: 13,
        title: 'ERP Code',
        updated_at: '2026-07-01T09:00:00Z',
        mode: 'code',
        external_application_id: 'erp',
        external_app_name: 'ERP',
      } as any,
    ])

    expect(out).toEqual([
      { id: 12, title: 'CRM Code', updatedAt: '2026-07-01T10:00:00Z', appName: 'CRM' },
      { id: 13, title: 'ERP Code', updatedAt: '2026-07-01T09:00:00Z', appName: 'ERP' },
    ])
  })

  it('maps opened Code runtime agent sessions into application grouped rail items', () => {
    const out = normalizeCodeRailHistory({
      apps: [
        {
          shell_session_id: 'e9a6aa2a-9043-4bb5-bb5d-6d764c5fbfa3',
          external_application_id: 'crm',
          app_name: 'CRM',
          app_code: 'crm',
          runtime_session_id: 'runtime-1',
          sessions: [
            {
              runtimeSessionId: 'runtime-2',
              title: '修复登录问题',
              state: 'waiting_input',
              lastActiveAt: '2026-07-01T07:00:00Z',
              current: false,
            },
            {
              runtimeSessionId: 'runtime-1',
              title: '',
              state: 'busy',
              lastActiveAt: '2026-07-01T06:30:00Z',
              current: true,
            },
          ],
        },
      ],
    } as any)

    expect(out).toEqual([
      {
        id: 'runtime-2',
        title: '修复登录问题',
        updatedAt: '2026-07-01T07:00:00Z',
        appName: 'CRM',
        shellSessionId: 'e9a6aa2a-9043-4bb5-bb5d-6d764c5fbfa3',
        runtimeSessionId: 'runtime-2',
        current: false,
        source: 'code-agent',
      },
      {
        id: 'runtime-1',
        title: '会话 1',
        updatedAt: '2026-07-01T06:30:00Z',
        appName: 'CRM',
        shellSessionId: 'e9a6aa2a-9043-4bb5-bb5d-6d764c5fbfa3',
        runtimeSessionId: 'runtime-1',
        current: true,
        source: 'code-agent',
      },
    ])
  })

  it('maps shell-only Code applications into clickable rail sessions', () => {
    const out = normalizeCodeRailHistory({
      apps: [
        {
          shell_session_id: 'e9a6aa2a-9043-4bb5-bb5d-6d764c5fbfa3',
          external_application_id: 'crm',
          app_name: 'CRM',
          app_code: 'crm',
          runtime_session_id: null,
          sessions: [],
        },
      ],
    } as any)

    expect(out).toEqual([
      {
        id: 'e9a6aa2a-9043-4bb5-bb5d-6d764c5fbfa3',
        title: 'CRM Code',
        updatedAt: undefined,
        appName: 'CRM',
        shellSessionId: 'e9a6aa2a-9043-4bb5-bb5d-6d764c5fbfa3',
        runtimeSessionId: undefined,
        current: false,
        source: 'code-shell',
      },
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

  it('routes code shell sessions to the embedded Code page', () => {
    expect(railSessionTarget('code', { id: 42, title: 'CRM Code' })).toEqual({ path: '/code/42' })
  })

  it('keeps a Code session execution location in the route', () => {
    expect(railSessionTarget('code', {
      id: 'shell-remote',
      title: 'CRM Code',
      executionLocation: 'remote',
    } as any)).toEqual({
      path: '/code/shell-remote',
      query: { source: 'remote' },
    })
  })

  it('routes code runtime agent sessions through their shell session with runtime query', () => {
    expect(railSessionTarget('code', {
      id: 'runtime-2',
      title: '修复登录问题',
      shellSessionId: 'e9a6aa2a-9043-4bb5-bb5d-6d764c5fbfa3',
      runtimeSessionId: 'runtime-2',
      source: 'code-agent',
    })).toEqual({
      path: '/code/e9a6aa2a-9043-4bb5-bb5d-6d764c5fbfa3',
      query: { agent: 'runtime-2' },
    })
  })

  it('preserves tenantId and other query values while replacing or removing agent', () => {
    const currentQuery = {
      tenantId: 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
      agent: 'runtime-old',
      panel: 'activity',
      repeated: ['one', null, 'two'],
      empty: null,
    } satisfies LocationQueryRaw
    const replaced: LocationQueryRaw = nextAgentQuery(currentQuery, 'runtime-new')
    const removed: LocationQueryRaw = nextAgentQuery(currentQuery)

    expect(replaced).toEqual({
      tenantId: 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
      agent: 'runtime-new',
      panel: 'activity',
      repeated: ['one', null, 'two'],
      empty: null,
    })
    expect(removed).toEqual({
      tenantId: 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
      panel: 'activity',
      repeated: ['one', null, 'two'],
      empty: null,
    })
  })

  it('preserves the current query when building a Code rail target', () => {
    expect(railSessionTarget('code', {
      id: 'runtime-2',
      title: '修复登录问题',
      shellSessionId: 'shell-1',
      runtimeSessionId: 'runtime-2',
      source: 'code-agent',
    }, {
      tenantId: 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
      agent: 'runtime-old',
      panel: 'activity',
    })).toEqual({
      path: '/code/shell-1',
      query: {
        tenantId: 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
        agent: 'runtime-2',
        panel: 'activity',
      },
    })
  })

  it('does not carry the embedded CodingPage navigation flag into Code routes', () => {
    expect(nextAgentQuery({ embed_nav: '0', panel: 'activity' })).toEqual({
      panel: 'activity',
    })
    expect(railSessionTarget('code', 42, { embed_nav: '0' })).toEqual({
      path: '/code/42',
    })
  })
})

describe('rail session active state', () => {
  it('highlights the builder/agent session by path', () => {
    expect(isRailSessionActive('builder', 9, { path: '/ai-chat/9', query: {} })).toBe(true)
    expect(isRailSessionActive('builder', 9, { path: '/ai-chat/10', query: {} })).toBe(false)
  })

  it('highlights the code session by /code/:id path', () => {
    const shell = { id: 9, title: 'CRM Code' }
    expect(isRailSessionActive('code', shell, { path: '/code/9', query: {} })).toBe(true)
    expect(isRailSessionActive('code', shell, { path: '/code/10', query: {} })).toBe(false)
    expect(isRailSessionActive('code', shell, { path: '/coding', query: {} })).toBe(false)
  })

  it('highlights code runtime agent sessions by shell path and runtime query', () => {
    const item = {
      id: 'runtime-2',
      title: '修复登录问题',
      shellSessionId: 'e9a6aa2a-9043-4bb5-bb5d-6d764c5fbfa3',
      runtimeSessionId: 'runtime-2',
      source: 'code-agent',
    } as const
    expect(isRailSessionActive('code', item, {
      path: '/code/e9a6aa2a-9043-4bb5-bb5d-6d764c5fbfa3',
      query: { agent: 'runtime-2' },
    })).toBe(true)
    expect(isRailSessionActive('code', item, {
      path: '/code/e9a6aa2a-9043-4bb5-bb5d-6d764c5fbfa3',
      query: { agent: 'runtime-1' },
    })).toBe(false)
    expect(isRailSessionActive('code', item, {
      path: '/code/e9a6aa2a-9043-4bb5-bb5d-6d764c5fbfa3',
      query: { agent: ['runtime-2', 'stale-runtime'] },
    })).toBe(true)
    expect(isRailSessionActive('code', item, { path: '/code/11', query: { agent: 'runtime-2' } })).toBe(false)
  })
})

describe('rail session fallback after delete', () => {
  it('falls back to home for all modes (统一外壳)', () => {
    expect(railSessionFallback('builder')).toBe('/')
    expect(railSessionFallback('agent')).toBe('/')
    expect(railSessionFallback('code')).toBe('/code/apps')
  })
})
