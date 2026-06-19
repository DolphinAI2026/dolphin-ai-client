<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { checkAndPromptUpdate } from '@/utils/desktop'
import { useUserStore } from '@/stores/user'
import { useThemeStore } from '@/stores/theme'
import ruijingWhaleMarkUrl from '@/assets/brand/ruijing-whale-mark.svg'

interface NavItem { key: string; label: string; icon: string; path: string; badge?: number }

const props = defineProps<{ collapsed?: boolean }>()
const route = useRoute()
const router = useRouter()
const user = useUserStore()
const theme = useThemeStore()

const RAIL_COLLAPSE_KEY = 'apaas-rail-collapsed-v1'
const internalCollapsed = ref<boolean>(localStorage.getItem(RAIL_COLLAPSE_KEY) === '1')
const appCount = ref<number | undefined>(undefined)
const tenantMenuOpen = ref(false)

const effectiveCollapsed = computed(() =>
  props.collapsed === true ? true : internalCollapsed.value
)

// 桌面包剔除指向 admin-spa 的路由（meta.desktop === 'hidden'）；
// 在线版此函数恒返回 false，tree-shake 后零开销。
function desktopHidden(path: string): boolean {
  if (!__DESKTOP__) return false
  try { return (router.resolve(path).meta as any)?.desktop === 'hidden' } catch { return false }
}

const NAV = computed<NavItem[]>(() => {
  const all: NavItem[] = [
    { key: 'home', label: 'AI Builder', icon: 'chat', path: '/' },
    // 临时入口: Phase 1 统一工作区预览; Phase 4 导航收口时再正式编排/移除。
    { key: 'workspace', label: '统一工作区(预览)', icon: 'flow', path: '/workspace' },
    { key: 'apps', label: '应用资产库', icon: 'apps', path: '/apps', badge: appCount.value || undefined },
    { key: 'catalog', label: '自开发资产库', icon: 'store', path: '/workspace-catalog' },
    { key: 'skills', label: '技能库', icon: 'sparkles', path: '/skills' },
    { key: 'tenantLogs', label: '租户日志分析', icon: 'activity', path: '/tenant-logs' },
    // AI Builder（/）= 首页融合页，与 /ai-chat 同组件：新建对话 + 历史会话一体。
    // 改已有应用从「应用资产库」点进工作室 (/chat)，/chat 不挂菜单。
    // 数据连接 / 运行发布先隐藏；平台级配置统一从平台管理工作台进入。
  ]
  return all.filter(item => !desktopHidden(item.path))
})
// 桌面包不含 admin-spa, /platform-admin 内嵌 iframe 会白屏; 桌面下直接进自渲染的配置页 /platform-envs。
const platformNavItem: NavItem = __DESKTOP__
  ? { key: 'platform', label: '平台配置', icon: 'shield', path: '/platform-envs' }
  : { key: 'platform', label: '平台管理', icon: 'shield', path: '/platform-admin' }

const userAccount = computed(() => user.user?.username || '')
const userName = computed(() => user.user?.display_name || userAccount.value || '未登录')
const userAvatarText = computed(() => Array.from(userName.value.trim())[0]?.toUpperCase() || 'U')
const tenantOptions = computed(() => user.availableTenants || [])
const currentTenantValue = computed(() => user.tenantId ? String(user.tenantId) : '')
function looksLikeLongId(value?: string | null) {
  return /^\d{12,}$/.test(String(value || '').trim())
}

function tenantLabel(tenant?: { tenant_name?: string | null; tenant_code?: string | null; tenant_id?: number | string | null }) {
  const name = String(tenant?.tenant_name || '').trim()
  const code = String(tenant?.tenant_code || '').trim()
  if (name && !looksLikeLongId(name)) return name
  if (code && !looksLikeLongId(code)) return code
  return name || code || (tenant?.tenant_id ? `租户 ${tenant.tenant_id}` : '未选择租户')
}

