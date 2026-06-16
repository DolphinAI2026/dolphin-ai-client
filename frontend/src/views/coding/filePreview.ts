export type WorkspaceFilePreviewKind = 'text' | 'image' | 'download'

const IMAGE_PREVIEW_EXT = new Set([
  'png', 'jpg', 'jpeg', 'gif', 'webp', 'svg', 'ico', 'bmp',
])

const DOWNLOAD_ONLY_EXT = new Set([
  'zip', 'tar', 'gz', 'tgz', 'rar', '7z',
  'pdf', 'woff', 'woff2', 'ttf', 'eot', 'otf',
  'mp4', 'mp3', 'wav', 'mov', 'avi',
  'exe', 'bin', 'so', 'dll', 'jar',
  'psd', 'sketch', 'xlsx', 'xls', 'docx', 'doc', 'ppt', 'pptx',
])

function extensionOf(filePath: string | null | undefined): string {
  const baseName = (filePath || '').split('/').pop() || ''
  return baseName.split('.').pop()?.toLowerCase() || ''
}

export function getWorkspaceFilePreviewKind(filePath: string | null | undefined): WorkspaceFilePreviewKind {
  const ext = extensionOf(filePath)
  if (IMAGE_PREVIEW_EXT.has(ext)) return 'image'
  if (DOWNLOAD_ONLY_EXT.has(ext)) return 'download'
  return 'text'
}
