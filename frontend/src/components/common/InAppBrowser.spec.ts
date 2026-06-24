import { describe, expect, it } from 'vitest'
import src from './InAppBrowser.vue?raw'

describe('InAppBrowser 共享内嵌浏览器', () => {
  it('trusted-url 模式: iframe 用 :src 且不加 sandbox', () => {
    expect(src).toMatch(/mode\s*===?\s*'trusted-url'/)
    expect(src).toMatch(/<iframe[\s\S]*:src=/)
  })
  it('untrusted-html 模式: srcdoc + sandbox=allow-scripts(不含 allow-same-origin)', () => {
    expect(src).toContain(':srcdoc')
    const m = src.match(/sandbox="([^"]*allow-scripts[^"]*)"/)
    expect(m).toBeTruthy()
    expect(m![1]).not.toContain('allow-same-origin')
  })
  it('reload 用 key 强制重挂 iframe', () => {
    expect(src).toMatch(/:key="reloadKey"/)
    expect(src).toContain('function reload')
    expect(src).toContain('defineExpose')
  })
  it('提供「用系统浏览器打开」兜底', () => {
    expect(src).toContain('openExternal')
    expect(src).toContain('用系统浏览器打开')
  })
})
