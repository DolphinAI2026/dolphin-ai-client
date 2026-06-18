import { describe, expect, it } from 'vitest'
import { buildServeLogsUrl } from './serveLogsUrl'

describe('buildServeLogsUrl', () => {
  it('appends last_seen_seq and token to the serve-logs SSE path', () => {
    expect(buildServeLogsUrl('/api', '1_8ae94ab4', 0, 'tok123')).toBe(
      '/api/coding/workspace/1_8ae94ab4/serve-logs?last_seen_seq=0&token=tok123',
    )
  })

  it('uses the provided after-seq cursor for reconnect', () => {
    expect(buildServeLogsUrl('/api', 'ws1', 42, 'tok123')).toBe(
      '/api/coding/workspace/ws1/serve-logs?last_seen_seq=42&token=tok123',
    )
  })

  it('omits the token param when no token is present', () => {
    expect(buildServeLogsUrl('/ai-builder/api', 'ws1', 7, '')).toBe(
      '/ai-builder/api/coding/workspace/ws1/serve-logs?last_seen_seq=7',
    )
  })

  it('url-encodes the token', () => {
    expect(buildServeLogsUrl('/api', 'ws1', 0, 'a b/c')).toBe(
      '/api/coding/workspace/ws1/serve-logs?last_seen_seq=0&token=a%20b%2Fc',
    )
  })
})
