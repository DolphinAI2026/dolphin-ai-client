import request, { API_PREFIX } from '@/utils/request'

export interface HelpMessage {
  role: 'user' | 'assistant'
  content: string
}

export interface HelpMeta {
  kb_files: number
  kb_chars: number
  files?: string[]
}

export const helpAssistantApi = {
  meta(): Promise<HelpMeta> {
    return request.get<any, HelpMeta>('/help/meta')
  },

  /** 流式对话：调用方拿到 ReadableStream，按 SSE `data: {delta|error}\n\n` 解析 */
  async stream(
    messages: HelpMessage[],
    opts?: {
      signal?: AbortSignal
      selected_llm_config_id?: number | null
      current_path?: string | null
    },
  ): Promise<Response> {
    const token = localStorage.getItem('token') || ''
    const url = `${API_PREFIX}/help/chat`
    const res = await fetch(url, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: token ? `Bearer ${token}` : '',
      },
      body: JSON.stringify({
        messages,
        selected_llm_config_id: opts?.selected_llm_config_id ?? null,
        current_path: opts?.current_path ?? null,
      }),
      signal: opts?.signal,
    })
    if (!res.ok) {
      const text = await res.text().catch(() => '')
      throw new Error(`help/chat ${res.status}: ${text.slice(0, 200)}`)
    }
    return res
  },
}

/** 解析 SSE 流，逐 chunk 回调 onDelta；异常回调 onError；结束回调 onDone */
export async function consumeHelpStream(
  response: Response,
  callbacks: {
    onDelta?: (text: string) => void
    onError?: (err: string) => void
    onDone?: () => void
  },
): Promise<void> {
  const reader = response.body?.getReader()
  if (!reader) {
    callbacks.onError?.('no response body')
    callbacks.onDone?.()
    return
  }
  const decoder = new TextDecoder('utf-8')
  let buffer = ''
  try {
    while (true) {
      const { value, done } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })
      let idx: number
      while ((idx = buffer.indexOf('\n\n')) !== -1) {
        const block = buffer.slice(0, idx).trim()
        buffer = buffer.slice(idx + 2)
        if (!block.startsWith('data:')) continue
        const raw = block.slice(5).trim()
        if (raw === '[DONE]') {
          callbacks.onDone?.()
          return
        }
        try {
          const obj = JSON.parse(raw)
          if (obj.delta) callbacks.onDelta?.(obj.delta)
          if (obj.error) callbacks.onError?.(obj.error)
        } catch {
          /* 非 JSON 行忽略 */
        }
      }
    }
  } finally {
    callbacks.onDone?.()
  }
}
