import { describe, expect, it } from 'vitest'
import {
  createShellActivityPanelCloseMessage,
  createShellStateMessages,
  resolveTrustedShellMessage,
  type ShellFrameEndpoint,
} from './codeShellProtocol'

const source = {} as WindowProxy
const endpoint: ShellFrameEndpoint = {
  key: 'code-frame-2',
  origin: 'https://runtime.example.com',
  source,
}

function messageEvent(overrides: Partial<{
  origin: string
  source: MessageEventSource | null
  data: unknown
}> = {}) {
  return {
    origin: 'https://runtime.example.com',
    source,
    data: {
      type: 'builder.ready',
      frameKey: 'code-frame-2',
      payload: { frameKey: 'code-frame-2' },
    },
    ...overrides,
  }
}

describe('code shell protocol', () => {
  it('accepts builder.ready only when origin, source, frame identity and type are trusted', () => {
    const resolved = resolveTrustedShellMessage(messageEvent(), [endpoint])

    expect(resolved).toEqual({
      frame: endpoint,
      message: {
        type: 'builder.ready',
        frameKey: 'code-frame-2',
        payload: { frameKey: 'code-frame-2' },
      },
    })
  })

  it.each([
    ['origin', { origin: 'https://attacker.example.com' }],
    ['source', { source: {} as WindowProxy }],
    ['frame key', {
      data: {
        type: 'builder.ready',
        frameKey: 'code-frame-stale',
        payload: { frameKey: 'code-frame-stale' },
      },
    }],
    ['message type', {
      data: {
        type: 'shell.executeArbitraryCode',
        frameKey: 'code-frame-2',
        payload: { frameKey: 'code-frame-2' },
      },
    }],
  ])('rejects a message with an untrusted %s', (_label, overrides) => {
    expect(resolveTrustedShellMessage(messageEvent(overrides), [endpoint])).toBeNull()
  })

  it('rejects conflicting top-level and payload frame identities', () => {
    expect(resolveTrustedShellMessage(messageEvent({
      data: {
        type: 'builder.ready',
        frameKey: 'code-frame-2',
        payload: { frameKey: 'code-frame-other' },
      },
    }), [endpoint])).toBeNull()
  })

  it('rejects messages without a concrete iframe source', () => {
    expect(resolveTrustedShellMessage(messageEvent({
      source: null,
    }), [{
      ...endpoint,
      source: null,
    }])).toBeNull()
  })

  it('accepts a payload frame identity for compatibility with shell event payloads', () => {
    const resolved = resolveTrustedShellMessage(messageEvent({
      data: {
        type: 'agent.sessionStateChanged',
        payload: { frameKey: 'code-frame-2', state: 'running' },
      },
    }), [endpoint])

    expect(resolved?.message.frameKey).toBe('code-frame-2')
    expect(resolved?.message.type).toBe('agent.sessionStateChanged')
  })

  it('creates visibility and activation messages with an explicit frame identity', () => {
    expect(createShellStateMessages({
      frameKey: 'code-frame-2',
      visible: true,
      interactive: false,
      active: false,
      occurredAt: '2026-07-16T12:00:00.000Z',
    })).toEqual([
      {
        type: 'shell.visibilityChanged',
        frameKey: 'code-frame-2',
        occurredAt: '2026-07-16T12:00:00.000Z',
        payload: {
          frameKey: 'code-frame-2',
          visible: true,
          interactive: false,
        },
      },
      {
        type: 'shell.sessionActivationChanged',
        frameKey: 'code-frame-2',
        occurredAt: '2026-07-16T12:00:00.000Z',
        payload: {
          frameKey: 'code-frame-2',
          active: false,
        },
      },
    ])
  })

  it('accepts activity drawer state only from the trusted frame', () => {
    const resolved = resolveTrustedShellMessage(messageEvent({
      data: {
        type: 'builder.activityPanelChanged',
        frameKey: 'code-frame-2',
        payload: {
          frameKey: 'code-frame-2',
          open: true,
          presentation: 'drawer',
          modal: true,
        },
      },
    }), [endpoint])

    expect(resolved?.message.type).toBe('builder.activityPanelChanged')
    expect(resolved?.message.payload.modal).toBe(true)
  })

  it('creates a frame-bound activity panel close command', () => {
    expect(createShellActivityPanelCloseMessage({
      frameKey: 'code-frame-2',
      occurredAt: '2026-07-16T12:00:00.000Z',
    })).toEqual({
      type: 'shell.activityPanelCloseRequested',
      frameKey: 'code-frame-2',
      occurredAt: '2026-07-16T12:00:00.000Z',
      payload: {
        frameKey: 'code-frame-2',
      },
    })
  })
})
