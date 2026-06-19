import { describe, expect, it } from 'vitest'
import src from './CodingPage.vue?raw'
import pipelineSrc from './coding/useCodingPipeline.ts?raw'

describe('useCodingPipeline run_result', () => {
  it('agent 跑预览(run_result)时递增 previewEpoch 以触发自动切预览位', () => {
    expect(pipelineSrc).toContain('previewEpoch++')
    // epoch 递增必须落在 run_result 段内(run_result: 之后、autofix_round: handler 之前),
    // 自愈轮不递增 → 不反复打断用户。
    const runResultAt = pipelineSrc.indexOf('run_result:')
    const epochAt = pipelineSrc.indexOf('previewEpoch++')
    const autofixHandlerAt = pipelineSrc.indexOf('autofix_round:')
    expect(runResultAt).toBeGreaterThan(-1)
    expect(epochAt).toBeGreaterThan(runResultAt)
    expect(epochAt).toBeLessThan(autofixHandlerAt)
  })
})

// 2026-06-19: 预览呈现修复 —— agent 已能主动跑预览, 但结果以裸链接呈现, 点了在 Tauri
// webview 里把主界面导航走(回不去)。修: ①预览结果到达自动切「预览」位 ②对话链接拦截
// (localhost 预览→聚焦预览位 / 外链→系统浏览器, 主界面永不被导航)。
describe('CodingPage 预览呈现', () => {
  it('对话区拦截链接点击(click.capture → onChatClick)', () => {
    expect(src).toMatch(/@click\.capture="onChatClick"/)
    expect(src).toContain('function onChatClick')
  })

  it('链接点击: localhost 预览聚焦预览位, 外链走系统浏览器, 一律 preventDefault', () => {
    expect(src).toContain('preventDefault')
    expect(src).toContain('localhost')               // 本地预览地址判定(走预览位)
    expect(src).toContain('openExternal')            // 外链走系统浏览器
    expect(src).toMatch(/wsPaneTab\.value\s*=\s*'run'/)  // 预览地址→聚焦预览位
  })

  it('本地预览链接取干净 origin(marked 把中文标点吞进 href)', () => {
    expect(src).toMatch(/new URL\(href\)\.origin/)
  })

  it('agent 跑预览(previewEpoch)强制自动切预览位 — 即使 url 不变也切', () => {
    expect(src).toMatch(/watch\(\s*\(\)\s*=>\s*codingStore\.previewEpoch/)
    // 兜底: dev_url 变化也切(覆盖按钮/链接写入)
    expect(src).toMatch(/watch\(\s*\(\)\s*=>\s*codingStore\.activePreview\?\.dev_url/)
  })
})
