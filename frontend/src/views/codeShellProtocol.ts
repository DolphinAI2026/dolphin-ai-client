export interface ShellFrameEndpoint {
  key: string
  origin: string
  source: MessageEventSource | null
}

export interface TrustedShellMessage {
  type: string
  frameKey: string
  payload: Record<string, unknown>
}

export interface ResolvedShellMessage {
  frame: ShellFrameEndpoint
  message: TrustedShellMessage
}

export type ShellStateMessage =
  | {
    type: 'shell.visibilityChanged'
    frameKey: string
    occurredAt: string
    payload: {
      frameKey: string
      visible: boolean
      interactive: boolean
    }
  }
  | {
    type: 'shell.sessionActivationChanged'
    frameKey: string
    occurredAt: string
    payload: {
      frameKey: string
      active: boolean
    }
  }

const trustedShellEventTypes = new Set([
  'sandbox.ready',
  'builder.ready',
  'builder.dirtyChanged',
  'agent.sessionStateChanged',
  'spec.confirmed',
  'outbox.statusChanged',
  'ci.statusChanged',
  'ide.ready',
  'sandbox.failed',
])

function isRecord(value: unknown): value is Record<string, unknown> {
  return value != null && typeof value === 'object' && !Array.isArray(value)
}

export function resolveTrustedShellMessage(
  event: { origin: string; source: MessageEventSource | null; data: unknown },
  frames: ShellFrameEndpoint[],
): ResolvedShellMessage | null {
  if (!isRecord(event.data) || typeof event.data.type !== 'string') return null
  if (!trustedShellEventTypes.has(event.data.type)) return null

  const payload = isRecord(event.data.payload) ? event.data.payload : {}
  const topLevelFrameKey = typeof event.data.frameKey === 'string' ? event.data.frameKey.trim() : ''
  const payloadFrameKey = typeof payload.frameKey === 'string' ? payload.frameKey.trim() : ''
  if (topLevelFrameKey && payloadFrameKey && topLevelFrameKey !== payloadFrameKey) return null

  const frameKey = topLevelFrameKey || payloadFrameKey
  if (!frameKey) return null

  const frame = frames.find(candidate => candidate.key === frameKey)
  if (!frame || !event.source || !frame.source) return null
  if (event.origin !== frame.origin || event.source !== frame.source) return null

  return {
    frame,
    message: {
      type: event.data.type,
      frameKey,
      payload,
    },
  }
}

export function createShellStateMessages(state: {
  frameKey: string
  visible: boolean
  interactive: boolean
  active: boolean
  occurredAt: string
}): ShellStateMessage[] {
  return [
    {
      type: 'shell.visibilityChanged',
      frameKey: state.frameKey,
      occurredAt: state.occurredAt,
      payload: {
        frameKey: state.frameKey,
        visible: state.visible,
        interactive: state.interactive,
      },
    },
    {
      type: 'shell.sessionActivationChanged',
      frameKey: state.frameKey,
      occurredAt: state.occurredAt,
      payload: {
        frameKey: state.frameKey,
        active: state.active,
      },
    },
  ]
}
