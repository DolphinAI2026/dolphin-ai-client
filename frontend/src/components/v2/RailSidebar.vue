<script lang="ts">
import { MODE_META as railModeMeta, type AppMode as RailAppMode } from '@/stores/mode'
import {
  defaultProductHome as railDefaultProductHome,
  type ProductAvailability as RailProductAvailability,
} from '@/stores/productAvailability'

export function railTenantHome(
  desktop: boolean,
  mode: RailAppMode,
  availability: RailProductAvailability,
): string {
  return desktop ? railModeMeta[mode].home : railDefaultProductHome(availability)
}

export function createLatestRailNavigationIntent() {
  let current = 0
  return {
    begin: () => ++current,
    isCurrent: (intent: number) => intent === current,
  }
}
</script>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  getDesktopState,
  resolveDesktopProductScope,
  type DesktopWorkspaceEntryScope,
} from '@/utils/desktop'
import { useUserStore } from '@/stores/user'
import { useCodeApplicationsStore } from '@/stores/codeApplications'
import {
  desktopModeLabel,
  isCodeRoutePath,
  useModeStore,
  MODE_META,
  visibleModeNav,
  visibleModesForDesktopScope,
  type AppMode,
} from '@/stores/mode'
import {
  defaultProductHome,
  enabledProductModes,
  loadProductAvailability,
  type ProductAvailability,
} from '@/stores/productAvailability'
import { aiChatApi, type AIChatSession } from '@/api/aiChat'
import {
  CODE_APPLICATION_SOURCE_CHANGED_EVENT,
  codeRuntimeApi,
  loadStoredCodeApplicationSource,
  type CodeApplicationSource,
  type CodeExecutionLocation,
} from '@/api/codeRuntime'
import { getControlPlaneCodeSession } from '@/utils/controlPlaneCodeSession'
import { ElMessage, ElMessageBox } from 'element-plus'
import SystemAssistantSessionSections from '@/components/v2/SystemAssistantSessionSections.vue'
import {
  groupRailSessionsByApplication,
  normalizeAiSessions,
  nextAgentQuery,
  railSessionTarget,
  isRailSessionActive,
  railSessionFallback,
  sortRailSessionsByUpdatedAt,
  type RailSession,
  type RailSessionGroup,
} from '@/composables/railSessions'
import type { CodeAgentSessionRecord, CodeRailHistoryResponse } from '@/api/codeRuntime'
import {
  codeRailHistorySessions,
  groupCodeRailHistoryByApplication,
  hydrateCodeRailHistorySessions,
  type CodeRailSessionGroup,
} from './codeRailHistory'
import ruijingWhaleMarkUrl from '@/assets/brand/ruijing-whale-mark.svg'

interface NavItem { key: string; label: string; icon: string; path: string; badge?: number }

const props = defineProps<{ collapsed?: boolean }>()
const route = useRoute()
const router = useRouter()
const user = useUserStore()
const modeStore = useModeStore()
const codeApplications = useCodeApplicationsStore()
const codeApplicationSource = ref<CodeApplicationSource>(
  __DESKTOP__ ? loadStoredCodeApplicationSource('local') : 'remote',
)
const productAvailability = ref<ProductAvailability>({ builder: true, code: true })

const desktopWorkspaceEntryScope = ref<DesktopWorkspaceEntryScope>('both')
const visibleModeOrder = computed(() => __DESKTOP__
  ? visibleModesForDesktopScope(desktopWorkspaceEntryScope.value)
  : enabledProductModes(productAvailability.value))
// 当前路由驱动左栏导航、会话加载和会话路由；桌面公共路由收敛到当前可见入口。
const currentMode = computed<AppMode>(() => {
  const routeMode: AppMode = isCodeRoutePath(route.path) ? 'code' : 'builder'
  return !visibleModeOrder.value.includes(routeMode)
    ? visibleModeOrder.value[0]
    : routeMode
})
const isSystemAssistantRoute = computed(() => route.path === '/code/system-assistant')
const activeCodeShellSessionId = computed(() => {
  if (currentMode.value !== 'code') return ''
  const match = route.path.match(/^\/code\/([^/]+)$/)
  return match ? decodeURIComponent(match[1]) : ''
})
const activeCodeRuntimeSessionId = computed(() => {
  const rawAgent = route.query.agent
  return String(Array.isArray(rawAgent) ? rawAgent[0] || '' : rawAgent || '')
})

// 会话历史 —— 收进左栏单一导航(参考 Claude Code), 页面内层 sidebar 隐掉。
// 统一使用 aiChatApi 会话; Code 模式只展示 mode=code 的应用会话。
const aiSessions = ref<AIChatSession[]>([])
const systemAssistantSessionData = ref<AIChatSession[]>([])
const codeRailHistory = ref<CodeRailHistoryResponse | null>(null)
const showRecent = computed(() => !effectiveCollapsed.value)
let railAppsSeq = 0
let railSessionsSeq = 0
let systemAssistantSessionsTimer: ReturnType<typeof setInterval> | null = null

// app_id → 应用名映射(供「按应用」分组,code 会话从工作区继承 app_id 后据此归到应用)。
const appNameById = ref<Map<number, string>>(new Map())

const systemAssistantSessions = computed<RailSession[]>(() =>
  sortRailSessionsByUpdatedAt(normalizeAiSessions(systemAssistantSessionData.value)),
)
const systemAssistantApplicationGroups = computed<CodeRailSessionGroup[]>(() =>
  groupCodeRailHistoryByApplication(codeRailHistory.value),
)

// 非系统助手入口仍使用当前模式对应的单一会话源。
const railSessions = computed<RailSession[]>(() => {
  return currentMode.value === 'code'
    ? codeRailHistorySessions(codeRailHistory.value)
    : normalizeAiSessions(aiSessions.value, appNameById.value)
})

async function loadRailApps() {
  const seq = ++railAppsSeq
  const mode = currentMode.value
  if (isSystemAssistantRoute.value) {
    appCount.value = undefined
    appNameById.value = new Map()
    return
  }
  try {
    if (mode === 'code') {
      const page = await codeApplications.load(
        { tenantId: user.tenantId || 0, tenantEpoch: 0 },
        { source: codeApplicationSource.value, pageSize: 100 },
      )
      if (seq !== railAppsSeq || mode !== currentMode.value) return
      const items = page?.items || []
      appCount.value = Number(page?.total ?? items.length)
      appNameById.value = new Map()
      return
    }
    const { applicationApi } = await import('@/api/application')
    const apps: any = (await applicationApi.list?.({
      include_remote: false,
      include_config: false,
      app_type: 'low-code',
    } as any)) ?? []
    if (seq !== railAppsSeq || mode !== currentMode.value) return
    const appList: any[] = Array.isArray(apps) ? apps : (apps?.items ?? [])
    appCount.value = Array.isArray(apps) ? apps.length : (apps?.items?.length ?? apps?.total ?? 0)
    // 建 app_id → 名称映射,供左栏「按应用」分组反查(含 code 会话继承的 app_id)。
    const map = new Map<number, string>()
    for (const a of appList) {
      const id = Number(a?.id)
      const name = a?.app_name || a?.appName
      if (Number.isFinite(id) && id && name) map.set(id, name)
    }
    appNameById.value = map
  } catch {
    if (seq !== railAppsSeq || mode !== currentMode.value) return
    appCount.value = undefined
    appNameById.value = new Map()
  }
}

async function loadRailSessions() {
  const seq = ++railSessionsSeq
  const mode = currentMode.value
  try {
    if (mode === 'code') {
      const [systemResult, applicationResult] = await Promise.allSettled([
        aiChatApi.listSessions({ mode: 'code', assistant_profile: 'system_assistant' }),
        codeRuntimeApi.listRailHistory(),
      ])
      if (seq !== railSessionsSeq || mode !== currentMode.value) return
      systemAssistantSessionData.value = systemResult.status === 'fulfilled'
        ? systemResult.value?.sessions || []
        : systemAssistantSessionData.value
      if (applicationResult.status === 'fulfilled') {
        const history = await hydrateCodeRailHistorySessions(
          applicationResult.value,
          codeRuntimeApi.listAgentSessions,
        )
        if (seq !== railSessionsSeq || mode !== currentMode.value) return
        codeRailHistory.value = history
      }
      return
    }
    const d = await aiChatApi.listSessions()
    if (seq !== railSessionsSeq || mode !== currentMode.value) return
    const sessions = d?.sessions || []
    aiSessions.value = sessions.filter(s => s.mode !== 'code')
  } catch {
    if (seq !== railSessionsSeq || mode !== currentMode.value) return
    if (mode !== 'code') aiSessions.value = []
  }
}

function syncSystemAssistantSessionPolling() {
  if (systemAssistantSessionsTimer) {
    clearInterval(systemAssistantSessionsTimer)
    systemAssistantSessionsTimer = null
  }
  if (currentMode.value !== 'code') return
  systemAssistantSessionsTimer = setInterval(() => {
    if (document.visibilityState === 'visible') void loadRailSessions()
  }, 6000)
}

function refreshCodeRail() {
  if (currentMode.value === 'code') {
    void loadRailApps()
    void loadRailSessions()
  }
}

// 分组方式: 按日期 / 按应用(参考 Claude Code 左栏的 Group by) + 分组可折叠。
const RAIL_GROUPBY_KEY = 'apaas-rail-sess-groupby-v1'
const RAIL_GROUPBY_CODE_KEY = 'apaas-rail-sess-groupby-code-v1'
function defaultGroupByForMode(mode: AppMode): 'date' | 'app' {
  return mode === 'builder' || mode === 'code' ? 'app' : 'date'
}
function groupByStorageKey(mode: AppMode): string {
  return mode === 'code' ? RAIL_GROUPBY_CODE_KEY : RAIL_GROUPBY_KEY
}
function loadGroupByForMode(mode: AppMode): 'date' | 'app' {
  try {
    const stored = localStorage.getItem(groupByStorageKey(mode))
    if (stored === 'date' || stored === 'app') return stored
  } catch { /* private */ }
  return defaultGroupByForMode(mode)
}
const groupBy = ref<'date' | 'app'>(loadGroupByForMode(currentMode.value))
const groupByMode = ref<AppMode>(currentMode.value)
const effectiveGroupBy = computed<'date' | 'app'>(() =>
  isSystemAssistantRoute.value
    ? 'date'
    : (groupByMode.value === currentMode.value ? groupBy.value : loadGroupByForMode(currentMode.value))
)
function setGroupBy(g: 'date' | 'app') {
  groupByMode.value = currentMode.value
  groupBy.value = g
  try { localStorage.setItem(groupByStorageKey(currentMode.value), g) } catch { /* private */ }
}

// 切模式时重新拉对应会话源(builder/agent↔code), 并恢复该模式自己的分组偏好。
watch(currentMode, () => {
  groupByMode.value = currentMode.value
  groupBy.value = loadGroupByForMode(currentMode.value)
  void loadRailApps()
  void loadRailSessions()
  syncSystemAssistantSessionPolling()
})
watch(isSystemAssistantRoute, () => {
  void loadRailApps()
  void loadRailSessions()
  syncSystemAssistantSessionPolling()
})
const collapsedGroups = ref<Set<string>>(new Set())
function toggleGroup(label: string) {
  const s = new Set(collapsedGroups.value)
  s.has(label) ? s.delete(label) : s.add(label)
  collapsedGroups.value = s
}

