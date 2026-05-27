import { createRouter, createWebHistory } from 'vue-router'

const router = createRouter({
  // 2026-05-13: 跟 vite --base 自动同步。dev 时 /, prod build 时 /mcp-server/admin/
  // （Dockerfile 里 npx vite build --base=/mcp-server/admin/ 注入 BASE_URL）
  history: createWebHistory(import.meta.env.BASE_URL),
  routes: [
    { path: '/login', component: () => import('@/views/LoginPage.vue') },
    {
      path: '/design-preview/:draftId',
      component: () => import('@/views/DesignPreview.vue'),
      meta: { requiresAdmin: true },
    },
    {
      path: '/',
      component: () => import('@/components/AdminLayout.vue'),
      meta: { requiresAdmin: true },
      redirect: '/mcp',
      children: [
        { path: 'status',     component: () => import('@/views/SystemStatus.vue') },
        { path: 'mcp',        component: () => import('@/views/McpServices.vue') },
        { path: 'tester',     component: () => import('@/views/McpTester.vue') },
        { path: 'tenants',    component: () => import('@/views/PlatformTenants.vue') },
        { path: 'envs',       component: () => import('@/views/PlatformEnvs.vue') },
        { path: 'llm-configs', component: () => import('@/views/LlmConfigs.vue') },
        { path: 'users',      component: () => import('@/views/PlatformUsers.vue') },
        { path: 'workspaces', component: () => import('@/views/SandboxMonitor.vue') },
        { path: 'logs',       component: () => import('@/views/CallLogs.vue') },
        // M4 (2026-05-27): 数据源 — 从 ai-builder 工作台搬到平台管理
        { path: 'datasources', component: () => import('@/views/PlatformDatasources.vue') },
      ],
    },
  ],
})

router.beforeEach((to, _from, next) => {
  const handoffToken = Array.isArray(to.query.handoff_token) ? to.query.handoff_token[0] : to.query.handoff_token
  if (handoffToken) {
    localStorage.setItem('admin_token', String(handoffToken))
    const cleanedQuery = { ...to.query }
    delete cleanedQuery.handoff_token
    return next({ path: to.path, query: cleanedQuery, hash: to.hash, replace: true })
  }

  const builderToken = localStorage.getItem('token')
  if (!localStorage.getItem('admin_token') && builderToken) {
    localStorage.setItem('admin_token', builderToken)
  }

  if (to.path === '/login' && localStorage.getItem('admin_token')) {
    return next('/')
  }

  if (!to.meta.requiresAdmin) return next()
  const token = localStorage.getItem('admin_token')
  if (!token) return next('/login')
  next()
})

export default router
