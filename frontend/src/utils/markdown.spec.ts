import { describe, it, expect, vi } from 'vitest'
import { marked } from 'marked'
import { renderMd } from './markdown'

// 记忆化是 Code 切会话「卡顿」的修复:同一条消息内容只解析一次,切会话/重渲染走缓存。
describe('renderMd 记忆化(切会话卡顿修复)', () => {
  it('相同内容只调用一次 marked.parse,后续走缓存', () => {
    const spy = vi.spyOn(marked, 'parse')
    const md = '# memo-unique-A\n\n- 项目一\n- 项目二\n\n`code`'
    const a = renderMd(md)
    const b = renderMd(md)
    const c = renderMd(md)
    expect(a).toBe(b)
    expect(b).toBe(c)
    expect(a).toContain('<h1')
    // 这段内容只解析一次(其余两次命中缓存)
    const callsForThis = spy.mock.calls.filter(call => call[0] === md).length
    expect(callsForThis).toBe(1)
    spy.mockRestore()
  })

  it('不同内容各解析一次', () => {
    const spy = vi.spyOn(marked, 'parse')
    const x = '内容-X-' + 'unique\n\n**bold**'
    const y = '内容-Y-' + 'unique\n\n*em*'
    renderMd(x)
    renderMd(y)
    renderMd(x)
    renderMd(y)
    expect(spy.mock.calls.filter(c => c[0] === x).length).toBe(1)
    expect(spy.mock.calls.filter(c => c[0] === y).length).toBe(1)
    spy.mockRestore()
  })

  it('空串返回空,不进缓存/不解析', () => {
    const spy = vi.spyOn(marked, 'parse')
    expect(renderMd('')).toBe('')
    expect(spy).not.toHaveBeenCalled()
    spy.mockRestore()
  })

  it('输出仍是完整 GFM(表格)', () => {
    const md = '表格-unique-Z\n\n| a | b |\n| - | - |\n| 1 | 2 |'
    const html = renderMd(md)
    expect(html).toContain('<table')
    expect(html).toContain('<td')
  })
})
