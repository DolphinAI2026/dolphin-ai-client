import { describe, expect, it } from 'vitest'
import railSidebarSource from './RailSidebar.vue?raw'

describe('RailSidebar brand mark', () => {
  it('uses the Ruijing whale mark in the rail logo', () => {
    expect(railSidebarSource).toContain('ruijing-whale-mark.svg')
    expect(railSidebarSource).toContain('rail-logo-mark')
    expect(railSidebarSource).not.toContain('<rect x="3" y="3" width="8" height="8"')
    expect(railSidebarSource).not.toContain('AI · 低代码')
  })
})

// SP2b(2026-06-25): rail 会话统一单一来源 aiChatApi; Code 模式复用同一
// 会话分组，只是按 mode=code 拉取并路由到 /code。
describe('RailSidebar unified session source (SP2b)', () => {
  it('uses a single aiChatApi session source (no codingApi)', () => {
    expect(railSidebarSource).toContain("from '@/api/aiChat'")
    expect(railSidebarSource).toContain('aiChatApi.listSessions(')
    expect(railSidebarSource).toContain('codeRuntimeApi.listRailHistory')
    expect(railSidebarSource).toContain('normalizeCodeRailHistory')
    expect(railSidebarSource).toContain("sessions.filter(s => s.mode !== 'code')")
    expect(railSidebarSource).not.toContain("from '@/api/coding'")
    expect(railSidebarSource).not.toContain('codingApi.getConversations()')
  })

  it('derives the active shell from the route before choosing a rail data source', () => {
    expect(railSidebarSource).toContain('isCodeRoutePath(route.path)')
    expect(railSidebarSource).toContain("isCodeRoutePath(route.path) ? 'code' : 'builder'")
  })

  it('delegates normalization + routing to the railSessions composable', () => {
    expect(railSidebarSource).toContain("from '@/composables/railSessions'")
    expect(railSidebarSource).toContain('normalizeAiSessions')
    expect(railSidebarSource).toContain('normalizeCodeRailHistory')
    expect(railSidebarSource).toContain('railSessionTarget(')
    expect(railSidebarSource).toContain('nextAgentQuery')
  })

  it('activates Code runtime history before opening the shell route', () => {
    expect(railSidebarSource).toContain('codeRuntimeApi.activateAgentSession')
    expect(railSidebarSource).toContain('session.runtimeSessionId')
    expect(railSidebarSource).toContain('session.shellSessionId')
  })

  it('exposes Code new runtime conversation actions on application groups', () => {
    expect(railSidebarSource).toContain('createCodeAgentSession')
    expect(railSidebarSource).toContain('codeRuntimeApi.createAgentSession')
    expect(railSidebarSource).toContain('rail-sess-group-new')
    expect(railSidebarSource).toContain('g.shellSessionId')
    expect(railSidebarSource).toContain("createCodeAgentSession(g.shellSessionId)")
    expect(railSidebarSource).toContain("effectiveGroupBy === 'app'")
    expect(railSidebarSource).not.toContain('class="rail-sess-new"')
    expect(railSidebarSource).toContain(
      'nextAgentQuery(route.query, result.runtime_session_id)',
    )
  })

  it('exposes Builder new conversations on application groups', () => {
    expect(railSidebarSource).toContain('createBuilderSession')
    expect(railSidebarSource).toContain('aiChatApi.createSession({ app_id: appId, mode: \'chat\' })')
    expect(railSidebarSource).toContain("currentMode === 'builder' && g.appId")
    expect(railSidebarSource).toContain("query: { ...route.query, app_id: String(appId) }")
  })

  it('keeps the application-scoped sessions returned by Code rail history', () => {
    expect(railSidebarSource).toContain('codeRuntimeApi.listRailHistory(codeApplicationSource.value)')
    expect(railSidebarSource).toContain('codeRailHistory.value = history')
    expect(railSidebarSource).not.toContain('hydrateCodeRailHistory')
    expect(railSidebarSource).not.toContain('codeRuntimeApi.listAgentSessions')
  })

  it('keeps desktop Code applications and history on the selected local or remote source', () => {
    expect(railSidebarSource).toContain('source: codeApplicationSource.value')
    expect(railSidebarSource).toContain('CODE_APPLICATION_SOURCE_CHANGED_EVENT')
  })

  it('shows a newly created Code conversation before history refresh finishes', () => {
    expect(railSidebarSource).toContain('upsertOptimisticCodeAgentSession')
    expect(railSidebarSource).toContain('sessions: [optimistic, ...sessions]')
    expect(railSidebarSource).toContain('void loadRailSessions()')
  })

  it('shows the recent-session list in every mode', () => {
    expect(railSidebarSource).not.toContain("currentMode.value !== 'code'")
  })

  it('defaults Code sessions to application grouping', () => {
    expect(railSidebarSource).toContain("mode === 'builder' || mode === 'code' ? 'app' : 'date'")
    expect(railSidebarSource).toContain('rail-sess-groupby-code')
  })

  it('uses the shared tenant-scoped Code application store', () => {
    expect(railSidebarSource).toContain("from '@/stores/codeApplications'")
    expect(railSidebarSource).toContain('codeApplications.load')
    expect(railSidebarSource).toContain('tenantId: user.tenantId')
    expect(railSidebarSource).not.toContain('codeRuntimeApi.listApplications')
  })

  it('starts independent rail loads in parallel', () => {
    expect(railSidebarSource).toContain('Promise.allSettled(startupTasks)')
    expect(railSidebarSource).toContain('loadRailApps()')
    expect(railSidebarSource).toContain('loadRailSessions()')
  })

  it('uses the remote tenant selection list in the desktop package', () => {
    expect(railSidebarSource).toContain('const tenantOptions = computed(() => user.availableTenants || [])')
    expect(railSidebarSource).toContain('startupTasks.push(user.fetchAvailableTenants())')
    expect(railSidebarSource).toContain('control_plane_tenant_name')
    expect(railSidebarSource).toContain('@click="selectTenant(String(tenant.tenant_id))"')
  })

  it('keeps the desktop organization switcher directly reachable in the rail footer', () => {
    const tenantSwitcher = railSidebarSource.indexOf('<div class="tenant-switch-wrap" @click.stop>')
    const userMenu = railSidebarSource.indexOf('<div v-show="userMenuOpen" class="rail-user-menu">')

    expect(tenantSwitcher).toBeGreaterThan(-1)
    expect(userMenu).toBeGreaterThan(-1)
    expect(tenantSwitcher).toBeLessThan(userMenu)
  })

  it('listens for Code rail refresh events from the app list', () => {
    expect(railSidebarSource).toContain("window.addEventListener('code-rail-refresh'")
    expect(railSidebarSource).toContain("window.removeEventListener('code-rail-refresh'")
    expect(railSidebarSource).toContain('refreshCodeRail')
  })
})

