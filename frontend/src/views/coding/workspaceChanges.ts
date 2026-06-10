export interface FileChangeMsg {
  type: string
  fileName?: string
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
    if (!FILE_TYPES.has(m.type) || !m.fileName) continue
    changed.set(m.fileName, { oldContent: m.oldContent, fileContent: m.fileContent })
    lastChangedFile = m.fileName
  }
  return { changed, lastChangedFile }
}
