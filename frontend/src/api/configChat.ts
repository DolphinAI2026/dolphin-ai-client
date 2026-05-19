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
  | { type: 'started'; app_id: number; spec_source: string; tools: number }
  | { type: 'turn_start'; turn: number; of: number }
  | { type: 'tool_call'; tool_name: string; args: Record<string, any> }
  | { type: 'tool_result'; tool_name: string; args: Record<string, any>; ok: boolean; summary: string }
  | { type: 'assistant'; content: string; has_tool_calls: boolean }
  | { type: 'done'; reply: string; change_plan: ChangePlanPreview | null; requires_confirmation: boolean; actions_summary: string[]; tool_trace: ConfigChatToolTrace[] }
  | { type: 'error'; message: string }

import { API_PREFIX } from '@/utils/request'

export const configChatApi = {
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
