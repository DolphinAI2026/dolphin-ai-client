// 运行/调试面板的纯状态工具（无 Vue/DOM 依赖，方便 vitest 单测）。

export interface LogLine {
  seq: number
  stream: 'stdout' | 'stderr'
  line: string
}

export interface ConsoleEntry {
  seq: number
  level: string
  text: string
  location: string
}

export interface NetEntry {
  seq: number
  url: string
  status: number
  method: string
  failed: boolean
}

/** 追加一行日志：按 seq 去重、保序、环形裁剪到 maxLines。 */
export function appendLogLine(ring: LogLine[], line: LogLine, maxLines = 2000): LogLine[] {
  if (ring.length && ring[ring.length - 1].seq >= line.seq) {
    if (ring.some(l => l.seq === line.seq)) return ring
  }
  const next = [...ring, line]
  return next.length > maxLines ? next.slice(next.length - maxLines) : next
}

/** 下一次轮询的游标 = 见过的最大 seq，没有新行则保持当前游标。 */
export function nextAfterSeq(entries: { seq: number }[], current: number): number {
  return entries.reduce((m, e) => (e.seq > m ? e.seq : m), current)
}

/** 把严格更新（seq 更大）的条目并到已有列表后面。 */
export function mergeBySeq<T extends { seq: number }>(existing: T[], incoming: T[]): T[] {
  const maxExisting = existing.reduce((m, e) => (e.seq > m ? e.seq : m), -Infinity)
  const fresh = incoming.filter(e => e.seq > maxExisting)
  return fresh.length ? [...existing, ...fresh] : existing
}

const ERROR_RE = /error|fail|exception/i

/** stderr 行或包含 error/fail/exception 的行 → 高亮为错误。 */
export function isErrorLog(line: LogLine): boolean {
  return line.stream === 'stderr' || ERROR_RE.test(line.line)
}
