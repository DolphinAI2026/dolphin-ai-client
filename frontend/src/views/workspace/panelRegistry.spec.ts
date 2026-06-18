import { describe, expect, it, beforeEach } from 'vitest'
import { registerPanel, listPanels, isAvailable, buildToolMenuItems, resetRegistryForTest } from './panelRegistry'

const stubComp = {} as any

beforeEach(() => resetRegistryForTest())

describe('panelRegistry', () => {
  it('lists panels in registration order', () => {
    registerPanel({ id: 'a', label: 'A', icon: 'x', group: 'common', availableWhen: () => true, component: stubComp })
    registerPanel({ id: 'b', label: 'B', icon: 'y', group: 'context', availableWhen: () => false, component: stubComp })
    expect(listPanels().map(p => p.id)).toEqual(['a', 'b'])
  })

  it('isAvailable delegates to the panel predicate against the binding', () => {
    const p = { id: 'files', label: 'Files', icon: 'f', group: 'context' as const,
      availableWhen: (b: any) => b.kind === 'workspace', component: stubComp }
    expect(isAvailable(p, { kind: 'workspace', workspaceId: 'w' })).toBe(true)
    expect(isAvailable(p, { kind: 'none' })).toBe(false)
  })

  it('buildToolMenuItems renders the full set with enabled flags per binding', () => {
    registerPanel({ id: 'artifacts', label: '产物', icon: 'doc', group: 'common', availableWhen: () => true, component: stubComp })
    registerPanel({ id: 'files', label: 'Files', icon: 'f', group: 'context',
      availableWhen: (b) => b.kind === 'workspace', component: stubComp })
    const none = buildToolMenuItems({ kind: 'none' })
    expect(none.map(i => [i.id, i.enabled])).toEqual([['artifacts', true], ['files', false]])
    const ws = buildToolMenuItems({ kind: 'workspace', workspaceId: 'w' })
    expect(ws.find(i => i.id === 'files')!.enabled).toBe(true)
  })

  it('availableWhen throwing or unknown binding degrades to disabled, never throws', () => {
    registerPanel({ id: 'boom', label: 'B', icon: 'b', group: 'context',
      availableWhen: () => { throw new Error('x') }, component: stubComp })
    expect(() => buildToolMenuItems({ kind: 'none' })).not.toThrow()
    expect(buildToolMenuItems({ kind: 'none' })[0].enabled).toBe(false)
  })
})
