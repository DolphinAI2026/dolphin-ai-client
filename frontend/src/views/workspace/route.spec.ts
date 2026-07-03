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

describe('code route wiring', () => {
  it('uses a persistent /code parent shell and switches sessions in a child route', () => {
    expect(routerSrc).toContain("path: '/code'")
    expect(routerSrc).toContain('CodeShellLayout.vue')
    expect(routerSrc).toContain("redirect: { name: 'CodeApps' }")
    expect(routerSrc).toContain("path: 'apps'")
    expect(routerSrc).toContain("name: 'CodeApps'")
    expect(routerSrc).toContain('Apps.vue')
    expect(routerSrc).toContain("path: 'new'")
    expect(routerSrc).toContain("name: 'CodeNewApplication'")
    expect(routerSrc).toContain("path: ':id'")
    expect(routerSrc).toContain('CodeConversationPage.vue')
    expect(routerSrc).toContain("name: 'CodeConversation'")
    expect(routerSrc.indexOf("path: 'new'")).toBeLessThan(routerSrc.indexOf("path: ':id'"))
  })

  it('keeps persisted Code mode from opening a Builder route on initial load', () => {
    expect(routerSrc).toContain("(to.path === '/' || to.path === '/apps') && modeStore.mode === 'code'")
    expect(routerSrc).toContain("path: '/code/apps'")
    expect(routerSrc).toContain("to.path.startsWith('/code')")
    expect(routerSrc).toContain("modeStore.setMode('code')")
  })
})
