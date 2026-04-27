/**
 * SSE 客户端 —— 订阅 /api/sse/conversation/{id}，带自动重连 + seq 去重。
 *
 * 架构文档 § 4.4：
 * - 客户端维护 lastSeenSeq（localStorage 持久化）
 * - 断线后带 last_seen_seq 重连，服务端补发 seq>N 的历史再接实时
 * - seq 跳跃（服务端侧 drop）→ 触发重连告警
 *
 * EventSource 原生不支持自定义 Authorization header —— 我们把 token 附到 URL query
 * 上；后端 sse 路由读取"Authorization" 时支持 query fallback（或走 Cookie/OAuth）。
 * MVP：开发环境同域没问题；生产走反向代理可另加鉴权。
 */
import { buildSseUrl } from '@/api/codingV2'

export interface SseEvent {
  type: string
  agent: string
  session_id: string | null
  conversation_id: number
  seq: number
  data: Record<string, any>
}

export interface SseClientOptions {
  conversationId: number
  /** 事件到达回调 */
  onEvent: (event: SseEvent) => void
  /** heartbeat 收到回调（可选） */
  onHeartbeat?: () => void
  /** 连接打开 */
  onOpen?: () => void
  /** 连接关闭（含被动断开） */
  onClose?: (reason: string) => void
  /** seq 跳跃告警 */
  onSeqJump?: (expected: number, got: number) => void
  /** localStorage key 前缀（每 conversation 独立） */
  storageKeyPrefix?: string
  /** 最大连续重连次数（超过认定失败） */
  maxReconnectAttempts?: number
  /** 基础重连间隔（ms） */
  baseReconnectDelayMs?: number
}

const TOKEN_QUERY_NAME = 'token'

export class SseClient {
  private conversationId: number
  private onEvent: (event: SseEvent) => void
  private onHeartbeat?: () => void
  private onOpen?: () => void
  private onClose?: (reason: string) => void
  private onSeqJump?: (expected: number, got: number) => void
  private storageKey: string
  private maxReconnectAttempts: number
  private baseReconnectDelayMs: number

  private source: EventSource | null = null
  private lastSeenSeq = 0
  private reconnectAttempts = 0
  private reconnectTimer: number | null = null
  private closedByUser = false

  constructor(opts: SseClientOptions) {
    this.conversationId = opts.conversationId
    this.onEvent = opts.onEvent
    this.onHeartbeat = opts.onHeartbeat
    this.onOpen = opts.onOpen
    this.onClose = opts.onClose
    this.onSeqJump = opts.onSeqJump
    const prefix = opts.storageKeyPrefix ?? 'apaas-sse-seq'
    this.storageKey = `${prefix}:${opts.conversationId}`
    this.maxReconnectAttempts = opts.maxReconnectAttempts ?? 10
    this.baseReconnectDelayMs = opts.baseReconnectDelayMs ?? 1000
    this.lastSeenSeq = this.loadSeq()
  }

  /** 启动订阅。多次调用会先 close 再建 */
  start(): void {
    this.closedByUser = false
    this.disconnect()
    this.connect()
  }

  /** 用户主动关闭（不会自动重连） */
  stop(): void {
    this.closedByUser = true
    this.cancelReconnect()
    this.disconnect()
  }

  /** 当前 last seen seq */
  getLastSeenSeq(): number {
    return this.lastSeenSeq
  }

  /** 重置 seq 为 0（强制全量补发） */
  resetSeq(): void {
    this.lastSeenSeq = 0
    localStorage.removeItem(this.storageKey)
  }

  // ── private ──

  private loadSeq(): number {
    const raw = localStorage.getItem(this.storageKey)
    const n = parseInt(raw ?? '0', 10)
    return Number.isFinite(n) && n >= 0 ? n : 0
  }

  private saveSeq(seq: number): void {
    try {
      localStorage.setItem(this.storageKey, String(seq))
    } catch {
      // ignore quota errors
    }
  }

  private buildUrl(): string {
    const base = buildSseUrl(this.conversationId, this.lastSeenSeq)
    // 附 token（若有），让后端在 query 里能读到
    const token = localStorage.getItem('token')
    if (!token) return base
    const sep = base.includes('?') ? '&' : '?'
    return `${base}${sep}${TOKEN_QUERY_NAME}=${encodeURIComponent(token)}`
  }

  private connect(): void {
    if (this.closedByUser) return

    const url = this.buildUrl()
    const source = new EventSource(url, { withCredentials: true })
    this.source = source

    source.onopen = () => {
      this.reconnectAttempts = 0
      this.onOpen?.()
    }

    source.onmessage = (ev) => {
      this.handleMessage(ev)
    }

    // 自定义 event 类型（heartbeat）
    source.addEventListener('heartbeat', () => {
      this.onHeartbeat?.()
    })

    source.onerror = () => {
      // EventSource 会自动尝试重连，但我们自己控制以带 last_seen_seq 精准续传
      this.disconnect()
      if (this.closedByUser) return
      this.scheduleReconnect()
    }
  }

  private handleMessage(ev: MessageEvent): void {
    let parsed: SseEvent
    try {
      parsed = JSON.parse(ev.data)
    } catch {
      return
    }
    // seq 校验
    if (typeof parsed.seq === 'number') {
      if (parsed.seq <= this.lastSeenSeq) {
        // 旧事件重复 —— 服务端补发时可能覆盖；忽略
        return
      }
      const expected = this.lastSeenSeq + 1
      if (parsed.seq > expected && this.lastSeenSeq !== 0) {
        this.onSeqJump?.(expected, parsed.seq)
      }
      this.lastSeenSeq = parsed.seq
      this.saveSeq(parsed.seq)
    }
    this.onEvent(parsed)
  }

  private disconnect(reason: string = 'disconnect'): void {
    if (this.source) {
      try {
        this.source.close()
      } catch {
        // ignore
      }
      this.source = null
      this.onClose?.(reason)
    }
  }

  private scheduleReconnect(): void {
    this.cancelReconnect()
    if (this.reconnectAttempts >= this.maxReconnectAttempts) {
      this.onClose?.('max_reconnect_exceeded')
      return
    }
    // 指数退避（带抖动）
    const attempt = this.reconnectAttempts++
    const delay = Math.min(
      this.baseReconnectDelayMs * 2 ** attempt,
      30_000,
    ) * (0.7 + Math.random() * 0.6)
    this.reconnectTimer = window.setTimeout(() => {
      this.connect()
    }, delay)
  }

  private cancelReconnect(): void {
    if (this.reconnectTimer !== null) {
      clearTimeout(this.reconnectTimer)
      this.reconnectTimer = null
    }
  }
}

/** 便捷工厂：创建并立即启动 */
export function startSseSubscription(opts: SseClientOptions): SseClient {
  const client = new SseClient(opts)
  client.start()
  return client
}
