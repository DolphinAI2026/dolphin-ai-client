import { describe, it, expect } from 'vitest'
import { collectChangedFiles } from './workspaceChanges'

describe('collectChangedFiles', () => {
  it('收集 file_write/file_edit 的改前改后,lastChangedFile 取最后一条', () => {
    const { changed, lastChangedFile } = collectChangedFiles([
      { type: 'thinking', content: 'x' },
      { type: 'file_write', fileName: 'src/a.ts', fileContent: 'A' },
      { type: 'file_edit', fileName: 'src/b.ts', oldContent: 'old', fileContent: 'new' },
    ])
    expect([...changed.keys()].sort()).toEqual(['src/a.ts', 'src/b.ts'])
    expect(changed.get('src/b.ts')).toEqual({ oldContent: 'old', fileContent: 'new' })
    expect(changed.get('src/a.ts')).toEqual({ oldContent: undefined, fileContent: 'A' })
    expect(lastChangedFile).toBe('src/b.ts')
  })

  it('同一文件多次改,后者覆盖前者', () => {
    const { changed } = collectChangedFiles([
      { type: 'file_edit', fileName: 'src/a.ts', oldContent: '1', fileContent: '2' },
      { type: 'file_edit', fileName: 'src/a.ts', oldContent: '2', fileContent: '3' },
    ])
    expect(changed.get('src/a.ts')).toEqual({ oldContent: '2', fileContent: '3' })
  })

  it('无文件改动时 lastChangedFile 为 null', () => {
    const { changed, lastChangedFile } = collectChangedFiles([{ type: 'status', content: 'ok' }])
    expect(changed.size).toBe(0)
    expect(lastChangedFile).toBeNull()
  })

  it('缺 fileName 的脏事件被跳过', () => {
    const { changed } = collectChangedFiles([{ type: 'file_write', fileContent: 'A' }])
    expect(changed.size).toBe(0)
  })

  it('有 filePath 时优先作 key(嵌套文件 basename 对不上树)', () => {
    const { changed, lastChangedFile } = collectChangedFiles([
      { type: 'file_write', fileName: 'a.ts', filePath: 'src/api/a.ts', fileContent: 'A' },
    ])
    expect([...changed.keys()]).toEqual(['src/api/a.ts'])
    expect(lastChangedFile).toBe('src/api/a.ts')
  })

  it('清理文件名里的行数展示后缀', () => {
    const { changed, lastChangedFile } = collectChangedFiles([
      {
        type: 'file_edit',
        fileName: 'src/service/LegacyQueryService.java (249 lines)',
        fileContent: 'A',
      },
      {
        type: 'file_edit',
        fileName: 'src/service/LegacyQueryController.java (12 行)',
        fileContent: 'B',
      },
    ])
    expect([...changed.keys()]).toEqual([
      'src/service/LegacyQueryService.java',
      'src/service/LegacyQueryController.java',
    ])
    expect(lastChangedFile).toBe('src/service/LegacyQueryController.java')
  })
})
