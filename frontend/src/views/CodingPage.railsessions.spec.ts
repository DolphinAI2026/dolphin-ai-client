import { describe, it, expect } from 'vitest'
import src from './CodingPage.vue?raw'

// Code 模式会话收进全局左栏(RailSidebar)后, 页面内层 SessionSidebar 不再渲染。
describe('CodingPage 会话收进全局左栏', () => {
  it('defines the useRailSessions flag (true)', () => {
    expect(src).toMatch(/const useRailSessions\s*=\s*true/)
  })

  it('gates the inner SessionSidebar with !useRailSessions', () => {
    expect(src).toMatch(/v-if="!embedMode && !embeddedAppId && !codeFirst && !useRailSessions"/)
  })

  it('still consumes ?conversation_id= from the route (rail navigates here)', () => {
    expect(src).toContain('route.query.conversation_id')
  })
})
