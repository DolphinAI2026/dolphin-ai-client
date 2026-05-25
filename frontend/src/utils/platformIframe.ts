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

export interface PlatformEmbedAppInfo {
  appName?: string
  appCode?: string
  description?: string
  adminName?: string
  desktopUrl?: string
  mobileUrl?: string
}

export function buildPlatformProxyEntryUrl(appId: number, token: string): string {
  const authQuery = token ? `&_auth=${encodeURIComponent(token)}` : ''
  return `${API_PREFIX}/platform-proxy/entry?app_id=${appId}${authQuery}&_ts=${Date.now()}`
}

// 2026-05-25: 进入指定菜单的 form 编辑器 (跟 backend _build_menu_redirect_path 配套).
// 不传 menu_id 等价于 buildPlatformProxyEntryUrl (落 app 编辑总览).
export function buildPlatformProxyMenuUrl(
  appId: number,
  token: string,
  opts: { menuId?: string; formId?: string | null; menuType?: string } = {},
): string {
  const parts = [`app_id=${appId}`]
  if (token) parts.push(`_auth=${encodeURIComponent(token)}`)
  if (opts.menuId) parts.push(`menu_id=${encodeURIComponent(opts.menuId)}`)
  if (opts.formId) parts.push(`form_id=${encodeURIComponent(opts.formId)}`)
  if (opts.menuType) parts.push(`menu_type=${encodeURIComponent(opts.menuType)}`)
  parts.push(`_ts=${Date.now()}`)
  return `${API_PREFIX}/platform-proxy/entry?${parts.join('&')}`
}

function normalizeText(value: string | null | undefined): string {
  return String(value || '').replace(/\s+/g, '').replace(/[:：*]/g, '').trim()
}

function matchesLabelText(rawText: string, labels: string[]): boolean {
  const text = normalizeText(rawText)
  return labels.some(label => text.includes(normalizeText(label)))
}

function resolveFormItem(node: Element | null): HTMLElement | null {
  if (!node) return null
  return (
    (node.closest('.el-form-item') as HTMLElement | null)
    || (node.closest('.ant-form-item') as HTMLElement | null)
    || (node.closest('.ivu-form-item') as HTMLElement | null)
    || (node.closest('.form-item') as HTMLElement | null)
    || (node.parentElement as HTMLElement | null)
  )
}

function findFieldContainer(doc: Document, labels: string[]): HTMLElement | null {
  const labelNodes = Array.from(doc.querySelectorAll(
    'label,.el-form-item__label,.ant-form-item-label,label span,.ivu-form-item-label,.van-field__label,.form-label'
  ))
  for (const node of labelNodes) {
    if (matchesLabelText(node.textContent || '', labels)) {
      const formItem = resolveFormItem(node)
      if (formItem) return formItem
    }
  }

  const textNodes = Array.from(doc.querySelectorAll('span,div,p,strong'))
  for (const node of textNodes) {
    if (matchesLabelText(node.textContent || '', labels)) {
      const formItem = resolveFormItem(node)
      if (formItem) return formItem
    }
  }

  return null
}

function setNativeValue(target: HTMLInputElement | HTMLTextAreaElement, value: string) {
  const proto = Object.getPrototypeOf(target)
  const descriptor = Object.getOwnPropertyDescriptor(proto, 'value')
  if (descriptor?.set) descriptor.set.call(target, value)
  else target.value = value
  target.dispatchEvent(new Event('input', { bubbles: true }))
  target.dispatchEvent(new Event('change', { bubbles: true }))
}

function fillInputValue(container: HTMLElement | null, value: string | undefined) {
  if (!container || !value) return
  const input = container.querySelector('input, textarea') as HTMLInputElement | HTMLTextAreaElement | null
  if (input) {
    setNativeValue(input, value)
    return
  }

  const textNode = container.querySelector('.el-input__inner,.ant-input,.ivu-input,.form-control,.cell-value,[contenteditable="true"]') as HTMLElement | null
  if (textNode) {
    textNode.textContent = value
    textNode.dispatchEvent(new Event('input', { bubbles: true }))
  }
}

function fillTextCell(doc: Document, labels: string[], value: string | undefined) {
  if (!value) return
  const container = findFieldContainer(doc, labels)
  if (!container) return
  fillInputValue(container, value)
}

function deriveMobileUrl(desktopUrl: string | undefined): string {
  if (!desktopUrl) return ''
  try {
    const url = new URL(desktopUrl)
    url.pathname = url.pathname.replace(/^\/app\//, '/m/')
    return url.toString()
  } catch {
    return desktopUrl.replace('/app/', '/m/')
  }
}

function deriveDesktopUrl(editUrl: string | undefined, appCode: string | undefined): string {
  if (!editUrl || !appCode) return ''
  try {
    const url = new URL(editUrl)
    const parts = url.pathname.split('/').filter(Boolean)
    const tenantId = parts[1] || ''
    return `${url.origin}/app/${tenantId}/${appCode}`
  } catch {
    return ''
  }
}

export function injectPlatformAppInfo(doc: Document, info: PlatformEmbedAppInfo | null | undefined) {
  if (!info) return

  const appName = info.appName || ''
  const appCode = info.appCode || ''
  const description = info.description || ''
  const adminName = info.adminName || ''
  const desktopUrl = info.desktopUrl || deriveDesktopUrl(doc.location?.href, appCode)
  const mobileUrl = info.mobileUrl || deriveMobileUrl(desktopUrl)

  fillTextCell(doc, ['应用名称'], appName)
  fillTextCell(doc, ['应用编码'], appCode)
  fillTextCell(doc, ['备注'], description)
  fillTextCell(doc, ['应用管理员', '管理员'], adminName)
  fillTextCell(doc, ['电脑端'], desktopUrl)
  fillTextCell(doc, ['移动端'], mobileUrl)
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

export function repairPlatformIframe(iframe: HTMLIFrameElement | null, appInfo?: PlatformEmbedAppInfo | null): boolean {
  if (!iframe) return false

  try {
    const win = iframe.contentWindow || null
    const doc = iframe.contentDocument || win?.document
    if (!doc) return false
    try {
      const localAuth = win?.localStorage?.getItem('__vuex__local') || ''
      const sessionAuth = win?.sessionStorage?.getItem('__vuex__session') || ''
      if (localAuth && localAuth !== sessionAuth) {
        win?.sessionStorage?.setItem('__vuex__session', localAuth)
      }
    } catch (error) {
      console.warn('sync platform auth storage failed:', error)
    }
    repairPlatformDocument(doc)
    injectPlatformAppInfo(doc, appInfo)
    return true
  } catch (error) {
    console.warn('repairPlatformIframe failed:', error)
    return false
  }
}
