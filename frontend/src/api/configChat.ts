/**
 * 配置助手 API — post-deploy chat against a deployed application.
 *
 * Backend route (owned by parallel agent P):
 *   POST /api/applications/:id/config-chat
 *
 * Returns a natural-language reply + an optional ChangePlan that can be
 * previewed / applied via the existing incremental update pipeline.
 */
import request from '@/utils/request'

export interface ConfigChatHistoryItem {
  role: 'user' | 'assistant'
  content: string
}

export interface ConfigChatReq {
  message: string
  history: ConfigChatHistoryItem[]
  /**
   * 2026-05-24: 用户在 ConfigAssistantHeader 选择的模型 id (LlmConfig.id)。
   * - 0 / null / undefined: 走后端默认 (跟老行为一致 — 当前租户的 builder default cfg)
   * - >0: 强制用该 LlmConfig 跑 agent (Claude/DeepSeek 等)
   */
  model_id?: number | null
  /** 2026-05-24 会话持久化：0/undefined → 后端自动新建 session 并在 'started' 事件回 session_id */
  session_id?: number | null
  /**
   * 2026-05-26 (PR2c SPEC v2 §1.2): SectionNav 当前 section 软引导.
   * 'data' | 'ui' | 'logic' | 'permission' | 'extension' 之一 → 后端 system_prompt
   * 加 focus 提示. 任何其他值 / null / undefined → 后端不加 hint (跟老行为一致).
   * **软引导**: 工具全集不变, agent 仍能跨 section 操作 — 避免上下文丢.
   */
  section?: string | null
}

/**
 * ChangePlan preview — loose shape on purpose. Backend may evolve the
 * structure (actions, summary, diff hints, etc); frontend just renders
 * whatever it gets.
 */
export interface ChangePlanPreview {
  summary?: string[]
  actions?: any[]
  [k: string]: any
}

/**
 * Tool trace — 2026-05-19 backend agent loop 调过的 MCP 工具痕迹。
 * 前端展示为 chip 让用户看见 AI 真在干活（拉了哪个真实结构 / 改了啥）。
 */
export interface ConfigChatToolTrace {
  tool_name: string
  args: Record<string, any>
  ok: boolean
  summary: string
  /** browser_screenshot 截图返回的 data URL，前端 <img> 直显 */
  image_data_url?: string
}

// ─── 会话持久化 (2026-05-24) ─────────────────────────────────────
export interface ConfigChatSessionSummary {
  id: number
  title: string
  message_count: number
  last_message_preview: string | null
  updated_at: string
  created_at: string
}

export interface ConfigChatSessionCreateResp {
  id: number
  title: string
  created_at: string
}

export interface ConfigChatMessageItem {
  id: number
  role: 'user' | 'assistant'
  content: string
  tool_trace?: ConfigChatToolTrace[] | null
  change_plan?: ChangePlanPreview | null
  actions_summary?: string[] | null
  created_at: string
}

export interface ConfigChatResp {
  reply: string
  change_plan: ChangePlanPreview | null
  requires_confirmation: boolean
  actions_summary: string[]
  tool_trace?: ConfigChatToolTrace[]
}

/**
 * SSE 流式事件类型 (跟 backend `_config_chat_event_stream` 对齐)
 */
export type ConfigChatStreamEvent =
  | { type: 'started'; app_id: number; spec_source: string; tools: number; skills?: number; model?: string; provider?: string; session_id?: number | null }
  | { type: 'turn_start'; turn: number; of: number }
  | { type: 'tool_call'; tool_name: string; args: Record<string, any> }
  | { type: 'tool_result'; tool_name: string; args: Record<string, any>; ok: boolean; summary: string }
  | { type: 'assistant'; content: string; has_tool_calls: boolean }
  | { type: 'done'; reply: string; change_plan: ChangePlanPreview | null; requires_confirmation: boolean; actions_summary: string[]; tool_trace: ConfigChatToolTrace[]; session_id?: number | null }
  | { type: 'error'; message: string }