const creatingCodeAgentSession = ref(false)
const creatingBuilderSession = ref(false)
const railNavigationIntent = createLatestRailNavigationIntent()
const sessionGroups = computed<(RailSessionGroup | CodeRailSessionGroup)[]>(() => {
  if (effectiveGroupBy.value === 'app' && currentMode.value === 'code') {
    return groupCodeRailHistoryByApplication(codeRailHistory.value)
  }
  if (effectiveGroupBy.value === 'app') {
    return groupRailSessionsByApplication(railSessions.value, currentMode.value)
  }
  const now = new Date()
  const startOfToday = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime()
  const dayMs = 86400000
  const buckets = [
    { label: '今天', items: [] as RailSession[] }, { label: '昨天', items: [] as RailSession[] },
    { label: '本周', items: [] as RailSession[] }, { label: '更早', items: [] as RailSession[] },
  ]
  for (const s of railSessions.value) {
    const t = s.updatedAt ? new Date(s.updatedAt).getTime() : 0
    if (t >= startOfToday) buckets[0].items.push(s)
    else if (t >= startOfToday - dayMs) buckets[1].items.push(s)
    else if (t >= startOfToday - 6 * dayMs) buckets[2].items.push(s)
    else buckets[3].items.push(s)
  }
  return buckets.filter(b => b.items.length)
})

async function openSession(session: RailSession) {
  const intent = railNavigationIntent.begin()
  if (currentMode.value === 'code' && session.source !== 'code-agent' && session.source !== 'code-shell') {
    if (railNavigationIntent.isCurrent(intent)) {
      router.push({ path: '/code/system-assistant', query: { ...route.query, session: String(session.id) } })
    }
    return
  }
  if (!railNavigationIntent.isCurrent(intent)) return
  router.push(railSessionTarget(currentMode.value, session, route.query))
}

function sessionGroupKey(group: RailSessionGroup | CodeRailSessionGroup): string {
  return 'logicalApplicationId' in group
    ? `application:${group.logicalApplicationId}`
    : group.label
}

function openCodeLocationSession(
  group: RailSessionGroup | CodeRailSessionGroup,
  location: CodeExecutionLocation,
) {
  if (!('locationSessions' in group)) return
  const session = group.locationSessions[location]
  if (session) void openSession(session)
}

function codeGroupStandardShellSessionId(
  group: RailSessionGroup | CodeRailSessionGroup,
): string | undefined {
  return 'standardShellSessionId' in group ? group.standardShellSessionId : undefined
}

function createSystemAssistantSession() {
  railNavigationIntent.begin()
  const query = { ...route.query }
  delete query.session
  router.push({ path: '/code/system-assistant', query })
}

function sessionActive(s: RailSession) {
  if (isSystemAssistantRoute.value) return String(route.query.session || '') === String(s.id)
  return isRailSessionActive(currentMode.value, s, route)
}

function sessionRunning(session: RailSession): boolean {
  return ['running', 'processing'].includes(String(session.status || '').toLowerCase())
}

async function renameSystemAssistantSession(session: RailSession) {
  try {
    const { value } = await ElMessageBox.prompt('输入新的会话名称', '重命名会话', {
      inputValue: session.title || '',
      inputPlaceholder: '会话名称',
      confirmButtonText: '保存',
      cancelButtonText: '取消',
      inputValidator: value => Boolean(String(value || '').trim()) || '请输入会话名称',
    })
    const title = String(value || '').trim()
    if (!title || title === session.title) return
    await aiChatApi.updateSession(Number(session.id), { title })
    await loadRailSessions()
    window.dispatchEvent(new CustomEvent('system-assistant-session-renamed', {
      detail: { id: Number(session.id), title },
    }))
  } catch (error: any) {
    if (error === 'cancel' || error === 'close') return
    ElMessage.error(error?.response?.data?.detail || error?.message || '重命名失败')
  }
}

function upsertOptimisticCodeAgentSession(
  shellSessionId: string,
  runtimeSessionId: string,
  session?: Record<string, any> | null,
) {
  const history = codeRailHistory.value
  if (!history || !runtimeSessionId) return
  const now = new Date().toISOString()
  const optimistic: CodeAgentSessionRecord = {
    runtimeSessionId,
    title: String(session?.title || session?.summary || '').trim() || null,
    summary: typeof session?.summary === 'string' ? session.summary : null,
    state: String(session?.state || 'waiting_input'),
    model: typeof session?.model === 'string' ? session.model : null,
    createdAt: String(session?.createdAt || now),
    updatedAt: String(session?.updatedAt || now),
    lastActiveAt: String(session?.lastActiveAt || session?.updatedAt || now),
    current: true,
    deletedAt: null,
    capabilityStale: Boolean(session?.capabilityStale),
    codexSessionResumable: session?.codexSessionResumable !== false,
  }
  codeRailHistory.value = {
    apps: history.apps.map((app) => {
      if (String(app.shell_session_id || '') !== shellSessionId) return app
      const sessions = (app.sessions || [])
        .filter(item => String(item.runtimeSessionId || '') !== runtimeSessionId)
        .map(item => ({ ...item, current: false }))
      return {
        ...app,
        runtime_session_id: runtimeSessionId,
        sessions: [optimistic, ...sessions],
      }
    }),
  }
}

async function createBuilderSession(appId?: number | null) {
  if (creatingBuilderSession.value || currentMode.value !== 'builder' || !appId) return
  creatingBuilderSession.value = true
  try {
    const session = await aiChatApi.createSession({ app_id: appId, mode: 'chat' })
    router.push({
      path: `/ai-chat/${session.id}`,
      query: { ...route.query, app_id: String(appId) },
    })
    void loadRailSessions()
  } catch (error: any) {
    ElMessage.error(error?.response?.data?.detail || error?.message || '新建会话失败')
  } finally {
    creatingBuilderSession.value = false
  }
}

async function createCodeAgentSession(
  shellSessionId?: string | null,
  group?: RailSessionGroup | CodeRailSessionGroup,
) {
  if (creatingCodeAgentSession.value) return
  const isCodeMode = currentMode.value === 'code'
  if (!isCodeMode) return
  const intent = railNavigationIntent.begin()
  creatingCodeAgentSession.value = true
  try {
    let targetShellSessionId = shellSessionId || ''
    if (!targetShellSessionId && group && 'locationSessions' in group) {
      const representative = group.locationSessions.local || group.locationSessions.remote
      if (representative) {
        const standardShell = await codeRuntimeApi.createSessionFromExternalApp({
          logical_application_id: representative.logicalApplicationId,
          external_application_id: representative.externalApplicationId,
          execution_location: representative.executionLocation,
          session_policy: 'resume_recent',
          session_purpose: 'standard',
          app_name: representative.appName,
        })
        targetShellSessionId = String(
          standardShell.route_id || standardShell.public_id || standardShell.id || '',
        )
      }
    }
    if (!targetShellSessionId) {
      ElMessage.warning('请先打开一个 Code 应用')
      return
    }
    if (!railNavigationIntent.isCurrent(intent)) return
    const result = await codeRuntimeApi.createAgentSession(targetShellSessionId)
    if (!railNavigationIntent.isCurrent(intent)) return
    if (result.runtime_session_id) {
      upsertOptimisticCodeAgentSession(targetShellSessionId, result.runtime_session_id, result.session)
      router.push({
        path: `/code/${result.shell_session_id || targetShellSessionId}`,
        query: nextAgentQuery(route.query, result.runtime_session_id),
      })
    } else {
      router.push({
        path: `/code/${targetShellSessionId}`,
        query: nextAgentQuery(route.query),
      })
    }
    void loadRailSessions()
  } catch (error: any) {
    ElMessage.error(error?.response?.data?.detail || error?.message || '新建对话失败')
  } finally {
    creatingCodeAgentSession.value = false
  }
}
async function deleteRailSession(s: RailSession) {
  try {
    await ElMessageBox.confirm(
      `删除会话「${s.title || '未命名会话'}」后无法恢复。`,
      '删除会话',
      { confirmButtonText: '删除', cancelButtonText: '取消', type: 'warning' },
    )
  } catch {
    return
  }
  try {
    if (currentMode.value === 'code' && s.source === 'code-agent' && s.shellSessionId && s.runtimeSessionId) {
      await codeRuntimeApi.deleteAgentSession(s.shellSessionId, s.runtimeSessionId)
    } else {
      await aiChatApi.deleteSession(Number(s.id))
    }
  } catch { /* ignore */ }
  await loadRailSessions()
  if (sessionActive(s)) {
    if (isSystemAssistantRoute.value) {
      const query = { ...route.query }
      delete query.session
      router.push({ path: '/code/system-assistant', query })
      return
    }
    router.push({
      path: railSessionFallback(currentMode.value),
      query: nextAgentQuery(route.query),
    })
  }
}

const RAIL_COLLAPSE_KEY = 'apaas-rail-collapsed-v1'
const internalCollapsed = ref<boolean>(localStorage.getItem(RAIL_COLLAPSE_KEY) === '1')
const appCount = ref<number | undefined>(undefined)
const tenantMenuOpen = ref(false)

const effectiveCollapsed = computed(() =>
  props.collapsed === true ? true : internalCollapsed.value
)

// 桌面包剔除指向 admin-spa 的路由（meta.desktop === 'hidden'）；
// 在线版此函数恒返回 false，tree-shake 后零开销。
function desktopHidden(path: string): boolean {
  if (!__DESKTOP__) return false
  try { return (router.resolve(path).meta as any)?.desktop === 'hidden' } catch { return false }
}

// 导航 = 当前模式自带的左栏(参考设计: 每模式不同)。apps 项带应用计数 badge。
const NAV = computed<NavItem[]>(() => {
  const items = visibleModeNav(currentMode.value, __DESKTOP__).map<NavItem>(it => ({
    ...it,
    badge: it.key.endsWith('-apps') ? (appCount.value || undefined) : undefined,
  }))
  return items.filter(item => !desktopHidden(item.path))
})
const auditLogNavItem: NavItem = { key: 'audit-logs', label: '管理审计日志', icon: 'activity', path: '/audit-logs' }
// 审计日志保留直达路由，默认不在主侧栏曝光。
const showAuditLogNavItem = false

const userAccount = computed(() => user.user?.username || '')
const userName = computed(() => user.user?.display_name || userAccount.value || '未登录')
const userAvatarText = computed(() => Array.from(userName.value.trim())[0]?.toUpperCase() || 'U')
const tenantOptions = computed(() => user.availableTenants || [])
const isControlPlaneTenantAuthority = computed(() => user.user?.tenant_authority === 'control_plane')
const currentTenantValue = computed(() => isControlPlaneTenantAuthority.value
  ? (user.user?.control_plane_tenant_id || getControlPlaneCodeSession()?.tenantId || '')
  : (user.tenantId ? String(user.tenantId) : ''))
