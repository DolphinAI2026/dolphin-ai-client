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
      <button v-if="showHome" class="top-bar-home" @click="router.push('/')" title="返回首页">
        <div class="top-bar-logo">A</div>
      </button>
      <span v-if="title" class="top-bar-title">{{ title }}</span>
      <!-- 中间 slot -->
      <slot name="center" />
    </div>
    <div v-if="$slots.actions" class="top-bar-right">
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
              <span class="menu-row"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 9l9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/><polyline points="9 22 9 12 15 12 15 22"/></svg> 首页</span>
            </el-dropdown-item>
            <el-dropdown-item command="apps">
              <span class="menu-row"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="7" height="7"/><rect x="14" y="3" width="7" height="7"/><rect x="14" y="14" width="7" height="7"/><rect x="3" y="14" width="7" height="7"/></svg> 我的应用</span>
            </el-dropdown-item>
            <el-dropdown-item command="coding">
              <span class="menu-row"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="16 18 22 12 16 6"/><polyline points="8 6 2 12 8 18"/></svg> AI Coding</span>
            </el-dropdown-item>
            <el-dropdown-item command="envs">
              <span class="menu-row"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z"/></svg> 环境管理</span>
            </el-dropdown-item>
            <el-dropdown-item divided command="logout">
              <span class="menu-row" style="color: var(--t-danger, #ef4444);"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/><polyline points="16 17 21 12 16 7"/><line x1="21" y1="12" x2="9" y2="12"/></svg> 退出登录</span>
            </el-dropdown-item>
          </el-dropdown-menu>
        </template>
      </el-dropdown>
    </div>
  </nav>
</template>

<script setup lang="ts">
import { useRouter } from 'vue-router'

const props = withDefaults(defineProps<{
  title?: string
  showHamburger?: boolean
  showBack?: boolean
  showHome?: boolean
  backTo?: string
}>(), {
  title: 'aPaaS Builder AI',
  showHamburger: false,
  showBack: false,
  showHome: true,
  backTo: '/',
})

defineEmits<{
  'toggle-sidebar': []
}>()

const router = useRouter()

function handleBack() {
  router.push(props.backTo)
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
.top-bar-right { display: flex; align-items: center; gap: 6px; flex-shrink: 0; }

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
.menu-row {
  display: flex;
  align-items: center;
  gap: 8px;
}
.menu-row svg {
  flex-shrink: 0;
}
</style>
