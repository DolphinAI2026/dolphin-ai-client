import { describe, expect, it } from 'vitest'
import src from './RunDebugPanel.vue?raw'

// 档1+档2(2026-06-19): 代码工作区预览位要有一键「启动预览」兜底(不依赖 agent 调
// run_workspace_preview)，且 serve 仍在编译(starting)时提示 + 自动重试加载，避免白屏。
describe('RunDebugPanel 一键预览', () => {
  it('一键启动走 codingApi.startServe，不依赖 agent', () => {
    expect(src).toContain('codingApi')
    expect(src).toContain('startServe')
    expect(src).toContain('启动预览')
  })

  it('startServe 拿不到 url 时用 port 本地兜底拼地址(防空头支票白屏)', () => {
    expect(src).toMatch(/r\.url\s*\|\|/)
    expect(src).toContain('http://127.0.0.1:')
  })

  it('serve 失败(status=error)先报错，不拿 port 兜底拼假地址吞掉报错', () => {
    // error 守卫必须在 port 兜底之前
    const errGuard = src.search(/status\s*===\s*'error'/)
    const fallback = src.search(/r\.port\s*\?/)
    expect(errGuard).toBeGreaterThan(-1)
    expect(fallback).toBeGreaterThan(-1)
    expect(errGuard).toBeLessThan(fallback)
  })

  it('手动预览标 source=panel(用于抑制无关的「抓取不可用」噪音)', () => {
    expect(src).toContain("source: 'panel'")
    expect(src).toContain('showCaptureDegrade')
    expect(src).toMatch(/source\s*!==\s*'panel'/)
  })

  it('卸载时清理 booting 定时器(防泄漏/卸载后触发)', () => {
    expect(src).toContain('onUnmounted')
    expect(src).toContain('clearTimeout')
  })

  it('starting(编译中)标启动态 + 自动重试加载 + 提供手动刷新', () => {
    expect(src).toContain('booting')
    expect(src).toMatch(/status\s*===\s*'ok'/)   // 区分 ready 与 starting
    expect(src).toContain('reload')
    expect(src).toContain('setTimeout')
  })

  it('iframe 用 key 强制重挂以刷新', () => {
    expect(src).toMatch(/<iframe[\s\S]*:key="reloadKey"/)
  })

  it('仍保留对话驱动预览(activePreview)的渲染', () => {
    expect(src).toContain('activePreview')
  })
})
