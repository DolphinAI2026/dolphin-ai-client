<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useUserStore } from '@/stores/user'
import { useThemeStore } from '@/stores/theme'

interface NavItem { key: string; label: string; icon: string; path: string; badge?: number }

const props = defineProps<{ collapsed?: boolean }>()
const route = useRoute()
const router = useRouter()
const user = useUserStore()
const theme = useThemeStore()

const RAIL_COLLAPSE_KEY = 'apaas-rail-collapsed-v1'
const internalCollapsed = ref<boolean>(localStorage.getItem(RAIL_COLLAPSE_KEY) === '1')
const appCount = ref<number | undefined>(undefined)
const codingWorkspaceCount = ref<number | undefined>(undefined)
const tenantMenuOpen = ref(false)

const effectiveCollapsed = computed(() =>
  props.collapsed === true ? true : internalCollapsed.value
)

const NAV = computed<NavItem[]>(() => [
  { key: 'home', label: '首页', icon: 'home', path: '/' },
  { key: 'apps', label: '应用', icon: 'apps', path: '/apps', badge: appCount.value || undefined },
  { key: 'builder', label: 'AI Builder', icon: 'chat', path: '/ai-chat?mode=requirements' },
  { key: 'coding', label: 'AI Coding', icon: 'code', path: '/coding', badge: codingWorkspaceCount.value || undefined },
  { key: 'marketplace', label: '组件市场', icon: 'store', path: '/marketplace' },
  // 数据接入 — DB 问数 wizard + 数据库连接管理
  { key: 'db-connections', label: '数据库连接', icon: 'database', path: '/db-connections' },
  { key: 'quick-db', label: 'DB 问数', icon: 'spark', path: '/quick-db' },
])

const userName = computed(() => user.user?.username || '未登录')
const tenantName = computed(() => user.user?.tenant_name || '未选择租户')
const tenantOptions = computed(() => user.availableTenants || [])
const currentTenantValue = computed(() => user.tenantId ? String(user.tenantId) : '')
const currentTenantLabel = computed(() => {
  const match = tenantOptions.value.find((tenant) => String(tenant.tenant_id) === currentTenantValue.value)
  return match?.tenant_name || tenantName.value
})
const isDark = computed(() => theme.mode === 'dark')
const platformActive = computed(() => route.path.startsWith('/platform-admin'))

function closeTenantMenu() {
  tenantMenuOpen.value = false
}

onMounted(async () => {
  try {
    const { applicationApi } = await import('@/api/application')
    const apps: any = (await applicationApi.list?.({ include_remote: false } as any)) ?? []
    appCount.value = Array.isArray(apps) ? apps.length : (apps?.items?.length ?? apps?.total ?? 0)
  } catch {
    appCount.value = undefined
  }

  try {
    const { codingApi } = await import('@/api/coding')
    const workspaces: any = (await (codingApi as any).listWorkspaces?.()) ?? []
    codingWorkspaceCount.value = Array.isArray(workspaces)
      ? workspaces.length
      : (workspaces?.items?.length ?? workspaces?.total ?? 0)
  } catch {
    codingWorkspaceCount.value = undefined
  }

  try {
    await user.fetchAvailableTenants()
  } catch {
    // Bottom tenant selector stays on current tenant when the list is unavailable.
  }

  window.addEventListener('click', closeTenantMenu)
})

onBeforeUnmount(() => {
  window.removeEventListener('click', closeTenantMenu)
})

function toggleCollapsed() {
  internalCollapsed.value = !internalCollapsed.value
  tenantMenuOpen.value = false
  try { localStorage.setItem(RAIL_COLLAPSE_KEY, internalCollapsed.value ? '1' : '0') } catch { /* private mode */ }
}

function isActive(path: string) {
  const basePath = path.split('?')[0]
  if (basePath === '/') return route.path === '/'
  return route.path === basePath || route.path.startsWith(basePath + '/')
}

function toggleTenantMenu(event: MouseEvent) {
  event.stopPropagation()
  tenantMenuOpen.value = !tenantMenuOpen.value
}

async function selectTenant(value: number) {
  tenantMenuOpen.value = false
  if (!Number.isFinite(value) || !value || value === user.tenantId) return
  await user.switchTenant(value)
  router.push('/')
}

function go(path: string) {
  tenantMenuOpen.value = false
  router.push(path)
}

function goPlatform() {
  tenantMenuOpen.value = false
  router.push('/platform-admin')
}