describe('RailSidebar tenant navigation', () => {
  it('maps the visible tenant id to the public id only for web navigation', () => {
    expect(railSidebarSource).toContain(
      '@click="selectTenant(String(tenant.tenant_id))"',
    )
    expect(railSidebarSource).toContain(
      'const targetPublicId = tenant.tenant_public_id',
    )
    expect(railSidebarSource).toContain(
      'if (__DESKTOP__) {',
    )
    expect(railSidebarSource).toContain('await user.switchTenant(value)')
  })

  it('enters the current mode home through the shared epoch switch contract', () => {
    expect(railSidebarSource).toContain('MODE_META[currentMode.value].home')
    expect(railSidebarSource).toContain('user.advanceTenantNavigationEpoch()')
    expect(railSidebarSource).toContain('user.switchTenantContext(')
    expect(railSidebarSource).toContain('withTenantId(')
  })

  it('leaves navigation replacement to the selected switch path', () => {
    expect(railSidebarSource).toContain('if (__DESKTOP__) {')
    expect(railSidebarSource).toContain('await user.switchTenant(value)')
    expect(railSidebarSource).not.toContain("router.push('/')")
  })
})

describe('RailSidebar desktop settings', () => {
  it('桌面用户菜单提供桌面设置且 Web 不显示', () => {
    const settingsClick = railSidebarSource.indexOf('@click="go(desktopSettingsItem.path)"')
    const settingsButtonStart = railSidebarSource.lastIndexOf('<button', settingsClick)
    const settingsButtonEnd = railSidebarSource.indexOf('</button>', settingsClick)
    const settingsButtonSource = railSidebarSource.slice(settingsButtonStart, settingsButtonEnd)
    const themeToggle = railSidebarSource.indexOf('@click="theme.toggle()"')

    expect(railSidebarSource).toContain("path: '/desktop-settings'")
    expect(settingsClick).toBeGreaterThan(-1)
    expect(settingsButtonSource).toContain('v-if="isDesktop"')
    expect(settingsButtonSource).toContain("renderIcon('settings')")
    expect(settingsButtonSource).toContain('桌面设置')
    expect(settingsClick).toBeLessThan(themeToggle)
  })
})
