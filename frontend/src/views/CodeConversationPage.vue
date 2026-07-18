<template>
  <main ref="codePageElement" class="code-page">
    <section v-if="isCreateApplicationRoute" class="code-new-chat" aria-label="新建 Code 应用">
      <div class="code-new-chat-stream">
        <div class="code-new-empty">
          <div class="code-new-mark">
            <AppIcon name="coding" :size="28" />
          </div>
          <div class="code-new-copy">
            <p class="code-new-kicker">Dolphin Code</p>
            <h1>全代码应用工作台</h1>
            <p>描述你要开发的系统、页面和关键能力。创建后会进入独立沙箱，由数字员工协作完成代码、测试和运行验证。</p>
          </div>
          <div class="code-new-suggestions" aria-label="Code 应用示例">
            <button
              v-for="suggestion in codeAppSuggestions"
              :key="suggestion.name"
              type="button"
              class="code-new-suggestion"
              @click="generateCodeAppFromSuggestion(suggestion)"
            >
              <span>{{ suggestion.name }}</span>
              <small>{{ suggestion.prompt }}</small>
            </button>
          </div>
        </div>
      </div>
      <form class="code-new-composer" @submit.prevent="confirmCreateCodeApplication">
        <input
          v-model="newCodeAppName"
          class="code-new-input"
          type="text"
          autocomplete="off"
          placeholder="应用名称，例如：销售线索评分助手"
        />
        <textarea
          v-model="newCodeAppPrompt"
          class="code-new-textarea"
          rows="3"
          placeholder="补充业务目标、页面或功能要求"
        />
        <div class="code-new-actions">
          <span class="code-new-error">{{ newCodeAppError }}</span>
          <button class="code-new-confirm" type="submit" :disabled="creatingCodeApplication">
            {{ creatingCodeApplication ? '创建中' : '确认创建' }}
          </button>
        </div>
      </form>
    </section>
    <template v-else>
      <iframe
        v-for="frame in frames"
        :key="frame.key"
        :ref="element => setCodeFrameElement(frame.key, element)"
        :class="[
          'code-frame',
          frame.phase === 'active'
            ? 'code-frame-active'
            : frame.phase === 'hot_hidden'
              ? 'code-frame-hidden'
              : 'code-frame-pending',
          { 'code-frame-frozen': !isFrameInteractive(frame) },
        ]"
        :src="frame.url"
        :name="frame.key"
        :data-frame-key="frame.key"
        title="Dolphin Code"
        allow="clipboard-read; clipboard-write"
        :aria-hidden="!isFrameVisible(frame)"
        :tabindex="isFrameInteractive(frame) ? 0 : -1"
        @load="onCodeFrameLoad(frame.key)"
        @error="onCodeFrameError(frame.key)"
      />
      <div v-if="showInitialLoading" class="code-status">正在打开 Code 工作台...</div>
      <div v-else-if="errorMessage && !hasAnyFrame" class="code-error">
        <strong>Code 工作台暂时无法打开</strong>
        <span>{{ errorMessage }}</span>
        <button type="button" @click="retryFailedSession">重试</button>
      </div>
      <div v-if="errorMessage && hasAnyFrame" class="code-error-toast">
        <span>{{ errorMessage }}</span>
        <button type="button" @click="retryFailedSession">重试</button>
      </div>
      <div v-if="frameSwitching" class="code-frame-interaction-guard">
        <div class="code-switching" aria-live="polite">正在切换 Code 工作台...</div>
      </div>
    </template>
    <Teleport to="body">
      <button
        v-if="hostActivityModalFrameKey && hostRailOverlayWidth > 0"
        type="button"
        class="code-host-activity-scrim"
        :style="{ width: `${hostRailOverlayWidth}px` }"
        tabindex="-1"
        aria-label="关闭执行活动面板"
        @click="closeHostedActivityDrawer"
      />
    </Teleport>
  </main>
