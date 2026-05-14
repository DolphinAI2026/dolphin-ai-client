<template>
  <aside class="global-nav-rail" :class="{ collapsed: !expanded }">
    <div class="sidebar-logo">
      <button class="logo-main" @click="navigateTo('/')" title="返回首页">
        <div class="logo-icon">
          <svg width="26" height="26" viewBox="0 0 22 22" fill="none" aria-hidden="true">
            <rect x="1" y="1" width="20" height="20" rx="6" fill="url(#railLogoBg)" />
            <rect x="8.6" y="5.8" width="4.8" height="4.8" rx="1.2" fill="#F5F4FF" />
            <rect x="5.4" y="9.8" width="4.8" height="4.8" rx="1.2" fill="#F5F4FF" />
            <rect x="11.8" y="9.8" width="4.8" height="4.8" rx="1.2" fill="#C9C2FF" />
            <defs>
              <linearGradient id="railLogoBg" x1="1" y1="1" x2="21" y2="21" gradientUnits="userSpaceOnUse">
                <stop stop-color="#5A4FD0" />
                <stop offset="1" stop-color="#43389F" />
              </linearGradient>
            </defs>
          </svg>
        </div>
        <span class="logo-text">aPaaS Builder</span>
      </button>

      <button
        class="collapse-btn-top"
        :title="expanded ? '收起导航' : '展开导航'"
        :aria-label="expanded ? '收起导航' : '展开导航'"
        @click="toggleExpanded"
      >
        <svg class="collapse-icon" viewBox="0 0 16 16" fill="none" aria-hidden="true">
          <path d="M10 3L5 8l5 5" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round" />
        </svg>
      </button>
    </div>

    <div class="sidebar-section">
      <div class="nav-section-label">主入口</div>
      <div class="sidebar-nav">
        <template v-for="item in primaryNavItems" :key="item.key">
          <button
            class="nav-item"
            :class="{ active: activeKey === item.key }"
            :title="item.label"
            @click="navigateTo(item.path)"
          >
            <svg v-if="item.key === 'home'" class="nav-icon" viewBox="0 0 16 16" fill="currentColor">
              <rect x="2" y="3" width="12" height="2" rx="1" />
              <rect x="2" y="7" width="8" height="2" rx="1" />
              <rect x="2" y="11" width="10" height="2" rx="1" />
            </svg>
            <svg v-else-if="item.key === 'ai-chat'" class="nav-icon" viewBox="0 0 16 16" fill="none">
              <path d="M2.5 3.5h11a1 1 0 011 1v6a1 1 0 01-1 1H6.5l-3 2.5v-2.5h-1a1 1 0 01-1-1v-6a1 1 0 011-1z" stroke="currentColor" stroke-width="1.3" stroke-linejoin="round" />
              <circle cx="5.5" cy="7.5" r="0.7" fill="currentColor" />
              <circle cx="8" cy="7.5" r="0.7" fill="currentColor" />
              <circle cx="10.5" cy="7.5" r="0.7" fill="currentColor" />
            </svg>
            <svg v-else-if="item.key === 'requirements'" class="nav-icon" viewBox="0 0 16 16" fill="none">
              <rect x="2.5" y="2" width="9" height="12" rx="1.2" stroke="currentColor" stroke-width="1.3" />
              <path d="M5 5h4M5 7.5h4M5 10h2.5" stroke="currentColor" stroke-width="1.2" stroke-linecap="round" />
              <circle cx="12.4" cy="11.4" r="2.2" fill="none" stroke="currentColor" stroke-width="1.3" />
              <path d="M11.4 11.4l0.7 0.7L13.4 10.7" stroke="currentColor" stroke-width="1.3" stroke-linecap="round" stroke-linejoin="round" />
            </svg>
            <svg v-else class="nav-icon" viewBox="0 0 16 16" fill="none">
              <path d="M4.5 5L2 8l2.5 3M11.5 5L14 8l-2.5 3M9.5 4l-3 8" stroke="currentColor" stroke-width="1.3" stroke-linecap="round" stroke-linejoin="round" />
            </svg>
            <span class="nav-label">{{ item.label }}</span>
          </button>
        </template>
      </div>
    </div>

    <div class="sidebar-divider"></div>

    <div class="sidebar-section">
      <div class="nav-section-label">辅助工作台</div>
      <div class="sidebar-nav sidebar-nav-secondary">
        <button
          v-for="item in workspaceNavItems"
          :key="item.key"
          class="nav-item"
          :class="{ active: activeKey === item.key }"
          :title="item.label"
          @click="navigateTo(item.path)"
        >
          <svg v-if="item.key === 'sandboxes'" class="nav-icon" viewBox="0 0 16 16" fill="none">
            <rect x="2" y="3" width="12" height="3" rx="0.6" stroke="currentColor" stroke-width="1.3" />
            <rect x="2" y="7" width="12" height="3" rx="0.6" stroke="currentColor" stroke-width="1.3" />
            <rect x="2" y="11" width="12" height="2" rx="0.6" stroke="currentColor" stroke-width="1.3" />
            <circle cx="4.5" cy="4.5" r="0.6" fill="currentColor" />
            <circle cx="4.5" cy="8.5" r="0.6" fill="currentColor" />
            <circle cx="4.5" cy="12" r="0.6" fill="currentColor" />
          </svg>
          <svg v-else class="nav-icon" viewBox="0 0 16 16" fill="none">
            <path d="M4.5 5L2 8l2.5 3M11.5 5L14 8l-2.5 3M9.5 4l-3 8" stroke="currentColor" stroke-width="1.3" stroke-linecap="round" stroke-linejoin="round" />
          </svg>
          <span class="nav-label">{{ item.label }}</span>
        </button>
      </div>
    </div>

    <div v-if="adminNavItems.length" class="sidebar-divider"></div>

    <div v-if="adminNavItems.length" class="sidebar-section">
      <div class="nav-section-label">管理</div>
      <div class="sidebar-nav sidebar-nav-secondary">
        <button
          v-for="item in adminNavItems"
          :key="item.key"
          class="nav-item"
          :class="{ active: activeKey === item.key }"
          :title="item.label"
          @click="navigateTo(item.path)"
        >
          <svg class="nav-icon" viewBox="0 0 16 16" fill="none">
            <rect x="2" y="2" width="12" height="9" rx="1.5" stroke="currentColor" stroke-width="1.3" />
            <path d="M5 14h6M8 11v3" stroke="currentColor" stroke-width="1.3" stroke-linecap="round" />
          </svg>
          <span class="nav-label">{{ item.label }}</span>
        </button>
      </div>
    </div>

    <div class="sidebar-bottom">
      <ThemeToggle class="sidebar-theme-toggle" />
      <el-dropdown trigger="click" @command="handleUserCommand" @visible-change="onUserDropdownVisibleChange" class="user-dropdown">
        <button class="user-row" :title="userStore.user?.username || 'admin'">
          <span class="user-avatar">{{ userInitial }}</span>
          <span class="user-name">{{ userStore.user?.username || 'admin' }}</span>
        </button>
        <template #dropdown>
          <el-dropdown-menu>
            <li class="user-current-tenant" v-if="userStore.tenantName">
              <span class="user-current-tenant-label">当前租户</span>
              <span class="user-current-tenant-value">{{ userStore.tenantName }}</span>
            </li>
            <template v-if="switchableTenants.length > 0">
              <li class="user-tenants-section-label">切换租户</li>
              <el-dropdown-item
                v-for="t in switchableTenants"
                :key="t.tenant_id"
                :command="`switch:${t.tenant_id}`"
              >
                <span class="user-tenant-name">{{ t.tenant_name }}</span>
              </el-dropdown-item>
            </template>
            <el-dropdown-item command="logout" divided>退出登录</el-dropdown-item>
          </el-dropdown-menu>
        </template>
      </el-dropdown>
    </div>
  </aside>
