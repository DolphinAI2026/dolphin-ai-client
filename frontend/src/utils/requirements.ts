/**
 * RequirementsPage 抽出的纯工具函数。
 *
 * 本文件只放**无 Vue 依赖、无 reactive state 依赖**的函数，方便单测 + 复用。
 */

// ── 类型 ─────────────────────────────────────────────────────────────
export interface AnalysisResultShape {
  app_info: unknown
  roles: unknown[]
  data_dictionary: unknown[]
  tables: unknown[]
  role_table_mapping: unknown[]
  [key: string]: unknown
}

// ── 文档结构校验 ─────────────────────────────────────────────────────
export function normalizeDocResult<T extends AnalysisResultShape>(raw: unknown): T | null {
  if (!raw || typeof raw !== 'object') return null
  const r = raw as Record<string, unknown>
  const hasCore =
    r.app_info &&
    Array.isArray(r.roles) &&
    Array.isArray(r.data_dictionary) &&
    Array.isArray(r.tables) &&
    Array.isArray(r.role_table_mapping)
  if (!hasCore) return null
  return raw as T
}

export function formatBuilderModelOption(option: { config_name: string }): string {
  return option.config_name
}

// ── 文件消息识别 ─────────────────────────────────────────────────────
const FILE_MSG_RE = /\[上传文件：([^\]]+)\]/

export function isFileMessage(content: string): boolean {
  return FILE_MSG_RE.test(content)
}

export function extractFileName(content: string): string {
  return content.match(FILE_MSG_RE)?.[1] ?? ''
}

export function extractUserText(content: string): string {
  const idx = content.indexOf('[上传文件：')
  return idx > 0 ? content.slice(0, idx).trim() : ''
}

// ── Markdown 轻量渲染 ─────────────────────────────────────────────────
export function stripThink(text: string): string {
  let t = text.replace(/<think>[\s\S]*?<\/think>/g, '')
  const idx = t.indexOf('<think>')
  if (idx >= 0) t = t.slice(0, idx)
  return t.trim()
}

export function renderMarkdown(text: string): string {
  if (!text) return ''
  const cleaned = stripThink(text)
  if (!cleaned) return '<span style="color:var(--c-text-muted);font-style:italic">(thinking...)</span>'
  return cleaned
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
    .replace(/\*(.+?)\*/g, '<em>$1</em>')
    .replace(/`(.+?)`/g, '<code>$1</code>')
    .replace(/^#{1,3}\s(.+)$/gm, '<strong>$1</strong>')
    .replace(/^[-•]\s(.+)$/gm, '• $1')
    .replace(/\n/g, '<br>')
}

// ── 时间 ─────────────────────────────────────────────────────────────
export function formatDate(dateStr: string): string {
  const d = new Date(dateStr)
  const now = new Date()
  const diff = now.getTime() - d.getTime()
  if (diff < 60000) return '刚刚'
  if (diff < 3600000) return `${Math.floor(diff / 60000)} 分钟前`
  if (diff < 86400000) return `${Math.floor(diff / 3600000)} 小时前`
  return d.toLocaleDateString('zh-CN', { month: 'short', day: 'numeric' })
}
