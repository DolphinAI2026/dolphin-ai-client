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

export function renderMd(s: string): string {
  if (!s) return ''
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
