/**
 * 拼装 serve-logs SSE 的完整 URL。EventSource 不能带自定义 header，
 * 故 token 走 query（对齐 extension.ts 的 extension-update-events 用法）。
 * 断线重连靠 last_seen_seq（后端补发 > last_seen_seq 的历史行）。
 */
export function buildServeLogsUrl(
  prefix: string,
  wsId: string,
  lastSeenSeq: number,
  token: string,
): string {
  const base = `${prefix}/coding/workspace/${wsId}/serve-logs?last_seen_seq=${lastSeenSeq}`
  return token ? `${base}&token=${encodeURIComponent(token)}` : base
}