</template>

<script setup lang="ts">
import { computed, ref, watch, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useUserStore } from '@/stores/user'
import ThemeToggle from '@/components/ThemeToggle.vue'
import request from '@/utils/request'

const router = useRouter()
const route = useRoute()
const userStore = useUserStore()
const expanded = ref(true)

// AI 需求分析菜单：只在 backend 配了 dolphin_requirements_agent_code 时显示
const requirementsAgentEnabled = ref(false)
async function fetchDolphinConfig() {
  if (!localStorage.getItem('token')) return
  try {
    const cfg = await request.get<unknown, { requirements_agent_code?: string }>('/dolphin/config')
    requirementsAgentEnabled.value = !!cfg?.requirements_agent_code
  } catch { /* 静默 — 没拿到就不显示菜单 */ }
}
onMounted(fetchDolphinConfig)
// token 变化（切账号 / 切租户）后重新拉一次
watch(() => userStore.token, fetchDolphinConfig)

const primaryNavItems = computed(() => {
  const items = [
    { key: 'home', label: 'AI Builder', path: '/' },
    { key: 'ai-chat', label: 'AI Chat', path: '/ai-chat' },
  ]
  if (requirementsAgentEnabled.value) {
    items.push({ key: 'requirements', label: 'AI 需求分析', path: '/requirements-assistant' })
  }
  return items
})