</template>

<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { codeRuntimeApi } from '@/api/codeRuntime'
import AppIcon from '@/components/common/AppIcon.vue'
import {
  activateCachedCodeFrame,
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
  setCodeFrameCacheLimit,
  type CodeFrame,
  type CodeFrameFailureInput,
  type CodeFrameRouteLocation,
} from './codeFrameLifecycle'
import {
  createShellActivityPanelCloseMessage,
  createShellStateMessages,
  resolveExternalNavigationUrl,
  resolveTrustedShellMessage,
  type ShellFrameEndpoint,
} from './codeShellProtocol'

const route = useRoute()
const router = useRouter()
const READY_TIMEOUT_MS = 30_000
const frameLifecycle = ref(createCodeFrameLifecycle())
const codePageElement = ref<HTMLElement | null>(null)
const frameElements = new Map<string, HTMLIFrameElement>()
const pageVisible = ref(document.visibilityState !== 'hidden')
const loading = ref(false)
const errorMessage = ref('')
const sessionState = ref('')
const hostActivityModalFrameKey = ref('')
const hostRailOverlayWidth = ref(0)
const newCodeAppName = ref('')
const newCodeAppPrompt = ref('')
const newCodeAppError = ref('')
const creatingCodeApplication = ref(false)
let railRefreshTimer: number | undefined
let openRequestSeq = 0
let runtimeAuthRecoveryPromise: Promise<void> | null = null
let pendingReadyTimer: {
  handle: number
  requestId: number
  frameKey: string
} | undefined
let routeRestoreTarget: CodeFrameRouteLocation | null = null

const outboundShellMessageTypes = [
  'shell.visibilityChanged',
  'shell.sessionActivationChanged',
] as const

const codeAppSuggestions = [
  {
    name: '销售线索评分与跟进助手',
    prompt: '支持线索列表、评分解释、跟进建议、业务助手查询客户和商机。',
  },
  {
    name: '项目风险预警工作台',
    prompt: '识别延期、预算偏差和未关闭问题，生成风险等级与整改建议。',
  },
  {
    name: '合同审核与归档中心',
    prompt: '管理合同草稿、审批状态、风险条款和归档记录，提供审核助手。',
  },
]

const isCreateApplicationRoute = computed(() => {
  const rawId = Array.isArray(route.params.id) ? route.params.id[0] : route.params.id
  return (
    route.name === 'CodeNewApplication'
    || route.path === '/code/new'
    || route.fullPath === '/code/new'
    || route.path.endsWith('/code/new')
    || route.fullPath.endsWith('/code/new')
    || rawId === 'new'
  )
})
const frames = computed(() => getCodeFrames(frameLifecycle.value))
const activeFrame = computed(() => frameLifecycle.value.active)
const pendingFrame = computed(() => frameLifecycle.value.pending)
const hasAnyFrame = computed(() => frames.value.length > 0)
const initialFramePending = computed(() => Boolean(frameLifecycle.value.request && !activeFrame.value))
const showInitialLoading = computed(() =>
  (loading.value || initialFramePending.value) && !activeFrame.value && !errorMessage.value
)
const frameSwitching = computed(() => isCodeFrameSwitching(frameLifecycle.value))

function currentSessionRef(): string {
  const raw = Array.isArray(route.params.id) ? route.params.id[0] : route.params.id
  return String(raw || '').trim()
}

function currentRuntimeAgentId(): string {
  const raw = Array.isArray(route.query.agent) ? route.query.agent[0] : route.query.agent
  return String(raw || '').trim()
}

function currentCodeRouteLocation(): CodeFrameRouteLocation {
  const query: CodeFrameRouteLocation['query'] = {}
  for (const [key, value] of Object.entries(route.query)) {
    query[key] = Array.isArray(value)
      ? value.map(item => item == null ? null : String(item))
      : value == null ? null : String(value)
  }
  return {
    path: route.path,
    query,
  }
}

