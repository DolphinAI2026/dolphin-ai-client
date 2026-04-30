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

    <el-dropdown trigger="click" @command="handleUserCommand">
      <button class="builder-nav-avatar" :title="userStore.user?.username || 'admin'">
        {{ userInitial }}
      </button>
      <template #dropdown>
        <el-dropdown-menu>
          <el-dropdown-item command="logout">退出登录</el-dropdown-item>
        </el-dropdown-menu>
      </template>
    </el-dropdown>
  </aside>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessageBox } from 'element-plus'
import {
  ChatLineRound,
  Connection,
  Grid,
  HomeFilled,
  MagicStick,
  Monitor,
  Promotion,
  Search,
  Setting,
  UserFilled,
} from '@element-plus/icons-vue'
import { useUserStore } from '@/stores/user'
import ThemeToggle from '@/components/ThemeToggle.vue'

const router = useRouter()
const route = useRoute()
const userStore = useUserStore()

const navItems = computed(() => [
  { key: 'home', label: '首页', path: '/', icon: HomeFilled },
  { key: 'apps', label: '应用', path: '/apps', icon: Grid },
  { key: 'ai-chat', label: 'AI Chat', path: '/ai-chat', icon: ChatLineRound },
  { key: 'chat', label: 'AI-Builder', path: '/chat', icon: MagicStick },
  { key: 'ide', label: 'IDE', path: '/coding', icon: Monitor },
  { key: 'online-coding', label: 'Vibe Coding', path: '/vibe-coding', icon: Connection },
  { key: 'devops', label: 'DevOps', path: '/devops', icon: Promotion },
  ...(userStore.isTenantAdmin ? [{ key: 'members', label: '成员管理', path: '/tenant-users', icon: UserFilled }] : []),
  { key: 'settings', label: '设置', path: '/platform-envs?tab=llm', icon: Setting },
])

const activeKey = computed(() => {
  if (route.path === '/') return 'home'
  if (route.path.startsWith('/ai-chat')) return 'ai-chat'
  if (route.path.startsWith('/apps') || route.path.startsWith('/project')) return 'apps'
  if (route.path.startsWith('/chat')) return 'chat'
  if (route.path.startsWith('/vibe-coding') || route.path.startsWith('/online-coding')) return 'online-coding'
  if (route.path.startsWith('/coding') && route.query.type === 'full-code') return 'online-coding'
  if (route.path.startsWith('/ide') || route.path.startsWith('/coding')) return 'ide'
  if (route.path.startsWith('/devops')) return 'devops'
  if (route.path.startsWith('/tenant-users')) return 'members'
  if (route.path.startsWith('/settings') || route.path.startsWith('/platform-envs')) return 'settings'
  return 'home'
})

const userInitial = computed(() => (userStore.user?.username || 'A').slice(0, 1).toUpperCase())

function go(path: string) {
  router.push(path)
}

function openCommand() {
  window.dispatchEvent(new CustomEvent('builder:open-command'))
}

async function handleUserCommand(command: string | number | object) {
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
