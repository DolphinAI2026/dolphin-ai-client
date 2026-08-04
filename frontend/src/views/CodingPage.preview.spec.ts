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
    expect(src).toMatch(/showPanel\('browser'\)/)    // 预览地址→聚焦浏览器面板(Codex 段控,旧 wsPaneTab='run' 升级)
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

// 2026-06-19 UX 打磨
describe('CodingPage UX 打磨', () => {
  it('默认模型统一显示默认模型，不暴露具体 provider/model 名称', () => {
    expect(src).toMatch(/selectedCodingModelLabel\s*=\s*computed/)
    expect(src).toContain("opt?.is_default ? '默认模型'")
    expect(src).toContain("option.is_default ? '默认模型' : option.config_name")
    expect(src).toContain("option.is_default ? '当前默认配置'")
  })

  it('文件选择守卫: 坏路径(含空格/代码括号)不打开 → 打开态不落文件红错', () => {
    expect(src).toContain('function looksLikeFilePath')
    // openFileFromChat 解析不到时只接受 looksLikeFilePath, 不再无条件回退 rawPath
    expect(src).toMatch(/resolveWorkspacePath\(rawPath\)\s*\|\|\s*\(looksLikeFilePath/)
  })

  it('run_result 卡不再恒显「运行时抓取不可用」噪音', () => {
    expect(src).not.toContain('class="rc-degrade"')
  })
})
