import { API_PREFIX } from '@/utils/request'

const PLATFORM_HEADER_SELECTORS = [
  '.app-top-header',
  '.header-wrap',
  '.layout-header',
  '.main-header',
  '.tenant-header',
  '.platform-header',
  '.x-header',
  '#header',
  'header.el-header',
  '.el-header',
]

export function buildPlatformProxyEntryUrl(appId: number, token: string): string {
  const authQuery = token ? `&_auth=${encodeURIComponent(token)}` : ''
  return `${API_PREFIX}/platform-proxy/entry?app_id=${appId}${authQuery}&_ts=${Date.now()}`
}

export function repairPlatformDocument(doc: Document) {
  doc.querySelectorAll('#iframe-overrides').forEach(node => node.parentNode?.removeChild(node))

  PLATFORM_HEADER_SELECTORS.forEach(selector => {
    doc.querySelectorAll(selector).forEach(node => {
      const el = node as HTMLElement
      if (el.style.display === 'none') {
        el.style.removeProperty('display')
      }
      if (el.style.visibility === 'hidden') {
        el.style.removeProperty('visibility')
      }
      if (el.hidden) {
        el.hidden = false
      }
    })
  })
}

export function repairPlatformIframe(iframe: HTMLIFrameElement | null): boolean {
  if (!iframe) return false

  try {
    const doc = iframe.contentDocument || iframe.contentWindow?.document
    if (!doc) return false
    repairPlatformDocument(doc)
    return true
  } catch (error) {
    console.warn('repairPlatformIframe failed:', error)
    return false
  }
}
