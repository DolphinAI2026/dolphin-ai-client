import { describe, expect, it } from 'vitest'
import pageSource from './CodeConversationPage.vue?raw'

describe('CodeConversationPage', () => {
  it('opens a Dolphin Code session and renders the d-ai-code iframe', () => {
    expect(pageSource).toContain("from '@/api/codeRuntime'")
    expect(pageSource).toContain('codeRuntimeApi.openSession')
    expect(pageSource).toContain('<iframe')
    expect(pageSource).toContain(':src="frame.url"')
    expect(pageSource).toContain('message')
    expect(pageSource).toContain('agent.sessionStateChanged')
  })

  it('does not own WorkbenchShell; the /code parent route keeps the rail mounted', () => {
    expect(pageSource).not.toContain("import WorkbenchShell")
    expect(pageSource).not.toContain('<WorkbenchShell>')
  })

  it('refreshes the outer rail after opening the runtime session', () => {
    expect(pageSource).toContain("new CustomEvent('code-rail-refresh')")
    expect(pageSource).toContain('window.dispatchEvent')
  })

  it('refreshes the outer rail when the embedded runtime reports session state changes', () => {
    const handlerSource = pageSource.slice(pageSource.indexOf('function onShellMessage'))

    expect(handlerSource).toContain("message.type === 'agent.sessionStateChanged'")
    expect(handlerSource).toContain('resolveTrustedShellMessage')
    expect(handlerSource).toContain('refreshOuterCodeRail()')
  })

  it('keeps the old Code iframe visible while the next iframe waits for trusted readiness', () => {
    expect(pageSource).toContain('v-for="frame in frames"')
    expect(pageSource).toContain('code-frame-pending')
    expect(pageSource).toContain('@load="onCodeFrameLoad(frame.key)"')
    expect(pageSource).toContain('markCodeFrameLoaded')
    expect(pageSource).not.toContain('@load="frame.phase === \'pending\' && promotePendingFrame(frame.key)"')
    expect(pageSource).toContain('frameSwitching')
    expect(pageSource).toContain('code-frame-interaction-guard')
    expect(pageSource).toContain('code-frame-frozen')
    expect(pageSource).not.toContain('v-if="loading" class="code-status"')
  })

  it('promotes only a trusted pending builder.ready message', () => {
    expect(pageSource).toContain("from './codeFrameLifecycle'")
    expect(pageSource).toContain("from './codeShellProtocol'")
    expect(pageSource).toContain('resolveTrustedShellMessage')
    expect(pageSource).toContain("message.type === 'builder.ready'")
    expect(pageSource).toContain("frame.phase === 'pending'")
    expect(pageSource).toContain('promoteReadyCodeFrame')
    expect(pageSource).toContain('event.origin')
    expect(pageSource).toContain('event.source')
    expect(pageSource).toContain('frame.key')
  })

  it('commits only the promoted pending shell preference after trusted readiness', () => {
    expect(pageSource).toContain('commitPendingCodeApplicationLocationPreferenceByShellSessionRef')
    expect(pageSource).toContain('promoteReadyCodeFrame(previousState, frame.key)')
    expect(pageSource).toContain('commitPendingCodeApplicationLocationPreferenceByShellSessionRef(frame.sessionRef)')
  })

  it('discards only the pending shell preference on open failure, timeout, sandbox failure, or exit', () => {
    expect(pageSource).toContain('discardPendingCodeApplicationLocationPreferenceByShellSessionRef')
    expect(pageSource).toContain('discardPendingCodeApplicationLocationPreferenceByShellSessionRef(previousState.request?.sessionRef')
    expect(pageSource).toContain('discardPendingCodeApplicationLocationPreferenceByShellSessionRef(pending.sessionRef)')
    expect(pageSource).toContain('onBeforeUnmount')
  })

  it('replays the current shell state when an active sandbox reports builder.ready again', () => {
    const readyHandlerSource = pageSource.slice(
      pageSource.indexOf("if (message.type === 'builder.ready')"),
      pageSource.indexOf("if (message.type === 'sandbox.failed')"),
    )

    expect(readyHandlerSource).toContain('nextTick(publishCodeFrameShellState)')
    expect(readyHandlerSource).toContain("frame.phase === 'active'")
  })

  it('publishes visibility and session activation state to every mounted frame', () => {
    expect(pageSource).toContain('createShellStateMessages')
    expect(pageSource).toContain('shell.visibilityChanged')
    expect(pageSource).toContain('shell.sessionActivationChanged')
    expect(pageSource).toContain('contentWindow')
    expect(pageSource).toContain('postMessage')
    expect(pageSource).toContain('visibilitychange')
  })

  it('extends drawer modality across the host rail and closes it through the trusted shell channel', () => {
    expect(pageSource).toContain("message.type === 'builder.activityPanelChanged'")
    expect(pageSource).toContain('code-host-activity-scrim')
    expect(pageSource).toContain('hostActivityModalFrameKey')
    expect(pageSource).toContain('createShellActivityPanelCloseMessage')
    expect(pageSource).toContain('closeHostedActivityDrawer')
    expect(pageSource).toContain('<Teleport to="body">')
  })

  it('opens trusted interactive runtime links in a new browser tab without navigating the iframe', () => {
    const handlerSource = pageSource.slice(
      pageSource.indexOf('function onShellMessage'),
      pageSource.indexOf('watch(', pageSource.indexOf('function onShellMessage')),
    )
    const interactiveGuardIndex = handlerSource.indexOf('if (!isFrameInteractive(frame)) return')
    const externalNavigationIndex = handlerSource.indexOf(
      "if (message.type === 'builder.externalNavigationRequested')",
    )

    expect(interactiveGuardIndex).toBeGreaterThanOrEqual(0)
    expect(externalNavigationIndex).toBeGreaterThan(interactiveGuardIndex)

    const externalNavigationSource = handlerSource.slice(
      externalNavigationIndex,
      handlerSource.indexOf("if (message.type === 'builder.activityPanelChanged')", externalNavigationIndex),
    )
    expect(externalNavigationSource).toContain('resolveExternalNavigationUrl(message.payload.url)')
    expect(externalNavigationSource).toContain("window.open(url, '_blank', 'noopener,noreferrer')")
    expect(externalNavigationSource).not.toMatch(/frame\.url\s*=|location\.(?:href|assign|replace)/)
  })

  it('binds frame identity to the iframe DOM node and disables stale interaction during switches', () => {
    expect(pageSource).toContain(':data-frame-key="frame.key"')
    expect(pageSource).toContain(':name="frame.key"')
    expect(pageSource).toContain('setCodeFrameElement(frame.key')
    expect(pageSource).toContain('isCodeFrameInteractive')
    expect(pageSource).toContain('pointer-events: none')
  })

  it('fails a pending frame after a request-bound builder.ready timeout and clears timers', () => {
    expect(pageSource).toContain('READY_TIMEOUT_MS = 120_000')
    expect(pageSource).toContain('pendingReadyTimer')
    expect(pageSource).toContain('startPendingReadyTimer')
    expect(pageSource).toContain('clearPendingReadyTimer')
    expect(pageSource).toContain('window.setTimeout')
    expect(pageSource).toContain('requestId')
    expect(pageSource).toContain('frameKey')
    expect(pageSource).toContain('Code 工作台准备超时')
    expect(pageSource).toContain('failCodeFrameOpen')
    expect(pageSource).toContain('onBeforeUnmount')
  })

  it('polls local startup status and exposes in-page recovery actions', () => {
    expect(pageSource).toContain('CodeWorkspaceOpening')
    expect(pageSource).toContain('codeRuntimeApi.getOpenStatus(sessionRef)')
    expect(pageSource).toContain('OPEN_STATUS_POLL_MS = 500')
    expect(pageSource).toContain('startOpenStatusPolling')
    expect(pageSource).toContain('stopOpenStatusPolling')
    expect(pageSource).toContain('codeRuntimeApi.restartLocalRuntime')
    expect(pageSource).toContain('codeRuntimeApi.rebindLocalWorkspace')
    expect(pageSource).toContain("pickDirectory('重新选择本地应用目录')")
    expect(pageSource).toContain("router.push('/code/apps')")
  })

  it('restores the last ready route after pending failure without reopening the active frame', () => {
    const restoreSource = pageSource.slice(
      pageSource.indexOf('function restoreActiveRouteAfterFailure'),
      pageSource.indexOf('function failCurrentFrameOpen'),
    )

    expect(pageSource).toContain('lastReadyRoute')
    expect(pageSource).toContain('restoreActiveRouteAfterFailure')
    expect(pageSource).toContain('routeRestoreTarget')
    expect(pageSource).toContain('consumeRouteRestore')
    expect(pageSource).toContain('router.replace')
    expect(pageSource).toContain('failed?.route')
    expect(pageSource).toContain('retryFailedSession')
    expect(pageSource).toContain('@click="retryFailedSession"')
    expect(pageSource).toContain('function clearRouteRestoreTarget')
    expect(restoreSource).toContain('.catch(() => undefined)')
    expect(restoreSource).toContain('.finally(() => {')
    expect(restoreSource).toContain('clearRouteRestoreTarget(target)')
  })

  it('opens the sandbox before activating the route agent so restore is not overwritten', () => {
    expect(pageSource).toContain('function currentRuntimeAgentId()')
    expect(pageSource).toContain('function currentSessionRef(): string')
    expect(pageSource).toContain('codeRuntimeApi.openSession(sessionRef)')
    expect(pageSource).toContain('codeRuntimeApi.activateAgentSession(opened.session_id, runtimeAgentId)')
    expect(pageSource).toContain('runtimeAgentId && opened.runtime_session_id !== runtimeAgentId')
    expect(pageSource.indexOf('codeRuntimeApi.openSession(sessionRef)'))
      .toBeLessThan(pageSource.indexOf('codeRuntimeApi.activateAgentSession(opened.session_id, runtimeAgentId)'))
    expect(pageSource.indexOf('codeRuntimeApi.activateAgentSession(opened.session_id, runtimeAgentId)'))
      .toBeLessThan(pageSource.indexOf('queuePendingFrame(opened.embed_url)'))
  })

  it('drops stale route agent query when the runtime session no longer exists', () => {
    expect(pageSource).toContain('function isUnavailableRuntimeSessionError')
    expect(pageSource).toContain('function clearRouteAgentQueryIfCurrent')
    expect(pageSource).toContain('nextAgentQuery(route.query)')
    expect(pageSource).toContain('isUnavailableRuntimeSessionError(activationError, runtimeAgentId)')
  })

  it('supports a new-application conversation before switching into the sandbox', () => {
    expect(pageSource).toContain('isCreateApplicationRoute')
    expect(pageSource).toContain("route.path.endsWith('/code/new')")
    expect(pageSource).toContain("rawId === 'new'")
    expect(pageSource).toContain('新建 Code 应用')
    expect(pageSource).toContain('确认创建')
    expect(pageSource).toContain('codeRuntimeApi.createApplication')
    expect(pageSource).toContain('codeRuntimeApi.createSessionFromExternalApp')
    expect(pageSource).toContain('`/code/${created.route_id || created.public_id}`')
    expect(pageSource).toContain('query: nextAgentQuery(route.query)')
    expect(pageSource).toContain('opened.route_id && opened.route_id !== sessionRef')
    expect(pageSource).toContain('router.replace')
  })

  it('uses a Builder-style empty page for the Code new-application conversation', () => {
    expect(pageSource).toContain('code-new-empty')
    expect(pageSource).toContain('全代码应用工作台')
    expect(pageSource).toContain('描述你要开发的系统、页面和关键能力')
    expect(pageSource).toContain('创建后会进入独立沙箱')
    expect(pageSource).toContain('code-new-suggestions')
    expect(pageSource).toContain('generateCodeAppFromSuggestion')
    expect(pageSource).toContain('销售线索评分与跟进助手')
  })
})