function codeRouteLocationKey(location: CodeFrameRouteLocation): string {
  return JSON.stringify([
    location.path,
    Object.keys(location.query)
      .sort()
      .map(key => [key, location.query[key]]),
  ])
}

function codeRouteLocationsEqual(left: CodeFrameRouteLocation, right: CodeFrameRouteLocation): boolean {
  return codeRouteLocationKey(left) === codeRouteLocationKey(right)
}

function consumeRouteRestore(): boolean {
  const target = routeRestoreTarget
  if (!target || !codeRouteLocationsEqual(currentCodeRouteLocation(), target)) return false
  routeRestoreTarget = null
  return true
}

function clearRouteRestoreTarget(target: CodeFrameRouteLocation) {
  if (routeRestoreTarget === target) routeRestoreTarget = null
}

function isUnavailableRuntimeSessionError(error: any, runtimeAgentId: string): boolean {
  if (!runtimeAgentId) return false
  const detail = String(error?.response?.data?.detail || error?.message || '')
  return detail.includes(runtimeAgentId) && detail.includes('agent session') && detail.includes('is not available')
}

function clearRouteAgentQueryIfCurrent(runtimeAgentId: string) {
  if (!runtimeAgentId || currentRuntimeAgentId() !== runtimeAgentId) return
  const query = { ...route.query }
  delete query.agent
  void router.replace({ path: route.path, query })
}

function generateCodeAppCode(appName: string) {
  const normalized = appName
    .trim()
    .toLowerCase()
    .normalize('NFKD')
    .replace(/[\u0300-\u036f]/g, '')
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')
  const prefix = /^[a-z]/.test(normalized) ? normalized : 'code-app'
  return `${prefix.slice(0, 42)}-${Date.now().toString(36)}`
}

function generateCodeAppFromSuggestion(suggestion: { name: string; prompt: string }) {
  newCodeAppName.value = suggestion.name
  newCodeAppPrompt.value = suggestion.prompt
  newCodeAppError.value = ''
}

async function confirmCreateCodeApplication() {
  const appName = newCodeAppName.value.trim()
  if (!appName) {
    newCodeAppError.value = '请输入应用名称'
    return
  }
  if (creatingCodeApplication.value) return

  creatingCodeApplication.value = true
  newCodeAppError.value = ''
  try {
    const app = await codeRuntimeApi.createApplication({
      app_name: appName,
      app_code: generateCodeAppCode(appName),
    })
    const created = await codeRuntimeApi.createSessionFromExternalApp({
      external_application_id: app.external_application_id,
      app_name: app.app_name,
      app_code: app.app_code,
    })
    refreshOuterCodeRail()
    router.push(`/code/${created.public_id}`)
  } catch (error: any) {
    newCodeAppError.value = error?.response?.data?.detail || error?.message || '创建 Code 应用失败'
  } finally {
    creatingCodeApplication.value = false
  }
}

