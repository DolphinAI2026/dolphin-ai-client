/**
 * Vibe Coding chat API + SSE 客户端。
 * 跟 ai_chat 完全独立 — 不复用 aiChat.ts 的 sessions/attachments 概念。
 */
import request, { API_PREFIX } from '@/utils/request'

export interface VibeChatThread {
  id: number
  workspace_id: string
  tenant_id: number
  owner_user_id: number
  title: string
  status: string
  selected_llm_config_id: number | null
  todos: Array<{ id: string; content: string; status: 'pending' | 'in_progress' | 'completed' }>
  requirement_baseline?: {
    roles: string[]; features: string[]; flows: string[]
    external: string[]; ai_points: string[]; acceptance: string[]
  }
  token_usage?: { prompt_tokens: number; completion_tokens: number; total_tokens: number; estimated?: boolean }
  created_at: string | null
  updated_at: string | null
}

export interface VibeChatMessage {
  id: number
  thread_id: number
  role: 'user' | 'assistant' | 'system'
  content: string
  user_id: number | null
  extra_meta?: Record<string, any>
  created_at: string | null
}

export interface VibeChatToolCall {
  id: number
  thread_id: number
  message_id: number | null
  tool_name: string
  args_json: Record<string, any>
  result_text: string | null
  status: 'pending' | 'running' | 'success' | 'error' | 'aborted'
  error_message: string | null
  duration_ms: number | null
  started_at: string | null
  ended_at: string | null
}

export interface VibeChatThreadDetail {
  thread: VibeChatThread
  messages: VibeChatMessage[]
  tool_calls: VibeChatToolCall[]
}

export interface VibeChatLLMConfig {
  id: number
  config_name: string
  provider: string
  model: string
  purpose: string
  is_default: boolean
}

const base = (workspaceId: string) => `/online-coding/workspaces/${workspaceId}/chat`

export const vibeCodingChatApi = {
  getThread(workspaceId: string): Promise<VibeChatThreadDetail> {
    return request.get<any, VibeChatThreadDetail>(base(workspaceId))
  },
  updateThread(
    workspaceId: string,
    body: { title?: string; selected_llm_config_id?: number | null },
  ): Promise<VibeChatThread> {
    return request.patch<any, VibeChatThread>(base(workspaceId), body)
  },
  clearThread(workspaceId: string): Promise<{ ok: boolean; thread: VibeChatThread }> {
    return request.delete<any, { ok: boolean; thread: VibeChatThread }>(base(workspaceId))
  },
  abort(workspaceId: string): Promise<{ ok: boolean }> {
    return request.post<any, { ok: boolean }>(`${base(workspaceId)}/abort`)
  },
  listLLMConfigs(workspaceId: string): Promise<{ configs: VibeChatLLMConfig[] }> {
    return request.get<any, { configs: VibeChatLLMConfig[] }>(`${base(workspaceId)}/llm-configs`)
  },

  getSandboxPorts(
    workspaceId: string,
  ): Promise<{ runtime: string; running: boolean; status?: string; ports: Record<number, number> }> {
    return request.get<any, any>(`/online-coding/workspaces/${workspaceId}/sandbox/ports`)
  },

  /** SSE 流式发消息。 */
  async sendMessage(
    workspaceId: string,
    body: {
      message: string
      attachments?: Array<{ kind: 'image' | 'file'; filename: string; mime?: string; data_url: string }>
    },
    options: {
      onEvent: (eventName: string, data: any) => void
      signal?: AbortSignal
    },
  ): Promise<void> {
    const token = localStorage.getItem('token')
    const resp = await fetch(`${API_PREFIX}${base(workspaceId)}/send`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${token}`,
      },
      body: JSON.stringify(body),
      signal: options.signal,
    })
    if (!resp.ok) {
      // 必须 read body — 不读直接 throw 浏览器会警告 "Attempted to access streaming response content without read()"
      let detail = ''
      try {
        detail = (await resp.text()).slice(0, 300)
      } catch {
        /* ignore */
      }
      throw new Error(`HTTP ${resp.status}${detail ? ': ' + detail : ''}`)
    }
    if (!resp.body) throw new Error('no body')

    const reader = resp.body.getReader()
    const decoder = new TextDecoder()
    let buffer = ''

    const findFrameEnd = (s: string): { idx: number; sep: number } => {
      const a = s.indexOf('\r\n\r\n')
      const b = s.indexOf('\n\n')
      if (a === -1 && b === -1) return { idx: -1, sep: 0 }
      if (a === -1) return { idx: b, sep: 2 }
      if (b === -1) return { idx: a, sep: 4 }
      return a < b ? { idx: a, sep: 4 } : { idx: b, sep: 2 }
    }

    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })
      while (true) {
        const { idx, sep } = findFrameEnd(buffer)
        if (idx === -1) break
        const frame = buffer.slice(0, idx)
        buffer = buffer.slice(idx + sep)
        let currentEvent = ''
        let dataLine = ''
        for (const line of frame.split(/\r?\n/)) {
          if (line.startsWith('event:')) currentEvent = line.slice(6).trim()
          else if (line.startsWith('data:')) dataLine += line.slice(5).trim()
        }
        if (currentEvent && dataLine) {
          let parsed: any = dataLine
          try {
            parsed = JSON.parse(dataLine)
          } catch {
            /* keep as string */
          }
          options.onEvent(currentEvent, parsed)
        }
      }
    }
  },
}
