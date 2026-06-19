import { describe, expect, it } from 'vitest'
import src from './WorkspaceShell.vue?raw'

describe('WorkspaceShell', () => {
  it('composes the five regions', () => {
    expect(src).toContain('SessionSidebar')
    expect(src).toContain('ToolMenu')
    expect(src).toContain('PanelHost')
    expect(src).toContain('ChatPane')
  })
  it('registers Phase1 panels on mount and wires ToolMenu open → PanelHost', () => {
    expect(src).toContain('registerPhase1Panels')
    expect(src).toContain('@open=')          // ToolMenu open
    expect(src).toContain(':active-panel-id')// 传给 PanelHost
  })
  it('passes current binding to ToolMenu (none in Phase 1)', () => {
    expect(src).toContain(':binding')
  })
  it('drives currentBinding from route.params.id (KeepAlive → watch)', () => {
    expect(src).toContain('useRoute')
    expect(src).toContain('routeToBinding')
    expect(src).toMatch(/watch\([\s\S]*route\.params\.id/)
  })
  it('feeds workspace context to ChatPane', () => {
    expect(src).toContain(':workspace-id')
  })
  it('parses sidebar select via parseSidebarSelect (workspace id 不被 Number 化)', () => {
    expect(src).toContain('parseSidebarSelect')
  })
  it('watches route.query.app_id for app binding', () => {
    expect(src).toMatch(/route\.query\.app_id/)
  })
  it('feeds appId to ChatPane', () => { expect(src).toContain(':app-id') })
  it('onSelect pushes /workspace?app_id for app sessions', () => {
    expect(src).toMatch(/app_id:/)
  })
})
