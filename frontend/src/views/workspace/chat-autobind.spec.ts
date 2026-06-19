// 对话 → 自动绑 workspace 的接线守卫(?raw)。
import { describe, expect, it } from 'vitest'
import chatPaneSrc from './ChatPane.vue?raw'
import shellSrc from './WorkspaceShell.vue?raw'

describe('chat → workspace auto-bind wiring', () => {
  it('ChatPane detects ws_id from messages and emits workspace-detected', () => {
    expect(chatPaneSrc).toContain('detectWorkspaceId')
    expect(chatPaneSrc).toContain("emit('workspace-detected'")
  })
  it('WorkspaceShell listens and upgrades binding (not over app, not over same ws)', () => {
    expect(shellSrc).toContain('@workspace-detected')
    expect(shellSrc).toContain('onWorkspaceDetected')
    expect(shellSrc).toMatch(/kind === 'app'[\s\S]*return/) // app 态不被覆盖
  })
})