const workspaceNavItems = [
  { key: 'coding', label: '开发工作区', path: '/coding' },
  { key: 'sandboxes', label: '沙箱监控', path: '/vibe-coding/sandboxes' },
]

const adminNavItems = computed(() => {
  const items: { key: string; label: string; path: string }[] = []
  if (userStore.isTenantAdmin) {
    items.push({ key: 'env', label: '平台环境', path: '/platform-envs' })
    items.push({ key: 'users', label: '组织用户', path: '/tenant-users' })
  }
  if (userStore.isPlatformAdmin) {
    items.push({ key: 'tenants', label: '租户管理', path: '/admin/tenants' })
  }
  // MCP 工具浏览 — 所有登录用户都能看（让开发者快速知道暴露了什么）
  items.push({ key: 'mcp', label: 'MCP 工具', path: '/admin/mcp' })
  return items
})

const activeKey = computed(() => {
  if (route.path.startsWith('/ai-chat')) return 'ai-chat'
  if (route.path.startsWith('/requirements-assistant')) return 'requirements'
  if (route.path === '/' || route.path.startsWith('/apps')) return 'home'
  if (route.path.startsWith('/coding')) return 'coding'
  if (route.path.startsWith('/platform-envs')) return 'env'
  if (route.path.startsWith('/tenant-users')) return 'users'
  if (route.path.startsWith('/admin/tenants')) return 'tenants'
  if (route.path.startsWith('/vibe-coding/sandboxes')) return 'sandboxes'
  return 'home'
})

const userInitial = computed(() => (userStore.user?.username || 'A').slice(0, 1).toLowerCase())
function syncExpandedWithRoute() {
  expanded.value = route.meta.navExpanded === true
}

watch(() => route.fullPath, syncExpandedWithRoute, { immediate: true })

function toggleExpanded() {
  expanded.value = !expanded.value
}

function navigateTo(path: string) {
  router.push(path)
}

const switchableTenants = computed(() =>
  userStore.availableTenants.filter((t) => t.tenant_id !== userStore.tenantId)
)

async function onUserDropdownVisibleChange(visible: boolean) {
  if (visible) {
    await userStore.fetchAvailableTenants()
  }
}

async function handleUserCommand(command: string | number | object) {
  if (typeof command === 'string' && command.startsWith('switch:')) {
    const targetId = Number(command.slice('switch:'.length))
    if (!targetId || targetId === userStore.tenantId) return
    try {
      await userStore.switchTenant(targetId)
      ElMessage.success(`已切换到「${userStore.tenantName || '新租户'}」`)
      // 重载当前页面，让所有数据按新租户重新拉
      router.go(0)
    } catch (e: any) {
      ElMessage.error(e?.message || '切换租户失败')
    }
    return
  }
  if (command === 'logout') {
    try {
      await ElMessageBox.confirm('确认退出当前账号吗？', '退出登录', {
        confirmButtonText: '退出登录',
        cancelButtonText: '取消',
        type: 'warning',
      })
      userStore.logout()
      router.push('/login')
    } catch {
      // noop
    }
  }
}
</script>

<style scoped>
.global-nav-rail {
  width: 194px;
  flex-shrink: 0;
  display: flex;
  flex-direction: column;
  background: #f6f7ff;
  border-right: 1px solid rgba(125, 132, 181, 0.16);
  transition: width 0.2s ease;
  overflow: hidden;
  --sidebar-gutter: 12px;
}

.global-nav-rail.collapsed {
  width: 48px;
}

.sidebar-logo {
  padding: 13px 10px 13px 12px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  border-bottom: 1px solid rgba(125, 132, 181, 0.16);
  min-height: 53px;
}

.logo-main {
  display: flex;
  align-items: center;
  gap: 6px;
  min-width: 0;
  cursor: pointer;
  border: none;
  background: transparent;
  padding: 0;
}

