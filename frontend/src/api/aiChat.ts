import request, { API_PREFIX } from '@/utils/request'

export interface AIChatSession {
  id: number
  title: string
  status: string
  /** 工作模式：'chat'（从零理需求）/ 'cowork'（批量材料整合） */
  mode?: 'chat' | 'cowork' | string
  selected_llm_config_id: number | null
  workspace_dir: string | null
  created_at: string | null
  updated_at: string | null
}

export interface AIChatMessage {
  id: number
  session_id: number
  role: 'user' | 'assistant' | 'system'
  content: string
  extra_meta?: Record<string, any>
  created_at: string | null
}

export interface AIChatToolCall {
  id: number
  session_id: number
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

export interface AIChatAttachment {
  id: number
  session_id: number
  filename: string
  kind: string
  mime: string | null
  size_bytes: number
  has_content_text: boolean
  has_image: boolean
  uploaded_at: string | null
}

export interface AIChatArtifact {
  id: number
  session_id: number
  filename: string
  format: string
  version: number
  preview: string
  size_bytes: number
  content?: string
  created_at: string | null
  updated_at: string | null
}

export interface AIChatSessionDetail {
  session: AIChatSession
  messages: AIChatMessage[]
  tool_calls: AIChatToolCall[]
  attachments: AIChatAttachment[]
  artifacts: AIChatArtifact[]
}

export const aiChatApi = {
  listSessions(): Promise<{ sessions: AIChatSession[] }> {
    return request.get<any, { sessions: AIChatSession[] }>('/ai-chat/sessions')
  },
  createSession(body: { title?: string; selected_llm_config_id?: number | null; mode?: 'chat' | 'cowork' }): Promise<AIChatSession> {
    return request.post<any, AIChatSession>('/ai-chat/sessions', body)
  },
  getSession(id: number): Promise<AIChatSessionDetail> {
    return request.get<any, AIChatSessionDetail>(`/ai-chat/sessions/${id}`)
  },
  updateSession(id: number, body: { title?: string; selected_llm_config_id?: number | null; status?: string }): Promise<AIChatSession> {
    return request.patch<any, AIChatSession>(`/ai-chat/sessions/${id}`, body)
  },
  deleteSession(id: number): Promise<{ ok: boolean }> {
    return request.delete<any, { ok: boolean }>(`/ai-chat/sessions/${id}`)
  },
  async uploadAttachments(id: number, files: File[]): Promise<{ attachments: AIChatAttachment[] }> {
    const fd = new FormData()
    for (const f of files) fd.append('files', f)
    return request.post<any, { attachments: AIChatAttachment[] }>(`/ai-chat/sessions/${id}/upload`, fd)
  },
  abort(id: number): Promise<{ ok: boolean }> {
    return request.post<any, { ok: boolean }>(`/ai-chat/sessions/${id}/abort`)
  },
  listArtifacts(id: number): Promise<{ artifacts: AIChatArtifact[] }> {
    return request.get<any, { artifacts: AIChatArtifact[] }>(`/ai-chat/sessions/${id}/artifacts`)
  },
  getArtifact(id: number, filename: string): Promise<AIChatArtifact> {
    return request.get<any, AIChatArtifact>(`/ai-chat/sessions/${id}/artifacts/${encodeURIComponent(filename)}`)
  },
  /**
   * SSE 发送消息 — 直接 fetch + 流式读 ReadableStream，支持 abort
   * 调用方传 onEvent 回调处理每个 SSE 事件
   */
  async sendMessage(
    sessionId: number,
    body: { message: string; attachment_ids?: number[] },
    options: {
      onEvent: (eventName: string, data: any) => void
      signal?: AbortSignal
    },
  ): Promise<void> {
    const token = localStorage.getItem('token')
    const resp = await fetch(`${API_PREFIX}/ai-chat/sessions/${sessionId}/send`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${token}`,
      },
      body: JSON.stringify(body),
      signal: options.signal,
    })
    if (!resp.ok) {
      throw new Error(`HTTP ${resp.status}`)
    }
    if (!resp.body) throw new Error('no body')

    const reader = resp.body.getReader()
    const decoder = new TextDecoder()
    let buffer = ''
    let currentEvent = ''

    // 兼容 \r\n\r\n（sse_starlette 默认）和 \n\n
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
        currentEvent = ''
        let dataLine = ''
        // SSE 行分隔可能是 \r\n 或 \n
        for (const line of frame.split(/\r?\n/)) {
          if (line.startsWith('event:')) currentEvent = line.slice(6).trim()
          else if (line.startsWith('data:')) dataLine += line.slice(5).trim()
        }
        if (currentEvent && dataLine) {
          let parsed: any = dataLine
          try { parsed = JSON.parse(dataLine) } catch { /* keep as string */ }
          options.onEvent(currentEvent, parsed)
        }
      }
    }
  },
}
