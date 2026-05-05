<template>
  <aside class="builder-nav-rail" aria-label="主导航">
    <button class="builder-nav-logo" title="aPaaS Builder AI" aria-label="返回首页" @click="go('/')">
      <svg class="builder-logo-mark" viewBox="0 0 24 24" fill="none" aria-hidden="true">
        <rect x="4" y="4" width="7" height="7" rx="2" fill="currentColor" opacity="0.92" />
        <rect x="13" y="4" width="7" height="7" rx="2" fill="currentColor" opacity="0.62" />
        <rect x="4" y="13" width="7" height="7" rx="2" fill="currentColor" opacity="0.62" />
        <path d="M15.2 18.8 19 15m0 0-3.8-3.8M19 15h-7" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round" />
      </svg>
    </button>

    <nav class="builder-nav-items">
      <button
        v-for="item in navItems"
        :key="item.key"
        class="builder-nav-item"
        :class="{ active: activeKey === item.key }"
        :title="item.label"
        @click="go(item.path)"
      >
        <component :is="item.icon" />
        <span class="builder-nav-tooltip">{{ item.label }}</span>
      </button>
    </nav>

    <div class="builder-nav-spacer" />

    <button class="builder-nav-item" title="命令面板" @click="openCommand">
      <Search />
      <span class="builder-nav-tooltip">命令面板</span>
    </button>

    <ThemeToggle class="builder-nav-theme" />

    <el-dropdown
      trigger="click"
      popper-class="builder-nav-user-dropdown"
      @command="handleUserCommand"
      @visible-change="onUserDropdownVisibleChange"
    >
      <button class="builder-nav-avatar" :title="userStore.user?.username || 'admin'">
        {{ userInitial }}
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
  </aside>
</template>

<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessageBox } from 'element-plus'
import {
  ChatLineRound,
  Connection,
  DocumentChecked,
  Grid,
  HomeFilled,
  MagicStick,
  Monitor,
  Odometer,
  OfficeBuilding,
  Promotion,
  Search,
  Setting,
  UserFilled,
} from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { useUserStore } from '@/stores/user'
import ThemeToggle from '@/components/ThemeToggle.vue'
import request from '@/utils/request'

const router = useRouter()
const route = useRoute()
const userStore = useUserStore()

// 仅在 backend 配了 dolphin_requirements_agent_code 时显示 'AI 需求分析' 菜单
const requirementsAgentEnabled = ref(false)
async function fetchDolphinConfig() {
  if (!localStorage.getItem('token')) return
  try {
    const cfg = await request.get<unknown, { requirements_agent_code?: string }>('/dolphin/config')
    requirementsAgentEnabled.value = !!cfg?.requirements_agent_code
  } catch { /* 静默 — 没拿到就不显示菜单 */ }
}
onMounted(fetchDolphinConfig)
watch(() => userStore.token, fetchDolphinConfig)

const navItems = computed(() => [
  { key: 'home', label: '首页', path: '/', icon: HomeFilled },
  { key: 'apps', label: '应用', path: '/apps', icon: Grid },
  { key: 'ai-chat', label: 'AI 对话', path: '/ai-chat', icon: ChatLineRound },
  ...(requirementsAgentEnabled.value
    ? [{ key: 'requirements', label: 'AI 需求分析', path: '/requirements-assistant', icon: DocumentChecked }]
    : []),
  // 'AI 搭建' 入口已隐藏 — dolphin 接管对话后默认从'我的应用'进具体应用编辑页
  // { key: 'chat', label: 'AI 搭建', path: '/chat', icon: MagicStick },
  { key: 'ide', label: 'AI 编码', path: '/coding', icon: Monitor },
  { key: 'online-coding', label: 'Vibe Coding', path: '/vibe-coding', icon: Connection },
  { key: 'sandboxes', label: '沙箱监控', path: '/vibe-coding/sandboxes', icon: Odometer },
  { key: 'devops', label: 'DevOps', path: '/devops', icon: Promotion },
  ...(userStore.isTenantAdmin ? [{ key: 'members', label: '成员管理', path: '/tenant-users', icon: UserFilled }] : []),
  ...(userStore.isPlatformAdmin ? [{ key: 'tenants', label: '租户管理', path: '/admin/tenants', icon: OfficeBuilding }] : []),
  { key: 'settings', label: '设置', path: '/platform-envs?tab=llm', icon: Setting },
])