const currentTenantLabel = computed(() => {
  const match = tenantOptions.value.find((tenant) => String(tenant.tenant_id) === currentTenantValue.value)
  return tenantLabel(match || {
    tenant_name: user.user?.tenant_name,
    tenant_code: undefined,
    tenant_id: user.tenantId,
  })
})
const isDark = computed(() => theme.mode === 'dark')
const platformActive = computed(() => route.path.startsWith(platformNavItem.path))
const platformHref = computed(() => resolveHref(platformNavItem.path))
// 桌面: 租户管理员就能进 /platform-envs 配自己的 LLM/aPaaS(每人独立租户)。
// 在线版: 那条入口指向 admin-spa(仅平台管理员), 保持 isPlatformAdmin 避免租户管理员点进去被弹。
const platformEntryVisible = computed(() => __DESKTOP__ ? user.isTenantAdmin : user.isPlatformAdmin)

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
  // AI Builder（/）= 融合页，/ai-chat 系列是同一功能，一并高亮。
  if (basePath === '/') return route.path === '/' || route.path.startsWith('/ai-chat')
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

function goPlatformAdmin() {
  tenantMenuOpen.value = false
  router.push(platformNavItem.path)
}

// 2026-05-23: rail nav 改 <a href> 让 Cmd+click / 中键 / 右键"在新标签中打开"
// 真开 chrome tab — 跟 admin-spa AdminLayout 一致体验
function resolveHref(path: string): string {
  try {
    return router.resolve(path).href
  } catch {
    return path
  }
}

function onMenuClick(e: MouseEvent, item: NavItem) {
  // modifier / 中键 → 浏览器原生开新 chrome tab，不拦
  if (e.metaKey || e.ctrlKey || e.shiftKey || e.altKey || e.button !== 0) {
    return
  }
  e.preventDefault()
  go(item.path)
}

function onPlatformClick(e: MouseEvent) {
  if (e.metaKey || e.ctrlKey || e.shiftKey || e.altKey || e.button !== 0) {
    return
  }
  e.preventDefault()
  goPlatformAdmin()
}

// __DESKTOP__/__APP_VERSION__ 是编译期常量, 但直接写进 <template> 会被 Vue 当成
// 组件实例属性(_ctx.__DESKTOP__)而 Vite define 不替换点号后属性 → 永远 undefined。
// 必须经脚本 const 暴露给模板。
const isDesktop = __DESKTOP__
const appVersion = __APP_VERSION__

// 桌面端手动检查更新(在线版不渲染按钮)。silentIfNone=false → 已是最新也提示。
function onCheckUpdate() {
  void checkAndPromptUpdate({ silentIfNone: false })
}

function onLogout() {
  tenantMenuOpen.value = false
  user.logout()
  // 退出只清认证态。主题、布局偏好等本地设置保留，避免登录页颜色模式被重置或半切换。
  try { localStorage.removeItem('ai-builder-tabs-v1') } catch { /* private mode */ }
  router.push({ path: '/login' })
}

