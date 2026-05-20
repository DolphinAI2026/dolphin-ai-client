<template>
  <section class="platform-admin-embed">
    <div class="embed-toolbar">
      <div class="embed-brand">
        <button class="embed-logo" type="button" aria-label="返回首页" :disabled="!canReturnWorkspace || tenantLoading" @click="goWorkspace">AI</button>
        <div>
          <div class="embed-breadcrumb">
            <span>睿鲸AI</span>
            <span>/</span>
            <strong>平台管理</strong>
          </div>
          <h1>{{ currentTitle }}</h1>
        </div>
      </div>
      <div class="embed-right">
        <div class="embed-actions">
          <button type="button" :class="{ active: adminPath === '/mcp' }" @click="openAdminPath('/mcp')">MCP</button>
          <button type="button" :class="{ active: adminPath === '/tester' }" @click="openAdminPath('/tester')">测试</button>
          <button type="button" :class="{ active: adminPath === '/logs' }" @click="openAdminPath('/logs')">日志</button>
          <span class="embed-nav-gap"></span>
          <button type="button" :class="{ active: adminPath === '/tenants' }" @click="openAdminPath('/tenants')">租户</button>
          <button type="button" :class="{ active: adminPath === '/users' }" @click="openAdminPath('/users')">成员</button>
          <span class="embed-nav-gap"></span>
          <button type="button" :class="{ active: adminPath === '/llm-configs' }" @click="openAdminPath('/llm-configs')">模型</button>
        </div>
        <button v-if="canReturnWorkspace" class="embed-back" type="button" :disabled="tenantLoading" @click="goWorkspace">
          {{ tenantLoading ? '切换中...' : '返回工作台' }}
        </button>
        <button class="embed-logout" type="button" @click="logout">退出登录</button>
      </div>
    </div>

    <div class="embed-frame-wrap">
      <iframe
        :key="iframeSrc"
        class="embed-frame"
        :src="iframeSrc"
        title="平台管理"
        @load="loading = false"
      />
      <div v-if="loading" class="embed-loading">正在加载平台管理...</div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useUserStore } from '@/stores/user'

const route = useRoute()
const router = useRouter()
const userStore = useUserStore()
const loading = ref(true)
const tenantLoading = ref(false)
const canReturnWorkspace = computed(() => Boolean(userStore.tenantId || userStore.availableTenants.length))

const adminPath = computed(() => {
  const raw = route.params.pathMatch
  const parts = Array.isArray(raw) ? raw : raw ? [String(raw)] : []
  const path = `/${parts.filter(Boolean).join('/')}`.replace(/\/+/g, '/')
  return path === '/' || path === '/status' ? '/mcp' : path
})

const iframeSrc = computed(() => {
  const token = localStorage.getItem('token') || ''
  const params = new URLSearchParams({ embed: '1' })
  if (token) params.set('handoff_token', token)

  if (import.meta.env.DEV) {
    return `${window.location.protocol}//${window.location.hostname}:5174${adminPath.value}?${params.toString()}`
  }

  const base = import.meta.env.BASE_URL.replace(/\/$/, '')
  return `${base}/admin${adminPath.value}?${params.toString()}`
})

const titleMap: Record<string, string> = {
  '/mcp': 'MCP 接入',
  '/tester': 'MCP 测试',
  '/logs': '调用日志',
  '/envs': '平台环境',
  '/llm-configs': '模型配置',
  '/users': '成员管理',
  '/tenants': '租户管理',
  '/workspaces': '工作区',
}

const currentTitle = computed(() => titleMap[adminPath.value] || '平台管理')

function openAdminPath(path: string) {
  if (path === adminPath.value) return
  router.push(`/platform-admin${path === '/mcp' ? '' : path}`)
}

async function goWorkspace() {
  if (!userStore.tenantId) {
    const firstTenant = userStore.availableTenants[0]
    if (!firstTenant) return
    tenantLoading.value = true
    try {
      await userStore.switchTenant(firstTenant.tenant_id)
    } finally {
      tenantLoading.value = false
    }
  }
  router.push('/')
}

function logout() {
  userStore.logout()
  localStorage.removeItem('admin_token')
  router.replace('/login')
}

watch(iframeSrc, () => {
  loading.value = true
})

onMounted(async () => {
  if (!userStore.tenantId) {
    tenantLoading.value = true
    try {
      await userStore.fetchAvailableTenants()
    } finally {
      tenantLoading.value = false
    }
  }
})
</script>

<style scoped>
/* v3 redesign · 2026-05-20 — token-driven, template/script untouched.
   Replaced v2 purple gradients (#766bf1/#5750d8/#5146d8/#eeeaff/#e2def0) +
   hardcode dark text (#17162f) with v3 blue brand + slate ramp tokens.
   Added :focus-visible rings on every clickable for a11y.
*/
.platform-admin-embed {
  min-width: 0;
  min-height: 0;
  height: 100vh;
  display: flex;
  flex-direction: column;
  background:
    radial-gradient(ellipse 700px 260px at 54% 0%, var(--brand-ring), transparent 70%),
    var(--bg-app, linear-gradient(180deg, var(--surface) 0%, var(--surface-2) 100%));
  color: var(--text);
  font-family: var(--font-sans, inherit);
}

.embed-toolbar {
  min-height: 82px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 24px;
  padding: 14px 28px;
  border-bottom: 1px solid var(--line);
  background: var(--surface-overlay, var(--surface));
  backdrop-filter: blur(14px);
}

