import { createRouter, createWebHistory } from 'vue-router'
import { useUserStore } from '@/stores/user'
import { usePreviewStore } from '@/stores/preview'
import request from '@/utils/request'
import { resolveDesktopRedirect } from './desktopGuard'
import { fetchOnboardingState, isOnboardingConfirmed, markOnboardingConfirmed } from '@/composables/useOnboardingState'

const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes: [
    { path: '/login', name: 'Login',
      component: () => (__DESKTOP__ ? import('@/views/DesktopLogin.vue') : import('@/views/Login.vue')) },
    {
      path: '/tenant-select',
      name: 'TenantSelect',
      component: () => import('@/views/TenantSelect.vue')
    },
    {
      path: '/',
      name: 'Home',
      // 首页 = AI Builder 融合页（新建 + 历史会话），与 /ai-chat 同组件。
      component: () => import('@/views/AIChatPage.vue'),
      meta: { requiresAuth: true, navExpanded: true }
    },
    {
      path: '/chat/:id?',
      name: 'Chat',
      component: () => import('@/views/ChatPage.vue'),
      meta: { requiresAuth: true },
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
      meta: { requiresAuth: true }
    },
    {
      // 数据接入 group 入口：数据库连接管理
      path: '/db-connections',
      name: 'DbConnections',
      component: () => import('@/views/DbConnectionsPage.vue'),
      meta: { requiresAuth: true, navExpanded: true }
    },
    {
      path: '/apps',
      name: 'Apps',
      component: () => import('@/views/Apps.vue'),
      meta: { requiresAuth: true }
    },
    // /projects (v2) 已删 — Project 表无真实进度字段, 真应用页在 /project/:id (单数).
    // /agents /specs /industry /runtime /mcp(McpHub) 这几个 v2 stub 页已删 (2026-06-08 清理).
    {
      path: '/workspace-catalog',
      name: 'WorkspaceCatalog',
      component: () => import('@/views/WorkspaceCatalogPage.vue'),
      meta: { requiresAuth: true }
    },
    {
      path: '/tenant-logs',
      name: 'TenantLogs',
      component: () => import('@/views/TenantLogsPage.vue'),
      meta: { requiresAuth: true }
    },
    {
      path: '/skills',
      name: 'Skills',
      component: () => import('@/views/SkillLibraryPage.vue'),
      meta: { requiresAuth: true, navExpanded: true }
    },
    {
      path: '/project/:id',
      name: 'ProjectOverview',
      component: () => import('@/views/ProjectOverview.vue'),
      meta: { requiresAuth: true }
    },
    {
      path: '/project/:id/git',
      name: 'ProjectGitSetup',
      component: () => import('@/views/ProjectGitSetup.vue'),
      meta: { requiresAuth: true }
    },
    {
      path: '/git/callback/:provider',
      name: 'GitOAuthCallback',
      component: () => import('@/views/GitOAuthCallback.vue'),
      meta: { requiresAuth: true }
    },
    {
      path: '/settings',
      name: 'Settings',
      redirect: to => {
        const rawTab = Array.isArray(to.query.tab) ? to.query.tab[0] : to.query.tab
        const tab = String(rawTab || 'llm')
        if (tab === 'envs') return { path: '/platform-envs', query: { tab: 'envs' } }
        if (tab === 'assistant') return { path: '/platform-envs', query: { tab: 'assistant' } }
        if (tab === 'team' || tab === 'members') return { path: '/tenant-users' }
        return { path: '/platform-envs', query: { tab: 'llm' } }
      },
      meta: { requiresAuth: true, navExpanded: true }
    },
    {
      path: '/coding',
      name: 'Coding',
      component: () => import('@/views/CodingPage.vue'),
      meta: { requiresAuth: true, navExpanded: true }
    },
    {
      path: '/admin/mcp',
      name: 'McpTools',
      component: () => import('@/views/McpToolsPage.vue'),
      meta: { requiresAuth: true, navExpanded: true }
    },
    {
      path: '/admin/agent-prompts',
      name: 'AgentPrompts',
      component: () => import('@/views/AgentPromptsPage.vue'),
      meta: { requiresAuth: true, requiresTenantAdmin: true, navExpanded: true }
    },
    {
      path: '/work/:appId',
      name: 'WorkspaceShell',
      redirect: to => ({ path: '/chat', query: { app_id: String(to.params.appId) } }),
      meta: { requiresAuth: true }
    },
    // M3 (2026-05-27): 删 /datasources stub — 用老 /db-connections 真页 (DbConnectionsPage)
    // 当 "数据源" nav 入口. 重定向兼容 G3 老路径.
    {
      path: '/datasources',
      redirect: '/db-connections',
    },
    // M1: 删 4 stub 路由 (/apis /docs /reports /models) — 产品定位不符.
    // L1: 删 /manage stub — admin-spa 已是平台管理完整入口. nav 管理直跳 /platform-admin.
    {
      path: '/platform-envs',
      name: 'PlatformEnvs',
      component: () => import('@/views/PlatformEnvs.vue'),
      meta: { requiresAuth: true, requiresTenantAdmin: true, navExpanded: true }
    },
    {
      path: '/platform-admin/:pathMatch(.*)*',
      name: 'PlatformAdmin',
      component: () => import('@/views/PlatformAdminEmbed.vue'),
      meta: { requiresAuth: true, requiresPlatformAdmin: true, navExpanded: true, desktop: 'hidden' }
    },
    {
      path: '/tenant-users',
      name: 'TenantUsers',
      component: () => import('@/views/TenantUsers.vue'),
      meta: { requiresAuth: true, requiresTenantAdmin: true, navExpanded: true }
    },
    {
      path: '/admin/tenants',
      name: 'PlatformTenants',
      component: () => import('@/views/PlatformTenants.vue'),
      meta: { requiresAuth: true, requiresPlatformAdmin: true, navExpanded: true, desktop: 'hidden' }
    },
    {
      path: '/desktop-setup',
      name: 'DesktopSetup',
      component: () => import('@/views/DesktopSetupWizard.vue'),
      meta: { requiresAuth: true }
    },
    {
      path: '/desktop-unavailable',
      name: 'DesktopUnavailable',
      component: () => import('@/views/DesktopUnavailable.vue'),
      meta: { requiresAuth: true }
    },
    {
      path: '/generate/:id?',
      name: 'Generate',
      // 重定向到 ChatPage 并自动打开部署面板
      redirect: to => ({ path: '/chat', query: { deploy_app_id: to.params.id as string } }),
      meta: { requiresAuth: true }
    }
  ]
})

