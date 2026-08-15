import { describe, expect, it } from 'vitest'
import railSidebarSource from './RailSidebar.vue?raw'
import { railTenantHome } from './RailSidebar.vue'
import { groupCodeRailHistoryByApplication } from './codeRailHistory'
import type { CodeRailHistoryResponse } from '@/api/codeRuntime'

type RailSidebarModule = typeof import('./RailSidebar.vue') & {
  createLatestRailNavigationIntent?: () => {
    begin: () => number
    isCurrent: (intent: number) => boolean
  }
}

describe('RailSidebar brand mark', () => {
  it('uses the Ruijing whale mark in the rail logo', () => {
    expect(railSidebarSource).toContain('ruijing-whale-mark.svg')
    expect(railSidebarSource).toContain('rail-logo-mark')
    expect(railSidebarSource).not.toContain('<rect x="3" y="3" width="8" height="8"')
    expect(railSidebarSource).not.toContain('AI · 低代码')
  })
})

describe('RailSidebar product availability', () => {
  it('uses public product availability for Web modes while preserving the desktop discovery scope', () => {
    expect(railSidebarSource).toContain("from '@/stores/productAvailability'")
    expect(railSidebarSource).toContain('enabledProductModes(productAvailability.value)')
    expect(railSidebarSource).toContain('loadProductAvailability()')
    expect(railSidebarSource).toContain('visibleModesForDesktopScope(desktopWorkspaceEntryScope.value)')
    expect(railSidebarSource).not.toContain(': MODE_ORDER')
  })

  it('sends the rail logo to the configured product home', () => {
    expect(railSidebarSource).toContain('go(defaultProductHome(productAvailability))')
  })
})

