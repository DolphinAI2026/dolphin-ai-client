<template>
  <aside class="builder-nav-rail" aria-label="主导航">
    <button class="builder-nav-logo" title="aPaaS Builder AI" @click="go('/')">ap</button>

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
  ChatDotRound,
  Grid,
  HomeFilled,
  Monitor,
  Promotion,
  Search,
  Setting,
} from '@element-plus/icons-vue'
import { useUserStore } from '@/stores/user'
import ThemeToggle from '@/components/ThemeToggle.vue'

const router = useRouter()
const route = useRoute()
const userStore = useUserStore()

const navItems = [
  { key: 'home', label: '首页', path: '/', icon: HomeFilled },
  { key: 'apps', label: '应用', path: '/apps', icon: Grid },
  { key: 'chat', label: 'Chat 工作台', path: '/chat', icon: ChatDotRound },
  { key: 'ide', label: 'IDE', path: '/coding', icon: Monitor },
  { key: 'devops', label: 'DevOps', path: '/devops', icon: Promotion },
  { key: 'settings', label: '设置', path: '/platform-envs?tab=llm', icon: Setting },
]

const activeKey = computed(() => {
  if (route.path === '/') return 'home'
  if (route.path.startsWith('/apps') || route.path.startsWith('/project')) return 'apps'
  if (route.path.startsWith('/chat')) return 'chat'
  if (route.path.startsWith('/ide') || route.path.startsWith('/coding')) return 'ide'
  if (route.path.startsWith('/devops')) return 'devops'
  if (route.path.startsWith('/settings') || route.path.startsWith('/platform-envs') || route.path.startsWith('/tenant-users')) return 'settings'
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
