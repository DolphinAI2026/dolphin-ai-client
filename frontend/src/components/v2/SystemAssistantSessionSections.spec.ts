import { describe, expect, it } from 'vitest'
import sectionsSource from './SystemAssistantSessionSections.vue?raw'

describe('SystemAssistantSessionSections', () => {
  it('applies the shared active matcher to application sessions', () => {
    expect(sectionsSource).toContain('isApplicationSessionActive?: (session: RailSession) => boolean')
    expect(sectionsSource).toContain('function applicationSessionActive(session: CodeRailSession): boolean')
    expect(sectionsSource).toContain('activeApplicationShellSessionId?: string')
    expect(sectionsSource).toContain('activeApplicationRuntimeSessionId?: string')
    expect(sectionsSource).toContain(':class="{ active: applicationSessionActive(session) }"')
  })

  it('lets a long conversation history scroll inside the rail', () => {
    expect(sectionsSource).toContain('min-height: 0; display: flex; flex: 1 1 auto;')
  })

  it('shows three recent conversations per application and expands the remainder on demand', () => {
    expect(sectionsSource).toContain('const APPLICATION_VISIBLE_SESSION_LIMIT = 3')
    expect(sectionsSource).toContain('group.items.slice(0, APPLICATION_VISIBLE_SESSION_LIMIT)')
    expect(sectionsSource).toContain('v-for="session in visibleApplicationSessions(group)"')
    expect(sectionsSource).toContain('展开更多')
    expect(sectionsSource).toContain('收起较早会话')
  })

  it('shows the application code alongside same-name application groups', () => {
    expect(sectionsSource).toContain('function applicationCode(group: CodeRailSessionGroup)')
    expect(sectionsSource).toContain("String(session.appCode || '').trim()")
    expect(sectionsSource).not.toContain('externalApplicationId || \'\'')
    expect(sectionsSource).toContain('class="sas-app-code"')
  })

  it('gives every system-assistant history row a subtle surface contrast', () => {
    expect(sectionsSource).toContain('background: #f8fafc')
    expect(sectionsSource).toContain('border: 1px solid #edf1f5')
    expect(sectionsSource).toContain('html[data-theme="dark"] .sas-item { background: #182230')
  })
})