.embed-brand,
.embed-right {
  display: flex;
  align-items: center;
  gap: 14px;
}

.embed-logo,
.embed-back,
.embed-logout {
  border: 0;
  cursor: pointer;
  font: inherit;
}

.embed-logo {
  width: 42px;
  height: 42px;
  display: grid;
  place-items: center;
  border-radius: var(--r-4, 12px);
  color: var(--text-inverse, #fff);
  background: linear-gradient(135deg, var(--blue-500, #3B82F6), var(--blue-800, #1E40AF));
  box-shadow: 0 14px 30px -10px var(--brand-glow);
  font-weight: var(--fw-bold, 700);
  transition: transform 0.14s var(--ease, cubic-bezier(0.2, 0.8, 0.2, 1)),
              box-shadow 0.14s var(--ease, cubic-bezier(0.2, 0.8, 0.2, 1));
}
.embed-logo:hover:not(:disabled) {
  transform: translateY(-1px);
  box-shadow: var(--sh-brand);
}
.embed-logo:focus-visible {
  outline: 2px solid var(--line-focus, var(--brand-ring));
  outline-offset: 2px;
}

.embed-logo:disabled {
  cursor: default;
  opacity: 0.7;
}

.embed-breadcrumb {
  display: flex;
  align-items: center;
  gap: 8px;
  color: var(--text-3);
  font-size: var(--t-small, 12.5px);
  font-weight: var(--fw-semibold, 600);
}

.embed-breadcrumb strong {
  color: var(--text);
  font-weight: var(--fw-semibold, 600);
}

.embed-toolbar h1 {
  margin: 6px 0 0;
  color: var(--text);
  font-size: var(--t-h2, 24px);
  line-height: 1.2;
  font-weight: var(--fw-bold, 700);
  letter-spacing: -0.01em;
}

.embed-actions {
  display: inline-flex;
  align-items: center;
  gap: 2px;
  padding: 4px;
  border: 1px solid var(--line);
  border-radius: var(--r-4, 12px);
  background: var(--surface);
}

.embed-nav-gap {
  width: 10px;
  height: 24px;
  border-left: 1px solid var(--line);
  margin-left: 4px;
}

.embed-actions button {
  height: 34px;
  border: 0;
  border-radius: var(--r-3, 8px);
  padding: 0 15px;
  background: transparent;
  color: var(--text-2);
  font: inherit;
  font-size: var(--t-body, 14px);
  font-weight: var(--fw-semibold, 600);
  cursor: pointer;
  transition: background 0.14s var(--ease, cubic-bezier(0.2, 0.8, 0.2, 1)),
              color 0.14s var(--ease, cubic-bezier(0.2, 0.8, 0.2, 1));
}
.embed-actions button:hover:not(.active) {
  background: var(--brand-soft);
  color: var(--brand);
}
.embed-actions button:focus-visible {
  outline: 2px solid var(--line-focus, var(--brand-ring));
  outline-offset: 2px;
}

.embed-actions button.active {
  color: var(--brand);
  background: var(--brand-soft);
}

.embed-back {
  height: 42px;
  padding: 0 16px;
  border: 1px solid var(--line);
  border-radius: var(--r-3, 8px);
  background: var(--surface);
  color: var(--text-2);
  font-size: var(--t-body, 14px);
  font-weight: var(--fw-semibold, 600);
  transition: border-color 0.14s var(--ease, cubic-bezier(0.2, 0.8, 0.2, 1)),
              background 0.14s var(--ease, cubic-bezier(0.2, 0.8, 0.2, 1)),
              color 0.14s var(--ease, cubic-bezier(0.2, 0.8, 0.2, 1));
}
.embed-back:hover:not(:disabled) {
  color: var(--brand);
  border-color: var(--brand-ring);
  background: var(--brand-soft);
}
.embed-back:focus-visible {
  outline: 2px solid var(--line-focus, var(--brand-ring));
  outline-offset: 2px;
}

.embed-back:disabled {
  cursor: wait;
  opacity: 0.68;
}

.embed-logout {
  height: 42px;
  padding: 0 14px;
  border: 1px solid var(--err-soft, rgba(185, 28, 28, 0.18));
  border-radius: var(--r-3, 8px);
  background: var(--surface);
  color: var(--err);
  font-size: var(--t-body, 14px);
  font-weight: var(--fw-semibold, 600);
  transition: background 0.14s var(--ease, cubic-bezier(0.2, 0.8, 0.2, 1));
}
.embed-logout:hover {
  background: var(--err-soft);
}
.embed-logout:focus-visible {
  outline: 2px solid var(--err);
  outline-offset: 2px;
}

.embed-frame-wrap {
  position: relative;
  flex: 1;
  min-height: 0;
  padding: 0 28px 28px;
}

.embed-frame {
  width: 100%;
  height: 100%;
  display: block;
  border: 0;
  border-radius: var(--r-5, 16px);
  background: transparent;
  box-shadow: var(--sh-4);
}

.embed-loading {
  position: absolute;
  inset: 0;
  display: grid;
  place-items: center;
  color: var(--text-3);
  background: var(--glass, rgba(255, 255, 255, 0.72));
  font-size: var(--t-body, 14px);
  font-weight: var(--fw-semibold, 600);
}

@media (max-width: 920px) {
  .embed-toolbar {
    align-items: stretch;
    flex-direction: column;
  }

  .embed-right {
    align-items: stretch;
    flex-direction: column;
  }

  .embed-actions {
    overflow-x: auto;
  }
}
</style>
