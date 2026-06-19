import { describe, expect, it } from 'vitest'
import routerSrc from '@/router/index.ts?raw'
import catalogSrc from '@/views/WorkspaceCatalogPage.vue?raw'

describe('phase2 strangler', () => {
  it('keeps /coding route + CodingPage intact', () => {
    expect(routerSrc).toContain("'@/views/CodingPage.vue'")
  })
  it('catalog opens workspaces in the unified shell (/workspace), not /coding', () => {
    expect(catalogSrc).toContain("'/workspace/'")
    expect(catalogSrc).not.toMatch(/push\(\{\s*path:\s*'\/coding'/)
  })
})
