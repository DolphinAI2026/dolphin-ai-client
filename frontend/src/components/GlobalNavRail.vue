<template>
  <aside class="global-nav-rail" :class="{ collapsed: !expanded }">
    <div class="sidebar-logo">
      <button class="logo-main" @click="navigateTo('/')" title="返回主页">
        <div class="logo-icon">
          <svg width="22" height="22" viewBox="0 0 22 22" fill="none" aria-hidden="true">
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
          <svg v-else class="nav-icon" viewBox="0 0 16 16" fill="none">
            <path d="M4.5 5L2 8l2.5 3M11.5 5L14 8l-2.5 3M9.5 4l-3 8" stroke="currentColor" stroke-width="1.3" stroke-linecap="round" stroke-linejoin="round" />
          </svg>
          <span class="nav-label">{{ item.label }}</span>
        </button>
      </template>
    </div>

    <div class="sidebar-divider"></div>

    <div class="sidebar-nav sidebar-nav-secondary">
      <button
        v-for="item in secondaryNavItems"
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

    <div class="sidebar-divider"></div>

    <div class="sidebar-bottom">
      <el-dropdown trigger="click" @command="handleUserCommand" class="user-dropdown">
        <button class="user-row" :title="userStore.user?.username || 'admin'">
          <span class="user-avatar">{{ userInitial }}</span>
          <span class="user-name">{{ userStore.user?.username || 'admin' }}</span>
        </button>
        <template #dropdown>
          <el-dropdown-menu>
            <el-dropdown-item command="logout" divided>退出登录</el-dropdown-item>
          </el-dropdown-menu>
        </template>
      </el-dropdown>
    </div>
  </aside>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessageBox } from 'element-plus'
import { useUserStore } from '@/stores/user'

const router = useRouter()
const route = useRoute()
const userStore = useUserStore()
const expanded = ref(true)

const primaryNavItems = [
  { key: 'home', label: '智能搭建', path: '/' },
  { key: 'coding', label: '智能开发', path: '/coding' },
]

const secondaryNavItems = [
  { key: 'env', label: '环境管理', path: '/platform-envs' },
]

const activeKey = computed(() => {
  if (route.path === '/' || route.path.startsWith('/apps')) return 'home'
  if (route.path.startsWith('/coding')) return 'coding'
  if (route.path.startsWith('/platform-envs')) return 'env'
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

async function handleUserCommand(command: string | number | object) {
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
  justify-content: flex-start;
  gap: 4px;
  flex: 1;
  min-width: 0;
  cursor: pointer;
  border: none;
  background: transparent;
  padding: 0;
  text-align: left;
}

.logo-icon {
  width: 30px;
  height: 30px;
  border-radius: 10px;
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
