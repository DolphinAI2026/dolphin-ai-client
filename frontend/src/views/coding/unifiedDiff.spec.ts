import { describe, expect, it } from 'vitest'
import { diffCounts, parseUnifiedDiff } from './unifiedDiff'

const SAMPLE = `diff --git a/src/app.js b/src/app.js
index 1234567..89abcde 100644
--- a/src/app.js
+++ b/src/app.js
@@ -1,3 +1,4 @@
 line1
-line2
+CHANGED
 line3
+line4
@@ -10,2 +11,2 @@ function foo()
 ctx-a
-old-tail
+new-tail
`

describe('parseUnifiedDiff', () => {
  it('解析 hunk/增/删/上下文行并标新旧行号', () => {
    const rows = parseUnifiedDiff(SAMPLE)
    expect(rows[0]).toEqual({ type: 'hunk', text: '' })
    expect(rows[1]).toEqual({ type: 'ctx', oldNo: 1, newNo: 1, text: 'line1' })
    expect(rows[2]).toEqual({ type: 'del', oldNo: 2, text: 'line2' })
    expect(rows[3]).toEqual({ type: 'add', newNo: 2, text: 'CHANGED' })
    expect(rows[4]).toEqual({ type: 'ctx', oldNo: 3, newNo: 3, text: 'line3' })
    expect(rows[5]).toEqual({ type: 'add', newNo: 4, text: 'line4' })
    // 第二个 hunk 带函数名
    expect(rows[6]).toEqual({ type: 'hunk', text: 'function foo()' })
    expect(rows[7]).toEqual({ type: 'ctx', oldNo: 10, newNo: 11, text: 'ctx-a' })
  })

  it('文件头与 No newline 标记被跳过', () => {
    const rows = parseUnifiedDiff(SAMPLE + '\\ No newline at end of file\n')
    expect(rows.every(r => !r.text.startsWith('diff --git') && !r.text.startsWith('No newline'))).toBe(true)
  })

  it('空输入返回空', () => {
    expect(parseUnifiedDiff('')).toEqual([])
  })

  it('diffCounts 统计增删', () => {
    const { additions, deletions } = diffCounts(parseUnifiedDiff(SAMPLE))
    expect(additions).toBe(3)
    expect(deletions).toBe(2)
  })

  it('新文件(对 /dev/null 的 diff)整体为 add', () => {
    const newFile = `diff --git a/dev/null b/x.js
--- /dev/null
+++ b/x.js
@@ -0,0 +1,2 @@
+a
+b
`
    const rows = parseUnifiedDiff(newFile)
    expect(rows.filter(r => r.type === 'add').map(r => r.newNo)).toEqual([1, 2])
  })
})
