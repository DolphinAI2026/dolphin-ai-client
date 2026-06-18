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
})