// SP2b(2026-06-25): rail 会话统一单一来源 aiChatApi; Code 模式复用同一
// 会话分组，只是按 mode=code 拉取并路由到 /code。
describe('RailSidebar unified session source (SP2b)', () => {
  it('lets only the latest async rail click commit navigation', async () => {
    const module = await import('./RailSidebar.vue') as RailSidebarModule
    expect(module.createLatestRailNavigationIntent).toBeTypeOf('function')
    const navigation = module.createLatestRailNavigationIntent!()
    const committed: string[] = []
    let releaseFirst!: () => void
    const firstActivation = new Promise<void>((resolve) => { releaseFirst = resolve })

    const firstIntent = navigation.begin()
    const first = firstActivation.then(() => {
      if (navigation.isCurrent(firstIntent)) committed.push('first')
    })
    const secondIntent = navigation.begin()
    if (navigation.isCurrent(secondIntent)) committed.push('second')
    releaseFirst()
    await first

    expect(committed).toEqual(['second'])
  })

  it('keeps same-name logical applications separate while grouping local and remote locations', () => {
    const history: CodeRailHistoryResponse = {
      apps: [
        {
          shell_session_id: 'local-shell',
          external_application_id: 'local-crm',
          logical_application_id: 'crm-primary',
          execution_location: 'local',
          app_name: 'CRM',
          workspace_path: '/home/user/workspaces/customer-crm',
          sessions: [],
        },
        {
          shell_session_id: 'remote-shell',
          external_application_id: 'remote-crm',
          logical_application_id: 'crm-primary',
          execution_location: 'remote',
          app_name: 'CRM',
          environment_name: '开发环境',
          sessions: [],
        },
        {
          shell_session_id: 'other-shell',
          external_application_id: 'other-crm',
          logical_application_id: 'crm-secondary',
          execution_location: 'remote',
          app_name: 'CRM',
          environment_name: '测试环境',
          sessions: [],
        },
      ],
    }

    const groups = groupCodeRailHistoryByApplication(history)
    const primary = groups.find(group => group.logicalApplicationId === 'crm-primary')
    const secondary = groups.find(group => group.logicalApplicationId === 'crm-secondary')

    expect(groups).toHaveLength(2)
    expect(primary?.availableLocations).toEqual(['local', 'remote'])
    expect(primary?.items.map(session => session.locationSummary)).toEqual([
      '本机 · customer-crm',
      '远程 · 开发环境',
    ])
    expect(primary?.locationSessions.local?.shellSessionId).toBe('local-shell')
    expect(primary?.locationSessions.remote?.shellSessionId).toBe('remote-shell')
    expect(secondary?.availableLocations).toEqual(['remote'])
    expect(secondary?.locationSessions.local).toBeUndefined()
  })

  it('groups Code history by logical application identity and renders fixed location labels', () => {
    expect(railSidebarSource).toContain("from './codeRailHistory'")
    expect(railSidebarSource).toContain('groupCodeRailHistoryByApplication')
    expect(railSidebarSource).toContain('g.availableLocations')
    expect(railSidebarSource).toContain('s.locationSummary')
    expect(railSidebarSource).toContain('g.localShellSessionId')
    expect(railSidebarSource).toContain('g.remoteShellSessionId')
  })

  it('uses a single aiChatApi session source (no codingApi)', () => {
    expect(railSidebarSource).toContain("from '@/api/aiChat'")
    expect(railSidebarSource).toContain('aiChatApi.listSessions(')
    expect(railSidebarSource).toContain('codeRuntimeApi.listRailHistory')
    expect(railSidebarSource).toContain('codeRailHistorySessions')
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
    expect(railSidebarSource).toContain('groupCodeRailHistoryByApplication')
    expect(railSidebarSource).toContain('railSessionTarget(')
    expect(railSidebarSource).toContain('nextAgentQuery')
  })

  it('delegates Code runtime activation to the conversation page after routing', () => {
    const openSessionSource = railSidebarSource.slice(
      railSidebarSource.indexOf('async function openSession('),
      railSidebarSource.indexOf('function sessionGroupKey('),
    )

    expect(openSessionSource).not.toContain('codeRuntimeApi.activateAgentSession')
    expect(openSessionSource).toContain('router.push(railSessionTarget(')
  })

  it('exposes Code new runtime conversation actions on application groups', () => {
    expect(railSidebarSource).toContain('createCodeAgentSession')
    expect(railSidebarSource).toContain('codeRuntimeApi.createAgentSession')
    expect(railSidebarSource).toContain('rail-sess-group-new')
    expect(railSidebarSource).toContain('g.standardShellSessionId')
    expect(railSidebarSource).toContain("createCodeAgentSession(g.standardShellSessionId, g)")
    expect(railSidebarSource).toContain("effectiveGroupBy === 'app'")
    expect(railSidebarSource).not.toContain('class="rail-sess-new"')
    expect(railSidebarSource).toContain(
      'nextAgentQuery(route.query, result.runtime_session_id)',
    )
  })

  it('keeps initialization shells visible but never selects them for a normal new conversation', () => {
    const history: CodeRailHistoryResponse = {
      apps: [
        {
          shell_session_id: 'standard-shell',
          external_application_id: 'local-crm',
          logical_application_id: 'crm',
          execution_location: 'local',
          session_purpose: 'standard',
          app_name: 'CRM',
          sessions: [],
        },
        {
          shell_session_id: 'initialization-shell',
          external_application_id: 'local-crm',
          logical_application_id: 'crm',
          execution_location: 'local',
          session_purpose: 'project_initialization',
          app_name: 'CRM',
          sessions: [],
        },
      ],
    }

    const [group] = groupCodeRailHistoryByApplication(history)

    expect(group.items.map(item => item.sessionPurpose)).toEqual([
      'standard',
      'project_initialization',
    ])
    expect(group.standardShellSessionId).toBe('standard-shell')
    expect(group.locationSessions.local?.shellSessionId).toBe('standard-shell')
  })

  it('exposes Builder new conversations on application groups', () => {
    expect(railSidebarSource).toContain('createBuilderSession')
    expect(railSidebarSource).toContain('aiChatApi.createSession({ app_id: appId, mode: \'chat\' })')
    expect(railSidebarSource).toContain("currentMode === 'builder' && g.appId")
    expect(railSidebarSource).toContain("query: { ...route.query, app_id: String(appId) }")
  })

  it('keeps the application-scoped sessions returned by Code rail history', () => {
    expect(railSidebarSource).toContain('codeRuntimeApi.listRailHistory()')
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

  it('keeps organization switching inside the unified account menu', () => {
    const tenantSwitcher = railSidebarSource.indexOf('<div class="user-menu-tenant" @click.stop>')
    const userMenu = railSidebarSource.indexOf('<div v-show="userMenuOpen" class="rail-user-menu">')

    expect(tenantSwitcher).toBeGreaterThan(-1)
    expect(userMenu).toBeGreaterThan(-1)
    expect(tenantSwitcher).toBeGreaterThan(userMenu)
  })

  it('listens for Code rail refresh events from the app list', () => {
    expect(railSidebarSource).toContain("window.addEventListener('code-rail-refresh'")
    expect(railSidebarSource).toContain("window.removeEventListener('code-rail-refresh'")
    expect(railSidebarSource).toContain('refreshCodeRail')
  })
})

describe('RailSidebar tenant navigation', () => {
  it('maps the visible tenant id to the public id for atomic tenant navigation', () => {
    expect(railSidebarSource).toContain(
      '@click="selectTenant(String(tenant.tenant_id))"',
    )
    expect(railSidebarSource).toContain(
      'const targetPublicId = tenant.tenant_public_id',
    )
    expect(railSidebarSource).toContain('await user.switchTenantContext(')
  })

  it('keeps the Code discovery home when desktop product configuration enables both products', () => {
    expect(railTenantHome(true, 'code', { builder: true, code: true })).toBe('/code/apps')
  })

  it('uses the configured Web product home outside desktop discovery', () => {
    expect(railTenantHome(false, 'code', { builder: false, code: true })).toBe('/code/apps')
    expect(railSidebarSource).toContain('user.advanceTenantNavigationEpoch()')
    expect(railSidebarSource).toContain('user.switchTenantContext(')
    expect(railSidebarSource).toContain('withTenantId(')
  })

  it('leaves navigation replacement to the selected switch path', () => {
    expect(railSidebarSource).not.toContain('await user.switchTenant(value)')
    expect(railSidebarSource).not.toContain("router.push('/')")
  })
})

describe('RailSidebar desktop settings', () => {
  it('uses one settings entry and removes duplicate top-level capability entries', () => {
    expect(railSidebarSource).toContain("@click=\"go(isDesktop ? '/desktop-settings' : '/settings?section=ai')\"")
    expect(railSidebarSource).toContain('<span>设置</span>')
    expect(railSidebarSource).not.toContain('能力中心</span>')
    expect(railSidebarSource).not.toContain('<span>平台管理</span>')
    expect(railSidebarSource).not.toContain('桌面设置</span>')
    expect(railSidebarSource).not.toContain("@click=\"theme.toggle()\"")
  })
})