function looksLikeLongId(value?: string | null) {
  return /^\d{12,}$/.test(String(value || '').trim())
}

function tenantLabel(tenant?: { tenant_name?: string | null; tenant_code?: string | null; tenant_id?: number | string | null }) {
  const name = String(tenant?.tenant_name || '').trim()
  const code = String(tenant?.tenant_code || '').trim()
  if (name && !looksLikeLongId(name)) return name
  if (code && !looksLikeLongId(code)) return code
  return name || code || (tenant?.tenant_id ? `租户 ${tenant.tenant_id}` : '未选择租户')
}

function tenantSubtitle(tenant?: { tenant_name?: string | null; tenant_code?: string | null; tenant_id?: number | string | null }) {
  const code = String(tenant?.tenant_code || '').trim()
  const name = String(tenant?.tenant_name || '').trim()
  if (code && !looksLikeLongId(code)) return `编码：${code}`
  if (name && looksLikeLongId(name)) return `平台租户ID：${name}`
  if (tenant?.tenant_id) return `租户ID：${tenant.tenant_id}`
  return ''
}

const currentTenantLabel = computed(() => {
  if (isControlPlaneTenantAuthority.value && getControlPlaneCodeSession()?.tenantName) {
    return getControlPlaneCodeSession()?.tenantName || '未选择组织'
  }
  if (__DESKTOP__) {
    return user.user?.control_plane_tenant_name || user.user?.tenant_name || '未选择组织'
  }
  const match = tenantOptions.value.find(
    tenant => String(tenant.tenant_id) === currentTenantValue.value,
  )
  return tenantLabel(match || {
    tenant_name: user.user?.tenant_name,
    tenant_code: undefined,
    tenant_id: user.tenantId,
  })
})
const userMenuOpen = ref(false)
function toggleUserMenu(e: MouseEvent) {
  e.stopPropagation()
  userMenuOpen.value = !userMenuOpen.value
  tenantMenuOpen.value = false
}
function closeTenantMenu() {
  tenantMenuOpen.value = false
  userMenuOpen.value = false
}

function applyDesktopWorkspaceEntryScope(scope: unknown) {
  if (scope === 'apaas' || scope === 'ai_platform' || scope === 'both') {
    desktopWorkspaceEntryScope.value = scope
  }
}

async function loadDesktopWorkspaceEntryScope() {
  if (!__DESKTOP__) return
  try {
    const snapshot = await getDesktopState()
    applyDesktopWorkspaceEntryScope(resolveDesktopProductScope(snapshot.config))
  } catch { /* desktop bootstrap owns state errors */ }
}

async function loadWebProductAvailability() {
  if (__DESKTOP__) return
  productAvailability.value = await loadProductAvailability()
}

function onDesktopWorkspaceEntryScopeChanged(event: Event) {
  applyDesktopWorkspaceEntryScope(
    (event as CustomEvent<DesktopWorkspaceEntryScope | undefined>).detail,
  )
}

function onCodeApplicationSourceChanged(event: Event) {
  const source = (event as CustomEvent<CodeApplicationSource | undefined>).detail
  if (source !== 'local' && source !== 'remote') return
  codeApplicationSource.value = source
  refreshCodeRail()
}

onMounted(() => {
  const startupTasks: Promise<unknown>[] = [
    loadRailApps(),
    loadRailSessions(),
  ]
  startupTasks.push(user.fetchAvailableTenants())
  if (__DESKTOP__) startupTasks.push(loadDesktopWorkspaceEntryScope())
  else startupTasks.push(loadWebProductAvailability())
  void Promise.allSettled(startupTasks)
  syncSystemAssistantSessionPolling()
  window.addEventListener('click', closeTenantMenu)
  window.addEventListener('code-rail-refresh', refreshCodeRail)
  if (__DESKTOP__) {
    window.addEventListener(
      CODE_APPLICATION_SOURCE_CHANGED_EVENT,
      onCodeApplicationSourceChanged,
    )
    window.addEventListener(
      'desktop-workspace-entry-scope-changed',
      onDesktopWorkspaceEntryScopeChanged,
    )
  }
})

onBeforeUnmount(() => {
  if (systemAssistantSessionsTimer) clearInterval(systemAssistantSessionsTimer)
  window.removeEventListener('click', closeTenantMenu)
  window.removeEventListener('code-rail-refresh', refreshCodeRail)
  if (__DESKTOP__) {
    window.removeEventListener(
      CODE_APPLICATION_SOURCE_CHANGED_EVENT,
      onCodeApplicationSourceChanged,
    )
    window.removeEventListener(
      'desktop-workspace-entry-scope-changed',
      onDesktopWorkspaceEntryScopeChanged,
    )
  }
})

function toggleCollapsed() {
  internalCollapsed.value = !internalCollapsed.value
  tenantMenuOpen.value = false
  try { localStorage.setItem(RAIL_COLLAPSE_KEY, internalCollapsed.value ? '1' : '0') } catch { /* private mode */ }
}

function isActive(path: string) {
  const basePath = path.split('?')[0]
  if (path.includes('create=1')) {
    return route.path === basePath && route.query.create != null
  }
  // AI Builder（/）= 融合页，/ai-chat 系列是同一功能，一并高亮。
  if (basePath === '/') return route.path === '/' || route.path.startsWith('/ai-chat')
  return route.path === basePath || route.path.startsWith(basePath + '/')
}

function toggleTenantMenu(event: MouseEvent) {
  event.stopPropagation()
  tenantMenuOpen.value = !tenantMenuOpen.value
}

function withTenantId(path: string, targetPublicId: string): string {
  const base = import.meta.env.BASE_URL || '/'
  const basePath = `/${base.replace(/^\/+|\/+$/g, '')}`
  const prefix = basePath === '/' ? '' : basePath
  const parsed = new URL(`${prefix}${path}`, 'https://tenant-navigation.invalid')
  parsed.searchParams.set('tenantId', targetPublicId)
  return `${parsed.pathname}${parsed.search}${parsed.hash}`
}

async function selectTenant(value: string) {
  tenantMenuOpen.value = false
  const tenant = tenantOptions.value.find(item => String(item.tenant_id) === value)
  if (!tenant || value === currentTenantValue.value) return
  if (isControlPlaneTenantAuthority.value && !__DESKTOP__) {
    const session = getControlPlaneCodeSession()
    const authToken = session?.token || user.token
    if (!authToken) return
    const outcome = await user.switchControlPlaneCodeTenant(value, authToken)
    if (outcome === 'committed') window.location.reload()
    return
  }
  const targetPublicId = tenant.tenant_public_id
  if (!targetPublicId) return
  const localTenantId = Number(tenant.tenant_id)
  if (!Number.isSafeInteger(localTenantId)) return
  const navigationEpoch = user.advanceTenantNavigationEpoch()
  if (!__DESKTOP__) {
    productAvailability.value = await loadProductAvailability()
  }
  const destination = withTenantId(
    railTenantHome(__DESKTOP__, currentMode.value, productAvailability.value),
    targetPublicId,
  )
  await user.switchTenantContext(
    localTenantId,
    targetPublicId,
    destination,
    navigationEpoch,
  )
}

function go(path: string) {
  railNavigationIntent.begin()
  tenantMenuOpen.value = false
  userMenuOpen.value = false
  router.push(path)
}

function goNav(item: NavItem) {
  railNavigationIntent.begin()
  tenantMenuOpen.value = false
  router.push(item.path)
}

function switchMode(mode: AppMode) {
  if (mode === currentMode.value) return
  railNavigationIntent.begin()
  modeStore.setMode(mode)
  tenantMenuOpen.value = false
  router.push(MODE_META[mode].home)
}

// 2026-05-23: rail nav 改 <a href> 让 Cmd+click / 中键 / 右键"在新标签中打开"
// 真开 chrome tab — 跟 admin-spa AdminLayout 一致体验
function resolveHref(path: string): string {
  try {
    return router.resolve(path).href
  } catch {
    return path
  }
}

function onMenuClick(e: MouseEvent, item: NavItem) {
  // modifier / 中键 → 浏览器原生开新 chrome tab，不拦
  if (e.metaKey || e.ctrlKey || e.shiftKey || e.altKey || e.button !== 0) {
    return
  }
  e.preventDefault()
  goNav(item)
}

const isDesktop = __DESKTOP__

function onLogout() {
  tenantMenuOpen.value = false
  user.logout()
  // 退出只清认证态。主题、布局偏好等本地设置保留，避免登录页颜色模式被重置或半切换。
  try { localStorage.removeItem('ai-builder-tabs-v1') } catch { /* private mode */ }
  router.push({ path: '/login' })
}

