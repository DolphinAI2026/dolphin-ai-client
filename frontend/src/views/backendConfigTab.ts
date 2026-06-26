import type { EditorUrlResp } from '@/api/editorUrl'

export interface AdminEditorState {
  url: string
  msg: string
}

const DEFAULT_MSG = '应用尚未部署到平台, 无法打开后台配置'

/**
 * 把 /editor-url 响应映射成「后台配置」tab 的展示态。
 * 有 url → 内嵌 apaas 应用管理后台；否则显引导文案(优先后端 message)。
 */
export function resolveAdminEditorState(resp: EditorUrlResp | null | undefined): AdminEditorState {
  if (resp?.ok && resp.url) return { url: resp.url, msg: '' }
  return { url: '', msg: resp?.message || DEFAULT_MSG }
}
