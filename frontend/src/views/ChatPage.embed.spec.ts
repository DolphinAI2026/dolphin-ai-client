// frontend/src/views/ChatPage.embed.spec.ts
import { describe, expect, it } from 'vitest'
import src from './ChatPage.vue?raw'

describe('ChatPage 内嵌原生编辑器', () => {
  it('设计 tab 用 InAppBrowser 内嵌编辑器', () => {
    expect(src).toContain('InAppBrowser')
    expect(src).toMatch(/mode="trusted-url"/)
  })
  it('编辑器 URL 来自 getEditorUrl', () => {
    expect(src).toContain('getEditorUrl')
    expect(src).toContain('embeddedEditorUrl')
  })
  it('CUSTOM 菜单仍走 CustomPagePreviewPanel', () => {
    expect(src).toContain('CustomPagePreviewPanel')
  })
  it('助手 refresh-iframe 接到内嵌编辑器 reload', () => {
    expect(src).toContain('editorBrowserRef')
    expect(src).toMatch(/editorBrowserRef[\s\S]{0,40}reload/)
  })
})
