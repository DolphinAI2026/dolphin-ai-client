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
      meta: { requiresAuth: true }
    },
    {
      path: '/ai-chat/:id?',
      name: 'AIChat',
      component: () => import('@/views/AIChatPage.vue'),
      meta: { requiresAuth: true }
    },
    {
      path: '/apps',
      name: 'Apps',
      component: () => import('@/views/Apps.vue'),
      meta: { requiresAuth: true }
    },
    {
      path: '/workspace-catalog',
      name: 'WorkspaceCatalog',
      component: () => import('@/views/WorkspaceCatalogPage.vue'),
      meta: { requiresAuth: true }
    },
    {
      path: '/vibe-coding',
      name: 'OnlineCoding',
      component: () => import('@/views/OnlineCodingWorkspacePage.vue'),
      meta: { requiresAuth: true, navExpanded: true }
    },
    {
      // 对话驱动：新建工作区不再弹表单，sidebar 直接 API 创建后跳 workspaces/:id；
      // 旧 URL 访问时回到工作区列表
      path: '/vibe-coding/new',
      redirect: '/vibe-coding',
    },
    {
      path: '/vibe-coding/sandboxes',
      name: 'SandboxMonitor',
      component: () => import('@/views/SandboxMonitorPage.vue'),
      meta: { requiresAuth: true, navExpanded: true }
    },
    {
      path: '/vibe-coding/workspaces/:id',
      name: 'OnlineCodingWorkspace',
      component: () => import('@/views/OnlineCodingWorkspacePage.vue'),
      meta: { requiresAuth: true, navExpanded: true }
    },
    {
      path: '/online-coding',
      redirect: '/vibe-coding',
    },
    {
      path: '/online-coding/new',
      redirect: '/vibe-coding/new',
    },
    {
      path: '/online-coding/workspaces/:id',
      redirect: to => ({ path: `/vibe-coding/workspaces/${to.params.id}`, query: to.query }),
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
      path: '/work/:appId',
      name: 'WorkspaceShell',
      redirect: to => ({ path: '/chat', query: { app_id: String(to.params.appId) } }),
      meta: { requiresAuth: true }
    },
    {
      path: '/marketplace',
      name: 'Marketplace',
      component: () => import('@/views/MarketplacePage.vue'),
      meta: { requiresAuth: true }
    },
    {
      path: '/platform-envs',
      name: 'PlatformEnvs',
      component: () => import('@/views/PlatformEnvs.vue'),
      meta: { requiresAuth: true, requiresTenantAdmin: true, navExpanded: true }
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
      path: '/generate/:id?',
      name: 'Generate',
      // 重定向到 ChatPage 并自动打开部署面板
      redirect: to => ({ path: '/chat', query: { deploy_app_id: to.params.id as string } }),
      meta: { requiresAuth: true }
    }
  ]
})

router.beforeEach(async (to, _from, next) => {
  const userStore = useUserStore()

  if (to.path === '/coding' && to.query.type === 'full-code') {
    const rawId = Array.isArray(to.query.online_workspace_id)
      ? to.query.online_workspace_id[0]
      : to.query.online_workspace_id || (Array.isArray(to.query.online_ws) ? to.query.online_ws[0] : to.query.online_ws)
    const workspaceId = rawId ? String(rawId) : ''
    const rawView = Array.isArray(to.query.online_view) ? to.query.online_view[0] : to.query.online_view
    next({
      path: workspaceId ? `/vibe-coding/workspaces/${workspaceId}` : '/vibe-coding',
      query: rawView === 'ide' ? { view: 'ide' } : {},
    })
    return
  }

  if (to.meta.requiresAuth && !userStore.token) {
    next('/login')
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
      next('/login')
      return
    }
  }

  if (to.meta.requiresTenantAdmin && !userStore.isTenantAdmin) {
    next('/')
    return
  }

  if (to.meta.requiresPlatformAdmin && !userStore.isPlatformAdmin) {
    next('/')
    return
  }

  if (to.path === '/login' && userStore.token) {
    next('/')
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
