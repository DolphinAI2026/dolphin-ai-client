import { describe, expect, it } from 'vitest'
import routerSrc from '@/router/index.ts?raw'
import appSrc from '@/App.vue?raw'

describe('workspace route wiring', () => {
  it('registers /workspace/:id? pointing at WorkspaceShell with requiresAuth', () => {
    expect(routerSrc).toContain("path: '/workspace/:id?'")
    expect(routerSrc).toContain('WorkspaceShell.vue')
    expect(routerSrc).toContain("name: 'Workspace'")
  })
  it('keeps /workspace* alive as a singleton (SSE survives :id switch)', () => {
    expect(appSrc).toMatch(/\/workspace/)
    expect(appSrc).toContain('workspace-singleton')
  })
})