// v3 2026-05-20: ACCENT_PRESETS 主题色 picker 删 — 让 admin/frontend brand 始终一致蓝色
// theme.ts 默认 #1D4ED8 v3 blue 不再被 user picker 覆盖
const ICONS: Record<string, string> = {
  home: '<path d="M3 11.5 12 4l9 7.5V20a1 1 0 0 1-1 1h-5v-6h-6v6H4a1 1 0 0 1-1-1z"/>',
  apps: '<path d="M3 5h7v7H3z"/><path d="M14 5h7v7h-7z"/><path d="M3 16h7v5H3z"/><path d="M14 16h7v5h-7z"/>',
  chat: '<path d="M21 12a8 8 0 0 1-11.9 7L4 21l1.6-4.4A8 8 0 1 1 21 12z"/>',
  code: '<path d="m9 17-5-5 5-5"/><path d="m15 7 5 5-5 5"/><path d="m13 5-2 14"/>',
  store: '<path d="M3 9 5 4h14l2 5"/><path d="M4 9v10a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1V9"/><path d="M3 9h18"/>',
  database: '<ellipse cx="12" cy="5" rx="9" ry="3"/><path d="M3 5v14a9 3 0 0 0 18 0V5"/><path d="M3 12a9 3 0 0 0 18 0"/>',
  activity: '<polyline points="22 12 18 12 15 21 9 3 6 12 2 12"/><path d="M4 19h16"/>',
  spark: '<path d="M12 3 14 9l6 2-6 2-2 6-2-6-6-2 6-2z"/>',
  sparkles: '<path d="M9 4 10 7 13 8 10 9 9 12 8 9 5 8 8 7z"/><path d="M17 3l.7 2.3L20 6l-2.3.7L17 9l-.7-2.3L14 6l2.3-.7z"/><path d="M16 15l1 2.5 2.5 1-2.5 1-1 2.5-1-2.5-2.5-1 2.5-1z"/>',
  bldg: '<path d="M4 21V5l8-3 8 3v16"/><path d="M9 9h.01M9 13h.01M9 17h.01M15 9h.01M15 13h.01M15 17h.01"/><path d="M4 21h16"/>',
  shield: '<path d="M12 2 4 5v7c0 5 3.5 8.5 8 10 4.5-1.5 8-5 8-10V5z"/><path d="M9 12l2 2 4-4"/>',
  sun: '<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4 12H2M22 12h-2M6.3 6.3 4.9 4.9M19.1 19.1l-1.4-1.4M6.3 17.7l-1.4 1.4M19.1 4.9l-1.4 1.4"/>',
  moon: '<path d="M21 13A9 9 0 0 1 11 3a9 9 0 1 0 10 10z"/>',
  chevronLeft: '<polyline points="15 18 9 12 15 6"/>',
  chevronRight: '<polyline points="9 18 15 12 9 6"/>',
  chevronDown: '<polyline points="6 9 12 15 18 9"/>',
  logout: '<path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/><polyline points="16 17 21 12 16 7"/><line x1="21" y1="12" x2="9" y2="12"/>',
  refresh: '<path d="M21 12a9 9 0 1 1-2.6-6.4"/><polyline points="21 3 21 9 15 9"/>',
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
        <img class="rail-logo-mark" :src="ruijingWhaleMarkUrl" alt="" aria-hidden="true" />
      </button>
      <div v-if="!effectiveCollapsed" class="rail-brand-copy">
        <div class="rail-title">睿鲸AI</div>
      </div>
      <!-- 收起按钮放在 brand 区右侧 — 跟 SessionSidebar 的 « 按钮位置一致，
           比放底部更顺手。展开 / 收起两个状态用同一个 button，方向不一样。 -->
      <button
        v-if="!effectiveCollapsed"
        type="button"
        class="rail-collapse-top"
        title="收起导航"
        aria-label="收起导航"
        @click="toggleCollapsed"
      >
        <span v-html="renderIcon('chevronLeft')" />
      </button>
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
      <!-- 2026-05-23: button → <a href> 让 cmd+click / 中键 / 右键"在新标签中打开" 真开 chrome tab.
           普通 click → router.push 直接导航 (2026-06-08 已删多 tab 体系). -->
      <a
        v-for="it in NAV"
        :key="it.key"
        :href="resolveHref(it.path)"
        class="rail-item"
        :class="{ active: isActive(it.path) }"
        :title="`${it.label} (Cmd+点 在新标签中打开)`"
        @click="onMenuClick($event, it)"
        @auxclick="onMenuClick($event, it)"
      >
        <span class="rail-item-icon" v-html="renderIcon(it.icon)" />
        <span class="rail-item-label">{{ it.label }}</span>
        <span v-if="it.badge" class="rail-item-badge">{{ it.badge }}</span>
      </a>
    </nav>

    <div class="rail-foot">
      <!-- 老的 .rail-collapse-btn 已移到顶部 brand 区，这里删掉减少重复入口 -->

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
            <span class="tenant-name" :title="user.user?.tenant_name || currentTenantLabel">{{ currentTenantLabel }}</span>
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
              <span class="tenant-option-name" :title="tenant.tenant_name">{{ tenantLabel(tenant) }}</span>
              <span v-if="tenant.tenant_code && tenant.tenant_code !== tenantLabel(tenant)" class="tenant-option-code">{{ tenant.tenant_code }}</span>
            </button>
            <div v-if="!tenantOptions.length" class="tenant-empty">暂无可切换租户</div>
          </div>
        </div>

        <a
          v-if="platformEntryVisible && !desktopHidden(platformNavItem.path)"
          class="console-row platform-row"
          :class="{ active: platformActive }"
          :href="platformHref"
          title="平台管理"
          @click="onPlatformClick"
          @auxclick="onPlatformClick"
        >
          <span class="console-row-icon" v-html="renderIcon('shield')" />
          <span>平台管理</span>
          <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="margin-left:auto;opacity:0.5">
            <path d="M7 17 17 7" />
            <path d="M7 7h10v10" />
          </svg>
        </a>

        <!-- v3 2026-05-20: 删主题色 picker 让 admin/frontend brand 始终一致蓝；只保留浅深切换 -->
        <!-- 2026-05-21 整 row 改成 button — 之前 label 跟太阳 icon 视觉分离体验割裂。
             现在 icon + 文字 + 切换方向提示一体，跟 admin-spa AdminLayout 一致 -->
        <button
          type="button"
          class="theme-row"
          :aria-label="isDark ? '切换到浅色模式' : '切换到深色模式'"
          @click="theme.toggle()"
        >
          <span class="theme-row-icon" v-html="renderIcon(isDark ? 'moon' : 'sun')" />
          <span class="theme-row-label">{{ isDark ? '深色模式 · 切到浅色' : '浅色模式 · 切到深色' }}</span>
        </button>

        <!-- 桌面端: 版本号 + 手动检查更新(在线版不渲染) -->
        <button
          v-if="isDesktop"
          type="button"
          class="theme-row"
          :title="`当前版本 v${appVersion} · 点击检查更新`"
          @click="onCheckUpdate"
        >
          <span class="theme-row-icon" v-html="renderIcon('refresh')" />
          <span class="theme-row-label">检查更新<span v-if="appVersion" class="rail-version">v{{ appVersion }}</span></span>
        </button>

        <div class="account-row">
          <div class="rail-avatar">{{ userAvatarText }}</div>
          <div class="rail-user-info">
            <div class="rail-user-name" :title="userName">{{ userName }}</div>
            <div class="rail-user-status" :title="userAccount || userName"><span />{{ userAccount || '在线' }}</div>
          </div>
          <button
            type="button"
            class="account-logout"
            title="退出登录"
            aria-label="退出登录"
            @click="onLogout"
          >
            <span v-html="renderIcon('logout')" />
          </button>
        </div>
      </div>
    </div>
  </aside>
</template>

<style scoped>
/* v3 redesign · 2026-05-20 — visual refresh only, template/script structure preserved.
   Phase 8A.1 + 8A.2:
     - Collapsed (56px) → centered 38×38 icons, active 3px left bar + brand-soft
     - Expanded (224px) → surface-2 bg, brand title, brand-soft active state, line dividers
     - Accent picker → 6-preset palette + custom rainbow swatch (template tweak in 8A.2)
   Preserved class names (used by script + external CSS):
     .rail, .rail-collapsed, .rail-brand, .rail-logo, .rail-brand-copy, .rail-title,
     .rail-title-sub, .rail-scroll, .rail-expand-top, .rail-item, .rail-item-icon,
     .rail-item-label, .rail-item-badge, .rail-foot, .rail-collapse-btn, .rail-console,
     .rail-console-label, .tenant-switch-wrap, .tenant-switch, .tenant-icon, .tenant-name,
     .tenant-arrow, .tenant-menu, .tenant-option, .tenant-empty, .console-row,
     .console-row-icon, .platform-row, .theme-row, .theme-row-label, .accent-picker,
     .theme-toggle, .account-row, .rail-avatar, .rail-user-info, .rail-user-name,
     .rail-user-status
   New classes (CSS only, no JS depends on them): .accent-swatch, .accent-custom
*/

.rail {
  width: 224px;
  height: 100%;
  display: flex;
  flex-direction: column;
  flex-shrink: 0;
  overflow: hidden;
  color: var(--text);
  background: var(--surface-2);
  border-right: 1px solid var(--line);
}

.rail-collapsed {
  width: 56px;
}

/* ─── Brand ─────────────────────────────────────────────────────── */
.rail-brand {
  min-height: 60px;
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 14px 16px 12px;
}

.rail-logo {
  width: 28px;
  height: 28px;
  display: grid;
  place-items: center;
  flex-shrink: 0;
  padding: 0;
  color: var(--text-inverse);
  background: transparent;
  border: none;
  border-radius: var(--r-2, 6px);
  box-shadow: 0 10px 22px rgba(7, 61, 139, 0.22);
  cursor: pointer;
  overflow: hidden;
  transition: box-shadow 0.14s var(--ease, cubic-bezier(0.2, 0.8, 0.2, 1)),
              transform 0.14s var(--ease, cubic-bezier(0.2, 0.8, 0.2, 1));
}
.rail-logo-mark {
  width: 100%;
  height: 100%;
  display: block;
  object-fit: cover;
}
.rail-logo:hover {
  box-shadow: var(--sh-brand);
  transform: translateY(-1px);
}
.rail-logo:focus-visible {
  outline: 2px solid var(--line-focus, var(--brand-ring));
  outline-offset: 2px;
}

.rail-brand-copy {
  min-width: 0;
  flex: 1;
}

/* 顶部 brand 区右侧的小收起按钮，跟 SessionSidebar 的 « 形态对齐 */
.rail-collapse-top {
  width: 26px;
  height: 26px;
  display: grid;
  place-items: center;
  flex-shrink: 0;
  margin-left: auto;
  color: var(--text-3);
  background: transparent;
  border: 1px solid transparent;
  border-radius: var(--r-2, 6px);
  cursor: pointer;
  transition: background 0.14s var(--ease, cubic-bezier(0.2, 0.8, 0.2, 1)),
              color 0.14s var(--ease, cubic-bezier(0.2, 0.8, 0.2, 1)),
              border-color 0.14s var(--ease, cubic-bezier(0.2, 0.8, 0.2, 1));
}
.rail-collapse-top:hover {
  background: var(--brand-soft);
  color: var(--brand);
  border-color: var(--brand-ring);
}
.rail-collapse-top:focus-visible {
  outline: 2px solid var(--line-focus, var(--brand-ring));
  outline-offset: 2px;
}

.rail-title {
  color: var(--text);
  font-size: 16px;
  font-weight: var(--fw-bold, 700);
  letter-spacing: -0.01em;
  line-height: 1.1;
  white-space: nowrap;
}

.rail-title-sub {
  margin-top: 3px;
  color: var(--text-3);
  font-size: 11.5px;
  font-weight: var(--fw-medium, 500);
  white-space: nowrap;
}

/* ─── Expand top (collapsed-only) ────────────────────────────── */
.rail-expand-top {
  width: 34px;
  height: 30px;
  display: grid;
  place-items: center;
  flex-shrink: 0;
  margin: -2px auto 6px;
  color: var(--text-3);
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: var(--r-2, 6px);
  cursor: pointer;
  box-shadow: var(--sh-1);
  transition: background 0.14s var(--ease, cubic-bezier(0.2, 0.8, 0.2, 1)),
              color 0.14s var(--ease, cubic-bezier(0.2, 0.8, 0.2, 1)),
              border-color 0.14s var(--ease, cubic-bezier(0.2, 0.8, 0.2, 1));
}
.rail-expand-top:hover {
  background: var(--brand-soft);
  color: var(--brand);
  border-color: var(--brand-ring);
}
.rail-expand-top:focus-visible {
  outline: 2px solid var(--line-focus, var(--brand-ring));
  outline-offset: 2px;
}

/* ─── Nav scroll + items ─────────────────────────────────────── */
.rail-scroll {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
  gap: 2px;
  overflow-y: auto;
  padding: 8px 10px 10px;
}

.rail-item {
  position: relative;
  width: 100%;
  min-height: 36px;
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 0 10px;
  color: var(--text-2);
  background: transparent;
  border: none;
  border-radius: var(--r-3, 8px);
  font-family: inherit;
  font-size: 13px;
  font-weight: var(--fw-medium, 500);
  text-align: left;
  cursor: pointer;
  /* 2026-05-23 button → <a> 后禁默认下划线, 跟 admin-spa AdminLayout 一致 */
  text-decoration: none;
  transition: background 0.14s var(--ease, cubic-bezier(0.2, 0.8, 0.2, 1)),
              color 0.14s var(--ease, cubic-bezier(0.2, 0.8, 0.2, 1));
}
.rail-item:hover,
.rail-item:visited,
.rail-item:active {
  text-decoration: none;  /* 各 :hover/:visited 状态锁住, 防 UA :visited 默认 underline */
}

.rail-item:hover {
  color: var(--text);
  background: var(--surface);
}

.rail-item.active {
  color: var(--brand);
  background: var(--brand-soft);
  font-weight: var(--fw-semibold, 600);
}

.rail-item.active::before {
  content: '';
  position: absolute;
  left: -2px;
  top: 6px;
  bottom: 6px;
  width: 3px;
  border-radius: 0 var(--r-1, 4px) var(--r-1, 4px) 0;
  background: var(--brand);
}

.rail-item:focus-visible {
  outline: 2px solid var(--line-focus, var(--brand-ring));
  outline-offset: -2px;
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
  padding: 0 6px;
  border-radius: var(--r-full, 999px);
  color: var(--brand);
  background: var(--brand-soft-2);
  font-family: var(--font-mono, 'JetBrains Mono', monospace);
  font-size: 11px;
  font-weight: var(--fw-semibold, 600);
  font-variant-numeric: tabular-nums;
  letter-spacing: 0;
}

/* ─── Foot ───────────────────────────────────────────────────── */
.rail-foot {
  padding: 10px 10px 12px;
  border-top: 1px solid var(--line);
}

.rail-collapse-btn {
  width: 100%;
  min-height: 30px;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  margin-bottom: 10px;
  color: var(--text-3);
  background: transparent;
  border: 1px solid var(--line);
  border-radius: var(--r-2, 6px);
  font-family: inherit;
  font-size: 12px;
  font-weight: var(--fw-medium, 500);
  cursor: pointer;
  transition: background 0.14s var(--ease, cubic-bezier(0.2, 0.8, 0.2, 1)),
              color 0.14s var(--ease, cubic-bezier(0.2, 0.8, 0.2, 1)),
              border-color 0.14s var(--ease, cubic-bezier(0.2, 0.8, 0.2, 1));
}

.rail-collapse-btn:hover {
  color: var(--brand);
  background: var(--brand-soft);
  border-color: var(--brand-ring);
}

.rail-collapse-btn:focus-visible {
  outline: 2px solid var(--line-focus, var(--brand-ring));
  outline-offset: 2px;
}

/* ─── Console (expanded only) ────────────────────────────────── */
.rail-console {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.rail-console-label {
  margin: 2px 4px 2px;
  color: var(--text-3);
  font-size: 11px;
  font-weight: var(--fw-semibold, 600);
  letter-spacing: 0.06em;
  text-transform: uppercase;
}

.tenant-switch-wrap {
  position: relative;
}

.tenant-switch {
  width: 100%;
  min-height: 34px;
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 0 10px;
  color: var(--text);
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: var(--r-3, 8px);
  font-family: inherit;
  font-size: 12.5px;
  font-weight: var(--fw-medium, 500);
  cursor: pointer;
  text-align: left;
  transition: background 0.14s var(--ease, cubic-bezier(0.2, 0.8, 0.2, 1)),
              border-color 0.14s var(--ease, cubic-bezier(0.2, 0.8, 0.2, 1));
}

.tenant-switch:hover,
.tenant-switch.open {
  border-color: var(--brand-ring);
  background: var(--brand-soft);
  color: var(--brand);
}

.tenant-switch:focus-visible {
  outline: 2px solid var(--line-focus, var(--brand-ring));
  outline-offset: 2px;
}

.tenant-icon {
  width: 16px;
  height: 16px;
  display: grid;
  place-items: center;
  flex-shrink: 0;
  color: var(--brand);
  background: var(--brand-soft);
  border-radius: var(--r-1, 4px);
  padding: 2px;
}

.tenant-name {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.tenant-arrow {
  width: 14px;
  height: 14px;
  display: grid;
  place-items: center;
  flex-shrink: 0;
  color: var(--text-4);
  transition: transform 0.14s var(--ease, cubic-bezier(0.2, 0.8, 0.2, 1));
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
  padding: 4px;
  border: 1px solid var(--line);
  border-radius: var(--r-3, 8px);
  background: var(--surface);
  box-shadow: var(--sh-3);
}

.tenant-option {
  width: 100%;
  min-height: 32px;
  padding: 6px 10px;
  color: var(--text);
  background: transparent;
  border: none;
  border-radius: var(--r-2, 6px);
  font-family: inherit;
  font-size: 12.5px;
  font-weight: var(--fw-medium, 500);
  text-align: left;
  cursor: pointer;
  display: flex;
  flex-direction: column;
  gap: 2px;
  transition: background 0.14s var(--ease, cubic-bezier(0.2, 0.8, 0.2, 1)),
              color 0.14s var(--ease, cubic-bezier(0.2, 0.8, 0.2, 1));
}

.tenant-option-name,
.tenant-option-code {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.tenant-option-code {
  color: var(--text-3);
  font-size: 11px;
  font-weight: var(--fw-regular, 400);
}

.tenant-option:hover,
.tenant-option.active {
  color: var(--brand);
  background: var(--brand-soft);
}

.tenant-option:focus-visible {
  outline: 2px solid var(--line-focus, var(--brand-ring));
  outline-offset: -2px;
}

.tenant-empty {
  padding: 8px 10px;
  color: var(--text-3);
  font-size: 12px;
  font-weight: var(--fw-regular, 400);
}

/* ─── Console rows (platform/etc) ─────────────────────────── */
.console-row {
  width: 100%;
  min-height: 32px;
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 0 10px;
  color: var(--text-2);
  background: transparent;
  border: none;
  border-radius: var(--r-3, 8px);
  font-family: inherit;
  font-size: 12.5px;
  font-weight: var(--fw-medium, 500);
  cursor: pointer;
  text-align: left;
  /* v3 2026-05-20: 兼容 <a> 元素（平台管理行用 a 标签）
     去掉 <a> 默认下划线，跟其他 console-row（button）视觉一致 */
  text-decoration: none;
  transition: background 0.14s var(--ease, cubic-bezier(0.2, 0.8, 0.2, 1)),
              color 0.14s var(--ease, cubic-bezier(0.2, 0.8, 0.2, 1));
}
.console-row:visited {
  color: var(--text-2);
}
.console-row:hover:visited,
.console-row.active:visited {
  color: var(--brand);
}

.console-row:hover {
  color: var(--brand);
  background: var(--brand-soft);
}

.console-row.active {
  color: var(--brand);
  background: var(--brand-soft);
  font-weight: var(--fw-semibold, 600);
}

.console-row:focus-visible {
  outline: 2px solid var(--line-focus, var(--brand-ring));
  outline-offset: -2px;
}

.console-row-icon {
  width: 14px;
  height: 14px;
  display: grid;
  place-items: center;
  flex-shrink: 0;
  color: currentColor;
}

/* ─── Theme row ──────────────────────────────────────────── */
/* 2026-05-21 整 row 改成可点击 button — 之前 label + sun icon 分离割裂。
   配色跟 .console-row hover/focus 一致让两个 footer entry 视觉同步 */
.theme-row {
  width: 100%;
  min-height: 36px;
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 0 10px;
  border: 1px solid transparent;
  border-radius: var(--r-3, 8px);
  background: transparent;
  color: var(--text-2);
  font-family: inherit;
  font-size: 12.5px;
  font-weight: var(--fw-medium, 500);
  text-align: left;
  cursor: pointer;
  transition: background 0.14s var(--ease, cubic-bezier(0.2, 0.8, 0.2, 1)),
              color 0.14s var(--ease, cubic-bezier(0.2, 0.8, 0.2, 1)),
              border-color 0.14s var(--ease, cubic-bezier(0.2, 0.8, 0.2, 1));
}
.theme-row:hover {
  color: var(--brand);
  background: var(--brand-soft);
  border-color: var(--brand-ring);
}
.theme-row:focus-visible {
  outline: 2px solid var(--line-focus, var(--brand-ring));
  outline-offset: 2px;
}

.theme-row-icon {
  display: grid;
  place-items: center;
  flex-shrink: 0;
  color: currentColor;
}

.theme-row-label {
  flex: 1;
  white-space: nowrap;
  color: inherit;
  display: flex;
  align-items: center;
}
/* 版本号徽标: 推到行尾, 弱化 */
.rail-version {
  margin-left: auto;
  font-size: 11px;
  font-variant-numeric: tabular-nums;
  opacity: 0.55;
  padding-left: 8px;
}

/* v3 2026-05-20 fix (code review #P2-5): 删 .accent-picker / .accent-swatch /
   .accent-custom 死 CSS 块 — template 已删 picker UI（commit f5e6c0a），
   只剩 CSS 选择器没人引用 = 死代码 55 行 */

/* 2026-05-21: 老 .theme-toggle 独立 button 已合并到 .theme-row 整 row
   可点击，删 30 行 dead CSS */

/* ─── Account row ─────────────────────────────────────── */
.account-row {
  min-height: 44px;
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 8px;
  margin-top: 4px;
  border-top: 1px solid var(--line);
  padding-top: 12px;
}

.rail-avatar {
  width: 28px;
  height: 28px;
  display: grid;
  place-items: center;
  flex-shrink: 0;
  color: var(--text-inverse);
  background: var(--brand);
  border-radius: var(--r-full, 999px);
  font-size: 12.5px;
  font-weight: var(--fw-semibold, 600);
}

.rail-user-info {
  min-width: 0;
  flex: 1;
}

.rail-user-name {
  color: var(--text);
  font-size: 12.5px;
  font-weight: var(--fw-semibold, 600);
  line-height: 1.2;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.rail-user-status {
  display: flex;
  align-items: center;
  gap: 5px;
  margin-top: 2px;
  color: var(--text-3);
  font-size: 11px;
  font-weight: var(--fw-regular, 400);
}

.rail-user-status span {
  width: 6px;
  height: 6px;
  border-radius: var(--r-full, 999px);
  background: var(--ok);
}

.account-logout {
  width: 28px;
  height: 28px;
  display: grid;
  place-items: center;
  flex-shrink: 0;
  color: var(--text-3);
  background: transparent;
  border: 1px solid var(--line);
  border-radius: var(--r-2, 6px);
  cursor: pointer;
  transition: background 0.14s var(--ease, cubic-bezier(0.2, 0.8, 0.2, 1)),
              color 0.14s var(--ease, cubic-bezier(0.2, 0.8, 0.2, 1)),
              border-color 0.14s var(--ease, cubic-bezier(0.2, 0.8, 0.2, 1));
}
.account-logout:hover {
  color: var(--danger, #ef4444);
  background: var(--danger-soft, rgba(239, 68, 68, 0.08));
  border-color: var(--danger-ring, rgba(239, 68, 68, 0.3));
}
.account-logout:focus-visible {
  outline: 2px solid var(--line-focus, var(--brand-ring));
  outline-offset: 2px;
}

/* ─── Collapsed state overrides (56px) ────────────────────── */
.rail-collapsed .rail-brand {
  justify-content: center;
  padding: 14px 8px 10px;
  min-height: 56px;
}

.rail-collapsed .rail-scroll {
  padding: 8px 6px;
  gap: 4px;
}

.rail-collapsed .rail-item {
  justify-content: center;
  padding: 0;
  width: 38px;
  height: 38px;
  min-height: 38px;
  margin: 0 auto;
  color: var(--text-3);
  border-radius: var(--r-3, 8px);
}

.rail-collapsed .rail-item:hover {
  color: var(--brand);
  background: var(--surface);
}

.rail-collapsed .rail-item.active {
  color: var(--brand);
  background: var(--brand-soft);
}

.rail-collapsed .rail-item.active::before {
  left: -6px;
  top: 8px;
  bottom: 8px;
}

.rail-collapsed .rail-item-label,
.rail-collapsed .rail-item-badge {
  display: none;
}

.rail-collapsed .rail-foot {
  padding: 8px 6px 10px;
}

.rail-collapsed .rail-collapse-btn {
  margin-bottom: 0;
  height: 38px;
  min-height: 38px;
}

/* ─── Dark theme tweaks ──────────────────────────────────── */
html[data-theme="dark"] .rail {
  background: var(--surface-2);
  border-right-color: var(--line);
}

html[data-theme="dark"] .rail-item:hover {
  background: var(--surface-3);
}

html[data-theme="dark"] .rail-item.active,
html[data-theme="dark"] .console-row:hover,
html[data-theme="dark"] .console-row.active,
html[data-theme="dark"] .tenant-option:hover,
html[data-theme="dark"] .tenant-option.active {
  background: var(--brand-soft);
}

html[data-theme="dark"] .tenant-switch {
  background: var(--surface);
}

html[data-theme="dark"] .tenant-switch:hover,
html[data-theme="dark"] .tenant-switch.open {
  background: var(--brand-soft);
}

html[data-theme="dark"] .tenant-menu {
  background: var(--surface);
}

html[data-theme="dark"] .rail-collapse-btn {
  background: transparent;
}

html[data-theme="dark"] .rail-expand-top {
  background: var(--surface);
  color: var(--text-3);
}

/* (deleted) html[data-theme="dark"] .accent-swatch.active — accent picker 死代码 */
</style>