const activeKey = computed(() => {
  if (route.path === '/') return 'home'
  if (route.path.startsWith('/ai-chat')) return 'ai-chat'
  if (route.path.startsWith('/requirements-assistant')) return 'requirements'
  if (route.path.startsWith('/apps') || route.path.startsWith('/project')) return 'apps'
  if (route.path.startsWith('/chat')) return 'chat'
  if (route.path.startsWith('/vibe-coding/sandboxes')) return 'sandboxes'
  if (route.path.startsWith('/vibe-coding') || route.path.startsWith('/online-coding')) return 'online-coding'
  if (route.path.startsWith('/coding') && route.query.type === 'full-code') return 'online-coding'
  if (route.path.startsWith('/ide') || route.path.startsWith('/coding')) return 'ide'
  if (route.path.startsWith('/devops')) return 'devops'
  if (route.path.startsWith('/tenant-users')) return 'members'
  if (route.path.startsWith('/admin/tenants')) return 'tenants'
  if (route.path.startsWith('/settings') || route.path.startsWith('/platform-envs')) return 'settings'
  return 'home'
})

const switchableTenants = computed(() =>
  userStore.availableTenants.filter((t) => t.tenant_id !== userStore.tenantId)
)

async function onUserDropdownVisibleChange(visible: boolean) {
  if (visible) {
    await userStore.fetchAvailableTenants()
  }
}

const userInitial = computed(() => (userStore.user?.username || 'A').slice(0, 1).toUpperCase())

function go(path: string) {
  // 1. 已经在目标路径就跳过，避免 NavigationDuplicated 触发 unhandled rejection
  //    导致后续 click 事件被 vue-router 静默吞掉（用户体验：点不动）
  // 2. 异步路由跳转加 catch 兜底，处理 NavigationCancelled / Aborted（用户快速连点
  //    /路由 beforeEach 主动 abort 时不抛错到全局）
  if (route.fullPath === path || route.path === path) return
  router.push(path).catch((err: any) => {
    const name = err?.name || ''
    if (!/Navigation(Duplicated|Cancelled|Aborted)/.test(name)) {
      console.warn('[nav] router.push failed:', err)
    }
  })
}

function openCommand() {
  window.dispatchEvent(new CustomEvent('builder:open-command'))
}

async function handleUserCommand(command: string | number | object) {
  if (typeof command === 'string' && command.startsWith('switch:')) {
    const targetId = Number(command.slice('switch:'.length))
    if (!targetId || targetId === userStore.tenantId) return
    try {
      await userStore.switchTenant(targetId)
      ElMessage.success(`已切换到「${userStore.tenantName || '新租户'}」`)
      router.go(0)
    } catch (e: any) {
      ElMessage.error(e?.message || '切换租户失败')
    }
    return
  }
  if (command !== 'logout') return
  try {
    await ElMessageBox.confirm('确认退出当前账号吗？', '退出登录', {
      confirmButtonText: '退出登录',
      cancelButtonText: '取消',
      type: 'warning',
    })
    userStore.logout()
    router.push('/login')
  } catch {
    // user cancelled
  }
}
</script>

<style>
.builder-nav-user-dropdown .user-current-tenant {
  list-style: none;
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: 8px 16px 6px;
  cursor: default;
}
.builder-nav-user-dropdown .user-current-tenant-label,
.builder-nav-user-dropdown .user-tenants-section-label {
  font-size: 10px;
  text-transform: uppercase;
  letter-spacing: 0.06em;
  color: var(--el-text-color-placeholder);
}
.builder-nav-user-dropdown .user-current-tenant-value {
  font-size: 13px;
  font-weight: 600;
  color: var(--el-text-color-primary);
}
.builder-nav-user-dropdown .user-tenants-section-label {
  list-style: none;
  padding: 6px 16px 2px;
  cursor: default;
}
.builder-nav-user-dropdown .user-tenant-name {
  font-size: 13px;
}
</style>
