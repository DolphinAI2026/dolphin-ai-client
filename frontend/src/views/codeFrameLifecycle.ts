export type CodeFramePhase = 'active' | 'hot_hidden' | 'pending'

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
  lastUsedOrder: number
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
  hot: CodeFrame[]
  pending: CodeFrame | null
  request: CodeFrameOpenRequest | null
  failed: CodeFrameFailure | null
  lastReadyRoute: CodeFrameRouteLocation | null
  nextFrameId: number
  nextAccessOrder: number
  maxFrames: number
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
    hot: [],
    pending: null,
    request: null,
    failed: null,
    lastReadyRoute: null,
    nextFrameId: 1,
    nextAccessOrder: 1,
    maxFrames: 2,
  }
}

function normalizeFrameLimit(maxFrames: number): number {
  if (!Number.isFinite(maxFrames)) return 2
  return Math.min(10, Math.max(1, Math.trunc(maxFrames)))
}

function trimHotFrames(hot: CodeFrame[], maxFrames: number): CodeFrame[] {
  const hiddenLimit = Math.max(0, normalizeFrameLimit(maxFrames) - 1)
  return [...hot]
    .sort((left, right) => right.lastUsedOrder - left.lastUsedOrder)
    .slice(0, hiddenLimit)
}

function hiddenFrame(frame: CodeFrame): CodeFrame {
  return {
    ...frame,
    phase: 'hot_hidden',
  }
}

export function setCodeFrameCacheLimit(
  state: CodeFrameLifecycle,
  maxFrames: number,
): CodeFrameLifecycle {
  const normalized = normalizeFrameLimit(maxFrames)
  const hot = trimHotFrames(state.hot, normalized)
  if (state.maxFrames === normalized && hot.length === state.hot.length) return state
  return {
    ...state,
    hot,
    maxFrames: normalized,
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

export function shouldDiscardPendingCodeFrameForNextSession(
  state: CodeFrameLifecycle,
  nextSessionRef: string,
): boolean {
  const pendingSessionRef = state.pending?.sessionRef || state.request?.sessionRef
  return Boolean(pendingSessionRef && pendingSessionRef !== nextSessionRef)
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
  resolvedUrl.searchParams.delete('tenantId')
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
      lastUsedOrder: 0,
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

  // A shell session owns at most one mounted iframe. Reopening another agent
  // route for the same shell replaces that frame instead of retaining a stale
  // duplicate with the same runtime identity.
  const previousFrames = [
    ...state.hot,
    ...(state.active ? [state.active] : []),
  ].filter(frame => frame.sessionRef !== pending.sessionRef)

  return {
    ...state,
    active: {
      ...pending,
      phase: 'active',
      loaded: true,
      lastUsedOrder: state.nextAccessOrder,
    },
    hot: trimHotFrames(previousFrames.map(hiddenFrame), state.maxFrames),
    pending: null,
    request: null,
    failed: null,
    lastReadyRoute: cloneCodeFrameRoute(pending.route),
    nextAccessOrder: state.nextAccessOrder + 1,
  }
}

export function activateCachedCodeFrame(
  state: CodeFrameLifecycle,
  options: {
    requestId: number
    sessionRef: string
    requireRouteMatch: boolean
  },
): CodeFrameLifecycle {
  const request = state.request
  if (
    request?.requestId !== options.requestId
    || request.sessionRef !== options.sessionRef
  ) {
    return state
  }

  const cached = state.hot.find(frame =>
    frame.sessionRef === options.sessionRef
    && (!options.requireRouteMatch || codeFrameRoutesEqual(frame.route, request.route)),
  )
  if (!cached) return state

  const previousFrames = [
    ...state.hot.filter(frame => frame.key !== cached.key),
    ...(state.active && state.active.sessionRef !== cached.sessionRef ? [state.active] : []),
  ]

  return {
    ...state,
    active: {
      ...cached,
      route: cloneCodeFrameRoute(request.route),
      phase: 'active',
      lastUsedOrder: state.nextAccessOrder,
    },
    hot: trimHotFrames(previousFrames.map(hiddenFrame), state.maxFrames),
    pending: null,
    request: null,
    failed: null,
    lastReadyRoute: cloneCodeFrameRoute(request.route),
    nextAccessOrder: state.nextAccessOrder + 1,
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
  return [state.active, ...state.hot, state.pending]
    .filter((frame): frame is CodeFrame => frame != null)
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