async function openCurrentSession() {
  clearPendingReadyTimer()
  if (isCreateApplicationRoute.value) {
    openRequestSeq += 1
    resetCodeFrames()
    loading.value = false
    errorMessage.value = ''
    return
  }
  const sessionRef = currentSessionRef()
  if (!sessionRef) {
    openRequestSeq += 1
    errorMessage.value = '缺少 Code 会话'
    resetCodeFrames()
    return
  }
  const requestSeq = ++openRequestSeq
  frameLifecycle.value = beginCodeFrameOpen(frameLifecycle.value, {
    requestId: requestSeq,
    sessionRef,
    route: currentCodeRouteLocation(),
  })
  loading.value = true
  errorMessage.value = ''

  // An exact cached route is already authenticated inside its mounted iframe.
  // Promote it synchronously so a normal back-and-forth sandbox switch does
  // not wait for Control Plane or rebuild the Runtime document.
  const exactCachedState = activateCachedCodeFrame(frameLifecycle.value, {
    requestId: requestSeq,
    sessionRef,
    requireRouteMatch: true,
  })
  if (exactCachedState !== frameLifecycle.value) {
    frameLifecycle.value = exactCachedState
    loading.value = false
    refreshOuterCodeRail()
    return
  }

  try {
    const runtimeAgentId = currentRuntimeAgentId()
    const opened = await codeRuntimeApi.openSession(sessionRef)
    if (opened.session_id !== sessionRef) {
      await router.replace({
        path: `/code/${opened.session_id}`,
        query: route.query,
      })
      return
    }
    if (runtimeAgentId && opened.runtime_session_id !== runtimeAgentId) {
      try {
        await codeRuntimeApi.activateAgentSession(opened.session_id, runtimeAgentId)
      } catch (activationError: any) {
        if (!isUnavailableRuntimeSessionError(activationError, runtimeAgentId)) throw activationError
        clearRouteAgentQueryIfCurrent(runtimeAgentId)
      }
    }
    if (requestSeq !== openRequestSeq) return

    frameLifecycle.value = setCodeFrameCacheLimit(
      frameLifecycle.value,
      Number(opened.browser_hot_frames || 2),
    )

    // A different agent route still needs the activation API above, but the
    // shell iframe itself can be reused after activation instead of reloaded.
    const cachedState = activateCachedCodeFrame(frameLifecycle.value, {
      requestId: requestSeq,
      sessionRef,
      requireRouteMatch: false,
    })
    if (cachedState !== frameLifecycle.value) {
      frameLifecycle.value = cachedState
      refreshOuterCodeRail()
      return
    }

    queuePendingFrame(opened.embed_url)
    refreshOuterCodeRail()
  } catch (error: any) {
    if (requestSeq === openRequestSeq) {
      const message = error?.response?.data?.detail || error?.message || '打开失败'
      failCurrentFrameOpen({
        requestId: requestSeq,
        message,
      })
    }
  } finally {
    if (requestSeq === openRequestSeq) loading.value = false
  }
}

function queuePendingFrame(url: string) {
  const request = frameLifecycle.value.request
  if (!request) return
  frameLifecycle.value = queuePendingCodeFrame(frameLifecycle.value, {
    ...request,
    url,
    baseUrl: window.location.href,
  })
  const pending = frameLifecycle.value.pending
  if (pending) startPendingReadyTimer(pending)
}

function isFrameVisible(frame: CodeFrame) {
  return isCodeFrameVisible(frameLifecycle.value, frame)
}

function isFrameInteractive(frame: CodeFrame) {
  return isCodeFrameInteractive(frameLifecycle.value, frame)
}

function onCodeFrameLoad(frameKey: string) {
  frameLifecycle.value = markCodeFrameLoaded(frameLifecycle.value, frameKey)
}

function onCodeFrameError(frameKey: string) {
  const pending = frameLifecycle.value.pending
  const request = frameLifecycle.value.request
  if (!pending || pending.key !== frameKey || !request) return
  failCurrentFrameOpen({
    requestId: request.requestId,
    frameKey,
    message: 'Code 工作台加载失败',
  })
}

function clearPendingReadyTimer() {
  if (!pendingReadyTimer) return
  window.clearTimeout(pendingReadyTimer.handle)
  pendingReadyTimer = undefined
}

function startPendingReadyTimer(frame: CodeFrame) {
  clearPendingReadyTimer()
  const requestId = frame.requestId
  const frameKey = frame.key
  const handle = window.setTimeout(() => {
    if (pendingReadyTimer?.handle === handle) pendingReadyTimer = undefined
    failCurrentFrameOpen({
      requestId,
      frameKey,
      message: 'Code 工作台准备超时，请重试',
    })
  }, READY_TIMEOUT_MS)
  pendingReadyTimer = {
    handle,
    requestId,
    frameKey,
  }
}

