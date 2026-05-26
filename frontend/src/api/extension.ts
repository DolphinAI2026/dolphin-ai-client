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
   * 返回一个 controlled handle (.close() 停掉 + 取消所有挂起重连) 而非裸 EventSource —
   * 2026-05-26 (PR6 reviewer Critical #2): 加指数退避防重连风暴 + 防 401 时
   * EventSource 自带重连无限刷.
   *
   * 后端 SSE endpoint 走 token query param (PR6 Critical #1) — EventSource 无法
   * set Authorization header. 后端 401 时不再 retry, 业务错由 onError 上报调用方.
   */
  openUpdateEventStream(
    appId: number,
    handlers: {
      onEvent?: (e: ExtensionUpdateEvent) => void
      onError?: (e: Event) => void
      onOpen?: () => void
    },
  ): { close: () => void } {
    const token = localStorage.getItem('token') || ''
    const url = `${API_PREFIX}/applications/${appId}/extension-update-events${token ? `?token=${encodeURIComponent(token)}` : ''}`

    let es: EventSource | null = null
    let reconnectTimer: number | null = null
    let attempt = 0
    let closed = false
    // 浏览器自带 EventSource 撞 onerror 时会自动 retry (默认 3s 间隔), 没退避.
    // 我们手动接管: onerror → close() → 退避 → reconnect, 防 backend 挂时风暴.
    const MAX_BACKOFF_MS = 60_000   // 1 分钟封顶
    const BASE_DELAY_MS = 1_000     // 1s 起点

    function scheduleReconnect() {
      if (closed) return
      const jitter = Math.random() * 500
      const delay = Math.min(MAX_BACKOFF_MS, BASE_DELAY_MS * Math.pow(2, attempt)) + jitter
      attempt++
      reconnectTimer = window.setTimeout(connect, delay)
    }

    function connect() {
      if (closed) return
      // 创建前先确保旧的清掉, 防 onerror 期间多个 ES 实例并存
      if (es) {
        try { es.close() } catch { /* ignore */ }
        es = null
      }
      const _es = new EventSource(url, { withCredentials: true })
      es = _es

      _es.addEventListener('open', () => {
        attempt = 0  // reset backoff on successful connect
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

      ;['hello', 'ping', 'dev_kit_published', 'republish_done', 'dev_kit_attached'].forEach(name => {
        _es.addEventListener(name, dispatch(name) as EventListener)
      })

      _es.onerror = (e) => {
        // EventSource 默认会自动重连, 但没退避. 关 native ES + 自管退避.
        // readyState: 0=CONNECTING, 1=OPEN, 2=CLOSED (后端拒后通常 0 然后跳 2)
        handlers.onError?.(e)
        try { _es.close() } catch { /* ignore */ }
        if (_es === es) es = null
        scheduleReconnect()
      }
    }

    connect()

    return {
      close() {
        closed = true
        if (reconnectTimer != null) {
          clearTimeout(reconnectTimer)
          reconnectTimer = null
        }
        if (es) {
          try { es.close() } catch { /* ignore */ }
          es = null
        }
      },
    }
  },
}

export default extensionApi
