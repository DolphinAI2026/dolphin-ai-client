import { describe, expect, it } from 'vitest'
import sectionsSource from './SystemAssistantSessionSections.vue?raw'

describe('SystemAssistantSessionSections', () => {
  it('applies the shared active matcher to application sessions', () => {
    expect(sectionsSource).toContain('isApplicationSessionActive?: (session: RailSession) => boolean')
    expect(sectionsSource).toContain('function applicationSessionActive(session: CodeRailSession): boolean')
    expect(sectionsSource).toContain('activeApplicationShellSessionId?: string')
    expect(sectionsSource).toContain('activeApplicationRuntimeSessionId?: string')
    expect(sectionsSource).toContain("String(session.runtimeSessionId || '') === activeRuntimeSessionId")
    expect(sectionsSource).toContain(':class="{ active: applicationSessionActive(session) }"')
  })

  it('leaves scrolling to the single outer rail instead of nesting another scroll area', () => {
    expect(sectionsSource).toContain('display: flex; flex: 0 0 auto; flex-direction: column;')
    expect(sectionsSource).not.toContain('overflow-y: scroll')
  })

  it('lets users archive a conversation or remove an application group without deleting the project', () => {
    expect(sectionsSource).toContain("'rename-application-session'")
    expect(sectionsSource).toContain("'generate-application-session-title'")
    expect(sectionsSource).toContain('AI 生成标题')
    expect(sectionsSource).toContain("'archive-application-session'")
    expect(sectionsSource).toContain("'hide-application'")
    expect(sectionsSource).toContain('从侧边栏移除项目')
    expect(sectionsSource).toContain('归档会话')
  })

  it('shows three recent conversations per application and expands the remainder on demand', () => {
    expect(sectionsSource).toContain('const APPLICATION_VISIBLE_SESSION_LIMIT = 3')
    expect(sectionsSource).toContain('group.items.slice(0, APPLICATION_VISIBLE_SESSION_LIMIT)')
    expect(sectionsSource).toContain('v-for="session in visibleApplicationSessions(group)"')
    expect(sectionsSource).toContain('展开更多')
    expect(sectionsSource).toContain('收起较早会话')
  })

  it('keeps application names prominent and renders location metadata as icons', () => {
    expect(sectionsSource).toContain('class="sas-app-name"')
    expect(sectionsSource).not.toContain('class="sas-app-code"')
    expect(sectionsSource).toContain('name="globe"')
    expect(sectionsSource).toContain('name="laptop"')
    expect(sectionsSource).toContain("session.executionLocation === 'local' ? 'laptop' : 'globe'")
  })

  it('gives every system-assistant history row a subtle surface contrast', () => {
    expect(sectionsSource).toContain('background: #fbfcfe')
    expect(sectionsSource).toContain('border: 1px solid #edf1f5')
    expect(sectionsSource).toContain('html[data-theme="dark"] .sas-item { background: #182230')
  })
})
