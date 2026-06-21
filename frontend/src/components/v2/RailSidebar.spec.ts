import { describe, expect, it } from 'vitest'
import railSidebarSource from './RailSidebar.vue?raw'

describe('RailSidebar brand mark', () => {
  it('uses the Ruijing whale mark in the rail logo', () => {
    expect(railSidebarSource).toContain('ruijing-whale-mark.svg')
    expect(railSidebarSource).toContain('rail-logo-mark')
    expect(railSidebarSource).not.toContain('<rect x="3" y="3" width="8" height="8"')
    expect(railSidebarSource).not.toContain('AI · 低代码')
  })
})

// Code 模式会话收进左栏(2026-06-21): rail 按当前模式切换会话源
// (builder/agent→aiChatApi, code→codingApi), 归一逻辑见 composables/railSessions。
describe('RailSidebar session source switches by mode', () => {
  it('pulls coding conversations as a session source', () => {
    expect(railSidebarSource).toContain("from '@/api/coding'")
    expect(railSidebarSource).toContain('codingApi.getConversations()')
  })

  it('delegates normalization + routing to the railSessions composable', () => {
    expect(railSidebarSource).toContain("from '@/composables/railSessions'")
    expect(railSidebarSource).toContain('normalizeCodingSessions')
    expect(railSidebarSource).toContain('railSessionTarget(currentMode.value')
  })

  it('shows the recent-session list in every mode (no longer excludes code)', () => {
    expect(railSidebarSource).not.toContain("currentMode.value !== 'code'")
  })
})
