import { describe, expect, it } from 'vitest'
import { createCodeAgentActivationCoordinator } from './codeAgentActivation'
import { awaitCurrentCodeFrameOpenRequest } from './codeFrameLifecycle'
import { formatCodeRailLocationSummary } from '@/components/v2/codeRailHistory'
import pageSource from './CodeConversationPage.vue?raw'
import projectInitializationSource from './codeProjectInitialization.ts?raw'

function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((resolvePromise) => {
    resolve = resolvePromise
  })
  return { promise, resolve }
}

describe('CodeConversationPage', () => {
  it('renders the location recovery panel for historical session open failures', () => {
    expect(pageSource).toContain('import CodeApplicationRecoveryPanel')
    expect(pageSource).toContain('<CodeApplicationRecoveryPanel')
    expect(pageSource).toContain('codeApplicationRecoveryStateFromError')
    expect(pageSource).toContain('codeRuntimeOpenErrorContext')
    expect(pageSource).not.toContain("const sessionExecutionLocation = ref<'local' | 'remote'>('remote')")
  })

  it('formats the session location without exposing an absolute path', () => {
    expect(formatCodeRailLocationSummary('local', '/srv/private/customer-crm')).toBe('本机 · customer-crm')
    expect(formatCodeRailLocationSummary('local', 'C:\\Users\\alice\\customer-crm\\')).toBe('本机 · customer-crm')
    expect(formatCodeRailLocationSummary('remote', null, '开发环境')).toBe('远程 · 开发环境')
    expect(formatCodeRailLocationSummary('remote')).toBe('远程 · 远程环境')
  })

  it('shows a fixed session location summary without exposing local paths', () => {
    expect(pageSource).toContain('sessionLocationSummary')
    expect(pageSource).toContain('loadSessionLocationSummary')
    expect(pageSource).toContain('formatCodeRailLocationSummary')
    expect(pageSource).toContain('codeRuntimeApi.listRailHistory')
    expect(pageSource).toContain('sessionLocationSummary.value =')
  })

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

  it('reveals a successfully loaded Builder frame when an older runtime omits builder.ready', () => {
    expect(pageSource).toContain('scheduleLoadedFrameFallback')
    expect(pageSource).toContain('loadedFrameFallbackTimer')
    expect(pageSource).toContain('pending.loaded')
    expect(pageSource).toContain('promoteReadyCodeFrame(frameLifecycle.value, frameKey)')
    expect(pageSource).toContain('}, 1200)')
  })

  it('commits only the promoted pending shell preference after trusted readiness', () => {
    expect(pageSource).toContain('commitPendingCodeApplicationLocationPreferenceByShellSessionRef')
    expect(pageSource).toContain('promoteReadyCodeFrame(previousState, frame.key)')
    expect(pageSource).toContain('commitPendingCodeApplicationLocationPreferenceByShellSessionRef(frame.sessionRef)')
  })

  it('dispatches project initialization from server shell metadata on every trusted readiness', () => {
    const readyHandlerSource = pageSource.slice(
      pageSource.indexOf("if (message.type === 'builder.ready')"),
      pageSource.indexOf("if (message.type === 'sandbox.failed')"),
    )
    const pendingReadyIndex = readyHandlerSource.indexOf("frame.phase === 'pending'")
    const pendingDispatchIndex = readyHandlerSource.indexOf('dispatchProjectInitialization(frame)')
    const activeReadyIndex = readyHandlerSource.indexOf("frame.phase === 'active'")
    const activeDispatchIndex = readyHandlerSource.lastIndexOf('dispatchProjectInitialization(frame)')

    expect(pageSource).toContain('opened.session_purpose')
    expect(pageSource).toContain('projectInitializationDispatcher.rememberSessionPurpose')
    expect(pageSource).toContain('function dispatchProjectInitialization')
    expect(projectInitializationSource).toContain('codeRuntimeApi.dispatchProjectInitialization')
    expect(pageSource).not.toContain('route.query.projectInitialization')
    expect(pageSource).not.toContain('query: { projectInitialization')
    expect(pendingDispatchIndex).toBeGreaterThan(pendingReadyIndex)
    expect(activeDispatchIndex).toBeGreaterThan(activeReadyIndex)
    expect(projectInitializationSource).toContain("response.state === 'retryable_failed'")
    expect(projectInitializationSource).toContain('retrySessionRef')
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

  it('activates a route agent after opening a fresh sandbox document', () => {
    const openSource = pageSource.slice(
      pageSource.indexOf('async function openCurrentSession()'),
      pageSource.indexOf('function queuePendingFrame'),
    )
    const openIndex = openSource.indexOf('codeRuntimeApi.openSession(sessionRef, {')
    const openedActivationIndex = openSource.lastIndexOf('activateCurrentCodeAgentSession(')

    expect(pageSource).toContain('function currentRuntimeAgentId()')
    expect(pageSource).toContain('function currentSessionRef(): string')
    expect(openSource).toContain('runtimeAgentId && opened.runtime_session_id !== runtimeAgentId')
    expect(openedActivationIndex).toBeGreaterThan(openIndex)
    expect(openedActivationIndex).toBeLessThan(openSource.indexOf('queuePendingFrame(opened.embed_url)'))
  })

  it('routes cached and freshly opened agent activation through one serial coordinator', () => {
    const openSource = pageSource.slice(
      pageSource.indexOf('async function openCurrentSession()'),
      pageSource.indexOf('function queuePendingFrame'),
    )

    expect(openSource).toContain('awaitCurrentCodeFrameOpenRequest')
    expect(openSource.match(/awaitCurrentCodeFrameOpenRequest/g)).toHaveLength(2)
    expect(openSource.match(/\.status === 'stale' \|\| !isCurrentRequest\(\)/g)).toHaveLength(4)
    expect(openSource).toContain("local: currentCodeApplicationSource() === 'local'")
    expect(openSource).toMatch(
      /activateCurrentCodeAgentSession\(\s*sessionRef,\s*runtimeAgentId,\s*isCurrentRequest,?\s*\)/,
    )
    expect(openSource).toMatch(
      /activateCurrentCodeAgentSession\(\s*sessionRef,\s*runtimeAgentId,\s*isCurrentRequest,\s*opened\.session_id,\s*\)/,
    )
    expect(openSource.match(/activateCurrentCodeAgentSession/g)).toHaveLength(2)
    expect(openSource).not.toContain('codeRuntimeApi.activateAgentSession')
  })

  it('only promotes a cached frame after synchronizing the target agent mapping', () => {
    const openSource = pageSource.slice(
      pageSource.indexOf('async function openCurrentSession()'),
      pageSource.indexOf('function queuePendingFrame'),
    )
    const cachedLookupIndex = openSource.indexOf('const exactCachedState = activateCachedCodeFrame')
    const cachedActivationIndex = openSource.indexOf('await activateCurrentCodeAgentSession(', cachedLookupIndex)
    const cachedPromotionIndex = openSource.indexOf('frameLifecycle.value = exactCachedState', cachedLookupIndex)

    expect(cachedLookupIndex).toBeGreaterThan(-1)
    expect(cachedActivationIndex).toBeGreaterThan(cachedLookupIndex)
    expect(cachedPromotionIndex).toBeGreaterThan(cachedActivationIndex)
    expect(openSource).toContain('requireRouteMatch: true')
    expect(openSource).not.toContain('requireRouteMatch: false')
  })

  it('ignores stale open completion before stopping polling, activating, or replacing the current frame', async () => {
    let currentRequestId = 1
    let activeAgent = ''
    const effects: string[] = []
    const agent1Open = deferred<string>()
    const agent2Open = deferred<string>()

    const completeOpen = async (
      requestId: number,
      agentId: string,
      openPromise: Promise<string>,
    ) => {
      const opened = await awaitCurrentCodeFrameOpenRequest(
        () => requestId === currentRequestId,
        () => openPromise,
      )
      if (opened.status === 'stale') return

      effects.push(`stop-polling:${agentId}`)
      const activated = await awaitCurrentCodeFrameOpenRequest(
        () => requestId === currentRequestId,
        async () => {
          effects.push(`activate:${agentId}`)
        },
      )
      if (activated.status === 'stale') return
      activeAgent = agentId
    }

    const agent1Request = completeOpen(1, 'agent-1', agent1Open.promise)
    currentRequestId = 2
    const agent2Request = completeOpen(2, 'agent-2', agent2Open.promise)

    agent2Open.resolve('agent-2-opened')
    await agent2Request
    agent1Open.resolve('agent-1-opened')
    await agent1Request

    expect(effects).toEqual([
      'stop-polling:agent-2',
      'activate:agent-2',
    ])
    expect(activeAgent).toBe('agent-2')
  })

  it('does not replace the current frame when activation becomes stale while awaiting', async () => {
    let currentRequestId = 1
    let activeAgent = ''
    const agent1Activation = deferred<void>()

    const activateAndCommit = async (
      requestId: number,
      agentId: string,
      activation: () => Promise<void>,
    ) => {
      const activated = await awaitCurrentCodeFrameOpenRequest(
        () => requestId === currentRequestId,
        activation,
      )
      if (activated.status === 'stale') return
      activeAgent = agentId
    }

    const agent1Request = activateAndCommit(1, 'agent-1', () => agent1Activation.promise)
    currentRequestId = 2
    await activateAndCommit(2, 'agent-2', async () => undefined)
    agent1Activation.resolve()
    await agent1Request

    expect(activeAgent).toBe('agent-2')
  })

  it('serializes same-shell activation so the latest selection is the last runtime side effect', async () => {
    const coordinator = createCodeAgentActivationCoordinator()
    const firstActivation = deferred<void>()
    const calls: string[] = []
    let currentRequestId = 1
    let activeAgent = ''

    const activateAndApply = async (requestId: number, agentId: string) => {
      const result = await coordinator.activate(
        'shell-1',
        () => requestId === currentRequestId,
        async () => {
          calls.push(`start:${agentId}`)
          if (agentId === 'agent-1') await firstActivation.promise
          calls.push(`finish:${agentId}`)
          return agentId
        },
      )
      if (result.status === 'current') activeAgent = result.value
    }

    const firstRequest = activateAndApply(1, 'agent-1')
    currentRequestId = 2
    const secondRequest = activateAndApply(2, 'agent-2')

    expect(calls).toEqual(['start:agent-1'])
    firstActivation.resolve()
    await Promise.all([firstRequest, secondRequest])

    expect(calls).toEqual([
      'start:agent-1',
      'finish:agent-1',
      'start:agent-2',
      'finish:agent-2',
    ])
    expect(activeAgent).toBe('agent-2')
  })

  it('skips an activation that becomes stale before its same-shell queue turn', async () => {
    const coordinator = createCodeAgentActivationCoordinator()
    const firstActivation = deferred<void>()
    const calls: string[] = []
    let currentRequestId = 1

    const activate = (requestId: number, agentId: string) => coordinator.activate(
      'shell-1',
      () => requestId === currentRequestId,
      async () => {
        calls.push(agentId)
        if (agentId === 'agent-1') await firstActivation.promise
        return agentId
      },
    )

    const firstRequest = activate(1, 'agent-1')
    currentRequestId = 2
    const staleQueuedRequest = activate(2, 'agent-2')
    currentRequestId = 3
    const latestRequest = activate(3, 'agent-3')

    firstActivation.resolve()
    const [, staleResult, latestResult] = await Promise.all([
      firstRequest,
      staleQueuedRequest,
      latestRequest,
    ])

    expect(calls).toEqual(['agent-1', 'agent-3'])
    expect(staleResult).toEqual({ status: 'stale' })
    expect(latestResult).toEqual({ status: 'current', value: 'agent-3' })
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
