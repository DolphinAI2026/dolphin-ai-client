import { createRouter, createWebHistory } from 'vue-router'
import { useUserStore } from '@/stores/user'
import { usePreviewStore } from '@/stores/preview'
import request from '@/utils/request'

const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes: [
    {
      path: '/login',
      name: 'Login',
      component: () => import('@/views/Login.vue')
    },
    {
      path: '/tenant-select',
      name: 'TenantSelect',
      component: () => import('@/views/TenantSelect.vue')
    },
    {
      path: '/',
      name: 'Home',
      component: () => import('@/views/Landing.vue'),
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
      // 存量 DB 快速接入 wizard：DB 连接 → 表多选 → 业务描述 → 进度。
      // Landing 第 4 张卡 "DB 问数" 入口。
      path: '/quick-db',
      name: 'QuickDb',
      component: () => import('@/views/QuickDbPage.vue'),
      meta: { requiresAuth: true, navExpanded: true }
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
    // P0 stub routes — full pages land in P2; these exist so the v2 sidebar
    // never 404s. See docs/superpowers/plans/2026-05-18-apaas-builder-redesign-p0-p1.md.
    // /projects v2 was deleted — the underlying Project table had no real
    // progress/stage fields, so the page surfaced fake 0% / 0 apps / 0 deploys
    // rows. Real per-app project page still lives at /project/:id (singular).
    {
      path: '/agents',
      name: 'Agents',
      component: () => import('@/views/v2/AgentsPage.vue'),
      meta: { requiresAuth: true }
    },
    {
      path: '/specs',
      name: 'Specs',
      component: () => import('@/views/v2/SpecsPage.vue'),
      meta: { requiresAuth: true }
    },
    {
      path: '/industry',
      name: 'Industry',
      component: () => import('@/views/v2/IndustryPage.vue'),
      meta: { requiresAuth: true }
    },
    {
      path: '/runtime',
      name: 'Runtime',
      component: () => import('@/views/v2/RuntimePage.vue'),
      meta: { requiresAuth: true }
    },
    {
      path: '/mcp',
      name: 'McpHub',
      component: () => import('@/views/v2/McpHubPage.vue'),
      meta: { requiresAuth: true }
    },
    {
      path: '/workspace-catalog',
      name: 'WorkspaceCatalog',
      component: () => import('@/views/WorkspaceCatalogPage.vue'),
      meta: { requiresAuth: true }
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
      path: '/ide',
      name: 'Ide',
      redirect: '/coding'
    },
    {
      path: '/devops',
      name: 'DevOps',
      component: () => import('@/views/BuilderDevOpsPage.vue'),
      meta: { navExpanded: true }
    },
    {
      path: '/proposals/:id',
      name: 'ProposalDetail',
      component: () => import('@/views/ProposalDetailPage.vue'),
      meta: { requiresAuth: true }
    },
    {
      path: '/settings',
      name: 'Settings',
      redirect: to => {
        const rawTab = Array.isArray(to.query.tab) ? to.query.tab[0] : to.query.tab
        const tab = String(rawTab || 'llm')
        if (tab === 'envs') return { path: '/platform-envs', query: { tab: 'envs' } }
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
      path: '/work/:appId',
      name: 'WorkspaceShell',
      redirect: to => ({ path: '/chat', query: { app_id: String(to.params.appId) } }),
      meta: { requiresAuth: true }
    },
    // PR6 — Extension Section 组件 demo / 验收用 (SPEC v2 §2 Section E0)
    {
      path: '/extension-demo',
      name: 'ExtensionSectionDemo',
      component: () => import('@/views/ExtensionSectionDemoPage.vue'),
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
      meta: { requiresAuth: true, requiresPlatformAdmin: true, navExpanded: true }
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
      meta: { requiresAuth: true, requiresPlatformAdmin: true, navExpanded: true }
    },
    {
      // PR2a 临时 demo 页 — SectionNav 组件验收 (PR2b 接入 ChatPage 后可删)
      path: '/section-nav-demo',
      name: 'SectionNavDemo',
      component: () => import('@/views/SectionNavDemoPage.vue'),
      meta: { requiresAuth: false }
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
