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

    <div class="sidebar-nav">
      <template v-for="item in primaryNavItems" :key="item.key">
        <button
          class="nav-item"
          :class="{ active: activeKey === item.key }"
          :title="item.label"
          @click="navigateTo(item.path)"
        >
          <!-- home — 智能搭建 (构建) -->
          <svg v-if="item.key === 'home'" class="nav-icon" viewBox="0 0 16 16" fill="currentColor" aria-hidden="true">
            <rect x="2" y="3" width="12" height="2" rx="1" />
            <rect x="2" y="7" width="8" height="2" rx="1" />
            <rect x="2" y="11" width="10" height="2" rx="1" />
          </svg>
          <!-- coding — 智能开发 -->
          <svg v-else-if="item.key === 'coding'" class="nav-icon" viewBox="0 0 16 16" fill="none" aria-hidden="true">
            <path d="M4.5 5L2 8l2.5 3M11.5 5L14 8l-2.5 3M9.5 4l-3 8" stroke="currentColor" stroke-width="1.3" stroke-linecap="round" stroke-linejoin="round" />
          </svg>
          <!-- datasources — 数据源 (database cylinder) -->
          <svg v-else-if="item.key === 'datasources'" class="nav-icon" viewBox="0 0 16 16" fill="none" aria-hidden="true">
            <ellipse cx="8" cy="3.5" rx="5" ry="1.8" stroke="currentColor" stroke-width="1.3" />
            <path d="M3 3.5v9c0 1 2.2 1.8 5 1.8s5-.8 5-1.8v-9" stroke="currentColor" stroke-width="1.3" stroke-linecap="round" />
            <path d="M3 8c0 1 2.2 1.8 5 1.8s5-.8 5-1.8" stroke="currentColor" stroke-width="1.3" />
          </svg>
          <!-- apis — 接口 (plug / link) -->
          <svg v-else-if="item.key === 'apis'" class="nav-icon" viewBox="0 0 16 16" fill="none" aria-hidden="true">
            <path d="M7 9L4.5 11.5a2 2 0 1 1-2.8-2.8L4 6.5" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" />
            <path d="M9 7l2.5-2.5a2 2 0 1 1 2.8 2.8L12 9.5" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" />
            <path d="M6.5 9.5l3-3" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" />
          </svg>
          <!-- docs — 文档 -->
          <svg v-else-if="item.key === 'docs'" class="nav-icon" viewBox="0 0 16 16" fill="none" aria-hidden="true">
            <path d="M3.5 2h6.3L13 5.2v8.3a1 1 0 0 1-1 1H3.5a1 1 0 0 1-1-1V3a1 1 0 0 1 1-1z" stroke="currentColor" stroke-width="1.3" stroke-linejoin="round" />
            <path d="M9.5 2v3.5H13" stroke="currentColor" stroke-width="1.3" stroke-linejoin="round" />
            <path d="M5.5 8.5h5M5.5 11h5M5.5 6h2.5" stroke="currentColor" stroke-width="1.2" stroke-linecap="round" />
          </svg>
          <!-- reports — 报表 (bar chart) -->
          <svg v-else-if="item.key === 'reports'" class="nav-icon" viewBox="0 0 16 16" fill="none" aria-hidden="true">
            <rect x="2.5" y="9" width="2.5" height="4.5" rx="0.4" stroke="currentColor" stroke-width="1.3" />
            <rect x="6.75" y="6" width="2.5" height="7.5" rx="0.4" stroke="currentColor" stroke-width="1.3" />
            <rect x="11" y="3.5" width="2.5" height="10" rx="0.4" stroke="currentColor" stroke-width="1.3" />
          </svg>
          <!-- models — 模型 (cube stack) -->
          <svg v-else-if="item.key === 'models'" class="nav-icon" viewBox="0 0 16 16" fill="none" aria-hidden="true">
            <path d="M8 2.2L13.3 5 8 7.8 2.7 5 8 2.2z" stroke="currentColor" stroke-width="1.3" stroke-linejoin="round" />
            <path d="M2.7 5v6L8 13.8 13.3 11V5" stroke="currentColor" stroke-width="1.3" stroke-linejoin="round" />
            <path d="M8 7.8v6" stroke="currentColor" stroke-width="1.3" />
          </svg>
          <!-- manage — 管理 (gear) -->
          <svg v-else-if="item.key === 'manage'" class="nav-icon" viewBox="0 0 16 16" fill="none" aria-hidden="true">
            <circle cx="8" cy="8" r="2.2" stroke="currentColor" stroke-width="1.3" />
            <path d="M8 1.5v2M8 12.5v2M14.5 8h-2M3.5 8h-2M12.6 3.4l-1.4 1.4M4.8 11.2l-1.4 1.4M12.6 12.6l-1.4-1.4M4.8 4.8L3.4 3.4" stroke="currentColor" stroke-width="1.3" stroke-linecap="round" />
          </svg>
          <span class="nav-label">{{ item.label }}</span>
        </button>
      </template>
    </div>

    <div class="sidebar-divider"></div>

    <div class="sidebar-bottom">
      <el-dropdown trigger="click" @command="handleUserCommand" @visible-change="onDropdownVisibleChange" class="user-dropdown">
        <button class="user-row" :title="userStore.user?.username || 'admin'">
          <span class="user-avatar">{{ userInitial }}</span>
          <span class="user-name">{{ userStore.user?.username || 'admin' }}</span>
        </button>
        <template #dropdown>
          <el-dropdown-menu class="user-menu">
            <el-popover
              trigger="manual"
              placement="right-start"
              :show-arrow="false"
              :width="220"
              popper-class="tenant-popover"
              :visible="tenantPopoverVisible"
              @show="onTenantPopoverShow"
            >
              <template #reference>
                <div class="menu-item tenant-trigger" @click.stop="tenantPopoverVisible = !tenantPopoverVisible">
                  <span class="menu-row">
                    <svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
                      <path d="M2.5 13.5V5l5.5-3 5.5 3v8.5"/>
                      <path d="M2.5 13.5h11"/>
                      <path d="M6.5 13.5v-3h3v3"/>
                    </svg>
                    <span class="tenant-trigger-name">{{ userStore.tenantName || '未选择租户' }}</span>
                  </span>
                  <svg class="chevron" width="12" height="12" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
                    <path d="M6 4l4 4-4 4"/>
                  </svg>
                </div>
              </template>
              <div class="tenant-list" v-loading="tenantsLoading">
                <div class="tenant-list-title">切换租户</div>
                <button
                  v-for="t in myTenants"
                  :key="t.tenant_id"
                  class="tenant-option"
                  :class="{ active: t.tenant_id === userStore.tenantId }"
                  @click="onTenantOptionClick(t.tenant_id)"
                >
                  <span class="tenant-option-name">{{ t.tenant_name }}</span>
                  <svg v-if="t.tenant_id === userStore.tenantId" width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
                    <path d="M3 8.5l3 3 7-7"/>
                  </svg>
                </button>
                <div v-if="!tenantsLoading && myTenants.length === 0" class="tenant-empty">没有可切换的租户</div>
              </div>
            </el-popover>
            <el-dropdown-item
              v-if="userStore.isPlatformAdmin"
              command="admin"
              divided
            >
              <span class="menu-row">
                <svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
                  <circle cx="8" cy="8" r="2.2"/>
                  <path d="M8 1.5v2M8 12.5v2M14.5 8h-2M3.5 8h-2M12.6 3.4l-1.4 1.4M4.8 11.2l-1.4 1.4M12.6 12.6l-1.4-1.4M4.8 4.8L3.4 3.4"/>
                </svg>
                平台管理
              </span>
            </el-dropdown-item>
            <el-dropdown-item command="logout" divided>
              <span class="menu-row danger">
                <svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
                  <path d="M6 14H3.5A1.5 1.5 0 0 1 2 12.5v-9A1.5 1.5 0 0 1 3.5 2H6"/>
                  <path d="M11 11l3-3-3-3"/>
                  <path d="M14 8H6"/>
                </svg>
                退出登录
              </span>
            </el-dropdown-item>
          </el-dropdown-menu>
        </template>
      </el-dropdown>
    </div>
  </aside>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useUserStore } from '@/stores/user'
