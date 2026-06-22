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

// 2026-06-22: /coding 用稳定 key 不 remount 后, 换会话/工作区靠监听 query 原地切(不闪)。
describe('CodingPage switches sessions in-place via a route watcher (no remount)', () => {
  it('has a reusable route-session resolver called from onMounted', () => {
    expect(src).toContain('resolveCodingRouteSession')
  })

  it('watches the route query to switch sessions in-place', () => {
    // watcher getter 串联 conversation_id + workspace_id 作为变化键
    expect(src).toContain('route.query.conversation_id ??')
    expect(src).toMatch(/watch\(\s*\(\)\s*=>\s*`\$\{route\.query\.conversation_id/s)
  })
})
