import { describe, it, expect } from 'vitest'
import src from './CodingPage.vue?raw'

describe('CodingPage 换 session 告警', () => {
  it('有 showContextWarning 计算 + 依赖 contextWarnDismissed/ctxLevel', () => {
    expect(src).toMatch(/showContextWarning/)
    expect(src).toContain('contextWarnDismissed')
    expect(src).toMatch(/ctxLevel/)
  })
  it('banner 文案 + 一键新建会话按钮调 createWorkspaceConversation', () => {
    expect(src).toContain('建议新建会话')
    expect(src).toContain('一键新建会话')
    expect(src).toMatch(/createWorkspaceConversation/)
  })
  it('有关闭告警的处理', () => {
    expect(src).toMatch(/dismissContextWarn/)
  })
  it('conversationId watcher 切换会话时清 tokenUsage 和 contextWarnDismissed', () => {
    // 断言 watcher 回调体内同时包含两条清除语句，防止旧会话告警/百分比泄漏到新会话
    expect(src).toMatch(/watch\s*\(\s*\(\)\s*=>\s*codingStore\.conversationId[\s\S]{0,300}tokenUsage\s*=\s*null/)
    expect(src).toMatch(/watch\s*\(\s*\(\)\s*=>\s*codingStore\.conversationId[\s\S]{0,300}contextWarnDismissed\s*=\s*false/)
  })
})