const ICONS: Record<string, string> = {
  home: '<path d="M3 11.5 12 4l9 7.5V20a1 1 0 0 1-1 1h-5v-6h-6v6H4a1 1 0 0 1-1-1z"/>',
  apps: '<path d="M3 5h7v7H3z"/><path d="M14 5h7v7h-7z"/><path d="M3 16h7v5H3z"/><path d="M14 16h7v5h-7z"/>',
  chat: '<path d="M21 12a8 8 0 0 1-11.9 7L4 21l1.6-4.4A8 8 0 1 1 21 12z"/>',
  code: '<path d="m9 17-5-5 5-5"/><path d="m15 7 5 5-5 5"/><path d="m13 5-2 14"/>',
  store: '<path d="M3 9 5 4h14l2 5"/><path d="M4 9v10a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1V9"/><path d="M3 9h18"/>',
  database: '<ellipse cx="12" cy="5" rx="9" ry="3"/><path d="M3 5v14a9 3 0 0 0 18 0V5"/><path d="M3 12a9 3 0 0 0 18 0"/>',
  spark: '<path d="M12 3 14 9l6 2-6 2-2 6-2-6-6-2 6-2z"/>',
  bldg: '<path d="M4 21V5l8-3 8 3v16"/><path d="M9 9h.01M9 13h.01M9 17h.01M15 9h.01M15 13h.01M15 17h.01"/><path d="M4 21h16"/>',
  shield: '<path d="M12 2 4 5v7c0 5 3.5 8.5 8 10 4.5-1.5 8-5 8-10V5z"/><path d="M9 12l2 2 4-4"/>',
  sun: '<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4 12H2M22 12h-2M6.3 6.3 4.9 4.9M19.1 19.1l-1.4-1.4M6.3 17.7l-1.4 1.4M19.1 4.9l-1.4 1.4"/>',
  moon: '<path d="M21 13A9 9 0 0 1 11 3a9 9 0 1 0 10 10z"/>',
  chevronLeft: '<polyline points="15 18 9 12 15 6"/>',
  chevronRight: '<polyline points="9 18 15 12 9 6"/>',
  chevronDown: '<polyline points="6 9 12 15 18 9"/>',
}

function renderIcon(name: string): string {
  const inner = ICONS[name] ?? ''
  return `<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">${inner}</svg>`
}
</script>

