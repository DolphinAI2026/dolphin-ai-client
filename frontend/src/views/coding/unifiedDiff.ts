/** unified diff 文本 → 渲染行。给 DiffView 用，只做展示不做语义。 */

export interface DiffRow {
  /** hunk = @@ 分隔行; add/del/ctx = 内容行 */
  type: 'hunk' | 'add' | 'del' | 'ctx'
  /** 旧文件行号(add 行没有) */
  oldNo?: number
  /** 新文件行号(del 行没有) */
  newNo?: number
  text: string
}

const HUNK_RE = /^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@(.*)$/

/**
 * 解析 git unified diff(单文件)。
 * 文件头(diff --git/index/---/+++)跳过；"\ No newline at end of file" 跳过。
 */
export function parseUnifiedDiff(diff: string): DiffRow[] {
  const rows: DiffRow[] = []
  let oldNo = 0
  let newNo = 0
  let inHunk = false
  for (const line of diff.split('\n')) {
    const hunk = HUNK_RE.exec(line)
    if (hunk) {
      oldNo = parseInt(hunk[1]!, 10)
      newNo = parseInt(hunk[2]!, 10)
      inHunk = true
      rows.push({ type: 'hunk', text: hunk[3]?.trim() || '' })
      continue
    }
    if (!inHunk) continue // 文件头区
    if (line.startsWith('\\')) continue // \ No newline at end of file
    if (line.startsWith('+')) {
      rows.push({ type: 'add', newNo: newNo++, text: line.slice(1) })
    } else if (line.startsWith('-')) {
      rows.push({ type: 'del', oldNo: oldNo++, text: line.slice(1) })
    } else if (line.startsWith(' ') || line === '') {
      // 末尾 split 出的空串若不在内容里会多一行,丢掉孤立的结尾空行
      if (line === '' && rows.length && rows[rows.length - 1]!.type === 'hunk') continue
      if (line === '' && oldNo === 0 && newNo === 0) continue
      rows.push({ type: 'ctx', oldNo: oldNo++, newNo: newNo++, text: line.slice(1) })
    }
  }
  // diff 末尾 split('\n') 产生的孤立空 ctx 行(行号已超出)修剪掉
  while (rows.length) {
    const last = rows[rows.length - 1]!
    if (last.type === 'ctx' && last.text === '') rows.pop()
    else break
  }
  return rows
}

/** 渲染行数统计(徽标用) */
export function diffCounts(rows: DiffRow[]): { additions: number; deletions: number } {
  let additions = 0
  let deletions = 0
  for (const r of rows) {
    if (r.type === 'add') additions++
    else if (r.type === 'del') deletions++
  }
  return { additions, deletions }
}
