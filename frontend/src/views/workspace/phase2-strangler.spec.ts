import { describe, expect, it } from 'vitest'
import routerSrc from '@/router/index.ts?raw'
import catalogSrc from '@/views/WorkspaceCatalogPage.vue?raw'

// SP2b(2026-06-25)三场景重新统一:自开发资产库(全代码开发)→ 统一外壳
// /ai-chat?workspace_id&mode=code,不再走独立 /coding 标签。
// CodingPage 与 /coding 路由保留(退役非删,SP3 清理),直接命中仍可渲染。
describe('catalog → /ai-chat 统一外壳(SP2b 统一)', () => {
  it('keeps /coding route + CodingPage intact (retired, not deleted)', () => {
    expect(routerSrc).toContain("'@/views/CodingPage.vue'")
  })
  it('catalog opens workspaces in the unified shell (/ai-chat, mode=code), not /coding', () => {
    expect(catalogSrc).toMatch(/push\(\{\s*path:\s*'\/ai-chat'/)
    expect(catalogSrc).toMatch(/mode:\s*'code'/)
    expect(catalogSrc).not.toMatch(/push\(\{\s*path:\s*'\/coding'/)
  })
})