function restoreActiveRouteAfterFailure() {
  const target = frameLifecycle.value.lastReadyRoute
  if (
    !frameLifecycle.value.active
    || !target
    || codeRouteLocationsEqual(currentCodeRouteLocation(), target)
  ) {
    return
  }
  routeRestoreTarget = target
  void router.replace({
    path: target.path,
    query: target.query,
  }).catch(() => undefined)
    .finally(() => {
      clearRouteRestoreTarget(target)
    })
}

function failCurrentFrameOpen(failure: CodeFrameFailureInput): boolean {
  const previousState = frameLifecycle.value
  const nextState = failCodeFrameOpen(previousState, failure)
  if (nextState === previousState) return false
  clearPendingReadyTimer()
  frameLifecycle.value = nextState
  errorMessage.value = failure.message
  restoreActiveRouteAfterFailure()
  return true
}

function retryFailedSession() {
  const target = frameLifecycle.value.failed?.route
  if (!target || codeRouteLocationsEqual(currentCodeRouteLocation(), target)) {
    void openCurrentSession()
    return
  }
  void router.push({
    path: target.path,
    query: target.query,
  })
}

function recoverRuntimeAuthentication() {
  if (runtimeAuthRecoveryPromise) return
  errorMessage.value = ''
  runtimeAuthRecoveryPromise = openCurrentSession()
    .finally(() => {
      runtimeAuthRecoveryPromise = null
    })
}

function setCodeFrameElement(frameKey: string, element: unknown) {
  if (element instanceof HTMLIFrameElement) {
    frameElements.set(frameKey, element)
    void nextTick(publishCodeFrameShellState)
    return
  }
  frameElements.delete(frameKey)
}

function shellFrameEndpoints(): ShellFrameEndpoint[] {
  return frames.value.flatMap((frame) => {
    const source = frameElements.get(frame.key)?.contentWindow
    return source ? [{ key: frame.key, origin: frame.origin, source }] : []
  })
}

function publishCodeFrameShellState() {
  const occurredAt = new Date().toISOString()
  for (const frame of frames.value) {
    const target = frameElements.get(frame.key)?.contentWindow
    if (!target) continue
    const visible = pageVisible.value && isFrameVisible(frame)
    const interactive = pageVisible.value && isFrameInteractive(frame)
    const active = frameLifecycle.value.active?.key === frame.key && frameLifecycle.value.request == null
    const messages = createShellStateMessages({
      frameKey: frame.key,
      visible,
      interactive,
      active,
      occurredAt,
    })
    for (const message of messages) {
      if (!outboundShellMessageTypes.includes(message.type)) continue
      target.postMessage(message, frame.origin)
    }
  }
}

function publishCodeFrameDeactivation() {
  const occurredAt = new Date().toISOString()
  for (const frame of frames.value) {
    const target = frameElements.get(frame.key)?.contentWindow
    if (!target) continue
    for (const message of createShellStateMessages({
      frameKey: frame.key,
      visible: false,
      interactive: false,
      active: false,
      occurredAt,
    })) {
      target.postMessage(message, frame.origin)
    }
  }
}

function updateHostRailOverlayWidth() {
  hostRailOverlayWidth.value = Math.max(0, Math.round(codePageElement.value?.getBoundingClientRect().left ?? 0))
}

function clearHostedActivityModal(frameKey = '') {
  if (frameKey && hostActivityModalFrameKey.value !== frameKey) return
  hostActivityModalFrameKey.value = ''
  hostRailOverlayWidth.value = 0
}

function closeHostedActivityDrawer() {
  const frameKey = hostActivityModalFrameKey.value
  if (!frameKey) return
  const frame = frames.value.find(candidate => candidate.key === frameKey)
  const target = frameElements.get(frameKey)?.contentWindow
  if (!frame || !target || !isFrameInteractive(frame)) {
    clearHostedActivityModal(frameKey)
    return
  }
  target.postMessage(createShellActivityPanelCloseMessage({
    frameKey,
    occurredAt: new Date().toISOString(),
  }), frame.origin)
}

