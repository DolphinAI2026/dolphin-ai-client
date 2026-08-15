import { describe, expect, it } from 'vitest'
import routerSrc from '@/router/index.ts?raw'
import catalogSrc from '@/views/WorkspaceCatalogPage.vue?raw'

// SP2b(2026-06-25)三场景重新统一:自开发资产库(全代码开发)→ Code 应用入口
// Code 工作区统一走 /code/apps，不再生成已废弃的 /ai-chat?workspace_id&mode=code。
// CodingPage 与 /coding 路由保留给工作区预览 iframe；用户直接命中旧入口会过期跳转。
describe('catalog → Code 应用入口(SP2b 统一)', () => {
  it('keeps the legacy CodingPage only as an embedded preview route', () => {
    expect(routerSrc).toContain("'@/views/CodingPage.vue'")
    expect(routerSrc).toContain("deprecated: true")
    expect(routerSrc).toContain("String(to.query.embed || '') === 'true'")
    expect(routerSrc).toContain("next({ path: '/code/apps', replace: true })")
  })
  it('does not expose the legacy page as a user-facing Code entry', () => {
    expect(routerSrc).toContain("if (String(to.query.embed || '') === 'true')")
    expect(routerSrc).toContain("next({ path: '/code/apps', replace: true })")
  })
  it('catalog opens workspaces in the Code app list, not the legacy Builder code mode', () => {
    expect(catalogSrc).toMatch(/push\(\{\s*path:\s*'\/code\/apps'/)
    expect(catalogSrc).not.toMatch(/mode:\s*'code'/)
    expect(catalogSrc).not.toMatch(/push\(\{\s*path:\s*'\/coding'/)
  })

  it('keeps the Builder route but redirects the expired code query', () => {
    expect(routerSrc).toContain("String(to.query.mode || '') === 'code'")
    expect(routerSrc).toContain("next({ path: '/code/apps' })")
  })
})