<template>
  <aside class="rail" :class="{ 'rail-collapsed': effectiveCollapsed }">
    <div class="rail-brand">
      <button
        class="rail-logo"
        type="button"
        :aria-label="effectiveCollapsed ? '展开导航' : '睿鲸AI 首页'"
        @click="effectiveCollapsed ? toggleCollapsed() : go('/')"
      >
        <svg width="17" height="17" viewBox="0 0 24 24" fill="none">
          <rect x="3" y="3" width="8" height="8" rx="2.2" fill="white" />
          <rect x="13" y="3" width="8" height="8" rx="2.2" fill="rgba(255,255,255,0.68)" />
          <rect x="3" y="13" width="8" height="8" rx="2.2" fill="rgba(255,255,255,0.68)" />
          <rect x="13" y="13" width="8" height="8" rx="2.2" fill="white" />
        </svg>
      </button>
      <div v-if="!effectiveCollapsed" class="rail-brand-copy">
        <div class="rail-title">睿鲸AI</div>
        <div class="rail-title-sub">AI · 低代码</div>
      </div>
    </div>

    <button
      v-if="effectiveCollapsed"
      type="button"
      class="rail-expand-top"
      title="展开导航"
      aria-label="展开导航"
      @click="toggleCollapsed"
    >
      <span v-html="renderIcon('chevronRight')" />
    </button>

    <nav class="rail-scroll" aria-label="主导航">
      <button
        v-for="it in NAV"
        :key="it.key"
        type="button"
        class="rail-item"
        :class="{ active: isActive(it.path) }"
        @click="go(it.path)"
      >
        <span class="rail-item-icon" v-html="renderIcon(it.icon)" />
        <span class="rail-item-label">{{ it.label }}</span>
        <span v-if="it.badge" class="rail-item-badge">{{ it.badge }}</span>
      </button>
    </nav>

    <div class="rail-foot">
      <button
        type="button"
        class="rail-collapse-btn"
        :title="effectiveCollapsed ? '展开导航' : '收起导航'"
        :aria-label="effectiveCollapsed ? '展开导航' : '收起导航'"
        @click="toggleCollapsed"
      >
        <span v-html="renderIcon(effectiveCollapsed ? 'chevronRight' : 'chevronLeft')" />
        <span v-if="!effectiveCollapsed">收起</span>
      </button>

      <div v-if="!effectiveCollapsed" class="rail-console">
        <div class="rail-console-label">当前租户</div>
        <div class="tenant-switch-wrap" @click.stop>
          <button
            type="button"
            class="tenant-switch"
            :class="{ open: tenantMenuOpen }"
            aria-haspopup="menu"
            :aria-expanded="tenantMenuOpen"
            @click="toggleTenantMenu"
          >
            <span class="tenant-icon" v-html="renderIcon('bldg')" />
            <span class="tenant-name">{{ currentTenantLabel }}</span>
            <span class="tenant-arrow" v-html="renderIcon('chevronDown')" />
          </button>
          <div v-if="tenantMenuOpen" class="tenant-menu" role="menu">
            <button
              v-for="tenant in tenantOptions"
              :key="tenant.tenant_id"
              type="button"
              class="tenant-option"
              :class="{ active: String(tenant.tenant_id) === currentTenantValue }"
              role="menuitem"
              @click="selectTenant(Number(tenant.tenant_id))"
            >
              {{ tenant.tenant_name }}
            </button>
            <div v-if="!tenantOptions.length" class="tenant-empty">暂无可切换租户</div>
          </div>
        </div>

        <button
          type="button"
          class="console-row platform-row"
          :class="{ active: platformActive }"
          @click="goPlatform"
        >
          <span class="console-row-icon" v-html="renderIcon('shield')" />
          <span>平台管理</span>
        </button>

        <div class="theme-row">
          <span class="theme-row-label">主题色</span>
          <label class="accent-picker" title="选择主题色">
            <input
              type="color"
              :value="theme.accentColor"
              aria-label="选择主题色"
              @input="theme.setAccentColor(($event.target as HTMLInputElement).value)"
            />
          </label>
          <button
            type="button"
            class="theme-toggle"
            :aria-label="isDark ? '切换浅色主题' : '切换深色主题'"
            @click="theme.toggle()"
          >
            <span v-html="renderIcon(isDark ? 'moon' : 'sun')" />
          </button>
        </div>

        <div class="account-row">
          <div class="rail-avatar">{{ userName.slice(0, 1).toUpperCase() }}</div>
          <div class="rail-user-info">
            <div class="rail-user-name">{{ userName }}</div>
            <div class="rail-user-status"><span />在线</div>
          </div>
        </div>
      </div>
    </div>
  </aside>
</template>

