export interface FileChangeMsg {
  type: string
  content?: string
  fileName?: string
  /** 工作区相对全路径(优先作 key, 嵌套文件 basename 对不上树) */
  filePath?: string
  fileContent?: string
  oldContent?: string
}

export interface FileChange {
  oldContent?: string
  fileContent?: string
}

export interface ChangedFiles {
  changed: Map<string, FileChange>
  lastChangedFile: string | null
}

const FILE_TYPES = new Set(['file_write', 'file_edit'])

export function collectChangedFiles(messages: FileChangeMsg[]): ChangedFiles {
  const changed = new Map<string, FileChange>()
  let lastChangedFile: string | null = null
  for (const m of messages) {
    const key = m.filePath || m.fileName
    if (!FILE_TYPES.has(m.type) || !key) continue
    changed.set(key, { oldContent: m.oldContent, fileContent: m.fileContent })
    lastChangedFile = key
  }
  return { changed, lastChangedFile }
}
