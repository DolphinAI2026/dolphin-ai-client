<template>
  <el-container class="admin-layout" :class="{ 'admin-layout-embedded': embedded }">
    <el-aside v-if="!embedded" width="220px" class="admin-sidebar">
      <div class="admin-brand">
        <div class="brand-mark">AI</div>
        <div>
          <div class="admin-brand-title">睿鲸AI</div>
          <div class="admin-brand-sub">平台管理</div>
        </div>
      </div>
      <el-menu
        :default-active="activeKey"
        router
        class="admin-menu"
      >
        <el-menu-item
          v-for="item in menus"
          :key="item.path"
          :index="item.path"
        >
          <el-icon><component :is="item.icon" /></el-icon>
          <span>{{ item.label }}</span>
        </el-menu-item>
      </el-menu>
    </el-aside>

    <el-container>
      <el-header v-if="!embedded" class="admin-header">
        <div class="admin-header-title">平台管理 / {{ currentTitle }}</div>
        <div class="admin-header-right">
          <el-tag v-if="auth.user" type="success" effect="light">{{ auth.user.username }}</el-tag>
          <el-button text @click="onLogout">退出</el-button>
        </div>
      </el-header>

      <el-main class="admin-main">
        <router-view />
      </el-main>
    </el-container>
  </el-container>
</template>

<script setup lang="ts">
import { computed, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  Connection,
  Operation,
  OfficeBuilding,
  User,
  Cpu,
  Tickets,
} from '@element-plus/icons-vue'
import { useAuthStore } from '@/stores/auth'

const route  = useRoute()
const router = useRouter()
const auth   = useAuthStore()

interface MenuItem {
  path: string
  label: string
  icon: any
}

const menus: MenuItem[] = [
  { path: '/mcp',       label: 'MCP 接入',          icon: Connection },
  { path: '/tester',    label: 'MCP 测试',          icon: Operation },
  { path: '/logs',      label: '调用日志',          icon: Tickets },
  { path: '/tenants',   label: 'aPaaS 租户',        icon: OfficeBuilding },
  { path: '/llm-configs', label: 'LLM 配置',        icon: Cpu },
  { path: '/users',     label: 'aPaaS 用户',        icon: User },
]

const activeKey    = computed(() => route.path)
const currentTitle = computed(() => menus.find((m) => m.path === route.path)?.label || '管理后台')
const embedded = computed(() => {
  const queryEmbedded = route.query.embed === '1' || route.query.embed === 'true'
  const framed = typeof window !== 'undefined' && window.self !== window.top
  return queryEmbedded || framed
})

onMounted(async () => {
  // 进 admin 之前先拉一次 /auth/me 让侧边显示账号
  if (auth.isAuthenticated && !auth.user) {
    await auth.fetchMe()
  }
})

function onLogout() {
  auth.logout()
  router.push('/login')
}
</script>

<style scoped>
.admin-layout {
  height: 100vh;
  color: var(--text);
}

.admin-sidebar {
  background: var(--surface-2);
  color: var(--text-2);
  display: flex;
  flex-direction: column;
  border-right: 1px solid var(--line);
}

.admin-brand {
  display: flex;
  align-items: center;
  gap: 12px;
  min-height: 72px;
  padding: 18px;
  border-bottom: 1px solid var(--line);
}

