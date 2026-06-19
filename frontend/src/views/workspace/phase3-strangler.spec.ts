import { describe, expect, it } from 'vitest'
import routerSrc from '@/router/index.ts?raw'
import appsSrc from '@/views/Apps.vue?raw'

describe('phase3 strangler', () => {
  it('keeps /chat route + ChatPage intact', () => {
    expect(routerSrc).toContain("'@/views/ChatPage.vue'")
  })

  it('Apps.openApp opens the unified workspace', () => {
    expect(appsSrc).toMatch(/openApp[\s\S]*path:\s*'\/workspace'/)
  })
})
