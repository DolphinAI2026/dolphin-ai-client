import { describe, expect, it, beforeEach } from 'vitest'
import { resetRegistryForTest, buildToolMenuItems } from './panelRegistry'
import { registerPhase1Panels } from './panels'

beforeEach(() => resetRegistryForTest())

describe('registerPhase1Panels', () => {
  it('registers the code panel for workspace binding (replaces stub)', () => {
    registerPhase1Panels()
    const none = buildToolMenuItems({ kind: 'none' })
    const byId = Object.fromEntries(none.map(i => [i.id, i.enabled]))
    expect('stub-code' in byId).toBe(false)
    expect(byId['code']).toBe(false)                 // none 绑定 → 代码面板灰
    const ws = buildToolMenuItems({ kind: 'workspace', workspaceId: 'w' })
    expect(ws.find(i => i.id === 'code')!.enabled).toBe(true)  // workspace → 亮
  })
  it('registers the config panel for app binding', () => {
    registerPhase1Panels()
    const none = buildToolMenuItems({ kind: 'none' })
    expect(none.find(i => i.id === 'config')!.enabled).toBe(false)
    const app = buildToolMenuItems({ kind: 'app', appId: 7 })
    expect(app.find(i => i.id === 'config')!.enabled).toBe(true)
    const ws = buildToolMenuItems({ kind: 'workspace', workspaceId: 'w' })
    expect(ws.find(i => i.id === 'config')!.enabled).toBe(false)   // workspace 态配置面板灰
  })
  it('registers the preview panel for workspace binding', () => {
    registerPhase1Panels()
    expect(buildToolMenuItems({ kind: 'none' }).find(i => i.id === 'preview')!.enabled).toBe(false)
    expect(buildToolMenuItems({ kind: 'app', appId: 7 }).find(i => i.id === 'preview')!.enabled).toBe(false)
    expect(buildToolMenuItems({ kind: 'workspace', workspaceId: 'w' }).find(i => i.id === 'preview')!.enabled).toBe(true)
  })
  it('is idempotent (safe to call twice / HMR)', () => {
    registerPhase1Panels(); registerPhase1Panels()
    const ids = buildToolMenuItems({ kind: 'none' }).map(i => i.id)
    expect(new Set(ids).size).toBe(ids.length)
  })
})