// v3 2026-05-20: ACCENT_PRESETS 主题色 picker 删 — 让 admin/frontend brand 始终一致蓝色
// theme.ts 默认 #1D4ED8 v3 blue 不再被 user picker 覆盖
const ICONS: Record<string, string> = {
  home: '<path d="M3 11.5 12 4l9 7.5V20a1 1 0 0 1-1 1h-5v-6h-6v6H4a1 1 0 0 1-1-1z"/>',
  apps: '<path d="M3 5h7v7H3z"/><path d="M14 5h7v7h-7z"/><path d="M3 16h7v5H3z"/><path d="M14 16h7v5h-7z"/>',
  chat: '<path d="M21 12a8 8 0 0 1-11.9 7L4 21l1.6-4.4A8 8 0 1 1 21 12z"/>',
  code: '<path d="m9 17-5-5 5-5"/><path d="m15 7 5 5-5 5"/><path d="m13 5-2 14"/>',
  store: '<path d="M3 9 5 4h14l2 5"/><path d="M4 9v10a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1V9"/><path d="M3 9h18"/>',
  database: '<ellipse cx="12" cy="5" rx="9" ry="3"/><path d="M3 5v14a9 3 0 0 0 18 0V5"/><path d="M3 12a9 3 0 0 0 18 0"/>',
  activity: '<polyline points="22 12 18 12 15 21 9 3 6 12 2 12"/><path d="M4 19h16"/>',
  spark: '<path d="M12 3 14 9l6 2-6 2-2 6-2-6-6-2 6-2z"/>',
  sparkles: '<path d="M9 4 10 7 13 8 10 9 9 12 8 9 5 8 8 7z"/><path d="M17 3l.7 2.3L20 6l-2.3.7L17 9l-.7-2.3L14 6l2.3-.7z"/><path d="M16 15l1 2.5 2.5 1-2.5 1-1 2.5-1-2.5-2.5-1 2.5-1z"/>',
  bldg: '<path d="M4 21V5l8-3 8 3v16"/><path d="M9 9h.01M9 13h.01M9 17h.01M15 9h.01M15 13h.01M15 17h.01"/><path d="M4 21h16"/>',
  shield: '<path d="M12 2 4 5v7c0 5 3.5 8.5 8 10 4.5-1.5 8-5 8-10V5z"/><path d="M9 12l2 2 4-4"/>',
  sun: '<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4 12H2M22 12h-2M6.3 6.3 4.9 4.9M19.1 19.1l-1.4-1.4M6.3 17.7l-1.4 1.4M19.1 4.9l-1.4 1.4"/>',
  moon: '<path d="M21 13A9 9 0 0 1 11 3a9 9 0 1 0 10 10z"/>',
  settings: '<path d="M12.22 2h-.44a2 2 0 0 0-2 2v.18a2 2 0 0 1-1 1.73l-.43.25a2 2 0 0 1-2 0l-.15-.08a2 2 0 0 0-2.73.73l-.22.38a2 2 0 0 0 .73 2.73l.15.1a2 2 0 0 1 1 1.72v.51a2 2 0 0 1-1 1.74l-.15.09a2 2 0 0 0-.73 2.73l.22.38a2 2 0 0 0 2.73.73l.15-.08a2 2 0 0 1 2 0l.43.25a2 2 0 0 1 1 1.73V20a2 2 0 0 0 2 2h.44a2 2 0 0 0 2-2v-.18a2 2 0 0 1 1-1.73l.43-.25a2 2 0 0 1 2 0l.15.08a2 2 0 0 0 2.73-.73l.22-.38a2 2 0 0 0-.73-2.73l-.15-.09a2 2 0 0 1-1-1.74v-.51a2 2 0 0 1 1-1.74l.15-.09a2 2 0 0 0 .73-2.73l-.22-.38a2 2 0 0 0-2.73-.73l-.15.08a2 2 0 0 1-2 0l-.43-.25a2 2 0 0 1-1-1.73V4a2 2 0 0 0-2-2z"/><circle cx="12" cy="12" r="3"/>',
  chevronLeft: '<polyline points="15 18 9 12 15 6"/>',
  chevronRight: '<polyline points="9 18 15 12 9 6"/>',
  chevronDown: '<polyline points="6 9 12 15 18 9"/>',
  logout: '<path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/><polyline points="16 17 21 12 16 7"/><line x1="21" y1="12" x2="9" y2="12"/>',
  refresh: '<path d="M21 12a9 9 0 1 1-2.6-6.4"/><polyline points="21 3 21 9 15 9"/>',
  plus: '<line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/>',
  trash: '<path d="M3 6h18"/><path d="M8 6V4h8v2"/><path d="M19 6l-1 14H6L5 6"/><path d="M10 11v5M14 11v5"/>',
  edit: '<path d="M12 20h9"/><path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4z"/>',
  moreHorizontal: '<circle cx="5" cy="12" r="1"/><circle cx="12" cy="12" r="1"/><circle cx="19" cy="12" r="1"/>',
}

function renderIcon(name: string): string {
  const inner = ICONS[name] ?? ''
  return `<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">${inner}</svg>`
}
</script>

<template>
  <aside class="rail" :class="{ 'rail-collapsed': effectiveCollapsed }">
    <div class="rail-brand">
      <button
        class="rail-logo"
        type="button"
        :aria-label="effectiveCollapsed ? '展开导航' : 'DolphinAI 首页'"
        @click="effectiveCollapsed ? toggleCollapsed() : go(defaultProductHome(productAvailability))"
      >
        <img class="rail-logo-mark" :src="ruijingWhaleMarkUrl" alt="" aria-hidden="true" />
      </button>
      <div v-if="!effectiveCollapsed" class="rail-brand-copy">
        <div class="rail-title">DolphinAI</div>
      </div>
      <!-- 收起按钮放在 brand 区右侧 — 跟 SessionSidebar 的 « 按钮位置一致，
           比放底部更顺手。展开 / 收起两个状态用同一个 button，方向不一样。 -->
      <button
        v-if="!effectiveCollapsed"
        type="button"
        class="rail-collapse-top"
        title="收起导航"
        aria-label="收起导航"
        @click="toggleCollapsed"
      >
        <span v-html="renderIcon('chevronLeft')" />
      </button>
    </div>

    <button
      v-if="effectiveCollapsed"
      type="button"
      class="rail-expand-top"
      title="展开导航"
      aria-label="展开导航"
      @click="toggleCollapsed"
    >
      <span v-html="renderIcon('chevronRight')" />
    </button>

    <div
      v-if="!effectiveCollapsed && visibleModeOrder.length > 1"
      class="rail-mode-switch"
      role="tablist"
      aria-label="工作模式"
      :style="{ gridTemplateColumns: `repeat(${visibleModeOrder.length}, minmax(0, 1fr))` }"
    >
      <button
        v-for="mode in visibleModeOrder"
        :key="mode"
        type="button"
        class="rail-mode-btn"
        :class="{ active: mode === currentMode }"
        role="tab"
        :aria-selected="mode === currentMode"
        @click="switchMode(mode)"
      >
        {{ isDesktop ? desktopModeLabel(mode) : MODE_META[mode].label }}
      </button>
    </div>

    <nav class="rail-scroll" aria-label="主导航">
      <!-- 2026-05-23: button → <a href> 让 cmd+click / 中键 / 右键"在新标签中打开" 真开 chrome tab.
           普通 click → router.push 直接导航 (2026-06-08 已删多 tab 体系). -->
      <a
        v-for="it in NAV"
        :key="it.key"
        :href="resolveHref(it.path)"
        class="rail-item"
        :class="{ active: isActive(it.path) }"
        :title="`${it.label} (Cmd+点 在新标签中打开)`"
        @click="onMenuClick($event, it)"
        @auxclick="onMenuClick($event, it)"
      >
        <span class="rail-item-icon" v-html="renderIcon(it.icon)" />
        <span class="rail-item-label">{{ it.label }}</span>
        <span v-if="it.badge" class="rail-item-badge">{{ it.badge }}</span>
      </a>

      <SystemAssistantSessionSections
        v-if="showRecent && currentMode === 'code'"
        class="rail-sessions rail-system-assistant-sessions"
        :system-sessions="systemAssistantSessions"
        :application-groups="systemAssistantApplicationGroups"
        :active-system-session-id="String(route.query.session || '')"
        :active-application-shell-session-id="activeCodeShellSessionId"
        :active-application-runtime-session-id="activeCodeRuntimeSessionId"
        :is-application-session-active="sessionActive"
        @new-system-session="createSystemAssistantSession"
        @open-system-session="openSession"
        @rename-system-session="renameSystemAssistantSession"
        @delete-system-session="deleteRailSession"
        @open-application-session="openSession"
        @new-application-session="createCodeAgentSession"
      />

      <!-- 普通应用会话继续按日期或应用分组。 -->
      <div v-else-if="showRecent" class="rail-sessions">
        <div class="rail-sess-toolbar">
          <span class="rail-sess-cap">会话</span>
          <div class="rail-sess-groupby">
            <button type="button" :class="{ on: effectiveGroupBy === 'date' }" @click="setGroupBy('date')">日期</button>
            <button type="button" :class="{ on: effectiveGroupBy === 'app' }" @click="setGroupBy('app')">应用</button>
          </div>
        </div>
        <div class="rail-sess-list">
          <div v-for="g in sessionGroups" :key="sessionGroupKey(g)" class="rail-sess-group">
            <div class="rail-sess-label-row">
              <button type="button" class="rail-sess-label" @click="toggleGroup(sessionGroupKey(g))">
                <span class="rail-sess-chev" :class="{ collapsed: collapsedGroups.has(sessionGroupKey(g)) }" v-html="renderIcon('chevronDown')" />
                <span class="rail-sess-glabel">{{ g.label }}</span>
                <span
                  v-if="currentMode === 'code' && effectiveGroupBy === 'app' && 'availableLocations' in g"
                  class="rail-sess-locations"
                >{{ g.availableLocations.map(location => location === 'local' ? '本机' : '远程').join('、') }}</span>
                <span class="rail-sess-cnt">{{ g.items.length }}</span>
              </button>
              <button
                v-if="currentMode === 'code' && effectiveGroupBy === 'app' && 'localShellSessionId' in g && g.localShellSessionId"
                type="button"
                class="rail-sess-location-open"
                @click.stop="openCodeLocationSession(g, 'local')"
              >本机打开</button>
              <button
                v-if="currentMode === 'code' && effectiveGroupBy === 'app' && 'remoteShellSessionId' in g && g.remoteShellSessionId"
                type="button"
                class="rail-sess-location-open"
                @click.stop="openCodeLocationSession(g, 'remote')"
              >远程打开</button>
              <button
                v-if="effectiveGroupBy === 'app' && ((currentMode === 'code' && ('locationSessions' in g)) || (currentMode === 'builder' && g.appId))"
                type="button"
                class="rail-sess-group-new"
                title="新建对话"
                aria-label="新建对话"
                :disabled="currentMode === 'code' ? creatingCodeAgentSession : creatingBuilderSession"
                @click.stop="currentMode === 'code' ? createCodeAgentSession(codeGroupStandardShellSessionId(g), g) : createBuilderSession(g.appId)"
              >
                <span v-html="renderIcon('plus')" />
              </button>
            </div>
            <template v-if="!collapsedGroups.has(sessionGroupKey(g))">
              <div
                v-for="s in g.items"
                :key="s.id"
                class="rail-sess-item"
                :class="{ active: sessionActive(s) }"
                :title="s.title || '未命名会话'"
                @click="openSession(s)"
              >
                <span
                  class="rail-sess-state"
                  :class="{ running: sessionRunning(s) }"
                  :title="sessionRunning(s) ? '执行中' : ''"
                />
                <span class="rail-sess-title">{{ s.title || '未命名会话' }}</span>
                <span v-if="currentMode === 'code' && 'locationSummary' in s" class="rail-sess-location">{{ s.locationSummary }}</span>
                <button class="rail-sess-del" type="button" title="删除会话" aria-label="删除会话" @click.stop="deleteRailSession(s)">
                  <span v-html="renderIcon('trash')" />
                </button>
              </div>
            </template>
          </div>
          <div v-if="!sessionGroups.length" class="rail-sess-empty">还没有会话</div>
        </div>
      </div>
    </nav>

    <div class="rail-foot">
      <!-- 老的 .rail-collapse-btn 已移到顶部 brand 区，这里删掉减少重复入口 -->

      <div v-if="!effectiveCollapsed" class="rail-console" @click.stop>
        <!-- 组织切换和配置入口统一收进头像菜单。 -->
        <div v-show="userMenuOpen" class="rail-user-menu">
          <div class="user-menu-tenant" @click.stop>
            <div class="user-menu-tenant-label">{{ isDesktop ? '当前组织' : '当前租户' }}</div>
            <div class="tenant-switch-wrap">
              <button
                type="button"
                class="tenant-switch"
                :class="{ open: tenantMenuOpen }"
                aria-haspopup="menu"
                :aria-expanded="tenantMenuOpen"
                @click="toggleTenantMenu"
              >
                <span class="tenant-icon" v-html="renderIcon('bldg')" />
                <span class="tenant-name" :title="user.user?.tenant_name || currentTenantLabel">{{ currentTenantLabel }}</span>
                <span class="tenant-arrow" v-html="renderIcon('chevronDown')" />
              </button>
              <div v-if="tenantMenuOpen" class="tenant-menu" role="menu">
                <button
                  v-for="tenant in tenantOptions"
                  :key="tenant.tenant_id"
                  type="button"
                  class="tenant-option"
                  :class="{ active: String(tenant.tenant_id) === currentTenantValue }"
                  role="menuitem"
                  @click="selectTenant(String(tenant.tenant_id))"
                >
                  <span class="tenant-option-name" :title="tenant.tenant_name">{{ tenantLabel(tenant) }}</span>
                  <span v-if="tenantSubtitle(tenant)" class="tenant-option-code">{{ tenantSubtitle(tenant) }}</span>
                </button>
                <div v-if="!tenantOptions.length" class="tenant-empty">暂无可切换组织</div>
              </div>
            </div>
          </div>

          <a
            v-if="showAuditLogNavItem && user.isTenantAdmin"
            class="console-row"
            :class="{ active: isActive(auditLogNavItem.path) }"
            :href="resolveHref(auditLogNavItem.path)"
            title="管理审计日志"
            @click="onMenuClick($event, auditLogNavItem)"
            @auxclick="onMenuClick($event, auditLogNavItem)"
          >
            <span class="console-row-icon" v-html="renderIcon('activity')" />
            <span>管理审计日志</span>
          </a>

          <button type="button" class="console-row settings-entry-row" @click="go(isDesktop ? '/desktop-settings' : '/settings?section=ai')">
            <span class="console-row-icon" v-html="renderIcon('settings')" />
            <span>设置</span>
          </button>

          <button type="button" class="console-row logout-row" title="退出登录" @click="onLogout">
            <span class="console-row-icon" v-html="renderIcon('logout')" />
            <span>退出登录</span>
          </button>
        </div><!-- /rail-user-menu -->

        <button
          type="button"
          class="account-row account-toggle"
          :class="{ open: userMenuOpen }"
          @click="toggleUserMenu"
        >
          <div class="rail-avatar">{{ userAvatarText }}</div>
          <div class="rail-user-info">
            <div class="rail-user-name" :title="userName">{{ userName }}</div>
            <div class="rail-user-status" :title="currentTenantLabel"><span />{{ currentTenantLabel }}</div>
          </div>
          <span class="account-chev" :class="{ open: userMenuOpen }" v-html="renderIcon('chevronDown')" />
        </button>
      </div>
    </div>
  </aside>
