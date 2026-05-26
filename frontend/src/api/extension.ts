/**
 * 扩展 section (Section E) API — PR6 SPEC v2 §2 Section E.
 *
 * 提供:
 *  - listDevKits: 轮询当前 app 已 attach 的自开发包 (zip)
 *  - openUpdateEventStream: 订 SSE 通道, 收外部资源更新通知
 *  - notifyExtensionUpdate: ai-coding 完成 publish 后由 backend 调; 前端测试用
 *  - republishApplication: 触发 aPaaS 重发版本
 */
import request, { API_PREFIX } from '@/utils/request'

export interface DevKitItem {
  id: string
  fileName: string
  fileType?: string
  size?: number | null
  userName?: string | null
  createTime?: string | null
}

export interface ListDevKitsResponse {
  ok: boolean
  env_id?: number | null
  apaas_app_id?: string | null
  total: number
  kits: DevKitItem[]
  note?: string | null
}

export interface NotifyExtensionUpdateRequest {
  event_type?: string
  payload?: Record<string, unknown>
}

export interface NotifyExtensionUpdateResponse {
  ok: boolean
  delivered: number
}

export interface RepublishResponse {
  ok: boolean
  version?: string | null
  remote_status?: string | null
  note?: string | null
}

/** SSE 通道收到的事件 (含 dev_kit_published / republish_done / ping / hello). */
export interface ExtensionUpdateEvent {
  type: string
  ts?: number
  [k: string]: unknown
}

export const extensionApi = {
  /** 列当前 apaas 应用已 attach 的自开发包 (轮询用) */
  listDevKits(appId: number, fileNameFilter = '') {
    return request.get<any, ListDevKitsResponse>(`/applications/${appId}/dev-kits`, {
      params: fileNameFilter ? { file_name_filter: fileNameFilter } : {},
    })
  },

  /** 内部 hook: ai-coding 完成 publish 后由 backend 调; 前端只 demo 用 */
  notifyExtensionUpdate(appId: number, body: NotifyExtensionUpdateRequest) {
    return request.post<any, NotifyExtensionUpdateResponse>(
      `/applications/${appId}/extension-update-notify`,
      body,
    )
  },

  /** 触发 aPaaS 应用重发版本 — 让自开发资源变更生效 */
  republishApplication(appId: number) {
    return request.post<any, RepublishResponse>(`/applications/${appId}/republish`, {})
  },

  /**
   * 订阅扩展更新 SSE 通道.
   * 返回 EventSource 实例 (调用方需保留以便 .close()).
   * onMessage 收到任何事件 (含 hello / ping / dev_kit_published / republish_done) 都会触发.
   */
  openUpdateEventStream(
    appId: number,
    handlers: {
      onEvent?: (e: ExtensionUpdateEvent) => void
      onError?: (e: Event) => void
      onOpen?: () => void
    },
  ): EventSource {
    // EventSource 自带带 cookie, 但 Bearer token 走不了 header — 用 query param 兜底.
    // 后端 sse_starlette + sse_no_buffering middleware 已处理 X-Accel-Buffering.
    const token = localStorage.getItem('token') || ''
    const url = `${API_PREFIX}/applications/${appId}/extension-update-events${token ? `?_t=${encodeURIComponent(token)}` : ''}`
    // 注意: 默认 EventSource 不传 Authorization header. backend cookie 模式 or
    // 网关层 token rewrite 时可 work. 当前阶段先用最简单方式, P1 加 sse polyfill 支持 header.
    const es = new EventSource(url, { withCredentials: true })

    es.addEventListener('open', () => {
      handlers.onOpen?.()
    })

    const dispatch = (typeName: string) => (msg: MessageEvent) => {
      try {
        const data = msg.data ? JSON.parse(msg.data) : {}
        handlers.onEvent?.({ type: typeName, ...data })
      } catch {
        handlers.onEvent?.({ type: typeName })
      }
    }

    // 后端发的 event: hello / ping / dev_kit_published / republish_done / dev_kit_attached
    ;['hello', 'ping', 'dev_kit_published', 'republish_done', 'dev_kit_attached'].forEach(name => {
      es.addEventListener(name, dispatch(name) as EventListener)
    })

    es.onerror = (e) => {
      handlers.onError?.(e)
    }

    return es
  },
}

export default extensionApi
