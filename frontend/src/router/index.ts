import {
  createRouter,
  createWebHistory,
  type RouteLocationRaw,
  type RouteRecordRaw,
  type Router,
} from 'vue-router'
import { useUserStore } from '@/stores/user'
import { usePreviewStore } from '@/stores/preview'
import { modeForRoutePath, useModeStore } from '@/stores/mode'
import request, {
  getAuthSessionState,
  isAuthSessionAlignmentPending,
} from '@/utils/request'
import { getCachedDesktopState, getDesktopState } from '@/utils/desktop'
import {
  loadDesktopBootstrapDecision,
  resolveDesktopRedirect,
  resolveDesktopWorkspaceRedirect,
} from './desktopGuard'
import { normalizeTenantPublicId, resolveTenantUrl } from './tenantUrlGuard'
import { resolveExternalLoginRedirect, safeLoginRedirectPath } from './loginRedirect'

const desktopRoutes: RouteRecordRaw[] = __DESKTOP__ ? [
    {
      path: '/desktop-setup',
      name: 'DesktopSetup',
      component: () => import('@/views/DesktopSetupWizard.vue'),
      meta: { tenantContext: 'none' }
    },
    {
      path: '/desktop-settings',
      name: 'DesktopSettings',
      component: () => import('@/views/DesktopSettings.vue'),
      meta: { requiresAuth: true, tenantContext: 'none' },
    },
    {
      path: '/desktop-unavailable',
      name: 'DesktopUnavailable',
      component: () => import('@/views/DesktopUnavailable.vue'),
      meta: { requiresAuth: true, tenantContext: 'none' }
    },
] : []