import { API_PREFIX } from '@/utils/request'

export const configChatApi = {
  // ─── 会话持久化 CRUD (2026-05-24) ─────────────────────────────
  /** 列当前用户在该 app 下的所有 sessions (按 updated_at DESC) */
  listSessions(applicationId: number) {
    return request.get<any, ConfigChatSessionSummary[]>(
      `/applications/${applicationId}/config-chat-sessions`,
    )
  },

  /** 主动新建空 session — 一般用户点 "+ 新对话" 时调 (不传 title 走 "新对话" 默认) */
  createSession(applicationId: number, title?: string) {
    return request.post<any, ConfigChatSessionCreateResp>(
      `/applications/${applicationId}/config-chat-sessions`,
      { title: title || null },
    )
  },

  /** 拉某 session 的全部消息 (按 created_at 升序) — 用户选历史 session 时调 */
  getMessages(sessionId: number) {
    return request.get<any, ConfigChatMessageItem[]>(
      `/config-chat-sessions/${sessionId}/messages`,
    )
  },

  /** 删 session (后端 cascade 清 messages) */
  deleteSession(sessionId: number) {
    return request.delete<any, { ok: boolean }>(
      `/config-chat-sessions/${sessionId}`,
    )
  },

  /** 改 session title */
  updateSessionTitle(sessionId: number, title: string) {
    return request.patch<any, { ok: boolean; id: number; title: string }>(
      `/config-chat-sessions/${sessionId}`,
      { title },
    )
  },

  chat(applicationId: number, payload: ConfigChatReq) {
    // legacy 同步接口保留 — 5 分钟 timeout
    return request.post<any, ConfigChatResp>(
      `/applications/${applicationId}/config-chat`,
      payload,
      { timeout: 300000 },
    )
  },

  /**
   * SSE 流式版 — 用 fetch + ReadableStream 解析 text/event-stream。
   * 调用方提供 onEvent 回调消费每个事件。返回的 Promise 在 done/error 后 resolve。
   */
  async chatStream(
    applicationId: number,
    payload: ConfigChatReq,
    onEvent: (ev: ConfigChatStreamEvent) => void,
    signal?: AbortSignal,
  ): Promise<void> {
    const token = localStorage.getItem('token') || ''
    const resp = await fetch(`${API_PREFIX}/applications/${applicationId}/config-chat-stream`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Accept': 'text/event-stream',
        'Authorization': token ? `Bearer ${token}` : '',
      },
      body: JSON.stringify(payload),
      signal,
    })
    if (!resp.ok || !resp.body) {
      const err = await resp.text().catch(() => '')
      throw new Error(`HTTP ${resp.status}: ${err || 'no body'}`)
    }
    const reader = resp.body.getReader()
    const decoder = new TextDecoder('utf-8')
    let buffer = ''
    let currentEvent = 'message'
    // SSE 解析：normalize CRLF → LF（sse-starlette 用 \r\n），以 \n\n 分块。
    while (true) {
      const { value, done } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true }).replace(/\r\n/g, '\n')
      let idx: number
      // eslint-disable-next-line no-cond-assign
      while ((idx = buffer.indexOf('\n\n')) !== -1) {
        const chunk = buffer.slice(0, idx)
        buffer = buffer.slice(idx + 2)
        for (const line of chunk.split('\n')) {
          if (line.startsWith(':')) continue   // SSE comment / heartbeat (e.g. ': ping')
          if (line.startsWith('event:')) {
            currentEvent = line.slice(6).trim()
          } else if (line.startsWith('data:')) {
            const rawData = line.slice(5).trim()
            if (!rawData) continue
            try {
              const parsed = JSON.parse(rawData)
              onEvent({ type: currentEvent, ...parsed } as ConfigChatStreamEvent)
            } catch (e) {
              console.warn('[configChatStream] failed to parse event data', rawData, e)
            }
          }
        }
        currentEvent = 'message'  // reset
      }
    }
  },
}

export default configChatApi
