import { describe, expect, it, beforeEach } from 'vitest'
import { resetRegistryForTest, buildToolMenuItems } from './panelRegistry'
import { registerPhase1Panels } from './panels'

beforeEach(() => resetRegistryForTest())

describe('registerPhase1Panels', () => {
  it('registers common panels always-on and the stub code panel only for workspace binding', () => {
    registerPhase1Panels()
    const none = buildToolMenuItems({ kind: 'none' })
    const byId = Object.fromEntries(none.map(i => [i.id, i.enabled]))
    expect(byId['artifacts']).toBe(true)
    expect(byId['background-tasks']).toBe(true)
    expect(byId['plan']).toBe(true)
    expect(byId['stub-code']).toBe(false)               // none 绑定 → 代码面板灰
    const ws = buildToolMenuItems({ kind: 'workspace', workspaceId: 'w' })
    expect(ws.find(i => i.id === 'stub-code')!.enabled).toBe(true)  // workspace → 亮
  })
  it('is idempotent (safe to call twice / HMR)', () => {
    registerPhase1Panels(); registerPhase1Panels()
    const ids = buildToolMenuItems({ kind: 'none' }).map(i => i.id)
    expect(new Set(ids).size).toBe(ids.length)
  })
})
