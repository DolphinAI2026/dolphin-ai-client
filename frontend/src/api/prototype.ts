import { API_PREFIX } from '@/utils/request'

/**
 * 触发 HTML 原型生成（SSE 流）。后端事件：started / progress / error / prototype_ready。
 * onEvent 收到每个事件；完成时是 prototype_ready，data.prototype_id 可用于 fetchPrototypeHtml。
 */
export async function generatePrototype(
  appId: number,
  onEvent: (event: string, data: any) => void | Promise<void>,
  signal?: AbortSignal,
): Promise<void> {
  const token = localStorage.getItem('token')
  const resp = await fetch(`${API_PREFIX}/applications/${appId}/prototype/generate`, {
    method: 'POST',
    headers: { Accept: 'text/event-stream', Authorization: `Bearer ${token}` },
    signal,
  })
  if (!resp.ok || !resp.body) throw new Error(`原型生成请求失败 (${resp.status})`)

  const reader = resp.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    const frames = buffer.split(/\n\n/)
    buffer = frames.pop() ?? ''
    for (const frame of frames) {
      let ev = 'message'
      let data = ''
      for (const line of frame.split(/\r?\n/)) {
        if (line.startsWith('event:')) ev = line.slice(6).trim()
        else if (line.startsWith('data:')) data += line.slice(5).trim()
      }
      if (data) {
        try { await onEvent(ev, JSON.parse(data)) } catch { await onEvent(ev, data) }
      }
    }
  }
}

/** 读取已生成的原型 HTML 全文（用于 iframe 渲染）。 */
export async function fetchPrototypeHtml(appId: number, prototypeId: number): Promise<string> {
  const token = localStorage.getItem('token')
  const resp = await fetch(`${API_PREFIX}/applications/${appId}/prototype/${prototypeId}`, {
    headers: { Authorization: `Bearer ${token}` },
  })
  if (!resp.ok) throw new Error(`读取原型失败 (${resp.status})`)
  const json = await resp.json()
  return json.html_content as string
}
