export function getPastedImageFiles(event: ClipboardEvent, prefix = 'pasted-image'): File[] {
  const items = Array.from(event.clipboardData?.items || [])
  const images = items.filter(item => item.type.startsWith('image/'))
  if (!images.length) return []

  const stamp = Date.now()
  return images
    .map((item, index) => {
      const file = item.getAsFile()
      if (!file) return null
      const ext = file.type.split('/')[1] || 'png'
      return new File([file], `${prefix}-${stamp}-${index + 1}.${ext}`, { type: file.type })
    })
    .filter((file): file is File => Boolean(file))
}

export function isImageFile(file: File): boolean {
  return file.type.startsWith('image/') || /\.(png|jpe?g|gif|webp|svg)$/i.test(file.name)
}
