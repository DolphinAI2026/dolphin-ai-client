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
import {
  loadProductAvailability,
  productForRoute,
  redirectForDisabledProduct,
} from '@/stores/productAvailability'
import request, {
  getAuthSessionState,
  isAuthSessionAlignmentPending,
} from '@/utils/request'
import { getCachedDesktopState, getDesktopState, resolveDesktopProductScope } from '@/utils/desktop'
import {
  loadDesktopBootstrapDecision,
  resolveDesktopRedirect,
  resolveDesktopSettingsRedirect,
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
      meta: { requiresAuth: true, tenantContext: 'required', navExpanded: true, product: 'builder' }
    },
    {
      path: '/chat/:id?',
      name: 'Chat',
      component: () => import('@/views/ChatPage.vue'),
      meta: { requiresAuth: true, tenantContext: 'required', product: 'builder' },
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
      meta: { requiresAuth: true, tenantContext: 'required', product: 'builder' },
      beforeEnter: (to, _from, next) => {
        // Code 会话已经迁移到 /code/:id（由 agent-runtime 承载）。
        // 保留 /ai-chat 给 Builder，但让历史 mode=code 链接失效，避免再次创建旧会话。
        if (String(to.query.mode || '') === 'code') {
          next({ path: '/code/apps' })
          return
        }
        next()
      },
    },
    {
      path: '/code',
      component: () => import('@/views/CodeShellLayout.vue'),
      // Code uses the per-tab Control Plane ticket (`cp_tid`), not the
      // Builder/aPaaS local tenant URL contract.
      meta: { requiresAuth: true, tenantContext: 'none', product: 'code' },
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
          path: 'system-assistant',
          name: 'CodeSystemAssistant',
          component: () => import('@/views/SystemAssistantPage.vue'),
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
      meta: { requiresAuth: true, tenantContext: 'required', navExpanded: true, product: 'builder' }
    },
    {
      path: '/apps',
      name: 'Apps',
      component: () => import('@/views/Apps.vue'),
      meta: { requiresAuth: true, tenantContext: 'required', product: 'builder' }
    },
    // /projects (v2) 已删 — Project 表无真实进度字段, 真应用页在 /project/:id (单数).
    // /agents /specs /industry /runtime /mcp(McpHub) 这几个 v2 stub 页已删 (2026-06-08 清理).
    {
      path: '/workspace-catalog',
      name: 'WorkspaceCatalog',
      component: () => import('@/views/WorkspaceCatalogPage.vue'),
      meta: { requiresAuth: true, tenantContext: 'required', product: 'builder' }
    },
    {
      path: '/workspace/:id?',
      name: 'Workspace',
      component: () => import('@/views/workspace/WorkspaceShell.vue'),
      meta: { requiresAuth: true, tenantContext: 'required', navExpanded: true, product: 'builder' }
    },
    {
      path: '/tenant-logs',
      name: 'TenantLogs',
      component: () => import('@/views/TenantLogsPage.vue'),
      meta: { requiresAuth: true, tenantContext: 'required', product: 'builder' }
    },
    {
      path: '/audit-logs', name: 'AuditLogs',
      component: () => import('@/views/TenantAuditLogsPage.vue'),
      meta: { requiresAuth: true, tenantContext: 'required', requiresTenantAdmin: true, product: 'builder' }
    },
    {
      path: '/applications/:id/audit-logs', name: 'ApplicationAuditLogs',
      component: () => import('@/views/ApplicationAuditLogsPage.vue'),
      meta: { requiresAuth: true, tenantContext: 'required', product: 'builder' }
    },
    {
      path: '/hub',
      name: 'CapabilitiesHub',
      redirect: to => {
        const tab = String(Array.isArray(to.query.tab) ? to.query.tab[0] : to.query.tab || 'skills')
        const target = tab === 'knowledge'
          ? '/knowledge'
          : tab === 'mcp'
            ? '/admin/mcp'
            : tab === 'models' || tab === 'gateway'
              ? '/settings'
              : '/skills'
        const query = target === '/settings'
          ? { ...to.query, section: 'ai' }
          : (() => {
              const next = { ...to.query }
              delete next.tab
              return next
            })()
        return { path: target, query, hash: to.hash }
      },
      meta: { requiresAuth: true, tenantContext: 'required', navExpanded: true, product: 'builder' }
    },
    {
      // 技能库由统一设置页进入；保留直达路径兼容旧书签。
      path: '/skills',
      name: 'Skills',
      component: () => import('@/views/SkillLibraryPage.vue'),
      meta: { requiresAuth: true, tenantContext: 'required', product: 'builder' }
    },
    {
      path: '/skills/:name/workspace',
      name: 'SkillWorkspace',
      component: () => import('@/views/SkillWorkspacePage.vue'),
      meta: { requiresAuth: true, tenantContext: 'required', product: 'builder' }
    },
    {
      path: '/project/:id',
      name: 'ProjectOverview',
      component: () => import('@/views/ProjectOverview.vue'),
      meta: { requiresAuth: true, tenantContext: 'required', product: 'builder' }
    },
    {
      path: '/project/:id/git',
      name: 'ProjectGitSetup',
      component: () => import('@/views/ProjectGitSetup.vue'),
      meta: { requiresAuth: true, tenantContext: 'required', product: 'builder' }
    },
    {
      path: '/git/callback/:provider',
      name: 'GitOAuthCallback',
      component: () => import('@/views/GitOAuthCallback.vue'),
      meta: { requiresAuth: true, tenantContext: 'required', product: 'builder' }
    },
    {
      path: '/settings',
      name: 'Settings',
      component: () => import('@/views/SettingsHubPage.vue'),
      meta: { requiresAuth: true, tenantContext: 'none', navExpanded: true }
    },
    {
      // Legacy CodingPage is kept only for the workspace preview iframe.
      // User-facing Code sessions live under /code/* now.
      path: '/coding',
      name: 'Coding',
      component: () => import('@/views/CodingPage.vue'),
      meta: {
        requiresAuth: true,
        tenantContext: 'required',
        navExpanded: true,
        product: 'code',
        deprecated: true,
      },
      beforeEnter: (to, _from, next) => {
        // The embedded Code preview is the only supported legacy entry.
        if (String(to.query.embed || '') === 'true') {
          next()
          return
        }
        next({ path: '/code/apps', replace: true })
      },
    },
    {
      path: '/admin/mcp',
      name: 'McpTools',
      component: () => import('@/views/McpToolsPage.vue'),
      meta: { requiresAuth: true, tenantContext: 'required', navExpanded: true, product: 'builder' }
    },
    {
      path: '/admin/agent-prompts',
      name: 'AgentPrompts',
      component: () => import('@/views/AgentPromptsPage.vue'),
      meta: { requiresAuth: true, tenantContext: 'required', requiresTenantAdmin: true, navExpanded: true, product: 'builder' }
    },
    {
      path: '/work/:appId',
      name: 'WorkspaceShell',
      redirect: to => ({
        path: '/chat',
        query: { ...to.query, app_id: String(to.params.appId) },
        hash: to.hash,
      }),
      meta: { requiresAuth: true, tenantContext: 'required', product: 'builder' }
    },
    // M3 (2026-05-27): 删 /datasources stub — 用老 /db-connections 真页 (DbConnectionsPage)
    // 当 "数据源" nav 入口. 重定向兼容 G3 老路径.
    {
      path: '/datasources',
      redirect: '/db-connections',
      meta: { requiresAuth: true, tenantContext: 'required', product: 'builder' }
    },
    // M1: 删 4 stub 路由 (/apis /docs /reports /models) — 产品定位不符.
    // L1: 删 /manage stub — admin-spa 已是平台管理完整入口. nav 管理直跳 /platform-admin.
    {
      path: '/platform-envs',
      name: 'PlatformEnvs',
      component: () => import('@/views/PlatformEnvs.vue'),
      // Deprecated compatibility page retained for old bookmarks only.
      props: route => ({
        only: route.query.tab === 'llm' ? 'llm' : route.query.tab === 'envs' ? 'envs' : undefined,
      }),
      meta: { requiresAuth: true, tenantContext: 'required', requiresTenantAdmin: true, navExpanded: true, product: 'builder' }
    },
    {
      path: '/platform-admin/:pathMatch(.*)*',
      name: 'PlatformAdmin',
      component: () => import('@/views/PlatformAdminEmbed.vue'),
      meta: { requiresAuth: true, tenantContext: 'none', requiresPlatformAdmin: true, navExpanded: true, desktop: 'hidden', product: 'builder' }
    },
    {
      path: '/tenant-users',
      name: 'TenantUsers',
      component: () => import('@/views/TenantUsers.vue'),
      meta: { requiresAuth: true, tenantContext: 'required', requiresTenantAdmin: true, navExpanded: true, product: 'builder' }
    },
    {
      path: '/admin/tenants',
      name: 'PlatformTenants',
      component: () => import('@/views/PlatformTenants.vue'),
      meta: { requiresAuth: true, tenantContext: 'none', requiresPlatformAdmin: true, navExpanded: true, desktop: 'hidden', product: 'builder' }
    },
    {
      // 知识库由统一设置页进入；保留直达路径兼容旧书签。
      path: '/knowledge',
      name: 'knowledge-base',
      component: () => import('@/views/KnowledgeBasePage.vue'),
      meta: { requiresAuth: true, tenantContext: 'required', product: 'builder' }
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
      meta: { requiresAuth: true, tenantContext: 'required', product: 'builder' }
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

    const settingsRedirect = resolveDesktopSettingsRedirect(true, to.path)
    if (settingsRedirect) {
      next({ path: settingsRedirect, replace: true })
      return
    }

    const workspaceEntryScope = resolveDesktopProductScope(getCachedDesktopState()?.config)
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

    const productRedirect = redirectForDisabledProduct(
      await loadProductAvailability(),
      productForRoute(to),
    )
    if (productRedirect) {
      next({ path: productRedirect, replace: true })
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
      if (!localStorage.getItem('access_token')?.trim()) {
        next()
        return
      }
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
