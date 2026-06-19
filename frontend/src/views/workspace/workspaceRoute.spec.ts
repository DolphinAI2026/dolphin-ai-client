import { describe, expect, it } from 'vitest'
import { routeToBinding, parseSidebarSelect } from './workspaceRoute'

describe('routeToBinding', () => {
  it('maps a route id to a workspace binding', () => {
    expect(routeToBinding('1_8ae94ab4')).toEqual({ kind: 'workspace', workspaceId: '1_8ae94ab4' })
  })
  it('maps empty/undefined route id to none (通用对话)', () => {
    expect(routeToBinding(undefined)).toEqual({ kind: 'none' })
    expect(routeToBinding('')).toEqual({ kind: 'none' })
  })
})

describe('parseSidebarSelect', () => {
  it('parses chat: prefix to a numeric session id', () => {
    expect(parseSidebarSelect('chat:123')).toEqual({ kind: 'none', sessionId: 123, workspaceId: null })
  })
  it('parses workspace: prefix to a string workspace id (NOT number)', () => {
    expect(parseSidebarSelect('workspace:1_8ae94ab4')).toEqual({ kind: 'workspace', sessionId: null, workspaceId: '1_8ae94ab4' })
  })
})