function resetCodeFrames() {
  clearPendingReadyTimer()
  clearHostedActivityModal()
  publishCodeFrameDeactivation()
  frameLifecycle.value = createCodeFrameLifecycle()
  frameElements.clear()
}

function onDocumentVisibilityChange() {
  pageVisible.value = document.visibilityState !== 'hidden'
  publishCodeFrameShellState()
}

function refreshOuterCodeRail() {
  window.dispatchEvent(new CustomEvent('code-rail-refresh'))
}

function scheduleOuterCodeRailRefresh(delay = 1200) {
  if (railRefreshTimer != null) window.clearTimeout(railRefreshTimer)
  railRefreshTimer = window.setTimeout(() => {
    railRefreshTimer = undefined
    refreshOuterCodeRail()
  }, delay)
}

function onShellMessage(event: MessageEvent) {
  const resolved = resolveTrustedShellMessage({
    origin: event.origin,
    source: event.source,
    data: event.data,
  }, shellFrameEndpoints())
  if (!resolved) return

  const { message } = resolved
  const frame = frames.value.find(candidate => candidate.key === resolved.frame.key)
  if (!frame) return
  if (message.type === 'builder.ready') {
    if (frameLifecycle.value.pending?.key !== frame.key || frame.phase !== 'pending') return
    const previousState = frameLifecycle.value
    frameLifecycle.value = promoteReadyCodeFrame(previousState, frame.key)
    if (frameLifecycle.value === previousState) return
    clearPendingReadyTimer()
    errorMessage.value = ''
    scheduleOuterCodeRailRefresh(500)
    return
  }

  if (message.type === 'sandbox.failed') {
    if (
      message.payload.recoverable === true
      && message.payload.code === 'runtime_auth_invalid'
      && isFrameInteractive(frame)
    ) {
      recoverRuntimeAuthentication()
      return
    }
    if (frame.phase === 'pending' && frameLifecycle.value.request) {
      const runtimeMessage = String(message.payload.message || 'Code runtime failed')
      failCurrentFrameOpen({
        requestId: frameLifecycle.value.request.requestId,
        frameKey: frame.key,
        message: runtimeMessage,
      })
    } else if (isFrameInteractive(frame)) {
      errorMessage.value = String(message.payload.message || 'Code runtime failed')
    }
    return
  }

  if (!isFrameInteractive(frame)) return
  if (message.type === 'builder.externalNavigationRequested') {
    const url = resolveExternalNavigationUrl(message.payload.url)
    if (!url) return
    window.open(url, '_blank', 'noopener,noreferrer')
    return
  }
  if (message.type === 'builder.activityPanelChanged') {
    const open = message.payload.open === true
    const modal = message.payload.modal === true
    const presentation = String(message.payload.presentation || '')
    if (open && modal && presentation === 'drawer') {
      hostActivityModalFrameKey.value = frame.key
      updateHostRailOverlayWidth()
    } else {
      clearHostedActivityModal(frame.key)
    }
    return
  }
  if (message.type === 'agent.sessionStateChanged') {
    sessionState.value = String(message.payload.state || message.payload.status || '')
    refreshOuterCodeRail()
    scheduleOuterCodeRailRefresh()
  }
}

watch(
  () => [route.name, route.params.id, route.query.agent],
  () => {
    if (consumeRouteRestore()) return
    void openCurrentSession()
  },
)

watch(frameLifecycle, () => {
  if (hostActivityModalFrameKey.value) {
    const hostedFrame = frames.value.find(candidate => candidate.key === hostActivityModalFrameKey.value)
    if (!hostedFrame || !isFrameInteractive(hostedFrame)) clearHostedActivityModal()
  }
  void nextTick(publishCodeFrameShellState)
})