.brand-mark {
  width: 36px;
  height: 36px;
  display: grid;
  place-items: center;
  border-radius: var(--r-3, 8px);
  color: var(--text-inverse, #fff);
  background: linear-gradient(135deg, var(--blue-500, #3B82F6), var(--blue-800, #1E40AF));
  box-shadow: var(--sh-brand, 0 8px 22px -8px rgba(29, 78, 216, 0.32));
  font-weight: var(--fw-bold, 700);
}

.admin-brand-title {
  color: var(--text);
  font-size: 17px;
  font-weight: var(--fw-bold, 700);
  letter-spacing: 0;
}

.admin-brand-sub {
  color: var(--text-3);
  font-size: 12px;
  margin-top: 3px;
}

.admin-menu {
  flex: 1;
  background: transparent;
  border-right: none;
  padding: 14px 10px;
}

.admin-menu :deep(.el-menu-item) {
  height: 40px;
  margin: 4px 0;
  border-radius: var(--r-3, 8px);
  color: var(--text-2);
  font-weight: var(--fw-semibold, 600);
}

.admin-menu :deep(.el-menu-item.is-active) {
  background: var(--brand-soft);
  color: var(--brand);
  box-shadow: inset 3px 0 0 var(--brand);
}

.admin-menu :deep(.el-menu-item:hover) {
  background: var(--surface-overlay);
  color: var(--brand);
}

.admin-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  height: 64px;
  background: var(--surface-overlay);
  border-bottom: 1px solid var(--line);
  padding: 0 28px;
  backdrop-filter: blur(12px);
}

.admin-header-title {
  color: var(--text);
  font-size: 15px;
  font-weight: var(--fw-semibold, 600);
}

.admin-header-right {
  display: flex;
  align-items: center;
  gap: 12px;
}

.admin-main {
  background:
    radial-gradient(ellipse 700px 260px at 54% 0%, var(--brand-soft), transparent 70%),
    linear-gradient(180deg, #F8FAFC 0%, var(--surface-2) 100%);
  padding: 28px 36px;
  overflow-y: auto;
}

.admin-layout-embedded .admin-main {
  padding: 28px 36px 56px;
}

.admin-layout-embedded .admin-main :deep(.page-header > div:first-child),
.admin-layout-embedded .admin-main :deep(.llm-hero > div:first-child),
.admin-layout-embedded .admin-main :deep(.platform-hero > div:first-child) {
  display: none;
}

.admin-layout-embedded .admin-main :deep(.mcp-hero) {
  display: none;
}

.admin-layout-embedded .admin-main :deep(.page-header),
.admin-layout-embedded .admin-main :deep(.llm-hero),
.admin-layout-embedded .admin-main :deep(.platform-hero) {
  justify-content: flex-end;
  margin-bottom: 18px;
}

.admin-main :deep(.page) {
  max-width: 1440px;
  margin: 0 auto;
  padding: 8px 0 56px;
  color: var(--text);
}

.admin-main :deep(.page-header) {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 24px;
  margin-bottom: 22px;
  flex-wrap: wrap;
}

.admin-main :deep(.page-header h1) {
  margin: 0;
  color: var(--text);
  font-size: 32px;
  line-height: 1.2;
  font-weight: var(--fw-bold, 700);
}

.admin-main :deep(.page-header p) {
  max-width: 940px;
  margin: 14px 0 0;
  color: var(--text-2);
  font-size: 16px;
  line-height: 1.7;
}

.admin-main :deep(.page-actions) {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
  justify-content: flex-end;
}

.admin-main :deep(.section.el-card),
.admin-main :deep(.page > .el-card),
.admin-main :deep(.page > .el-table),
.admin-main :deep(.page > .el-empty) {
  overflow: hidden;
  border: 1px solid var(--line);
  border-radius: var(--r-5, 16px);
  background: var(--surface);
  box-shadow: var(--sh-2);
}

.admin-main :deep(.section.el-card),
.admin-main :deep(.page > .el-card) {
  margin-bottom: 20px;
}

.admin-main :deep(.el-card__header) {
  min-height: 62px;
  display: flex;
  align-items: center;
  padding: 0 22px;
  border-bottom: 1px solid var(--line);
  background: var(--surface-2);
  color: var(--text);
  font-size: 17px;
  font-weight: var(--fw-bold, 700);
}

.admin-main :deep(.el-card__body) {
  padding: 22px;
}

.admin-main :deep(.el-table) {
  --el-table-border-color: var(--line);
  --el-table-header-bg-color: var(--surface-2);
  --el-table-row-hover-bg-color: var(--surface-2);
  color: var(--text-2);
  font-size: 14px;
}

.admin-main :deep(.el-table th.el-table__cell) {
  background: var(--surface-2);
  color: var(--text-3);
  font-weight: var(--fw-semibold, 600);
}

.admin-main :deep(.el-table td.el-table__cell) {
  border-bottom-color: var(--line);
}

.admin-main :deep(.el-table__empty-text) {
  color: var(--text-3);
}

.admin-main :deep(.el-input__wrapper),
.admin-main :deep(.el-select__wrapper),
.admin-main :deep(.el-textarea__inner) {
  border-radius: var(--r-3, 8px);
  box-shadow: 0 0 0 1px var(--line) inset;
}

.admin-main :deep(.el-button) {
  border-radius: var(--r-3, 8px);
  font-weight: var(--fw-semibold, 600);
}

.admin-main :deep(.el-button--primary) {
  border: 0;
  background: var(--brand);
  box-shadow: var(--sh-brand, 0 8px 22px -8px rgba(29, 78, 216, 0.32));
}

.admin-main :deep(.el-button--primary:hover) {
  background: var(--brand-hover);
}

.admin-main :deep(.el-tag) {
  border: 0;
  border-radius: var(--r-2, 6px);
  font-weight: var(--fw-semibold, 600);
}

.admin-main :deep(.el-alert) {
  border-radius: var(--r-4, 12px);
  border: 1px solid var(--line);
}

.admin-main :deep(.el-dialog) {
  border-radius: var(--r-5, 16px);
}

.admin-main :deep(.el-dialog__header) {
  padding: 20px 24px 14px;
  border-bottom: 1px solid var(--line);
}

.admin-main :deep(.el-dialog__body) {
  padding: 22px 24px;
}

.admin-main :deep(.el-dialog__footer) {
  padding: 14px 24px 22px;
  border-top: 1px solid var(--line);
}

@media (max-width: 1180px) {
  .admin-main :deep(.page-header) {
    align-items: flex-start;
    flex-direction: column;
  }

  .admin-main :deep(.page-actions) {
    width: 100%;
    justify-content: flex-start;
  }
}
</style>
