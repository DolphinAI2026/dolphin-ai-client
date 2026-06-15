export interface LogSubTab {
  code: string
  label: string
}

export interface LogItem {
  id?: string
  timestamp: string
  type: string
  user?: string
  summary: string
  status: string
  details?: any
}

export interface LogsPanelData {
  ok: boolean
  items: LogItem[]
  total: number
  errorCount: number
  hasMore: boolean
  analysis?: any
  message?: string
}

export const LOG_SUB_TABS: LogSubTab[] = [
  { code: 'deploy', label: '部署历史' },
  { code: 'operation', label: '操作日志' },
  { code: 'lowcode', label: '低代码日志' },
  { code: 'ai', label: 'AI 行为' },
  { code: 'error', label: '错误日志' },
]

export function buildLogsRequestUrl(appId: number, kind: string, page: number, pageSize: number): string {
  if (kind === 'lowcode') {
    return `/applications/${appId}/lowcode-logs?page=${page}&page_size=${pageSize}`
  }
  return `/applications/${appId}/logs/${kind}?page=${page}&page_size=${pageSize}`
}

export function normalizeLogStatus(s?: string): string {
  const lo = (s || '').toLowerCase()
  if (lo === 'risk_high') return 'err'
  if (lo === 'risk_medium') return 'pending'
  if (lo === 'risk_low') return 'ok'
  if (lo.includes('success') || lo === 'completed' || lo === 'ok') return 'ok'
  if (lo.includes('fail') || lo === 'error' || lo === 'failed') return 'err'
  if (lo.includes('progress') || lo === 'pending' || lo === 'running') return 'pending'
  return 'neutral'
}

export function statusLabel(s?: string): string {
  if (s === 'risk_high') return '高风险'
  if (s === 'risk_medium') return '需关注'
  if (s === 'risk_low') return '正常'
  const n = normalizeLogStatus(s)
  if (n === 'ok') return '成功'
  if (n === 'err') return '失败'
  if (n === 'pending') return '进行中'
  return s || '—'
}

export function readLogsResponse(resp: any): LogsPanelData {
  const items = (resp?.items || []) as LogItem[]
  return {
    ok: !!resp?.ok,
    items,
    total: Number(resp?.total ?? items.length),
    errorCount: Number(resp?.error_count ?? resp?.stats?.errors ?? 0),
    hasMore: !!resp?.has_more,
    analysis: resp?.analysis,
    message: resp?.message || resp?.error_code,
  }
}
