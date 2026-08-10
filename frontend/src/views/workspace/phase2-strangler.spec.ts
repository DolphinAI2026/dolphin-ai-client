import { describe, expect, it } from 'vitest'
import routerSrc from '@/router/index.ts?raw'
import catalogSrc from '@/views/WorkspaceCatalogPage.vue?raw'

// SP2b(2026-06-25)三场景重新统一:自开发资产库(全代码开发)→ Code 应用入口
// Code 工作区统一走 /code/apps，不再生成已废弃的 /ai-chat?workspace_id&mode=code。
// CodingPage 与 /coding 路由保留(退役非删,SP3 清理),直接命中仍可渲染。
describe('catalog → Code 应用入口(SP2b 统一)', () => {
  it('keeps /coding route + CodingPage intact (retired, not deleted)', () => {
    expect(routerSrc).toContain("'@/views/CodingPage.vue'")
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