</template>

<style scoped>
/* v3 redesign · 2026-05-20 — visual refresh only, template/script structure preserved.
   Phase 8A.1 + 8A.2:
     - Collapsed (56px) → centered 38×38 icons, active 3px left bar + brand-soft
     - Expanded (224px) → surface-2 bg, brand title, brand-soft active state, line dividers
     - Accent picker → 6-preset palette + custom rainbow swatch (template tweak in 8A.2)
   Preserved class names (used by script + external CSS):
     .rail, .rail-collapsed, .rail-brand, .rail-logo, .rail-brand-copy, .rail-title,
     .rail-title-sub, .rail-scroll, .rail-expand-top, .rail-item, .rail-item-icon,
     .rail-item-label, .rail-item-badge, .rail-foot, .rail-collapse-btn, .rail-console,
     .rail-console-label, .tenant-switch-wrap, .tenant-switch, .tenant-icon, .tenant-name,
     .tenant-arrow, .tenant-menu, .tenant-option, .tenant-empty, .console-row,
     .console-row-icon, .platform-row, .theme-row, .theme-row-label, .accent-picker,
     .theme-toggle, .account-row, .rail-avatar, .rail-user-info, .rail-user-name,
     .rail-user-status
   New classes (CSS only, no JS depends on them): .accent-swatch, .accent-custom
*/

.rail {
  width: 224px;
  height: 100%;
  display: flex;
  flex-direction: column;
  flex-shrink: 0;
  overflow: hidden;
  color: var(--text);
  background: var(--surface-2);
  border-right: 1px solid var(--line);
}

.rail-collapsed {
  width: 56px;
}

/* ─── Brand ─────────────────────────────────────────────────────── */
.rail-brand {
  min-height: 60px;
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 14px 16px 12px;
}

.rail-logo {
  width: 28px;
  height: 28px;
  display: grid;
  place-items: center;
  flex-shrink: 0;
  padding: 0;
  color: var(--text-inverse);
  background: transparent;
  border: none;
  border-radius: var(--r-2, 6px);
  box-shadow: 0 10px 22px rgba(7, 61, 139, 0.22);
  cursor: pointer;
  overflow: hidden;
  transition: box-shadow 0.14s var(--ease, cubic-bezier(0.2, 0.8, 0.2, 1)),
              transform 0.14s var(--ease, cubic-bezier(0.2, 0.8, 0.2, 1));
}
.rail-logo-mark {
  width: 100%;
  height: 100%;
  display: block;
  object-fit: cover;
}
.rail-logo:hover {
  box-shadow: var(--sh-brand);
  transform: translateY(-1px);
}
.rail-logo:focus-visible {
  outline: 2px solid var(--line-focus, var(--brand-ring));
  outline-offset: 2px;
}

.rail-brand-copy {
  min-width: 0;
  flex: 1;
}

/* 顶部 brand 区右侧的小收起按钮，跟 SessionSidebar 的 « 形态对齐 */
.rail-collapse-top {
  width: 26px;
  height: 26px;
  display: grid;
  place-items: center;
  flex-shrink: 0;
  margin-left: auto;
  color: var(--text-3);
  background: transparent;
  border: 1px solid transparent;
  border-radius: var(--r-2, 6px);
  cursor: pointer;
  transition: background 0.14s var(--ease, cubic-bezier(0.2, 0.8, 0.2, 1)),
              color 0.14s var(--ease, cubic-bezier(0.2, 0.8, 0.2, 1)),
              border-color 0.14s var(--ease, cubic-bezier(0.2, 0.8, 0.2, 1));
}
.rail-collapse-top:hover {
  background: var(--brand-soft);
  color: var(--brand);
  border-color: var(--brand-ring);
}
.rail-collapse-top:focus-visible {
  outline: 2px solid var(--line-focus, var(--brand-ring));
  outline-offset: 2px;
}

.rail-title {
  color: var(--text);
  font-size: 16px;
  font-weight: var(--fw-bold, 700);
  letter-spacing: -0.01em;
  line-height: 1.1;
  white-space: nowrap;
}

.rail-title-sub {
  margin-top: 3px;
  color: var(--text-3);
  font-size: 11.5px;
  font-weight: var(--fw-medium, 500);
  white-space: nowrap;
}

/* ─── Expand top (collapsed-only) ────────────────────────────── */
.rail-expand-top {
  width: 34px;
  height: 30px;
  display: grid;
  place-items: center;
  flex-shrink: 0;
  margin: -2px auto 6px;
  color: var(--text-3);
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: var(--r-2, 6px);
  cursor: pointer;
  box-shadow: var(--sh-1);
  transition: background 0.14s var(--ease, cubic-bezier(0.2, 0.8, 0.2, 1)),
              color 0.14s var(--ease, cubic-bezier(0.2, 0.8, 0.2, 1)),
              border-color 0.14s var(--ease, cubic-bezier(0.2, 0.8, 0.2, 1));
}
.rail-expand-top:hover {
  background: var(--brand-soft);
  color: var(--brand);
  border-color: var(--brand-ring);
}
.rail-expand-top:focus-visible {
  outline: 2px solid var(--line-focus, var(--brand-ring));
  outline-offset: 2px;
}

.rail-mode-switch {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 2px;
  margin: 0 10px 6px;
  padding: 3px;
  border: 1px solid var(--line);
  border-radius: var(--r-3, 8px);
  background: var(--surface-2);
}

.rail-mode-btn {
  min-width: 0;
  height: 28px;
  border: 0;
  border-radius: var(--r-2, 6px);
  background: transparent;
  color: var(--text-3);
  font-family: inherit;
  font-size: 12px;
  font-weight: var(--fw-semibold, 600);
  cursor: pointer;
}

.rail-mode-btn:hover {
  color: var(--brand);
  background: var(--brand-soft);
}

.rail-mode-btn.active {
  color: var(--brand);
  background: var(--surface);
  box-shadow: var(--sh-1);
}

/* ─── Nav scroll + items ─────────────────────────────────────── */
.rail-scroll {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
  gap: 2px;
  overflow-y: auto;
  padding: 8px 10px 10px;
}

.rail-item {
  position: relative;
  width: 100%;
  min-height: 36px;
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 0 10px;
  color: var(--text-2);
  background: transparent;
  border: none;
  border-radius: var(--r-3, 8px);
  font-family: inherit;
  font-size: 13px;
  font-weight: var(--fw-medium, 500);
  text-align: left;
  cursor: pointer;
  /* 2026-05-23 button → <a> 后禁默认下划线, 跟 admin-spa AdminLayout 一致 */
  text-decoration: none;
  transition: background 0.14s var(--ease, cubic-bezier(0.2, 0.8, 0.2, 1)),
              color 0.14s var(--ease, cubic-bezier(0.2, 0.8, 0.2, 1));
}
.rail-item:hover,
.rail-item:visited,
.rail-item:active {
  text-decoration: none;  /* 各 :hover/:visited 状态锁住, 防 UA :visited 默认 underline */
}

.rail-item:hover {
  color: var(--text);
  background: var(--surface);
}

.rail-item.active {
  color: var(--brand);
  background: var(--brand-soft);
  font-weight: var(--fw-semibold, 600);
}

.rail-item.active::before {
  content: '';
  position: absolute;
  left: -2px;
  top: 6px;
  bottom: 6px;
  width: 3px;
  border-radius: 0 var(--r-1, 4px) var(--r-1, 4px) 0;
  background: var(--brand);
}

.rail-item:focus-visible {
  outline: 2px solid var(--line-focus, var(--brand-ring));
  outline-offset: -2px;
}

.rail-item-icon {
  width: 18px;
  height: 18px;
  display: grid;
  place-items: center;
  flex-shrink: 0;
  color: currentColor;
}