onMounted(() => {
  window.addEventListener('message', onShellMessage)
  window.addEventListener('resize', updateHostRailOverlayWidth)
  document.addEventListener('visibilitychange', onDocumentVisibilityChange)
  void openCurrentSession()
})

onBeforeUnmount(() => {
  clearPendingReadyTimer()
  publishCodeFrameDeactivation()
  clearHostedActivityModal()
  window.removeEventListener('message', onShellMessage)
  window.removeEventListener('resize', updateHostRailOverlayWidth)
  document.removeEventListener('visibilitychange', onDocumentVisibilityChange)
  if (railRefreshTimer != null) window.clearTimeout(railRefreshTimer)
})
</script>

<style scoped>
.code-page {
  position: relative;
  flex: 1;
  min-width: 0;
  min-height: 0;
  display: flex;
  background: var(--bg-app);
  overflow: hidden;
}

.code-host-activity-scrim {
  position: fixed;
  z-index: 3000;
  inset: 0 auto 0 0;
  display: block;
  height: 100vh;
  padding: 0;
  border: 0;
  background: rgba(15, 23, 42, 0.28);
  cursor: default;
}

.code-new-chat {
  width: min(920px, calc(100% - 48px));
  min-height: 0;
  margin: 0 auto;
  padding: 22px 0 24px;
  display: flex;
  flex: 1;
  flex-direction: column;
  justify-content: space-between;
  gap: 18px;
}

.code-new-chat-stream {
  flex: 1;
  min-height: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 18px 0 8px;
}

.code-new-empty {
  width: min(760px, 100%);
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 18px;
  color: var(--text-2);
  text-align: center;
}

.code-new-mark {
  width: 56px;
  height: 56px;
  display: grid;
  place-items: center;
  border: 1px solid var(--line);
  border-radius: 14px;
  background: var(--surface);
  color: var(--brand);
  box-shadow: var(--shadow-sm, 0 4px 14px rgba(15, 23, 42, 0.08));
}

.code-new-copy {
  max-width: 620px;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
}

.code-new-kicker {
  margin: 0;
  color: var(--brand);
  font-size: 12px;
  font-weight: var(--fw-semibold, 600);
  line-height: 18px;
}

.code-new-copy h1 {
  margin: 0;
  color: var(--text);
  font-size: 26px;
  line-height: 1.25;
  font-weight: var(--fw-semibold, 600);
  letter-spacing: 0;
}

.code-new-copy p:last-child {
  margin: 0;
  font-size: 13px;
  line-height: 1.6;
}

.code-new-suggestions {
  width: 100%;
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 10px;
}

.code-new-suggestion {
  min-height: 88px;
  padding: 12px;
  border: 1px solid var(--line);
  border-radius: var(--r-3, 8px);
  background: var(--surface);
  color: var(--text);
  font-family: inherit;
  text-align: left;
  cursor: pointer;
  transition: border-color .16s ease, background .16s ease, transform .16s ease;
}

.code-new-suggestion:hover {
  border-color: var(--brand-ring);
  background: var(--brand-soft);
  transform: translateY(-1px);
}

.code-new-suggestion span,
.code-new-suggestion small {
  display: block;
}

.code-new-suggestion span {
  font-size: 13px;
  font-weight: var(--fw-semibold, 600);
  line-height: 18px;
}

.code-new-suggestion small {
  margin-top: 7px;
  color: var(--text-3);
  font-size: 12px;
  line-height: 17px;
}

.code-new-composer {
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding: 14px;
  border: 1px solid var(--line);
  border-radius: var(--r-3, 8px);
  background: var(--surface);
  box-shadow: var(--shadow-sm, 0 4px 14px rgba(15, 23, 42, 0.08));
}

