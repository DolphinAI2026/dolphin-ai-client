import { describe, expect, it } from 'vitest'
import {
  beginCodeFrameOpen,
  createCodeFrameLifecycle,
  failCodeFrameOpen,
  getCodeFrames,
  isCodeFrameInteractive,
  isCodeFrameSwitching,
  isCodeFrameVisible,
  markCodeFrameLoaded,
  promoteReadyCodeFrame,
  queuePendingCodeFrame,
} from './codeFrameLifecycle'

const baseUrl = 'https://builder.example.com/code/session-1'

function openInitialFrame() {
  let state = createCodeFrameLifecycle()
  state = beginCodeFrameOpen(state, { requestId: 1, sessionRef: 'session-1' })
  state = queuePendingCodeFrame(state, {
    requestId: 1,
    sessionRef: 'session-1',
    url: '/api/code-runtime/session-1/embed?token=one',
    baseUrl,
  })
  return state
}

function activateInitialFrame() {
  const pending = openInitialFrame().pending!
  return promoteReadyCodeFrame(openInitialFrame(), pending.key)
}

describe('code frame lifecycle', () => {
  it('keeps the first frame pending until trusted readiness promotes it', () => {
    let state = openInitialFrame()
    const pending = state.pending!

    expect(state.active).toBeNull()
    expect(pending).toMatchObject({
      key: 'code-frame-1',
      sessionRef: 'session-1',
      sourceUrl: '/api/code-runtime/session-1/embed?token=one',
      origin: 'https://builder.example.com',
      phase: 'pending',
      loaded: false,
    })
    expect(pending.url).toContain('frameKey=code-frame-1')

    state = markCodeFrameLoaded(state, pending.key)

    expect(state.active).toBeNull()
    expect(state.pending).toMatchObject({ key: pending.key, loaded: true, phase: 'pending' })

    state = promoteReadyCodeFrame(state, pending.key)

    expect(state.pending).toBeNull()
    expect(state.active).toMatchObject({ key: pending.key, phase: 'active', loaded: true })
    expect(isCodeFrameInteractive(state, state.active!)).toBe(true)
  })

  it('keeps the old frame visible but freezes it immediately during a switch', () => {
    let state = activateInitialFrame()
    const oldFrame = state.active!

    state = beginCodeFrameOpen(state, { requestId: 2, sessionRef: 'session-2' })

    expect(isCodeFrameSwitching(state)).toBe(true)
    expect(isCodeFrameVisible(state, oldFrame)).toBe(true)
    expect(isCodeFrameInteractive(state, oldFrame)).toBe(false)

    state = queuePendingCodeFrame(state, {
      requestId: 2,
      sessionRef: 'session-2',
      url: 'https://runtime.example.com/workspaces/session-2?token=two',
      baseUrl,
    })

    const [active, pending] = getCodeFrames(state)
    expect(active.key).toBe(oldFrame.key)
    expect(pending.phase).toBe('pending')
    expect(isCodeFrameVisible(state, active)).toBe(true)
    expect(isCodeFrameVisible(state, pending)).toBe(false)
    expect(isCodeFrameInteractive(state, active)).toBe(false)
    expect(isCodeFrameInteractive(state, pending)).toBe(false)
  })

  it('atomically replaces the old frame only when the current pending frame is ready', () => {
    let state = activateInitialFrame()
    const oldKey = state.active!.key
    state = beginCodeFrameOpen(state, { requestId: 2, sessionRef: 'session-2' })
    state = queuePendingCodeFrame(state, {
      requestId: 2,
      sessionRef: 'session-2',
      url: '/api/code-runtime/session-2/embed',
      baseUrl,
    })
    const pendingKey = state.pending!.key

    state = promoteReadyCodeFrame(state, pendingKey)

    expect(state.request).toBeNull()
    expect(state.pending).toBeNull()
    expect(state.active).toMatchObject({ key: pendingKey, sessionRef: 'session-2', phase: 'active' })
    expect(getCodeFrames(state).map(frame => frame.key)).not.toContain(oldKey)
  })

  it('ignores a late ready from a frame replaced by a newer switch', () => {
    let state = activateInitialFrame()
    state = beginCodeFrameOpen(state, { requestId: 2, sessionRef: 'session-2' })
    state = queuePendingCodeFrame(state, {
      requestId: 2,
      sessionRef: 'session-2',
      url: '/api/code-runtime/session-2/embed',
      baseUrl,
    })
    const staleKey = state.pending!.key

    state = beginCodeFrameOpen(state, { requestId: 3, sessionRef: 'session-3' })
    state = queuePendingCodeFrame(state, {
      requestId: 3,
      sessionRef: 'session-3',
      url: '/api/code-runtime/session-3/embed',
      baseUrl,
    })
    const currentPendingKey = state.pending!.key
    const afterLateReady = promoteReadyCodeFrame(state, staleKey)

    expect(afterLateReady).toBe(state)
    expect(afterLateReady.pending?.key).toBe(currentPendingKey)
    expect(afterLateReady.active?.sessionRef).toBe('session-1')

    state = promoteReadyCodeFrame(afterLateReady, currentPendingKey)
    expect(state.active?.sessionRef).toBe('session-3')
  })

  it('rolls back a failed switch and restores old-frame interaction', () => {
    let state = activateInitialFrame()
    const oldFrame = state.active!
    state = beginCodeFrameOpen(state, { requestId: 2, sessionRef: 'session-2' })
    state = queuePendingCodeFrame(state, {
      requestId: 2,
      sessionRef: 'session-2',
      url: '/api/code-runtime/session-2/embed',
      baseUrl,
    })

    state = failCodeFrameOpen(state, {
      requestId: 2,
      frameKey: state.pending!.key,
      message: 'runtime failed',
    })

    expect(state.pending).toBeNull()
    expect(state.request).toBeNull()
    expect(state.failed).toEqual({
      requestId: 2,
      sessionRef: 'session-2',
      frameKey: 'code-frame-2',
      message: 'runtime failed',
    })
    expect(state.active?.key).toBe(oldFrame.key)
    expect(isCodeFrameInteractive(state, state.active!)).toBe(true)
  })

  it('does not mount a duplicate frame for the same active session URL', () => {
    let state = activateInitialFrame()
    const active = state.active!
    state = beginCodeFrameOpen(state, { requestId: 2, sessionRef: active.sessionRef })
    state = queuePendingCodeFrame(state, {
      requestId: 2,
      sessionRef: active.sessionRef,
      url: active.sourceUrl,
      baseUrl,
    })

    expect(state.active).toBe(active)
    expect(state.pending).toBeNull()
    expect(state.request).toBeNull()
    expect(state.nextFrameId).toBe(2)
    expect(isCodeFrameInteractive(state, active)).toBe(true)
  })
})