<style scoped>
.rail {
  width: 224px;
  height: 100%;
  display: flex;
  flex-direction: column;
  flex-shrink: 0;
  overflow: hidden;
  color: var(--text);
  background:
    linear-gradient(
      180deg,
      color-mix(in srgb, var(--brand-soft) 72%, #fff 28%) 0%,
      color-mix(in srgb, var(--brand-soft-2) 58%, #fff 42%) 100%
    );
  border-right: 1px solid rgba(58, 50, 121, 0.12);
}

.rail-collapsed {
  width: 48px;
}

.rail-brand {
  min-height: 76px;
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 16px 18px 14px;
}

.rail-logo {
  width: 36px;
  height: 36px;
  display: grid;
  place-items: center;
  flex-shrink: 0;
  color: #fff;
  background: linear-gradient(135deg, var(--brand-400), var(--brand-700));
  border: none;
  border-radius: 10px;
  box-shadow: 0 10px 22px rgba(91, 91, 214, 0.22), inset 0 -1px 0 rgba(255, 255, 255, 0.2);
  cursor: pointer;
}

.rail-title {
  color: #18152e;
  font-size: 17px;
  font-weight: 820;
  letter-spacing: 0;
  line-height: 1.1;
  white-space: nowrap;
}

.rail-title-sub {
  margin-top: 4px;
  color: #817ba0;
  font-size: 12px;
  font-weight: 650;
  white-space: nowrap;
}

.rail-scroll {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
  gap: 6px;
  overflow-y: auto;
  padding: 12px 14px 10px;
}

.rail-expand-top {
  width: 34px;
  height: 30px;
  display: grid;
  place-items: center;
  flex-shrink: 0;
  margin: -4px auto 6px;
  color: var(--brand-text);
  background: rgba(255, 255, 255, 0.72);
  border: 1px solid rgba(91, 91, 214, 0.18);
  border-radius: 9px;
  cursor: pointer;
  box-shadow: var(--shadow-xs);
  transition: background 0.14s, border-color 0.14s, transform 0.14s;
}

.rail-expand-top:hover {
  background: #fff;
  border-color: rgba(91, 91, 214, 0.34);
  transform: translateX(1px);
}

.rail-item {
  position: relative;
  width: 100%;
  min-height: 42px;
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 0 14px;
  color: #565171;
  background: transparent;
  border: 1px solid transparent;
  border-radius: 10px;
  font-family: inherit;
  font-size: 14px;
  font-weight: 720;
  text-align: left;
  cursor: pointer;
  transition: background 0.16s, color 0.16s, border-color 0.16s, box-shadow 0.16s;
}

.rail-item:hover {
  color: var(--brand-text);
  background: rgba(255, 255, 255, 0.7);
}

.rail-item.active {
  color: var(--brand-text);
  background: rgba(230, 227, 253, 0.88);
  border-color: rgba(91, 91, 214, 0.16);
  box-shadow: inset 3px 0 0 var(--brand);
}

.rail-item-icon {
  width: 18px;
  height: 18px;
  display: grid;
  place-items: center;
  flex-shrink: 0;
  color: currentColor;
}

.rail-item-label {
  flex: 1;
  min-width: 0;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.rail-item-badge {
  min-width: 18px;
  height: 18px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  padding: 0 7px;
  border-radius: 999px;
  color: var(--brand-text);
  background: rgba(255, 255, 255, 0.8);
  font-size: 10px;
  font-weight: 800;
}

.rail-foot {
  padding: 10px 12px 14px;
  border-top: 1px solid rgba(58, 50, 121, 0.10);
}

.rail-collapse-btn {
  width: 100%;
  min-height: 30px;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  margin-bottom: 8px;
  color: #8b85a8;
  background: rgba(255, 255, 255, 0.34);
  border: 1px solid rgba(58, 50, 121, 0.10);
  border-radius: 8px;
  font-family: inherit;
  font-size: 12px;
  font-weight: 650;
  cursor: pointer;
}

.rail-collapse-btn:hover {
  color: var(--brand-text);
  background: rgba(255, 255, 255, 0.74);
}

.rail-console {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 10px;
  border: 1px solid rgba(91, 91, 214, 0.18);
  border-radius: 14px;
  background: rgba(246, 244, 255, 0.92);
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.72);
}

.rail-console-label {
  color: #837ea0;
  font-size: 11px;
  font-weight: 760;
}

.tenant-switch,
.console-row,
.theme-row,
.account-row {
  min-height: 42px;
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 0 10px;
  border: 1px solid rgba(91, 91, 214, 0.13);
  border-radius: 10px;
  background: rgba(255, 255, 255, 0.86);
  box-shadow: var(--shadow-xs);
}

.tenant-switch-wrap {
  position: relative;
}

.tenant-icon,
.console-row-icon {
  width: 22px;
  height: 22px;
  display: grid;
  place-items: center;
  flex-shrink: 0;
  color: var(--brand-text);
}

.tenant-switch {
  width: 100%;
  color: #211d3a;
  font-family: inherit;
  font-size: 13px;
  font-weight: 780;
  cursor: pointer;
  text-align: left;
}

.tenant-switch:hover,
.tenant-switch.open {
  color: var(--brand-text);
  border-color: rgba(91, 91, 214, 0.32);
  background: #fff;
}

.tenant-name {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.tenant-arrow {
  width: 16px;
  height: 16px;
  display: grid;
  place-items: center;
  flex-shrink: 0;
  color: #8b85a8;
  transition: transform 0.14s;
}

.tenant-switch.open .tenant-arrow {
  transform: rotate(180deg);
}

.tenant-menu {
  position: absolute;
  left: 0;
  right: 0;
  bottom: calc(100% + 6px);
  z-index: 20;
  max-height: 220px;
  overflow-y: auto;
  padding: 6px;
  border: 1px solid rgba(91, 91, 214, 0.18);
  border-radius: 12px;
  background: rgba(255, 255, 255, 0.98);
  box-shadow: 0 16px 36px rgba(28, 21, 73, 0.16);
}

.tenant-option {
  width: 100%;
  min-height: 34px;
  padding: 0 10px;
  color: #211d3a;
  background: transparent;
  border: none;
  border-radius: 8px;
  font-family: inherit;
  font-size: 12px;
  font-weight: 720;
  text-align: left;
  cursor: pointer;
}

.tenant-option:hover,
.tenant-option.active {
  color: var(--brand-text);
  background: var(--brand-soft);
}

.tenant-empty {
  padding: 8px 10px;
  color: var(--text-3);
  font-size: 12px;
  font-weight: 650;
}

.console-row {
  width: 100%;
  color: #211d3a;
  font-family: inherit;
  font-size: 13px;
  font-weight: 780;
  cursor: pointer;
}

.console-row:hover {
  color: var(--brand-text);
  border-color: rgba(91, 91, 214, 0.32);
  background: #fff;
}

.console-row.active {
  color: var(--brand-text);
  border-color: rgba(91, 91, 214, 0.24);
  background: var(--brand-soft);
}

.theme-row {
  min-height: 48px;
  justify-content: space-between;
  color: #565171;
  font-size: 12px;
  font-weight: 760;
}

.theme-row-label {
  white-space: nowrap;
}

.accent-picker {
  width: 30px;
  height: 26px;
  display: grid;
  place-items: center;
  margin-left: auto;
  padding: 3px;
  border: 1px solid rgba(91, 91, 214, 0.18);
  border-radius: 8px;
  background: var(--surface);
  cursor: pointer;
}

.accent-picker input {
  width: 22px;
  height: 18px;
  padding: 0;
  border: none;
  border-radius: 5px;
  background: transparent;
  cursor: pointer;
}

.accent-picker input::-webkit-color-swatch-wrapper {
  padding: 0;
}

.accent-picker input::-webkit-color-swatch {
  border: none;
  border-radius: 5px;
}

.theme-toggle {
  width: 30px;
  height: 26px;
  display: grid;
  place-items: center;
  color: var(--brand-text);
  background: var(--brand-soft);
  border: 1px solid rgba(91, 91, 214, 0.18);
  border-radius: 999px;
  cursor: pointer;
}

.account-row {
  min-height: 50px;
}

.rail-avatar {
  width: 30px;
  height: 30px;
  display: grid;
  place-items: center;
  flex-shrink: 0;
  color: #fff;
  background: linear-gradient(135deg, var(--brand-400), var(--brand-700));
  border-radius: 50%;
  font-size: 13px;
  font-weight: 820;
  box-shadow: 0 8px 18px rgba(91, 91, 214, 0.2);
}

.rail-user-info {
  min-width: 0;
}

.rail-user-name {
  color: #211d3a;
  font-size: 13px;
  font-weight: 820;
  line-height: 1.2;
}

.rail-user-status {
  display: flex;
  align-items: center;
  gap: 5px;
  margin-top: 3px;
  color: #7f789f;
  font-size: 11px;
  font-weight: 650;
}

.rail-user-status span {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: #22c55e;
  box-shadow: 0 0 0 2px rgba(34, 197, 94, 0.14);
}

.rail-collapsed .rail-brand {
  justify-content: center;
  padding: 14px 6px;
}

.rail-collapsed .rail-scroll {
  padding: 10px 6px;
}

.rail-collapsed .rail-item {
  justify-content: center;
  padding: 0;
}

.rail-collapsed .rail-item-label,
.rail-collapsed .rail-item-badge {
  display: none;
}

.rail-collapsed .rail-foot {
  padding: 8px 6px;
}

.rail-collapsed .rail-collapse-btn {
  margin-bottom: 0;
}

html[data-theme="dark"] .rail {
  background: var(--bg-rail);
}

html[data-theme="dark"] .rail-title,
html[data-theme="dark"] .tenant-switch,
html[data-theme="dark"] .tenant-option,
html[data-theme="dark"] .console-row,
html[data-theme="dark"] .rail-user-name {
  color: var(--text);
}

html[data-theme="dark"] .rail-console,
html[data-theme="dark"] .tenant-switch,
html[data-theme="dark"] .console-row,
html[data-theme="dark"] .theme-row,
html[data-theme="dark"] .account-row {
  background: var(--surface);
}

html[data-theme="dark"] .tenant-menu {
  background: var(--surface);
  border-color: var(--border-strong);
}

html[data-theme="dark"] .tenant-switch:hover,
html[data-theme="dark"] .tenant-switch.open,
html[data-theme="dark"] .console-row:hover {
  background: var(--surface-2);
}
</style>
