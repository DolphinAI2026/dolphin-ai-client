export interface SseMessage {
  event: string
  data: string
  id?: string
}

interface ConsumeSseOptions {
  yieldEvery?: number
}

function normalizeLineEndings(input: string): string {
  return input.replace(/\r\n/g, '\n').replace(/\r/g, '\n')
}

function parseSseMessage(block: string): SseMessage | null {
  let event = 'message'
  let id: string | undefined
  const dataLines: string[] = []

  for (const rawLine of block.split('\n')) {
    if (!rawLine || rawLine.startsWith(':')) {
      continue
    }

    const separatorIndex = rawLine.indexOf(':')
    const field = separatorIndex === -1 ? rawLine : rawLine.slice(0, separatorIndex)
    let value = separatorIndex === -1 ? '' : rawLine.slice(separatorIndex + 1)
    if (value.startsWith(' ')) {
      value = value.slice(1)
    }

    if (field === 'event') {
      event = value || 'message'
    } else if (field === 'data') {
      dataLines.push(value)
    } else if (field === 'id') {
      id = value
    }
  }

  if (dataLines.length === 0) {
    return null
  }

  return {
    event,
    data: dataLines.join('\n'),
    id,
  }
}

function waitForPaint(): Promise<void> {
  if (typeof window === 'undefined' || typeof window.requestAnimationFrame !== 'function') {
    return Promise.resolve()
  }

  return new Promise((resolve) => {
    window.requestAnimationFrame(() => resolve())
  })
}

export async function consumeSseResponse(
  response: Response,
  onMessage: (message: SseMessage) => void | Promise<void>,
  options: ConsumeSseOptions = {},
): Promise<void> {
  const reader = response.body?.getReader()
  if (!reader) {
    return
  }

  const decoder = new TextDecoder()
  const yieldEvery = Math.max(1, options.yieldEvery ?? 8)

  let buffer = ''
  let processed = 0

  const flushBuffer = async (flushRemainder = false) => {
    buffer = normalizeLineEndings(buffer)

    let separatorIndex = buffer.indexOf('\n\n')
    while (separatorIndex !== -1) {
      const block = buffer.slice(0, separatorIndex)
      buffer = buffer.slice(separatorIndex + 2)

      const message = parseSseMessage(block)
      if (message) {
        await onMessage(message)
        processed += 1
        if (processed % yieldEvery === 0) {
          await waitForPaint()
        }
      }

      separatorIndex = buffer.indexOf('\n\n')
    }

    if (flushRemainder) {
      const tail = buffer.trim()
      buffer = ''
      const message = tail ? parseSseMessage(tail) : null
      if (message) {
        await onMessage(message)
      }
    }
  }

  while (true) {
    const { done, value } = await reader.read()
    if (done) {
      buffer += decoder.decode()
      await flushBuffer(true)
      return
    }

    buffer += decoder.decode(value, { stream: true })
    await flushBuffer(false)
  }
}