.rail-item-label {
  flex: 1;
  min-width: 0;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.rail-item-badge {
  min-width: 18px;
  height: 18px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  padding: 0 6px;
  border-radius: var(--r-full, 999px);
  color: var(--brand);
  background: var(--brand-soft-2);
  font-family: var(--font-mono, 'JetBrains Mono', monospace);
  font-size: 11px;
  font-weight: var(--fw-semibold, 600);
  font-variant-numeric: tabular-nums;
  letter-spacing: 0;
}

/* ─── Foot ───────────────────────────────────────────────────── */
.rail-foot {
  padding: 10px 10px 12px;
  border-top: 1px solid var(--line);
}

.rail-collapse-btn {
  width: 100%;
  min-height: 30px;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  margin-bottom: 10px;
  color: var(--text-3);
  background: transparent;
  border: 1px solid var(--line);
  border-radius: var(--r-2, 6px);
  font-family: inherit;
  font-size: 12px;
  font-weight: var(--fw-medium, 500);
  cursor: pointer;
  transition: background 0.14s var(--ease, cubic-bezier(0.2, 0.8, 0.2, 1)),
              color 0.14s var(--ease, cubic-bezier(0.2, 0.8, 0.2, 1)),
              border-color 0.14s var(--ease, cubic-bezier(0.2, 0.8, 0.2, 1));
}

.rail-collapse-btn:hover {
  color: var(--brand);
  background: var(--brand-soft);
  border-color: var(--brand-ring);
}

.rail-collapse-btn:focus-visible {
  outline: 2px solid var(--line-focus, var(--brand-ring));
  outline-offset: 2px;
}

/* ─── Console (expanded only) ────────────────────────────────── */
.rail-console {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.rail-console-label {
  margin: 2px 4px 2px;
  color: var(--text-3);
  font-size: 11px;
  font-weight: var(--fw-semibold, 600);
  letter-spacing: 0.06em;
  text-transform: uppercase;
}

.tenant-switch-wrap {
  position: relative;
}

.tenant-switch {
  width: 100%;
  min-height: 34px;
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 0 10px;
  color: var(--text);
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: var(--r-3, 8px);
  font-family: inherit;
  font-size: 12.5px;
  font-weight: var(--fw-medium, 500);
  cursor: pointer;
  text-align: left;
  transition: background 0.14s var(--ease, cubic-bezier(0.2, 0.8, 0.2, 1)),
              border-color 0.14s var(--ease, cubic-bezier(0.2, 0.8, 0.2, 1));
}

.tenant-switch:hover,
.tenant-switch.open {
  border-color: var(--brand-ring);
  background: var(--brand-soft);
  color: var(--brand);
}

.tenant-switch:focus-visible {
  outline: 2px solid var(--line-focus, var(--brand-ring));
  outline-offset: 2px;
}

.tenant-icon {
  width: 16px;
  height: 16px;
  display: grid;
  place-items: center;
  flex-shrink: 0;
  color: var(--brand);
  background: var(--brand-soft);
  border-radius: var(--r-1, 4px);
  padding: 2px;
}

.tenant-name {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.tenant-arrow {
  width: 14px;
  height: 14px;
  display: grid;
  place-items: center;
  flex-shrink: 0;
  color: var(--text-4);
  transition: transform 0.14s var(--ease, cubic-bezier(0.2, 0.8, 0.2, 1));
}

.tenant-switch.open .tenant-arrow {
  transform: rotate(180deg);
}

.tenant-menu {
  position: absolute;
  left: 0;
  right: 0;
  bottom: calc(100% + 6px);
  z-index: 20;
  max-height: 220px;
  overflow-y: auto;
  padding: 4px;
  border: 1px solid var(--line);
  border-radius: var(--r-3, 8px);
  background: var(--surface);
  box-shadow: var(--sh-3);
}

.tenant-option {
  width: 100%;
  min-height: 32px;
  padding: 6px 10px;
  color: var(--text);
  background: transparent;
  border: none;
  border-radius: var(--r-2, 6px);
  font-family: inherit;
  font-size: 12.5px;
  font-weight: var(--fw-medium, 500);
  text-align: left;
  cursor: pointer;
  display: flex;
  flex-direction: column;
  gap: 2px;
  transition: background 0.14s var(--ease, cubic-bezier(0.2, 0.8, 0.2, 1)),
              color 0.14s var(--ease, cubic-bezier(0.2, 0.8, 0.2, 1));
}

.tenant-option-name,
.tenant-option-code {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.tenant-option-code {
  color: var(--text-3);
  font-size: 11px;
  font-weight: var(--fw-regular, 400);
}

.tenant-option:hover,
.tenant-option.active {
  color: var(--brand);
  background: var(--brand-soft);
}

.tenant-option:focus-visible {
  outline: 2px solid var(--line-focus, var(--brand-ring));
  outline-offset: -2px;
}

.tenant-empty {
  padding: 8px 10px;
  color: var(--text-3);
  font-size: 12px;
  font-weight: var(--fw-regular, 400);
}

/* ─── Console rows (platform/etc) ─────────────────────────── */
.console-row {
  width: 100%;
  min-height: 32px;
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 0 10px;
  color: var(--text-2);
  background: transparent;
  border: none;
  border-radius: var(--r-3, 8px);
  font-family: inherit;
  font-size: 12.5px;
  font-weight: var(--fw-medium, 500);
  cursor: pointer;
  text-align: left;
  /* v3 2026-05-20: 兼容历史链接行
     去掉 <a> 默认下划线，跟其他 console-row（button）视觉一致 */
  text-decoration: none;
  transition: background 0.14s var(--ease, cubic-bezier(0.2, 0.8, 0.2, 1)),
              color 0.14s var(--ease, cubic-bezier(0.2, 0.8, 0.2, 1));
}
.console-row:visited {
  color: var(--text-2);
}
.console-row:hover:visited,
.console-row.active:visited {
  color: var(--brand);
}

.console-row:hover {
  color: var(--brand);
  background: var(--brand-soft);
}

.console-row.active {
  color: var(--brand);
  background: var(--brand-soft);
  font-weight: var(--fw-semibold, 600);
}

.console-row:focus-visible {
  outline: 2px solid var(--line-focus, var(--brand-ring));
  outline-offset: -2px;
}

.console-row-icon {
  width: 14px;
  height: 14px;
  display: grid;
  place-items: center;
  flex-shrink: 0;
  color: currentColor;
}

/* ─── Theme row ──────────────────────────────────────────── */
/* 2026-05-21 整 row 改成可点击 button — 之前 label + sun icon 分离割裂。
   配色跟 .console-row hover/focus 一致让两个 footer entry 视觉同步 */
.theme-row {
  width: 100%;
  min-height: 36px;
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 0 10px;
  border: 1px solid transparent;
  border-radius: var(--r-3, 8px);
  background: transparent;
  color: var(--text-2);
  font-family: inherit;
  font-size: 12.5px;
  font-weight: var(--fw-medium, 500);
  text-align: left;
  cursor: pointer;
  transition: background 0.14s var(--ease, cubic-bezier(0.2, 0.8, 0.2, 1)),
              color 0.14s var(--ease, cubic-bezier(0.2, 0.8, 0.2, 1)),
              border-color 0.14s var(--ease, cubic-bezier(0.2, 0.8, 0.2, 1));
}
.theme-row:hover {
  color: var(--brand);
  background: var(--brand-soft);
  border-color: var(--brand-ring);
}
.theme-row:focus-visible {
  outline: 2px solid var(--line-focus, var(--brand-ring));
  outline-offset: 2px;
}

.theme-row-icon {
  display: grid;
  place-items: center;
  flex-shrink: 0;
  color: currentColor;
}

.theme-row-label {
  flex: 1;
  white-space: nowrap;
  color: inherit;
  display: flex;
  align-items: center;
}
/* 版本号徽标: 推到行尾, 弱化 */
.rail-version {
  margin-left: auto;
  font-size: 11px;
  font-variant-numeric: tabular-nums;
  opacity: 0.55;
  padding-left: 8px;
}

/* v3 2026-05-20 fix (code review #P2-5): 删 .accent-picker / .accent-swatch /
   .accent-custom 死 CSS 块 — template 已删 picker UI（commit f5e6c0a），
   只剩 CSS 选择器没人引用 = 死代码 55 行 */

/* 2026-05-21: 老 .theme-toggle 独立 button 已合并到 .theme-row 整 row
   可点击，删 30 行 dead CSS */

/* ─── Account row ─────────────────────────────────────── */
.account-row {
  min-height: 44px;
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 8px;
  margin-top: 4px;
  border-top: 1px solid var(--line);
  padding-top: 12px;
}

.rail-avatar {
  width: 28px;
  height: 28px;
  display: grid;
  place-items: center;
  flex-shrink: 0;
  color: var(--text-inverse);
  background: var(--brand);
  border-radius: var(--r-full, 999px);
  font-size: 12.5px;
  font-weight: var(--fw-semibold, 600);
}

.rail-user-info {
  min-width: 0;
  flex: 1;
}

.rail-user-name {
  color: var(--text);
  font-size: 12.5px;
  font-weight: var(--fw-semibold, 600);
  line-height: 1.2;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.rail-user-status {
  display: flex;
  align-items: center;
  gap: 5px;
  margin-top: 2px;
  color: var(--text-3);
  font-size: 11px;
  font-weight: var(--fw-regular, 400);
}

.rail-user-status span {
  width: 6px;
  height: 6px;
  border-radius: var(--r-full, 999px);
  background: var(--ok);
}

.account-logout {
  width: 28px;
  height: 28px;
  display: grid;
  place-items: center;
  flex-shrink: 0;
  color: var(--text-3);
  background: transparent;
  border: 1px solid var(--line);
  border-radius: var(--r-2, 6px);
  cursor: pointer;
  transition: background 0.14s var(--ease, cubic-bezier(0.2, 0.8, 0.2, 1)),
              color 0.14s var(--ease, cubic-bezier(0.2, 0.8, 0.2, 1)),
              border-color 0.14s var(--ease, cubic-bezier(0.2, 0.8, 0.2, 1));
}
.account-logout:hover {
  color: var(--danger, #ef4444);
  background: var(--danger-soft, rgba(239, 68, 68, 0.08));
  border-color: var(--danger-ring, rgba(239, 68, 68, 0.3));
}
.account-logout:focus-visible {
  outline: 2px solid var(--line-focus, var(--brand-ring));
  outline-offset: 2px;
}

/* ─── Collapsed state overrides (56px) ────────────────────── */
.rail-collapsed .rail-brand {
  justify-content: center;
  padding: 14px 8px 10px;
  min-height: 56px;
}

.rail-collapsed .rail-scroll {
  padding: 8px 6px;
  gap: 4px;
}

.rail-collapsed .rail-item {
  justify-content: center;
  padding: 0;
  width: 38px;
  height: 38px;
  min-height: 38px;
  margin: 0 auto;
  color: var(--text-3);
  border-radius: var(--r-3, 8px);
}

.rail-collapsed .rail-item:hover {
  color: var(--brand);
  background: var(--surface);
}

.rail-collapsed .rail-item.active {
  color: var(--brand);
  background: var(--brand-soft);
}

.rail-collapsed .rail-item.active::before {
  left: -6px;
  top: 8px;
  bottom: 8px;
}

.rail-collapsed .rail-item-label,
.rail-collapsed .rail-item-badge {
  display: none;
}

.rail-collapsed .rail-foot {
  padding: 8px 6px 10px;
}

.rail-collapsed .rail-collapse-btn {
  margin-bottom: 0;
  height: 38px;
  min-height: 38px;
}

/* ─── Dark theme tweaks ──────────────────────────────────── */
html[data-theme="dark"] .rail {
  background: var(--surface-2);
  border-right-color: var(--line);
}

html[data-theme="dark"] .rail-item:hover {
  background: var(--surface-3);
}

html[data-theme="dark"] .rail-item.active,
html[data-theme="dark"] .console-row:hover,
html[data-theme="dark"] .console-row.active,
html[data-theme="dark"] .tenant-option:hover,
html[data-theme="dark"] .tenant-option.active {
  background: var(--brand-soft);
}

html[data-theme="dark"] .tenant-switch {
  background: var(--surface);
}

html[data-theme="dark"] .tenant-switch:hover,
html[data-theme="dark"] .tenant-switch.open {
  background: var(--brand-soft);
}

html[data-theme="dark"] .tenant-menu {
  background: var(--surface);
}

html[data-theme="dark"] .rail-collapse-btn {
  background: transparent;
}

html[data-theme="dark"] .rail-expand-top {
  background: var(--surface);
  color: var(--text-3);
}

/* Sidebar refinement: quieter chrome, clearer hierarchy, and a stronger active state. */
.rail {
  width: 248px;
  background: #f7f9fc;
  border-right: 1px solid #e3e8f0;
}

.rail-brand {
  min-height: 72px;
  padding: 16px 16px 14px;
  gap: 11px;
  border-bottom: 1px solid #e8edf4;
}

.rail-logo {
  width: 32px;
  height: 32px;
  border-radius: 9px;
  box-shadow: 0 7px 16px rgba(31, 82, 177, 0.18);
}

.rail-title {
  font-size: 15px;
  letter-spacing: -0.02em;
}

.rail-brand-copy::after {
  content: 'AI 应用工作台';
  display: block;
  margin-top: 4px;
  color: #8a96a8;
  font-size: 10.5px;
  font-weight: 500;
  letter-spacing: 0.03em;
}

.rail-collapse-top {
  width: 28px;
  height: 28px;
  border-radius: 8px;
  color: #77859a;
}

.rail-mode-switch {
  margin: 14px 14px 10px;
  padding: 3px;
  gap: 3px;
  border: 1px solid #e1e7f0;
  border-radius: 10px;
  background: #eef2f7;
}

.rail-mode-btn {
  height: 30px;
  border-radius: 8px;
  color: #7b8799;
  font-size: 12px;
}

.rail-mode-btn.active {
  color: #1f56c7;
  background: #fff;
  box-shadow: 0 2px 7px rgba(25, 52, 96, 0.09);
}

.rail-scroll {
  gap: 3px;
  padding: 9px 12px 12px;
}

.rail-scroll::before {
  content: '工作区';
  display: block;
  padding: 4px 10px 7px;
  color: #9aa6b7;
  font-size: 10px;
  font-weight: 700;
  letter-spacing: 0.1em;
}

.rail-item {
  min-height: 40px;
  gap: 11px;
  padding: 0 11px;
  border-radius: 10px;
  color: #56657a;
  font-size: 13px;
  transition: background .16s ease, color .16s ease, transform .16s ease;
}

.rail-item:hover {
  color: #274d92;
  background: #edf3ff;
  transform: translateX(1px);
}

.rail-item.active {
  color: #1f56c7;
  background: #e9f1ff;
  font-weight: 650;
}

.rail-item.active::before {
  left: 0;
  top: 8px;
  bottom: 8px;
  width: 3px;
  border-radius: 0 4px 4px 0;
}

.rail-item-icon {
  width: 20px;
  height: 20px;
  color: #7d8ca3;
}

.rail-item.active .rail-item-icon,
.rail-item:hover .rail-item-icon {
  color: #2f65d5;
}

.rail-item-badge {
  min-width: 20px;
  height: 20px;
  background: #dce9ff;
  color: #2860ca;
}

.rail-sessions {
  margin-top: 13px;
  padding: 13px 9px 0;
  border-top: 1px solid #e7ecf3;
}

.rail-sess-cap {
  color: #97a3b4;
  font-size: 10px;
  font-weight: 700;
  letter-spacing: .1em;
}

.rail-sess-group {
  margin-top: 5px;
}

.rail-sess-item {
  min-height: 31px;
  border-radius: 8px;
  color: #68768a;
}

.rail-sess-item:hover,
.rail-sess-item.active {
  color: #2458bd;
  background: #edf3ff;
}

.rail-hub {
  margin: 5px 12px 8px;
  padding: 11px 11px 0;
  border-top: 1px solid #e5eaf2;
}

.rail-hub .rail-item-icon { color: #c88710; }

.rail-foot {
  padding: 12px 12px 14px;
  border-top: 1px solid #e3e8f0;
  background: #f4f7fb;
}

.rail-console {
  gap: 8px;
}

.rail-console-label {
  margin: 0 4px 1px;
  color: #94a0b1;
  font-size: 10px;
  letter-spacing: .1em;
}

.tenant-switch {
  min-height: 38px;
  padding: 0 11px;
  border-color: #e0e6ee;
  border-radius: 10px;
  background: #fff;
  color: #34445b;
}

.tenant-switch:hover,
.tenant-switch.open {
  border-color: #b9cdf5;
  background: #eef4ff;
  color: #2458bd;
}

.account-row {
  min-height: 48px;
  margin-top: 2px;
  padding: 10px 4px 0;
  border-top-color: #e1e7f0;
}

.rail-avatar {
  width: 30px;
  height: 30px;
  background: #285bd0;
  box-shadow: 0 3px 8px rgba(40, 91, 208, .22);
}

.rail-user-name { color: #273952; }
.rail-user-status { color: #8b98aa; }

html[data-theme="dark"] .rail {
  background: #151b25;
  border-right-color: #273243;
}

html[data-theme="dark"] .rail-brand,
html[data-theme="dark"] .rail-sessions,
html[data-theme="dark"] .rail-hub,
html[data-theme="dark"] .rail-foot,
html[data-theme="dark"] .account-row {
  border-color: #273243;
}

html[data-theme="dark"] .rail-foot { background: #121822; }
html[data-theme="dark"] .rail-scroll::before,
html[data-theme="dark"] .rail-console-label,
html[data-theme="dark"] .rail-sess-cap { color: #748198; }
html[data-theme="dark"] .tenant-switch { background: #1b2431; border-color: #2a374a; color: #d6deeb; }
html[data-theme="dark"] .rail-item { color: #a8b5c8; }

.rail-collapsed .rail-scroll::before,
.rail-collapsed .rail-brand-copy { display: none; }
.rail-collapsed .rail-brand { border-bottom: 0; }
.rail-collapsed .rail-foot { background: transparent; }

/* (deleted) html[data-theme="dark"] .accent-swatch.active — accent picker 死代码 */

/* 得小帆·共性能力 共用入口(导航与页脚之间) */
.rail-hub {
  margin: 4px 8px;
  border-top: 1px solid var(--line-1, rgba(127,127,127,.12));
  padding-top: 10px;
  color: var(--text-2, #9aa);
}
.rail-hub .rail-item-icon { color: var(--agent, #FBBF24); }
.rail-collapsed .rail-hub { margin: 4px 6px; }

/* 会话历史(单一左栏, 参考 Claude Code: 日期/应用分组 + 折叠) */
.rail-sessions { margin-top: 10px; padding: 0 8px; }
.rail-sess-toolbar { display: flex; align-items: center; justify-content: space-between; padding: 0 4px 6px; }
.rail-sess-cap { font-size: 11px; color: var(--text-3, #777); }
.rail-sess-groupby { display: inline-flex; gap: 2px; background: var(--surface-3, rgba(127,127,127,.08)); border-radius: 7px; padding: 2px; }
.rail-sess-groupby button { border: none; background: none; color: var(--text-3, #888); font-size: 11px; padding: 2px 8px; border-radius: 5px; cursor: pointer; }
.rail-sess-groupby button.on { background: var(--surface-1, rgba(127,127,127,.18)); color: var(--text, #eee); }
.rail-sess-group { margin-bottom: 6px; }
.rail-sess-label-row { display: flex; align-items: center; gap: 2px; }
.rail-sess-group-new {
  width: 22px;
  height: 22px;
  display: grid;
  place-items: center;
  flex-shrink: 0;
  border: 1px solid transparent;
  border-radius: 6px;
  background: transparent;
  color: var(--text-3, #888);
  cursor: pointer;
}
.rail-sess-group-new:hover:not(:disabled) {
  color: var(--brand);
  background: var(--brand-soft);
  border-color: var(--brand-ring);
}
.rail-sess-group-new:disabled { opacity: .5; cursor: wait; }
.rail-sess-group-new :deep(svg) { width: 13px; height: 13px; }
.rail-sess-label {
  display: flex; align-items: center; gap: 4px; flex: 1; min-width: 0;
  border: none; background: none; cursor: pointer;
  font-size: 13px; font-weight: 600; color: var(--text-2, #aaa); padding: 5px 4px;
}
.rail-sess-label:hover { color: var(--text-2, #aaa); }
.rail-sess-chev { display: inline-flex; transition: transform .12s; }
.rail-sess-chev.collapsed { transform: rotate(-90deg); }
.rail-sess-chev :deep(svg) { width: 12px; height: 12px; }
.rail-sess-glabel { flex: 1; text-align: left; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; font-weight: 600; }
.rail-sess-cnt { font-size: 10px; opacity: .7; }
.rail-sess-item {
  display: flex; align-items: center; gap: 6px;
  padding: 6px 8px; border-radius: 7px; cursor: pointer;
  font-size: 12.5px; color: var(--text-2, #9aa);
}
.rail-sess-item:hover { background: var(--surface-3, rgba(127,127,127,.08)); color: var(--text, #eee); }
.rail-sess-item.active { background: var(--surface-3, rgba(127,127,127,.14)); color: var(--text, #eee); }
.rail-sess-title { flex: 1; min-width: 0; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.rail-sess-del { opacity: 0; border: none; background: none; color: var(--text-3, #888); font-size: 15px; line-height: 1; cursor: pointer; padding: 0 2px; }
.rail-sess-item:hover .rail-sess-del { opacity: .7; }
.rail-sess-del:hover { opacity: 1 !important; color: #d9685e; }
.rail-sess-empty { font-size: 12px; color: var(--text-3, #777); padding: 8px; }

/* 头像点开的菜单(收起页脚, 参考 Claude) */
.rail-user-menu {
  border: 1px solid var(--line-2, #333); border-radius: 10px;
  background: var(--surface-1, var(--surface, #161616)); padding: 8px; margin-bottom: 8px;
}
.user-menu-tenant {
  padding: 2px 2px 8px;
  margin-bottom: 6px;
  border-bottom: 1px solid var(--line);
}
.user-menu-tenant-label {
  margin: 0 8px 5px;
  color: var(--text-3);
  font-size: 10px;
  font-weight: 700;
  letter-spacing: .08em;
  text-transform: uppercase;
}
.settings-entry-row { margin-top: 2px; }
.account-toggle {
  display: flex; align-items: center; gap: 10px; width: 100%;
  border: 1px solid transparent; background: none; cursor: pointer;
  padding: 6px; border-radius: 10px; text-align: left;
}
.account-toggle:hover, .account-toggle.open { background: var(--surface-3, rgba(127,127,127,.08)); }
.account-chev { margin-left: auto; display: inline-flex; transition: transform .12s; color: var(--text-3, #888); }
.account-chev :deep(svg) { width: 14px; height: 14px; }
.account-chev.open { transform: rotate(180deg); }
.logout-row { width: 100%; }
.logout-row:hover { color: #d9685e; }

/* Final visual pass (kept at the end so it wins over legacy compatibility rules). */
.rail { width: 232px; background: #f7f9fc; border-right-color: #e3e8f0; }
.rail-brand { min-height: 58px; padding: 11px 12px; border-bottom: 1px solid #e8edf4; }
.rail-logo { width: 30px; height: 30px; border-radius: 8px; }
.rail-brand-copy::after { content: 'AI 应用工作台'; display: block; margin-top: 2px; color: #8a96a8; font-size: 10px; font-weight: 500; letter-spacing: .03em; }
.rail-mode-switch { margin: 8px 10px 6px; padding: 3px; gap: 3px; border-color: #e1e7f0; border-radius: 9px; background: #eef2f7; }
.rail-mode-btn { height: 28px; border-radius: 7px; }
.rail-mode-btn.active { color: #1f56c7; background: #fff; box-shadow: 0 2px 7px rgba(25,52,96,.09); }
.rail-scroll { gap: 2px; padding: 5px 10px 0; overflow: hidden; }
.rail-scroll::before { content: '工作区'; display: block; flex: 0 0 auto; padding: 3px 9px 5px; color: #9aa6b7; font-size: 10px; font-weight: 700; letter-spacing: .08em; }
.rail-item { flex: 0 0 auto; min-height: 36px; gap: 10px; padding: 0 10px; border-radius: 8px; color: #56657a; font-size: 13px; transition: background .16s ease, color .16s ease, transform .16s ease; }
.rail-item:hover { color: #274d92; background: #edf3ff; transform: translateX(1px); }
.rail-item.active { color: #1f56c7; background: #e9f1ff; font-weight: 650; }
.rail-item.active::before { left: 0; top: 7px; bottom: 7px; width: 3px; border-radius: 0 4px 4px 0; }
.rail-item-icon { width: 18px; height: 18px; color: #7d8ca3; }
.rail-item.active .rail-item-icon, .rail-item:hover .rail-item-icon { color: #2f65d5; }
.rail-item-badge { min-width: 20px; height: 20px; background: #dce9ff; color: #2860ca; }
.rail-sessions { flex: 1 1 0; min-height: 0; display: flex; flex-direction: column; margin-top: 7px; padding: 9px 2px 0; overflow: hidden; border-top: 1px solid #e7ecf3; }
.rail-sessions.rail-system-assistant-sessions { overflow: hidden; }
.rail-sessions.rail-system-assistant-sessions :deep(.sas-sections) { flex: 1 1 auto; min-height: 0; }
.rail-sess-toolbar { flex: 0 0 auto; min-height: 28px; padding: 0 6px 5px; }
.rail-sess-cap { color: #7f8b9d; font-size: 10.5px; font-weight: 700; letter-spacing: .06em; }
.rail-sess-new { width: 26px; height: 26px; display: grid; place-items: center; padding: 0; color: #637188; background: transparent; border: 1px solid transparent; border-radius: 7px; cursor: pointer; }
.rail-sess-new:hover { color: #1f56c7; background: #e9f1ff; border-color: #d4e2fb; }
.rail-sess-new:focus-visible { outline: 2px solid var(--line-focus, var(--brand-ring)); outline-offset: 1px; }
.rail-sess-new :deep(svg) { width: 15px; height: 15px; }
.rail-sess-list { flex: 1 1 auto; min-height: 0; overflow-y: auto; overscroll-behavior: contain; padding: 0 2px 8px 0; scrollbar-width: thin; scrollbar-color: #cfd7e3 transparent; }
.rail-sess-list::-webkit-scrollbar { width: 5px; }
.rail-sess-list::-webkit-scrollbar-thumb { background: #cfd7e3; border-radius: 999px; }
.rail-sess-group { margin: 0 0 5px; }
.rail-sess-label { min-height: 28px; padding: 4px 5px; color: #68768a; font-size: 12px; }
.rail-sess-cnt { min-width: 18px; text-align: right; }
.rail-sess-locations, .rail-sess-location { flex: 0 0 auto; color: var(--text-3, #7f8b9d); font-size: 10px; font-weight: 500; }
.rail-sess-location-open { flex: 0 0 auto; border: 0; border-radius: 5px; padding: 3px 5px; color: var(--brand); background: var(--brand-soft); font: inherit; font-size: 10px; cursor: pointer; }
.rail-sess-location-open:hover { background: var(--surface-3, rgba(127,127,127,.12)); }
.rail-sess-item { position: relative; min-height: 30px; padding: 4px 5px 4px 8px; border-radius: 7px; color: #68768a; }
.rail-sess-state { width: 5px; height: 5px; flex: 0 0 auto; border-radius: 50%; background: #c2cad6; }
.rail-sess-state.running { background: #2f65d5; box-shadow: 0 0 0 3px rgba(47, 101, 213, .12); animation: rail-session-pulse 1.6s ease-in-out infinite; }
.rail-sess-item:hover { color: #2458bd; background: #edf3ff; }
.rail-sess-item.active { color: #1f56c7; background: #dceaff; box-shadow: inset 3px 0 0 #2f65d5; font-weight: 600; }
.rail-sess-item.active .rail-sess-state { background: #2f65d5; }
.rail-sess-item:focus-visible { outline: 2px solid #7ea5ee; outline-offset: -1px; }
.rail-sess-manage { position: relative; flex: 0 0 auto; }
.rail-sess-more,
.rail-sess-del { width: 22px; height: 22px; display: grid; place-items: center; flex: 0 0 auto; padding: 0; border-radius: 6px; }
.rail-sess-more { opacity: 0; color: #758298; background: transparent; border: 0; cursor: pointer; }
.rail-sess-item:hover .rail-sess-more,
.rail-sess-item.active .rail-sess-more,
.rail-sess-more[aria-expanded="true"] { opacity: 1; }
.rail-sess-more:hover { color: #1f56c7; background: #fff; }
.rail-sess-more :deep(svg),
.rail-sess-del :deep(svg) { width: 13px; height: 13px; }
.rail-sess-del:hover { background: #fff; }
.rail-sess-menu { position: absolute; right: 0; top: 26px; z-index: 30; width: 112px; padding: 4px; border: 1px solid #dfe5ee; border-radius: 8px; background: #fff; box-shadow: 0 8px 24px rgba(28, 43, 68, .14); }
.rail-sess-menu button { width: 100%; min-height: 30px; display: flex; align-items: center; gap: 8px; padding: 0 8px; color: #46556b; background: transparent; border: 0; border-radius: 6px; font: inherit; font-size: 12px; text-align: left; cursor: pointer; }
.rail-sess-menu button:hover { color: #1f56c7; background: #edf3ff; }
.rail-sess-menu button.danger { color: #bb3f3f; }
.rail-sess-menu button.danger:hover { color: #a82f2f; background: #fff0f0; }
.rail-sess-menu button :deep(svg) { width: 14px; height: 14px; }
.rail-sess-empty { padding: 18px 8px; text-align: center; }
.rail-hub { min-height: 36px; margin: 5px 10px 6px; padding: 8px 10px 0; border-top: 1px solid #e5eaf2; }
.rail-hub .rail-item-icon { color: #c88710; }
.rail-foot { padding: 9px 10px 10px; border-top: 1px solid #e3e8f0; background: #f4f7fb; }
.rail-console { gap: 6px; }
.rail-console-label { margin: 0 4px 1px; color: #94a0b1; font-size: 10px; letter-spacing: .1em; }
.tenant-switch { min-height: 34px; padding: 0 10px; border-color: #e0e6ee; border-radius: 8px; background: #fff; color: #34445b; }
.tenant-switch:hover, .tenant-switch.open { border-color: #b9cdf5; background: #eef4ff; color: #2458bd; }
.account-row { min-height: 42px; margin-top: 1px; padding: 8px 4px 0; border-top-color: #e1e7f0; }
.rail-avatar { width: 28px; height: 28px; background: #285bd0; box-shadow: 0 3px 8px rgba(40,91,208,.22); }
.rail-user-name { color: #273952; }
.rail-user-status { color: #8b98aa; }
.rail-collapsed .rail-scroll::before, .rail-collapsed .rail-brand-copy { display: none; }
.rail-collapsed .rail-brand { border-bottom: 0; }
.rail-collapsed .rail-foot { background: transparent; }
html[data-theme="dark"] .rail { background: #151b25; border-right-color: #273243; }
html[data-theme="dark"] .rail-brand, html[data-theme="dark"] .rail-sessions, html[data-theme="dark"] .rail-hub, html[data-theme="dark"] .rail-foot, html[data-theme="dark"] .account-row { border-color: #273243; }
html[data-theme="dark"] .rail-foot { background: #121822; }
html[data-theme="dark"] .rail-scroll::before, html[data-theme="dark"] .rail-console-label, html[data-theme="dark"] .rail-sess-cap { color: #748198; }
html[data-theme="dark"] .tenant-switch { background: #1b2431; border-color: #2a374a; color: #d6deeb; }
html[data-theme="dark"] .rail-item { color: #a8b5c8; }
html[data-theme="dark"] .rail-sess-new { color: #94a3b8; }
html[data-theme="dark"] .rail-sess-new:hover { color: #8fb4ff; background: #202d42; border-color: #334763; }
html[data-theme="dark"] .rail-sess-list { scrollbar-color: #3b485a transparent; }
html[data-theme="dark"] .rail-sess-list::-webkit-scrollbar-thumb { background: #3b485a; }
html[data-theme="dark"] .rail-sess-label,
html[data-theme="dark"] .rail-sess-item { color: #9eacc0; }
html[data-theme="dark"] .rail-sess-state { background: #526177; }
html[data-theme="dark"] .rail-sess-item:hover { color: #cbd8eb; background: #1d2838; }
html[data-theme="dark"] .rail-sess-item.active { color: #d5e4ff; background: #283b5c; box-shadow: inset 3px 0 0 #7da5f8; }
html[data-theme="dark"] .rail-sess-item.active .rail-sess-state,
html[data-theme="dark"] .rail-sess-state.running { background: #7da5f8; box-shadow: 0 0 0 3px rgba(125, 165, 248, .14); }
html[data-theme="dark"] .rail-sess-more { color: #94a3b8; }
html[data-theme="dark"] .rail-sess-more:hover { color: #a9c5ff; background: #151b25; }
html[data-theme="dark"] .rail-sess-menu { background: #1b2431; border-color: #334155; box-shadow: 0 10px 28px rgba(0, 0, 0, .32); }
html[data-theme="dark"] .rail-sess-menu button { color: #c2cede; }
html[data-theme="dark"] .rail-sess-menu button:hover { color: #a9c5ff; background: #26344a; }
html[data-theme="dark"] .rail-sess-menu button.danger { color: #f09a9a; }
html[data-theme="dark"] .rail-sess-menu button.danger:hover { color: #ffb0b0; background: #3a2428; }
html[data-theme="dark"] .rail-sess-del:hover { background: #151b25; }

@keyframes rail-session-pulse {
  0%, 100% { opacity: .65; }
  50% { opacity: 1; }
}
</style>
