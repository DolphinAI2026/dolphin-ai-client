import { createRouter, createWebHistory } from 'vue-router'
import { useUserStore } from '@/stores/user'
import { usePreviewStore } from '@/stores/preview'
import { API_PREFIX } from '@/utils/request'

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
      path: '/project/:id',
      name: 'ProjectOverview',
      component: () => import('@/views/ProjectOverview.vue'),
      meta: { requiresAuth: true }
    },
    {
      path: '/coding',
      name: 'Coding',
      component: () => import('@/views/CodingPage.vue'),
      meta: { requiresAuth: true, navExpanded: true }
    },
    {
      path: '/platform-shell',
      name: 'PlatformShell',
      component: () => import('@/views/PlatformShellPage.vue'),
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
      meta: { requiresAuth: true, navExpanded: true }
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
        const res = await fetch(`${API_PREFIX}/apaas/status`, {
          headers: { 'Authorization': `Bearer ${userStore.token}` }
        })
        if (res.ok) {
          const data = await res.json()
          previewStore.connected = data.connected
        }
      } catch { /* ignore */ }
    } catch {
      // token 过期或无效，跳登录
      next('/login')
      return
    }
  }

  if (to.path === '/login' && userStore.token) {
    next('/')
  } else {
    next()
  }
})

export default router
