import { describe, it, expect } from 'vitest'
import src from './App.vue?raw'

// 2026-06-22: 修「Code 切会话抖动」—— /coding 之前走 v-else 的 :key="$route.fullPath",
// query(conversation_id/workspace_id)一变就整页 remount → 闪。给 /coding 稳定 key 复用实例,
// 换会话由 CodingPage 监听 query 原地切。
describe('App routing keys /coding stably (no remount on session switch)', () => {
  it('routes /coding through a stable key, not $route.fullPath', () => {
    expect(src).toContain('isCodingRoute')
    expect(src).toContain('coding-stable')
  })
})
