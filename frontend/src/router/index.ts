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
      component: () => import('@/views/OnlineCodingPage.vue'),
      meta: { requiresAuth: true, navExpanded: true }
    },
    {
      path: '/vibe-coding/new',
      name: 'OnlineCodingNew',
      component: () => import('@/views/OnlineCodingWorkspacePage.vue'),
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
      path: '/requirements/:id?',
      name: 'Requirements',
      // 重定向到 ChatPage 的 requirements 模式
      redirect: () => ({ path: '/chat', query: { mode: 'requirements' } }),
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

router.beforeEach(async (to, _from, next) => {
  const userStore = useUserStore()

  if (to.path === '/coding' && to.query.type === 'full-code') {
    const rawId = Array.isArray(to.query.online_workspace_id)
      ? to.query.online_workspace_id[0]
      : to.query.online_workspace_id || (Array.isArray(to.query.online_ws) ? to.query.online_ws[0] : to.query.online_ws)
    const workspaceId = rawId ? String(rawId) : ''
    const rawView = Array.isArray(to.query.online_view) ? to.query.online_view[0] : to.query.online_view
    next({
      path: workspaceId ? `/vibe-coding/workspaces/${workspaceId}` : '/vibe-coding/new',
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

  if (to.path === '/login' && userStore.token) {
    next('/')
  } else {
    next()
  }
})

export default router
