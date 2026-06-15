import { describe, expect, it } from 'vitest'

import {
  LOG_SUB_TABS,
  buildLogsRequestUrl,
  normalizeLogStatus,
  readLogsResponse,
  statusLabel,
} from './logsPanelData'

describe('logsPanelData', () => {
  it('includes low-code tenant logs as a first-class sub tab', () => {
    expect(LOG_SUB_TABS.map(tab => tab.code)).toEqual([
      'deploy',
      'operation',
      'lowcode',
      'ai',
      'error',
    ])
  })

  it('builds the dedicated low-code endpoint while keeping existing log endpoints', () => {
    expect(buildLogsRequestUrl(10, 'lowcode', 3, 50)).toBe('/applications/10/lowcode-logs?page=3&page_size=50')
    expect(buildLogsRequestUrl(10, 'deploy', 1, 50)).toBe('/applications/10/logs/deploy?page=1&page_size=50')
  })

  it('labels low-code risk statuses for the table chip', () => {
    expect(normalizeLogStatus('risk_high')).toBe('err')
    expect(statusLabel('risk_high')).toBe('高风险')
    expect(normalizeLogStatus('risk_medium')).toBe('pending')
    expect(statusLabel('risk_medium')).toBe('需关注')
    expect(normalizeLogStatus('risk_low')).toBe('ok')
    expect(statusLabel('risk_low')).toBe('正常')
  })

  it('normalizes response counts and keeps low-code analysis', () => {
    const result = readLogsResponse({
      ok: true,
      total: 2,
      has_more: true,
      error_count: 1,
      items: [{ id: 'x', timestamp: '2026-06-14 21:59:46', type: '发布', summary: '发布应用', status: 'risk_medium' }],
      analysis: { total: 2, risk_total: 1, summary: '最近 2 条低代码变更' },
    })

    expect(result.ok).toBe(true)
    expect(result.total).toBe(2)
    expect(result.errorCount).toBe(1)
    expect(result.hasMore).toBe(true)
    expect(result.analysis?.risk_total).toBe(1)
  })
})
