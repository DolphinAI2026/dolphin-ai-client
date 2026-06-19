import { describe, expect, it } from 'vitest'
import routerSrc from '@/router/index.ts?raw'
import catalogSrc from '@/views/WorkspaceCatalogPage.vue?raw'

// 2026-06-19 三场景重新分开: 撤掉统一工作区入口改道。
// 自开发资产库(全代码开发) → 代码工作区 /coding?workspace_id=...，不再进 /workspace。
describe('catalog → /coding (全代码开发场景分开)', () => {
  it('keeps /coding route + CodingPage intact', () => {
    expect(routerSrc).toContain("'@/views/CodingPage.vue'")
  })
  it('catalog opens workspaces in the code workspace (/coding), not the unified shell', () => {
    expect(catalogSrc).toMatch(/push\(\{\s*path:\s*'\/coding'/)
    expect(catalogSrc).not.toContain("'/workspace/'")
  })
})