export const routes: RouteRecordRaw[] = [
    { path: '/login', name: 'Login',
      component: () => import('@/views/Login.vue') },
    {
      path: '/tenant-select',
      name: 'TenantSelect',
      component: () => import('@/views/TenantSelect.vue')
    },
    {
      path: '/',
      name: 'Home',
      // 首页 = AI Builder 融合页(新建欢迎草稿 + 对话流), 与 /ai-chat 同组件。
      // (2026-06-21 撤回 ModeHome —— 用已有的新会话欢迎页, 不重复造。)
      component: () => import('@/views/AIChatPage.vue'),
      meta: { requiresAuth: true, tenantContext: 'required', navExpanded: true }
    },
    {
      path: '/chat/:id?',
      name: 'Chat',
      component: () => import('@/views/ChatPage.vue'),
      meta: { requiresAuth: true, tenantContext: 'required' },
      beforeEnter: (to, _from, next) => {
        // ChatPage 必须绑定到某个应用才有意义
        // 没 app_id / conversation_id / deploy_app_id 也没 pending 上传素材的话直接重定向应用列表
        // from=upload: Landing 传 md 创建新应用流程，靠 store.pendingFile
        // from=aichat: AIChatPage 把生成的设计文档送过来，靠 store.pendingMarkdown
        const hasAppCtx = to.query.app_id
          || to.params.id
          || to.query.deploy_app_id
          || to.query.conversation_id
          || to.query.from === 'upload'
          || to.query.from === 'aichat'
        if (!hasAppCtx) {
          next({ path: '/apps' })
        } else {
          next()
        }
      }
    },
    {
      path: '/ai-chat/:id?',
      name: 'AIChat',
      component: () => import('@/views/AIChatPage.vue'),
      meta: { requiresAuth: true, tenantContext: 'required' }
    },
    {
      path: '/code',
      component: () => import('@/views/CodeShellLayout.vue'),
      // Code uses the per-tab Control Plane ticket (`cp_tid`), not the
      // Builder/aPaaS local tenant URL contract.
      meta: { requiresAuth: true, tenantContext: 'none' },
      children: [
        {
          path: '',
          redirect: { name: 'CodeApps' },
        },
        {
          path: 'apps',
          name: 'CodeApps',
          component: () => import('@/views/Apps.vue'),
        },
        {
          path: 'new',
          name: 'CodeNewApplication',
          component: () => import('@/views/CodeConversationPage.vue'),
        },
        {
          path: ':id',
          name: 'CodeConversation',
          component: () => import('@/views/CodeConversationPage.vue'),
        }
      ]
    },
    {
      // 数据接入 group 入口：数据库连接管理
      path: '/db-connections',
      name: 'DbConnections',
      component: () => import('@/views/DbConnectionsPage.vue'),
      meta: { requiresAuth: true, tenantContext: 'required', navExpanded: true }
    },
    {
      path: '/apps',
      name: 'Apps',
      component: () => import('@/views/Apps.vue'),
      meta: { requiresAuth: true, tenantContext: 'required' }
    },
    // /projects (v2) 已删 — Project 表无真实进度字段, 真应用页在 /project/:id (单数).
    // /agents /specs /industry /runtime /mcp(McpHub) 这几个 v2 stub 页已删 (2026-06-08 清理).
    {
      path: '/workspace-catalog',
      name: 'WorkspaceCatalog',
      component: () => import('@/views/WorkspaceCatalogPage.vue'),
      meta: { requiresAuth: true, tenantContext: 'required' }
    },
    {
      path: '/workspace/:id?',
      name: 'Workspace',
      component: () => import('@/views/workspace/WorkspaceShell.vue'),
      meta: { requiresAuth: true, tenantContext: 'required', navExpanded: true }
    },
    {
      path: '/tenant-logs',
      name: 'TenantLogs',
      component: () => import('@/views/TenantLogsPage.vue'),
      meta: { requiresAuth: true, tenantContext: 'required' }
    },
    {
      path: '/hub',
      name: 'CapabilitiesHub',
      component: () => import('@/views/CapabilitiesHubPage.vue'),
      meta: { requiresAuth: true, tenantContext: 'required', navExpanded: true }
    },
    {
      // 技能库已并入 hub;老链接 / router.push('/skills') 重定向到 hub 的技能 tab
      path: '/skills',
      name: 'Skills',
      redirect: to => ({
        path: '/hub',
        query: { ...to.query, tab: 'skills' },
        hash: to.hash,
      }),
      meta: { requiresAuth: true, tenantContext: 'required' }
    },
    {
      path: '/skills/:name/workspace',
      name: 'SkillWorkspace',
      component: () => import('@/views/SkillWorkspacePage.vue'),
      meta: { requiresAuth: true, tenantContext: 'required' }
    },
    {
      path: '/project/:id',
      name: 'ProjectOverview',
      component: () => import('@/views/ProjectOverview.vue'),
      meta: { requiresAuth: true, tenantContext: 'required' }
    },
    {
      path: '/project/:id/git',
      name: 'ProjectGitSetup',
      component: () => import('@/views/ProjectGitSetup.vue'),
      meta: { requiresAuth: true, tenantContext: 'required' }
    },
    {
      path: '/git/callback/:provider',
      name: 'GitOAuthCallback',
      component: () => import('@/views/GitOAuthCallback.vue'),
      meta: { requiresAuth: true, tenantContext: 'required' }
    },
    {
      path: '/settings',
      name: 'Settings',
      redirect: to => {
        const rawTab = Array.isArray(to.query.tab) ? to.query.tab[0] : to.query.tab
        const tab = String(rawTab || 'llm')
        if (tab === 'envs') {
          return { path: '/platform-envs', query: { ...to.query, tab: 'envs' }, hash: to.hash }
        }
        if (tab === 'assistant') {
          return { path: '/platform-envs', query: { ...to.query, tab: 'assistant' }, hash: to.hash }
        }
        if (tab === 'team' || tab === 'members') {
          return { path: '/tenant-users', query: { ...to.query }, hash: to.hash }
        }
        return { path: '/platform-envs', query: { ...to.query, tab: 'llm' }, hash: to.hash }
      },
      meta: { requiresAuth: true, tenantContext: 'required', navExpanded: true }
    },
    {
      path: '/coding',
      name: 'Coding',
      component: () => import('@/views/CodingPage.vue'),
      meta: { requiresAuth: true, tenantContext: 'required', navExpanded: true }
    },
    {
      path: '/admin/mcp',
      name: 'McpTools',
      component: () => import('@/views/McpToolsPage.vue'),
      meta: { requiresAuth: true, tenantContext: 'required', navExpanded: true }
    },
    {
      path: '/admin/agent-prompts',
      name: 'AgentPrompts',
      component: () => import('@/views/AgentPromptsPage.vue'),
      meta: { requiresAuth: true, tenantContext: 'required', requiresTenantAdmin: true, navExpanded: true }
    },
    {
      path: '/work/:appId',
      name: 'WorkspaceShell',
      redirect: to => ({
        path: '/chat',
        query: { ...to.query, app_id: String(to.params.appId) },
        hash: to.hash,
      }),
      meta: { requiresAuth: true, tenantContext: 'required' }
    },
    // M3 (2026-05-27): 删 /datasources stub — 用老 /db-connections 真页 (DbConnectionsPage)
    // 当 "数据源" nav 入口. 重定向兼容 G3 老路径.
    {
      path: '/datasources',
      redirect: '/db-connections',
      meta: { requiresAuth: true, tenantContext: 'required' }
    },
    // M1: 删 4 stub 路由 (/apis /docs /reports /models) — 产品定位不符.
    // L1: 删 /manage stub — admin-spa 已是平台管理完整入口. nav 管理直跳 /platform-admin.
    {
      path: '/platform-envs',
      name: 'PlatformEnvs',
      component: () => import('@/views/PlatformEnvs.vue'),
      meta: { requiresAuth: true, tenantContext: 'required', requiresTenantAdmin: true, navExpanded: true }
    },
    {
      path: '/platform-admin/:pathMatch(.*)*',
      name: 'PlatformAdmin',
      component: () => import('@/views/PlatformAdminEmbed.vue'),
      meta: { requiresAuth: true, tenantContext: 'none', requiresPlatformAdmin: true, navExpanded: true, desktop: 'hidden' }
    },
    {
      path: '/tenant-users',
      name: 'TenantUsers',
      component: () => import('@/views/TenantUsers.vue'),
      meta: { requiresAuth: true, tenantContext: 'required', requiresTenantAdmin: true, navExpanded: true }
    },
    {
      path: '/admin/tenants',
      name: 'PlatformTenants',
      component: () => import('@/views/PlatformTenants.vue'),
      meta: { requiresAuth: true, tenantContext: 'none', requiresPlatformAdmin: true, navExpanded: true, desktop: 'hidden' }
    },
    {
      // 知识库已并入 hub;老链接重定向到 hub 的知识 tab(hub 内按 isPlatformAdmin 过滤可见性)
      path: '/knowledge',
      name: 'knowledge-base',
      redirect: to => ({
        path: '/hub',
        query: { ...to.query, tab: 'knowledge' },
        hash: to.hash,
      }),
      meta: { requiresAuth: true, tenantContext: 'required' }
    },
    ...desktopRoutes,
    {
      path: '/generate/:id?',
      name: 'Generate',
      // 重定向到 ChatPage 并自动打开部署面板
      redirect: to => ({
        path: '/chat',
        query: { ...to.query, deploy_app_id: to.params.id as string },
        hash: to.hash,
      }),
      meta: { requiresAuth: true, tenantContext: 'required' }
    }
]

