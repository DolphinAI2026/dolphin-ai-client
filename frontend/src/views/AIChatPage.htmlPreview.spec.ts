import { describe, expect, it } from 'vitest'
import src from './AIChatPage.vue?raw'

describe('AIChatPage 设计稿 HTML 预览', () => {
  it('HTML 产物 iframe 放开脚本(allow-scripts)让多页能切', () => {
    const frame = src.slice(src.indexOf('art-preview-frame'))
    const sandbox = frame.match(/sandbox="([^"]*)"/)?.[1] || ''
    expect(sandbox).toContain('allow-scripts')
  })
  it('安全: 放开脚本时绝不同时给 allow-same-origin(防读父页 token)', () => {
    const frame = src.slice(src.indexOf('art-preview-frame'))
    const sandbox = frame.match(/sandbox="([^"]*)"/)?.[1] || ''
    if (sandbox.includes('allow-scripts')) {
      expect(sandbox).not.toContain('allow-same-origin')
    }
  })

  it('Code 输入框底栏显示本地或远程工作区的最后一级目录', () => {
    expect(src).toContain('codeWorkspaceContext')
    expect(src).toContain('本地目录')
    expect(src).toContain('远程目录')
    expect(src).toContain('code-workspace-context')
  })
})