function safeRedirectPath(raw: unknown): string {
  const value = Array.isArray(raw) ? raw[0] : raw
  const text = typeof value === 'string' ? value.trim() : ''
  if (!text.startsWith('/') || text.startsWith('//')) return ''
  if (text.startsWith('/login') || text.startsWith('/tenant-select')) return ''
  return text
}

router.beforeEach(async (to, _from, next) => {
  const userStore = useUserStore()

  if (to.meta.requiresAuth && !userStore.token) {
    next({ path: '/login', query: { redirect: to.fullPath } })
    return
  }

  // 有 token 但 user 对象为空（页面刷新后），自动恢复用户信息 + aPaaS 连接状态
  if (userStore.token && !userStore.user) {
    try {
      await userStore.fetchUser()
      // 同时恢复 aPaaS 连接状态
      const previewStore = usePreviewStore()
      try {
        const data = await request.get<any, any>('/apaas/status')
        if (data) {
          previewStore.connected = data.connected
        }
      } catch { /* ignore */ }
    } catch {
      // token 过期或无效，跳登录
      next({ path: '/login', query: { redirect: to.fullPath } })
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

  if (
    to.meta.requiresAuth
    && userStore.isPlatformAdmin
    && !userStore.tenantId
    && !to.path.startsWith('/platform-admin')
  ) {
    next('/platform-admin')
    return
  }

  if (__DESKTOP__ && userStore.token) {
    // 功能边界: hidden 路由落降级页
    const red = resolveDesktopRedirect(true, (to.meta as any), to.path)
    if (red) { next({ path: red, replace: true }); return }
    // 首启分流: 未配齐 aPaaS+LLM → 向导 (排除向导/登录/降级页自身防环; 已确认配齐则跳过拉取)
    const exempt = ['/desktop-setup', '/desktop-unavailable', '/login'].some(p => to.path.startsWith(p))
    if (!exempt && !isOnboardingConfirmed()) {
      const st = await fetchOnboardingState()
      if (st.configured) {
        markOnboardingConfirmed()
      } else {
        next({ path: '/desktop-setup', replace: true }); return
      }
    }
  }

  if (to.path === '/login' && userStore.token) {
    next(safeRedirectPath(to.query.redirect) || '/')
  } else {
    next()
  }
})

// 部署后老 tab 引用旧 index.html，里面 import 的 chunk hash 已被新 build 覆盖：
// 切路由时 dynamic import 404 → 用户卡死。这里捕获该错误自动 reload 一次拿新 index.html。
// sessionStorage 标志位防止 reload 后还失败导致死循环。
router.onError((error) => {
  const msg = (error && (error as Error).message) || ''
  if (/Failed to fetch dynamically imported module|Importing a module script failed|Loading chunk \S+ failed/.test(msg)) {
    if (!sessionStorage.getItem('__chunk_reload_attempted')) {
      sessionStorage.setItem('__chunk_reload_attempted', String(Date.now()))
      window.location.reload()
    }
  }
})

// reload 之后清掉标志位（10 秒后），让下次部署也能再触发
if (typeof window !== 'undefined') {
  setTimeout(() => sessionStorage.removeItem('__chunk_reload_attempted'), 10_000)
}

export default router
