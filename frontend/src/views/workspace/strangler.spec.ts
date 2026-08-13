import { describe, expect, it } from 'vitest'
import routerSrc from '@/router/index.ts?raw'

describe('strangler: old pages untouched in Phase 1', () => {
  it('keeps legacy page implementations available for compatibility', () => {
    expect(routerSrc).toContain("'@/views/AIChatPage.vue'")
    expect(routerSrc).toContain("'@/views/ChatPage.vue'")
    expect(routerSrc).toContain("'@/views/CodingPage.vue'")
  })
})