import { authApi } from '@/api/auth'
import type { TenantOption } from '@/types'

const router = useRouter()
const route = useRoute()
const userStore = useUserStore()
const expanded = ref(true)

const primaryNavItems = [
  { key: 'home', label: '智能搭建', path: '/' },
  { key: 'coding', label: '智能开发', path: '/coding' },
  { key: 'datasources', label: '数据源', path: '/datasources' },
]

const activeKey = computed(() => {
  const p = route.path
  if (p === '/' || p.startsWith('/apps')) return 'home'
  if (p.startsWith('/coding')) return 'coding'
  if (p.startsWith('/datasources')) return 'datasources'
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

const myTenants = ref<TenantOption[]>([])
const tenantsLoading = ref(false)
const tenantPopoverVisible = ref(false)

async function loadMyTenants() {
  tenantsLoading.value = true
  try {
    myTenants.value = await authApi.myTenants()
  } catch {
    myTenants.value = []
  } finally {
    tenantsLoading.value = false
  }
}

function onDropdownVisibleChange(visible: boolean) {
  if (visible) {
    loadMyTenants()
  } else {
    tenantPopoverVisible.value = false
  }
}

function onTenantPopoverShow() {
  tenantPopoverVisible.value = true
  if (myTenants.value.length === 0) loadMyTenants()
}

async function onTenantOptionClick(tenantId: number) {
  if (!tenantId || tenantId === userStore.tenantId) {
    tenantPopoverVisible.value = false
    return
  }
  try {
    await userStore.switchTenant(tenantId)
    ElMessage.success('已切换租户')
    router.go(0)
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '切换失败')
  } finally {
    tenantPopoverVisible.value = false
  }
}

async function handleUserCommand(command: string | number | object) {
  if (command === 'admin') {
    router.push('/admin')
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

/* User dropdown menu */
.user-menu { padding: 6px; min-width: 220px; }
.user-menu :deep(.el-dropdown-menu__item) {
  border-radius: 8px;
  margin: 2px 0;
  padding: 8px 10px;
  font-size: 13px;
  line-height: 1.3;
}
.user-menu :deep(.el-dropdown-menu__item--divided) {
  margin-top: 6px;
}
.user-menu :deep(.el-dropdown-menu__item--divided)::before {
  margin: 4px 6px;
  background: var(--t-border-subtle, rgba(125,132,181,0.18));
}

.menu-row {
  display: inline-flex;
  align-items: center;
  gap: 9px;
  width: 100%;
  color: var(--t-text-primary, #1f2347);
}
.menu-row svg { color: var(--t-text-muted, #7d84b5); flex-shrink: 0; }
.menu-row.danger,
.menu-row.danger svg { color: var(--t-danger, #ef4444); }

/* Tenant trigger — styled like a menu-item with chevron */
.menu-item.tenant-trigger {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  padding: 8px 10px;
  margin: 2px 0;
  border-radius: 8px;
  cursor: pointer;
  font-size: 13px;
  line-height: 1.3;
  color: var(--t-text-primary, #1f2347);
  transition: background 0.15s;
}
.menu-item.tenant-trigger:hover { background: rgba(90, 79, 208, 0.08); }
.tenant-trigger-name {
  font-weight: 500;
  max-width: 140px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.menu-item.tenant-trigger .chevron { color: var(--t-text-muted, #7d84b5); flex-shrink: 0; }

/* Tenant popover (sub-menu) */
.tenant-list { padding: 4px 2px; }
.tenant-list-title {
  font-size: 11px;
  color: var(--t-text-muted, #94a0b8);
  text-transform: uppercase;
  letter-spacing: 0.06em;
  padding: 4px 10px 6px;
  font-weight: 600;
}
.tenant-option {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  width: 100%;
  padding: 8px 10px;
  border: none;
  background: transparent;
  border-radius: 8px;
  font-size: 13px;
  color: var(--t-text-primary, #1f2347);
  cursor: pointer;
  text-align: left;
  transition: background 0.15s;
}
.tenant-option:hover { background: rgba(90, 79, 208, 0.08); }
.tenant-option.active {
  color: var(--t-brand, #5a4fd0);
  font-weight: 500;
  background: rgba(90, 79, 208, 0.06);
}
.tenant-option.active svg { color: var(--t-brand, #5a4fd0); }
.tenant-option-name {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.tenant-empty {
  padding: 10px;
  font-size: 12px;
  color: var(--t-text-muted, #94a0b8);
  text-align: center;
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
