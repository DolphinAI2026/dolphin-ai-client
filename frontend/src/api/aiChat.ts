import request, { API_PREFIX } from '@/utils/request'

export interface AIChatSession {
  id: number
  title: string
  status: string
  generation?: {
    app_id: number
    app_name?: string | null
    app_code?: string | null
    is_new?: boolean | null
    status: string
    label: string
    deploy_record_id?: number | null
    error_message?: string | null
  } | null
  /** 工作模式：'chat'（从零理需求）/ 'cowork'（批量材料整合） */
  mode?: 'chat' | 'cowork' | string
  selected_llm_config_id: number | null
  workspace_dir: string | null
  created_at: string | null
  updated_at: string | null
}

export interface AIChatGenerationMeta {
  app_id: number
  app_name?: string | null
  app_code?: string | null
  is_new?: boolean | null
  status: string
  label: string
  deploy_record_id?: number | null
  error_message?: string | null
}

export interface AIChatMessage {
  id: number
  session_id: number
  role: 'user' | 'assistant' | 'system'
  content: string
  run_id?: string | null
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
  generation?: AIChatGenerationMeta | null
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
  // 图片附件:base64 data URL(后端仅对 kind=image 回带), 用于历史消息气泡渲染缩略图。
  image_data_url?: string | null
  uploaded_at: string | null
}

export interface AIChatArtifact {
  id: number
  session_id: number
  filename: string
  format: string
  version: number
  /** 'text'（默认，content 即正文）/ 'file'（二进制产物，走 download 端点） */
  storage?: string
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

/** 读 fetch 的 SSE 流,逐帧调 onEvent(eventName, parsedData)。send 与 attach 共用。 */
async function _consumeSse(resp: Response, onEvent: (eventName: string, data: any) => void): Promise<void> {
  if (!resp.body) throw new Error('no body')
  const reader = resp.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  // 兼容 \r\n\r\n(sse_starlette 默认)和 \n\n
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
        try { parsed = JSON.parse(dataLine) } catch { /* keep as string */ }
        onEvent(currentEvent, parsed)
      }
    }
  }
}

export const aiChatApi = {
  listSessions(params?: { app_id?: number }): Promise<{ sessions: AIChatSession[] }> {
    const qs = params?.app_id != null ? `?app_id=${params.app_id}` : ''
    return request.get<any, { sessions: AIChatSession[] }>(`/ai-chat/sessions${qs}`)
  },
  createSession(body: { title?: string; selected_llm_config_id?: number | null; mode?: 'chat' | 'cowork'; app_id?: number | null; section?: string | null }): Promise<AIChatSession> {
    return request.post<any, AIChatSession>('/ai-chat/sessions', body)
  },
  getSession(id: number, params?: { app_id?: number | null }): Promise<AIChatSessionDetail> {
    const qs = params?.app_id != null ? `?app_id=${params.app_id}` : ''
    return request.get<any, AIChatSessionDetail>(`/ai-chat/sessions/${id}${qs}`)
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
  getArtifact(id: number, filename: string, version?: number): Promise<AIChatArtifact> {
    const v = version != null ? `?version=${version}` : ''
    return request.get<any, AIChatArtifact>(`/ai-chat/sessions/${id}/artifacts/${encodeURIComponent(filename)}${v}`)
  },
  listArtifactVersions(id: number, filename: string): Promise<{ versions: AIChatArtifact[] }> {
    return request.get<any, { versions: AIChatArtifact[] }>(`/ai-chat/sessions/${id}/artifacts/${encodeURIComponent(filename)}/versions`)
  },
  /** 二进制产物（storage=='file'）的下载地址 —— 带 token query 让浏览器直接 GET 拿文件 */
  artifactDownloadUrl(id: number, filename: string, version?: number): string {
    const token = localStorage.getItem('token') || ''
    const params = new URLSearchParams()
    if (version != null) params.set('version', String(version))
    if (token) params.set('token', token)
    const qs = params.toString()
    return `${API_PREFIX}/ai-chat/sessions/${id}/artifacts/${encodeURIComponent(filename)}/download${qs ? `?${qs}` : ''}`
  },
  /**
   * SSE 发送消息 — 直接 fetch + 流式读 ReadableStream，支持 abort
   * 调用方传 onEvent 回调处理每个 SSE 事件
   */
  async sendMessage(
    sessionId: number,
    body: { message: string; attachment_ids?: number[]; section?: string | null; view_context?: string | null },
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
      let detail = `HTTP ${resp.status}`
      try { const j = await resp.json(); detail = j?.detail || detail } catch { /* ignore */ }
      const err: any = new Error(detail)
      err.status = resp.status  // 409 = 该会话有任务在跑(单会话单 run 守卫)
      throw err
    }
    await _consumeSse(resp, options.onEvent)
  },

  /** 该会话是否有在跑 run + 最新 seq —— 切回会话据此决定是否 attach 续看 */
  getRunStatus(id: number): Promise<{ running: boolean; last_seq: number; run_id: string | null }> {
    return request.get(`/ai-chat/sessions/${id}/run-status`)
  },

  /** 重连在跑 run 的 SSE(切会话/刷新后续看):补 seq>afterSeq + 跟实时。复用 send 的事件回调。 */
  async attachRun(
    sessionId: number,
    afterSeq: number,
    options: { onEvent: (eventName: string, data: any) => void; signal?: AbortSignal },
  ): Promise<void> {
    const token = localStorage.getItem('token')
    const resp = await fetch(`${API_PREFIX}/ai-chat/sessions/${sessionId}/attach?after_seq=${afterSeq}`, {
      method: 'GET',
      headers: { Authorization: `Bearer ${token}` },
      signal: options.signal,
    })
    if (!resp.ok) return
    await _consumeSse(resp, options.onEvent)
  },
}