.code-new-input,
.code-new-textarea {
  width: 100%;
  box-sizing: border-box;
  border: 1px solid var(--line);
  border-radius: var(--r-2, 6px);
  background: var(--surface-2);
  color: var(--text);
  font-family: inherit;
  font-size: 13px;
  outline: none;
}

.code-new-input {
  height: 36px;
  padding: 0 11px;
}

.code-new-textarea {
  min-height: 72px;
  resize: vertical;
  padding: 9px 11px;
  line-height: 1.5;
}

.code-new-input:focus,
.code-new-textarea:focus {
  border-color: var(--brand-ring);
  background: var(--surface);
}

.code-new-actions {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.code-new-error {
  min-height: 18px;
  color: var(--err);
  font-size: 12px;
}

.code-new-confirm {
  height: 32px;
  padding: 0 14px;
  border: 1px solid var(--brand);
  border-radius: var(--r-2, 6px);
  background: var(--brand);
  color: var(--text-inverse, #fff);
  font-family: inherit;
  font-size: 13px;
  font-weight: var(--fw-medium, 500);
  cursor: pointer;
}

.code-new-confirm:disabled {
  cursor: not-allowed;
  opacity: 0.65;
}

.code-frame {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  border: 0;
  display: block;
  background: var(--surface);
}

.code-frame-active {
  z-index: 1;
  opacity: 1;
}

.code-frame-pending {
  z-index: 0;
  opacity: 0;
  pointer-events: none;
}

.code-frame-hidden {
  z-index: 0;
  visibility: hidden;
  pointer-events: none;
}

.code-frame-frozen {
  pointer-events: none;
}

.code-frame-interaction-guard {
  position: absolute;
  z-index: 2;
  inset: 0;
  pointer-events: auto;
  cursor: progress;
}

.code-status,
.code-error {
  position: relative;
  z-index: 3;
  margin: auto;
  max-width: 420px;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 10px;
  color: var(--text-3);
  font-size: 13px;
  text-align: center;
}

.code-error strong {
  color: var(--text);
  font-size: 15px;
  letter-spacing: 0;
}

.code-error button {
  height: 30px;
  padding: 0 12px;
  border: 1px solid var(--line);
  border-radius: var(--r-2, 6px);
  background: var(--surface);
  color: var(--text);
  font-family: inherit;
  cursor: pointer;
}

.code-error button:hover {
  border-color: var(--brand-ring);
  color: var(--brand);
  background: var(--brand-soft);
}

.code-error-toast,
.code-switching {
  position: absolute;
  z-index: 4;
  top: 14px;
  left: 50%;
  transform: translateX(-50%);
  min-height: 32px;
  max-width: min(520px, calc(100% - 48px));
  padding: 6px 10px;
  border: 1px solid var(--line);
  border-radius: var(--r-2, 6px);
  background: color-mix(in srgb, var(--surface) 92%, transparent);
  box-shadow: var(--shadow-sm, 0 4px 14px rgba(15, 23, 42, 0.08));
  color: var(--text-2);
  font-size: 12px;
  line-height: 18px;
}

.code-error-toast {
  display: flex;
  align-items: center;
  gap: 8px;
}

.code-error-toast span {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.code-error-toast button {
  height: 22px;
  flex: 0 0 auto;
  padding: 0 8px;
  border: 1px solid var(--line);
  border-radius: var(--r-2, 6px);
  background: var(--surface);
  color: var(--text);
  font-family: inherit;
  font-size: 12px;
  cursor: pointer;
}

.code-switching {
  z-index: 1;
  pointer-events: none;
  text-align: center;
}

@media (max-width: 760px) {
  .code-new-chat {
    width: min(100% - 28px, 920px);
    padding: 16px 0 18px;
  }

  .code-new-copy h1 {
    font-size: 22px;
  }

  .code-new-suggestions {
    grid-template-columns: 1fr;
  }

  .code-new-suggestion {
    min-height: 72px;
  }
}
</style>
