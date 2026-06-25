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

// SP2b(2026-06-25): rail 会话统一单一来源 aiChatApi(含 code 会话, Task6 放行后一起列出),
// 不再按 mode 切换 codingApi/aiChatApi 双源; 路由经 railSessions 组合式恒落 /ai-chat。
describe('RailSidebar unified session source (SP2b)', () => {
  it('uses a single aiChatApi session source (no codingApi)', () => {
    expect(railSidebarSource).toContain("from '@/api/aiChat'")
    expect(railSidebarSource).toContain('aiChatApi.listSessions()')
    expect(railSidebarSource).not.toContain("from '@/api/coding'")
    expect(railSidebarSource).not.toContain('codingApi.getConversations()')
  })

  it('delegates normalization + routing to the railSessions composable', () => {
    expect(railSidebarSource).toContain("from '@/composables/railSessions'")
    expect(railSidebarSource).toContain('normalizeAiSessions')
    expect(railSidebarSource).toContain('railSessionTarget(')
  })

  it('shows the recent-session list in every mode (no longer excludes code)', () => {
    expect(railSidebarSource).not.toContain("currentMode.value !== 'code'")
  })
})
