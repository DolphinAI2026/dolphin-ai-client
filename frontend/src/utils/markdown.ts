// frontend/src/utils/markdown.ts
//
// 2026-05-19 image #39 抽出 — 之前 tiny renderer 只处理 bold/code/换行,
// AI 输出的表格全是 raw pipe 字符. 改用 marked 完整 GFM 渲染 (表格 / 列表 /
// 代码块 / 标题).
//
// 2026-05-24 从 ConfigAssistantPanel.vue 顶部 script 块 抽出到 utils,
// 让多个组件复用 (Messages / Plan Card 等).

import { marked } from 'marked'

marked.setOptions({ breaks: true, gfm: true })

// 记忆化：消息 / SPEC / 思维链内容一旦生成就不可变，按内容缓存 marked.parse 结果。
// 切会话 / 列表重渲染会把整条对话重新渲染，没缓存就对每条消息重复解析 marked —— 这是 Code
// 切会话「卡顿」的主线程阻塞根因（对话越重：思维链 + diff + SPEC，重复解析越贵）。
const _mdCache = new Map<string, string>()
const _MD_CACHE_MAX = 3000

function _parse(s: string): string {
  try {
    return marked.parse(s, { async: false }) as string
  } catch {
    // 极端 fallback：保留旧 tiny renderer 逻辑避免崩
    const escaped = s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    return escaped
      .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
      .replace(/`([^`]+)`/g, '<code>$1</code>')
      .replace(/\n/g, '<br/>')
  }
}

export function renderMd(s: string): string {
  if (!s) return ''
  const hit = _mdCache.get(s)
  if (hit !== undefined) return hit
  const html = _parse(s)
  if (_mdCache.size >= _MD_CACHE_MAX) _mdCache.clear()  // 简单上限：超了清空，避免无界增长
  _mdCache.set(s, html)
  return html
}
