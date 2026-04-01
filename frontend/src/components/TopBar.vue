<template>
  <nav class="top-bar">
    <div class="top-bar-left">
      <!-- 汉堡菜单 -->
      <button v-if="showHamburger" class="top-bar-btn" @click="$emit('toggle-sidebar')" title="切换侧栏">
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><line x1="3" y1="6" x2="21" y2="6"/><line x1="3" y1="12" x2="21" y2="12"/><line x1="3" y1="18" x2="21" y2="18"/></svg>
      </button>
      <!-- 返回按钮 -->
      <button v-if="showBack" class="top-bar-btn" @click="handleBack" title="返回">
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="15 18 9 12 15 6"/></svg>
      </button>
      <!-- Logo + 标题 -->
      <button class="top-bar-home" @click="router.push('/')" title="返回首页">
        <div class="top-bar-logo">A</div>
      </button>
      <span class="top-bar-title">{{ title }}</span>
      <!-- 中间 slot -->
      <slot name="center" />
    </div>
    <div class="top-bar-right">
      <!-- 右侧额外操作 -->
      <slot name="actions" />
      <ThemeToggle />
      <el-dropdown @command="handleCommand" trigger="click">
        <button class="user-avatar-btn">
          {{ userInitial }}
        </button>
        <template #dropdown>
          <el-dropdown-menu>
            <el-dropdown-item disabled>
              <div class="user-menu-info">
                <div class="user-menu-label">用户</div>
                <div class="user-menu-value">{{ userStore.user?.username }}</div>
              </div>
            </el-dropdown-item>
            <el-dropdown-item disabled v-if="userStore.tenantName">
              <div class="user-menu-info">
                <div class="user-menu-label">租户</div>
                <div class="user-menu-value">{{ userStore.tenantName }}</div>
              </div>
            </el-dropdown-item>
            <el-dropdown-item divided command="home">
              <span>🏠 首页</span>
            </el-dropdown-item>
            <el-dropdown-item command="apps">
              <span>📱 我的应用</span>
            </el-dropdown-item>
            <el-dropdown-item command="coding">
              <span>💻 AI Coding</span>
            </el-dropdown-item>
            <el-dropdown-item command="envs">
              <span>⚙️ 环境管理</span>
            </el-dropdown-item>
            <el-dropdown-item divided command="logout">
              <span style="color: #ef4444;">退出登录</span>
            </el-dropdown-item>
          </el-dropdown-menu>
        </template>
      </el-dropdown>
    </div>
  </nav>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useRouter } from 'vue-router'
import { useUserStore } from '@/stores/user'
import ThemeToggle from '@/components/ThemeToggle.vue'

const props = withDefaults(defineProps<{
  title?: string
  showHamburger?: boolean
  showBack?: boolean
  backTo?: string
}>(), {
  title: 'aPaaS Builder AI',
  showHamburger: false,
  showBack: false,
  backTo: '/',
})

defineEmits<{
  'toggle-sidebar': []
}>()

const router = useRouter()
const userStore = useUserStore()

const userInitial = computed(() =>
  (userStore.user?.username || 'U').charAt(0).toUpperCase()
)

function handleBack() {
  router.push(props.backTo)
}

function handleCommand(cmd: string) {
  switch (cmd) {
    case 'home':
      router.push('/')
      break
    case 'apps':
      router.push('/apps')
      break
    case 'coding':
      router.push('/coding')
      break
    case 'envs':
      router.push('/platform-envs')
      break
    case 'logout':
      userStore.logout()
      router.push('/login')
      break
  }
}
</script>

<style scoped>
.top-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  height: 48px;
  padding: 0 12px;
  background: var(--t-bg-panel);
  border-bottom: 1px solid var(--t-border-subtle);
  flex-shrink: 0;
  z-index: 10;
}
.top-bar-left {
  display: flex;
  align-items: center;
  gap: 6px;
  min-width: 0;
  flex: 1;
}
.top-bar-right {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-shrink: 0;
}

/* Buttons */
.top-bar-btn {
  width: 34px;
  height: 34px;
  border: none;
  border-radius: 8px;
  background: transparent;
  color: var(--t-text-secondary);
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all 0.15s;
  flex-shrink: 0;
}
.top-bar-btn:hover {
  background: var(--t-bg-panel-hover);
  color: var(--t-text-primary);
}

/* Logo */
.top-bar-home {
  border: none;
  background: none;
  cursor: pointer;
  padding: 0;
  display: flex;
  align-items: center;
  flex-shrink: 0;
}
.top-bar-logo {
  width: 28px;
  height: 28px;
  background: var(--t-brand-gradient);
  border-radius: 7px;
  color: #fff;
  font-weight: 700;
  font-size: 13px;
  display: flex;
  align-items: center;
  justify-content: center;
}

/* Title */
.top-bar-title {
  font-size: 14px;
  font-weight: 600;
  color: var(--t-text-primary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  margin-left: 2px;
}

/* User avatar */
.user-avatar-btn {
  width: 30px;
  height: 30px;
  border-radius: 50%;
  border: none;
  background: var(--t-brand-gradient);
  color: #fff;
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: opacity 0.15s;
  flex-shrink: 0;
}
.user-avatar-btn:hover {
  opacity: 0.85;
}

/* User menu */
.user-menu-info {
  display: flex;
  flex-direction: column;
  gap: 1px;
  padding: 2px 0;
}
.user-menu-label {
  font-size: 10px;
  color: var(--t-text-muted);
  text-transform: uppercase;
  letter-spacing: 0.04em;
}
.user-menu-value {
  font-size: 13px;
  font-weight: 500;
  color: var(--t-text-primary);
}
</style>
