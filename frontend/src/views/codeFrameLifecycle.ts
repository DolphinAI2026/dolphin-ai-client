export type CodeFramePhase = 'active' | 'pending'

export interface CodeFrameRouteLocation {
  path: string
  query: Record<string, string | null | Array<string | null>>
}

export interface CodeFrame {
  key: string
  sessionRef: string
  route: CodeFrameRouteLocation
  sourceUrl: string
  url: string
  origin: string
  phase: CodeFramePhase
  loaded: boolean
  requestId: number
}

export interface CodeFrameOpenRequest {
  requestId: number
  sessionRef: string
  route: CodeFrameRouteLocation
}

export interface CodeFrameFailure extends CodeFrameOpenRequest {
  frameKey?: string
  message: string
}

export interface CodeFrameFailureInput {
  requestId: number
  frameKey?: string
  message: string
}

export interface CodeFrameLifecycle {
  active: CodeFrame | null
  pending: CodeFrame | null
  request: CodeFrameOpenRequest | null
  failed: CodeFrameFailure | null
  lastReadyRoute: CodeFrameRouteLocation | null
  nextFrameId: number
}

function cloneCodeFrameRoute(route: CodeFrameRouteLocation): CodeFrameRouteLocation {
  return {
    path: route.path,
    query: Object.fromEntries(
      Object.entries(route.query).map(([key, value]) => [
        key,
        Array.isArray(value) ? [...value] : value,
      ]),
    ),
  }
}

function codeFrameRoutesEqual(
  left: CodeFrameRouteLocation,
  right: CodeFrameRouteLocation,
): boolean {
  return JSON.stringify([
    left.path,
    Object.keys(left.query).sort().map(key => [key, left.query[key]]),
  ]) === JSON.stringify([
    right.path,
    Object.keys(right.query).sort().map(key => [key, right.query[key]]),
  ])
}

export function createCodeFrameLifecycle(): CodeFrameLifecycle {
  return {
    active: null,
    pending: null,
    request: null,
    failed: null,
    lastReadyRoute: null,
    nextFrameId: 1,
  }
}

export function beginCodeFrameOpen(
  state: CodeFrameLifecycle,
  request: CodeFrameOpenRequest,
): CodeFrameLifecycle {
  return {
    ...state,
    pending: null,
    request: {
      ...request,
      route: cloneCodeFrameRoute(request.route),
    },
    failed: null,
  }
}

export function queuePendingCodeFrame(
  state: CodeFrameLifecycle,
  input: Pick<CodeFrameOpenRequest, 'requestId' | 'sessionRef'> & { url: string; baseUrl: string },
): CodeFrameLifecycle {
  if (
    state.request?.requestId !== input.requestId
    || state.request.sessionRef !== input.sessionRef
  ) {
    return state
  }

  if (
    state.active?.sessionRef === input.sessionRef
    && state.active.sourceUrl === input.url
    && codeFrameRoutesEqual(state.active.route, state.request.route)
  ) {
    return {
      ...state,
      active: {
        ...state.active,
        route: cloneCodeFrameRoute(state.request.route),
      },
      pending: null,
      request: null,
      failed: null,
      lastReadyRoute: cloneCodeFrameRoute(state.request.route),
    }
  }

  if (
    state.pending?.requestId === input.requestId
    && state.pending.sessionRef === input.sessionRef
    && state.pending.sourceUrl === input.url
  ) {
    return state
  }

  const key = `code-frame-${state.nextFrameId}`
  const resolvedUrl = new URL(input.url, input.baseUrl)
  resolvedUrl.searchParams.set('frameKey', key)

  return {
    ...state,
    pending: {
      key,
      sessionRef: input.sessionRef,
      route: cloneCodeFrameRoute(state.request.route),
      sourceUrl: input.url,
      url: resolvedUrl.toString(),
      origin: resolvedUrl.origin,
      phase: 'pending',
      loaded: false,
      requestId: input.requestId,
    },
    failed: null,
    nextFrameId: state.nextFrameId + 1,
  }
}

export function markCodeFrameLoaded(state: CodeFrameLifecycle, frameKey: string): CodeFrameLifecycle {
  if (state.pending?.key !== frameKey || state.pending.loaded) return state
  return {
    ...state,
    pending: {
      ...state.pending,
      loaded: true,
    },
  }
}

export function promoteReadyCodeFrame(state: CodeFrameLifecycle, frameKey: string): CodeFrameLifecycle {
  const pending = state.pending
  if (
    pending?.key !== frameKey
    || state.request?.requestId !== pending.requestId
    || state.request.sessionRef !== pending.sessionRef
  ) {
    return state
  }

  return {
    ...state,
    active: {
      ...pending,
      phase: 'active',
      loaded: true,
    },
    pending: null,
    request: null,
    failed: null,
    lastReadyRoute: cloneCodeFrameRoute(pending.route),
  }
}

export function failCodeFrameOpen(
  state: CodeFrameLifecycle,
  failure: CodeFrameFailureInput,
): CodeFrameLifecycle {
  const request = state.request
  if (!request || request.requestId !== failure.requestId) return state
  if (failure.frameKey && state.pending?.key !== failure.frameKey) return state

  return {
    ...state,
    pending: null,
    request: null,
    failed: {
      ...request,
      ...(failure.frameKey ? { frameKey: failure.frameKey } : {}),
      message: failure.message,
    },
  }
}

export function getCodeFrames(state: CodeFrameLifecycle): CodeFrame[] {
  return [state.active, state.pending].filter((frame): frame is CodeFrame => frame != null)
}

export function isCodeFrameSwitching(state: CodeFrameLifecycle): boolean {
  return Boolean(state.active && state.request)
}

export function isCodeFrameVisible(state: CodeFrameLifecycle, frame: CodeFrame): boolean {
  return state.active?.key === frame.key
}

export function isCodeFrameInteractive(state: CodeFrameLifecycle, frame: CodeFrame): boolean {
  return (
    state.active?.key === frame.key
    && state.request == null
    && state.pending == null
  )
}