.logo-icon {
  width: 38px;
  height: 38px;
  border-radius: 11px;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.logo-text {
  font-size: 15px;
  font-weight: 600;
  color: #20253f;
  white-space: nowrap;
  text-align: left;
}

.collapse-btn-top {
  border: none;
  background: transparent;
  width: 24px;
  height: 24px;
  border-radius: 8px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #7f8097;
  cursor: pointer;
  flex-shrink: 0;
}

.collapse-btn-top:hover {
  background: rgba(79, 72, 146, 0.08);
  color: #43389f;
}

.collapse-icon {
  width: 16px;
  height: 16px;
  flex-shrink: 0;
  transition: transform 0.2s ease;
}

.global-nav-rail:not(.collapsed) .collapse-icon {
  transform: rotate(0deg);
}

.global-nav-rail.collapsed .collapse-icon {
  transform: rotate(180deg);
}

.sidebar-nav {
  padding: 6px 10px;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.sidebar-section {
  display: flex;
  flex-direction: column;
}

.nav-section-label {
  padding: 10px 22px 4px;
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.04em;
  color: rgba(99, 96, 136, 0.78);
}

.sidebar-nav-secondary {
  padding-top: 2px;
}

.nav-item {
  display: flex;
  align-items: center;
  gap: 10px;
  width: 100%;
  min-height: 42px;
  border: none;
  background: transparent;
  padding: 8px 14px;
  border-radius: 14px;
  cursor: pointer;
  font-size: 13px;
  color: #252f46;
  white-space: nowrap;
  text-align: left;
  transition: all 0.15s ease;
}

.nav-item:hover {
  background: rgba(79, 72, 146, 0.05);
}

.nav-item.active {
  background: rgba(230, 227, 255, 0.95);
  color: #3b3781;
  font-weight: 600;
  box-shadow: inset 0 0 0 1px rgba(83, 74, 183, 0.05);
}

.nav-icon {
  width: 18px;
  height: 18px;
  flex-shrink: 0;
}

.nav-label {
  overflow: hidden;
}

.sidebar-divider {
  height: 1px;
  background: rgba(125, 132, 181, 0.16);
  margin: 4px 10px;
}

.sidebar-bottom {
  margin-top: auto;
  padding: 10px 10px;
  border-top: 1px solid rgba(125, 132, 181, 0.16);
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.sidebar-theme-toggle {
  align-self: flex-start;
}
.global-nav-rail.collapsed .sidebar-theme-toggle {
  align-self: center;
}

.user-dropdown {
  width: 100%;
}

.user-row {
  width: 100%;
  border: none;
  background: transparent;
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 7px 8px;
  border-radius: 12px;
  white-space: nowrap;
  cursor: pointer;
}

.user-row:hover {
  background: rgba(79, 72, 146, 0.05);
}

.user-avatar {
  width: 26px;
  height: 26px;
  border-radius: 50%;
  background: #534ab7;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 11px;
  font-weight: 500;
  color: #eeedfe;
  flex-shrink: 0;
}

.user-name {
  font-size: 13px;
  color: var(--color-text-secondary);
}

.user-current-tenant {
  list-style: none;
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: 8px 16px 6px;
  cursor: default;
}
.user-current-tenant-label {
  font-size: 10px;
  text-transform: uppercase;
  letter-spacing: 0.06em;
  color: var(--color-text-tertiary, #999);
}
.user-current-tenant-value {
  font-size: 13px;
  font-weight: 600;
  color: var(--color-text-primary, #20253f);
}
.user-tenants-section-label {
  list-style: none;
  font-size: 10px;
  text-transform: uppercase;
  letter-spacing: 0.06em;
  color: var(--color-text-tertiary, #999);
  padding: 6px 16px 2px;
  cursor: default;
}
.user-tenant-name {
  font-size: 13px;
}

.global-nav-rail.collapsed .sidebar-logo {
  padding: 12px 8px 10px;
  flex-direction: column;
  justify-content: flex-start;
  gap: 8px;
  min-height: 92px;
}

.global-nav-rail.collapsed .logo-main {
  width: 100%;
  justify-content: center;
}

.global-nav-rail.collapsed .logo-text,
.global-nav-rail.collapsed .nav-section-label,
.global-nav-rail.collapsed .nav-label,
.global-nav-rail.collapsed .user-name {
  display: none;
}

.global-nav-rail.collapsed .collapse-btn-top {
  width: 28px;
  height: 28px;
  border-radius: 10px;
}

.global-nav-rail.collapsed .sidebar-nav,
.global-nav-rail.collapsed .sidebar-bottom {
  padding-left: 8px;
  padding-right: 8px;
}

.global-nav-rail.collapsed .nav-item,
.global-nav-rail.collapsed .user-row {
  justify-content: center;
  padding-left: 0;
  padding-right: 0;
}

.global-nav-rail.collapsed .sidebar-divider {
  margin-left: 8px;
  margin-right: 8px;
}

:global(.dark) .global-nav-rail,
:global(html.dark) .global-nav-rail,
:global(body.dark) .global-nav-rail {
  background: #f6f7ff;
  border-right-color: rgba(125, 132, 181, 0.16);
}

:global(.dark) .nav-item,
:global(.dark) .logo-main,
:global(html.dark) .nav-item,
:global(html.dark) .logo-main,
:global(body.dark) .nav-item,
:global(body.dark) .logo-main {
  color: #2e3853;
}
</style>
