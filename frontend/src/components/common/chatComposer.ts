export interface UnifiedChatAttachment {
  id: string | number
  name: string
  previewUrl?: string | null
  kind?: 'image' | 'file'
}