const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes,
})

function hasCommittedAuthSession(): boolean {
  const session = getAuthSessionState()
  return session.initialized && Boolean(session.token)
}

let previewStatusRestorePending = false
let previewStatusRestoreGeneration = 0
let previewStatusRestoreInFlightGeneration: number | null = null
let previewStatusRestoreFailures = 0
let previewStatusRestoreRetryAt = 0
const PREVIEW_STATUS_RETRY_DELAYS_MS = [0, 1_000, 5_000, 30_000]
let desktopBootstrapReadyForDocument = false
let userRefreshRevision: number | null = null

async function restorePreviewStatus(): Promise<boolean> {
  const previewStore = usePreviewStore()
  try {
    const data = await request.get<any, any>('/apaas/status')
    if (data) previewStore.connected = data.connected
    return true
  } catch {
    // Preview state is optional and must not block route resolution.
    return false
  }
}

export function installRouterGuards(targetRouter: Router): void {
  targetRouter.beforeEach(async (to, _from, next) => {
  if (typeof __DESKTOP__ !== 'undefined' && __DESKTOP__) {
    if (!desktopBootstrapReadyForDocument) {
      const desktopDecision = await loadDesktopBootstrapDecision(getDesktopState, to.path)
      desktopBootstrapReadyForDocument = desktopDecision.readyForDocument
      if (desktopDecision.redirect) {
        next({ path: desktopDecision.redirect, replace: true })
        return
      }
    }

    const workspaceEntryScope = getCachedDesktopState()?.config?.workspace_entry_scope
    if (workspaceEntryScope) {
      const workspaceRedirect = resolveDesktopWorkspaceRedirect(workspaceEntryScope, to.path)
      if (workspaceRedirect) {
        next({ path: workspaceRedirect, replace: true })
        return
      }
    }
  }

  const userStore = useUserStore()
  const modeStore = useModeStore()
  let hasCommittedSession = hasCommittedAuthSession()

  // 已提交 session 或 bootstrap candidate 但 user 对象为空时，尝试恢复用户信息。
  // bootstrap 5xx/network 只会保留候选，不可把它当作已登录状态。
  if (!userStore.user && (hasCommittedSession || userStore.token)) {
    try {
      await userStore.fetchUser()
      hasCommittedSession = hasCommittedAuthSession()
      if (hasCommittedSession) {
        previewStatusRestorePending = true
        previewStatusRestoreGeneration += 1
        previewStatusRestoreFailures = 0
        previewStatusRestoreRetryAt = 0
      }
    } catch {
      hasCommittedSession = hasCommittedAuthSession()
      if (to.meta.requiresAuth) {
        next({ path: '/login', query: { redirect: to.fullPath } })
        return
      }
    }
  }

  if (to.meta.requiresAuth && isAuthSessionAlignmentPending()) {
    next(false)
    return
  }

  if (to.meta.requiresAuth && !hasCommittedSession) {
    next({ path: '/login', query: { redirect: to.fullPath } })
    return
  }

  if (to.meta.requiresAuth) {
    // A tab can retain the previous Pinia user after its signed session
    // changes. Refresh once per committed session before resolving the
    // tenant URL, including the canonical `/apps` entry without tenantId.
    const session = getAuthSessionState()
    if (
      to.meta.tenantContext === 'required'
      && userStore.user
      && session.token
      && userRefreshRevision !== session.revision
    ) {
      userRefreshRevision = session.revision
      try {
        await userStore.fetchUser()
      } catch {
        // Tenant URL resolution remains fail-closed if the refresh is unavailable.
      }
    }
    const tenantResolution = await resolveTenantUrl(to, userStore, modeStore)
    if (tenantResolution !== true) {
      if (tenantResolution === false) {
        next(false)
      } else {
        next(tenantResolution as RouteLocationRaw)
      }
      return
    }
  }

  // v3 2026-05-20 fix (code review #P2-10): 权限被拒时用 replace
  // 之前 next('/') 默认 push → 浏览器历史栈多一格 /tenant-admin-page 死路径
  // → 用户点后退按钮先回到 '/' 再点又回 '/' → 后退坏
  if (to.meta.requiresTenantAdmin && !userStore.isTenantAdmin) {
    next({ path: '/', replace: true })
    return
  }

  if (to.meta.requiresPlatformAdmin && !userStore.isPlatformAdmin) {
    next({ path: '/', replace: true })
    return
  }

  if (__DESKTOP__ && hasCommittedSession) {
    // 功能边界: hidden 路由落降级页
    const red = resolveDesktopRedirect(true, (to.meta as any), to.path)
    if (red) { next({ path: red, replace: true }); return }
  }

  if (to.meta.requiresAuth) {
    const routeMode = modeForRoutePath(to.path)
    if (modeStore.mode !== routeMode) modeStore.setMode(routeMode)
  }

  if (to.path === '/login' && hasCommittedSession) {
    const externalRedirect = resolveExternalLoginRedirect(to.query.redirect)
    if (externalRedirect) {
      window.location.replace(externalRedirect)
      next(false)
      return
    }
    next(safeLoginRedirectPath(to.query.redirect) || '/')
  } else {
    next()
  }
  })

  targetRouter.afterEach((to, _from, failure) => {
    if (
      !previewStatusRestorePending
      || previewStatusRestoreInFlightGeneration === previewStatusRestoreGeneration
      || Date.now() < previewStatusRestoreRetryAt
      || failure
      || !to.meta.requiresAuth
      || to.meta.tenantContext !== 'required'
      || !hasCommittedAuthSession()
    ) {
      return
    }
    const userStore = useUserStore()
    const routeTenantPublicId = normalizeTenantPublicId(to.query.tenantId)
    const committedTenantPublicId = normalizeTenantPublicId(
      userStore.user?.tenant_public_id,
    )
    if (
      !routeTenantPublicId
      || !committedTenantPublicId
      || routeTenantPublicId !== committedTenantPublicId
    ) {
      return
    }
    const restoreGeneration = previewStatusRestoreGeneration
    previewStatusRestoreInFlightGeneration = restoreGeneration
    void restorePreviewStatus().then((restored) => {
      if (previewStatusRestoreInFlightGeneration === restoreGeneration) {
        previewStatusRestoreInFlightGeneration = null
      }
      if (previewStatusRestoreGeneration !== restoreGeneration) return
      if (restored) {
        previewStatusRestorePending = false
        previewStatusRestoreFailures = 0
        previewStatusRestoreRetryAt = 0
        return
      }
      const delayIndex = Math.min(
        previewStatusRestoreFailures,
        PREVIEW_STATUS_RETRY_DELAYS_MS.length - 1,
      )
      previewStatusRestoreFailures += 1
      previewStatusRestoreRetryAt = Date.now() + PREVIEW_STATUS_RETRY_DELAYS_MS[delayIndex]
    })
  })

// 部署后老 tab 引用旧 index.html，里面 import 的 chunk hash 已被新 build 覆盖：
// 切路由时 dynamic import 404 → 用户卡死。这里捕获该错误自动 reload 一次拿新 index.html。
// sessionStorage 标志位防止 reload 后还失败导致死循环。
  targetRouter.onError((error) => {
    const msg = (error && (error as Error).message) || ''
    if (/Failed to fetch dynamically imported module|Importing a module script failed|Loading chunk \S+ failed/.test(msg)) {
      if (!sessionStorage.getItem('__chunk_reload_attempted')) {
        sessionStorage.setItem('__chunk_reload_attempted', String(Date.now()))
        window.location.reload()
      }
    }
  })
}

installRouterGuards(router)

// reload 之后清掉标志位（10 秒后），让下次部署也能再触发
if (typeof window !== 'undefined') {
  setTimeout(() => sessionStorage.removeItem('__chunk_reload_attempted'), 10_000)
}

export default router
