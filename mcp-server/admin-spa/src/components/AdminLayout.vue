<template>
  <!-- v3 2026-05-20 FINAL FIX: 严格 mirror frontend/src/components/v2/RailSidebar.vue
       所有尺寸/padding/字号/字重 1:1 复刻，不再凭印象写。 -->
  <!-- v3 2026-05-20 fix (code review #P2-13): 去掉 :class admin-shell-embedded
       这个 class 没对应 CSS 选择器，是 v-class hook 没写完的 placeholder -->
  <div class="admin-shell">
    <!-- ═══════════ 左 RAIL ═══════════ -->
    <aside class="rail" :class="{ 'rail-collapsed': railCollapsed }">
      <div class="rail-brand">
        <button
          class="rail-logo"
          type="button"
          :aria-label="railCollapsed ? '展开平台管理导航' : '平台管理首页'"
          @click="railCollapsed ? toggleRailCollapsed() : router.push('/mcp')"
        >
          <img src="/ruijing-sailboat.png" alt="" />
        </button>
        <div v-if="!railCollapsed" class="rail-brand-copy">
          <div class="rail-title">睿鲸AI</div>
          <div class="rail-title-sub">AI · 低代码</div>
        </div>
        <button
          v-if="!railCollapsed"
          type="button"
          class="rail-collapse-top"
          title="收起导航"
          aria-label="收起导航"
          @click="toggleRailCollapsed"
        >
          <span v-html="renderIcon('chevronLeft')" />
        </button>
      </div>

      <button
        v-if="railCollapsed"
        type="button"
        class="rail-expand-top"
        title="展开导航"
        aria-label="展开导航"
        @click="toggleRailCollapsed"
      >
        <span v-html="renderIcon('chevronRight')" />
      </button>

      <nav class="rail-scroll" aria-label="平台管理导航">
        <button
          v-for="item in menus"
          :key="item.path"
          type="button"
          class="rail-item"
          :class="{ active: route.path === item.path }"
          @click="router.push(item.path)"
        >
          <span class="rail-item-icon" v-html="renderIcon(item.icon)" />
          <span v-if="!railCollapsed" class="rail-item-label">{{ item.label }}</span>
          <span v-if="!railCollapsed && item.badge" class="rail-item-badge">{{ item.badge }}</span>
        </button>
      </nav>

      <div v-if="!railCollapsed" class="rail-foot">
        <div class="rail-console">
          <a
            class="console-row"
            :href="workspaceUrl"
            target="_blank"
            rel="noopener"
          >
            <span class="console-row-icon" v-html="renderIcon('shield')" />
            <span>返回工作台</span>
            <span class="external-mark" v-html="renderIcon('external')" />
          </a>

          <button
            type="button"
            class="theme-row"
            :aria-label="isDark ? '切换到浅色模式' : '切换到深色模式'"
            @click="toggleTheme"
          >
            <span class="theme-row-icon" v-html="renderIcon(isDark ? 'moon' : 'sun')" />
            <span class="theme-row-label">{{ isDark ? '深色模式 · 切到浅色' : '浅色模式 · 切到深色' }}</span>
          </button>

          <div class="account-row">
            <div class="rail-avatar">{{ (auth.user?.username || 'A').slice(0, 1).toUpperCase() }}</div>
            <div class="rail-user-info">
              <div class="rail-user-name">{{ auth.user?.username || '管理员' }}</div>
              <div class="rail-user-status"><span />在线</div>
            </div>
            <button class="logout-icon-btn" type="button" title="退出" @click="onLogout">
              <span v-html="renderIcon('logout')" />
            </button>
          </div>
        </div>
      </div>
    </aside>

    <!-- ═══════════ 主区域 ═══════════ -->
    <div class="admin-main-col">
      <header class="tabbar" aria-label="打开的页面">
        <button
          v-for="item in tabItems"
          :key="item.path"
          type="button"
          class="tab"
          :class="{ active: isTabActive(item.path) }"
          :title="item.label"
          @click="router.push(item.path)"
        >
          <span class="tab-icon" v-html="renderIcon(item.icon)" />
          <span class="tab-label">{{ item.label }}</span>
          <span v-if="item.path !== '/mcp'" class="tab-close" aria-hidden="true">×</span>
        </button>
      </header>

      <main class="admin-content">
        <router-view />
      </main>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'

const route  = useRoute()
const router = useRouter()
const auth   = useAuthStore()
const RAIL_COLLAPSE_KEY = 'ruijing-admin-rail-collapsed-v1'
const railCollapsed = ref<boolean>(
  typeof localStorage !== 'undefined' && localStorage.getItem(RAIL_COLLAPSE_KEY) === '1',
)

interface MenuItem {
  path: string
  label: string
  icon: string
  badge?: number
}

const menus: MenuItem[] = [
  { path: '/mcp',         label: 'MCP 接入',  icon: 'connection' },
  { path: '/tester',      label: 'MCP 测试',  icon: 'flask' },
  { path: '/logs',        label: '调用日志',  icon: 'logs' },
  { path: '/tenants',     label: 'aPaaS 租户', icon: 'building' },
  { path: '/users',       label: 'aPaaS 用户', icon: 'user' },
  { path: '/llm-configs', label: 'LLM 配置',  icon: 'spark' },
]

const tabItems = computed(() => {
  const fixed = menus.slice(0, 5)
  const current = menus.find(m => m.path === route.path)
  if (current && !fixed.some(item => item.path === current.path)) {
    return [...fixed, current]
  }
  return fixed
})

// 主题切换（admin-spa 没 theme store，简单 localStorage + data-theme 接管）
const isDark = ref<boolean>((() => {
  if (typeof window === 'undefined') return false
  const saved = localStorage.getItem('theme')
  return saved === 'dark'
})())

function applyTheme(dark: boolean) {
  isDark.value = dark
  if (typeof document !== 'undefined') {
    document.documentElement.setAttribute('data-theme', dark ? 'dark' : 'light')
  }
  if (typeof localStorage !== 'undefined') {
    localStorage.setItem('theme', dark ? 'dark' : 'light')
  }
}

function toggleTheme() {
  applyTheme(!isDark.value)
}

function toggleRailCollapsed() {
  railCollapsed.value = !railCollapsed.value
  if (typeof localStorage !== 'undefined') {
    localStorage.setItem(RAIL_COLLAPSE_KEY, railCollapsed.value ? '1' : '0')
  }
}

function isTabActive(path: string) {
  return route.path === path || route.path.startsWith(`${path}/`)
}

onMounted(async () => {
  // 初始化主题
  applyTheme(isDark.value)

  if (auth.isAuthenticated && !auth.user) {
    await auth.fetchMe()
  }
})

function onLogout() {
  auth.logout()
  try { localStorage.clear() } catch { /* private mode */ }
  const targetUrl = workspaceLoginUrl.value
  if (typeof window !== 'undefined' && window.self !== window.top && window.top) {
    const parentOrigin = (() => {
      try {
        if (document.referrer) return new URL(document.referrer).origin
        if (window.location.ancestorOrigins?.length) return window.location.ancestorOrigins[0]
        return window.location.origin
      } catch {
        return window.location.origin
      }
    })()
    window.parent?.postMessage({ type: 'admin-logout', targetUrl }, parentOrigin)
    try {
      if (window.top.location.origin === window.location.origin) {
        window.top.location.href = targetUrl
      }
    } catch {
      // Cross-origin parent will handle the postMessage above.
    }
    return
  }
  window.location.href = targetUrl
}

const workspaceUrl = computed(() => {
  if (typeof window === 'undefined') return '/'
  if (import.meta.env.DEV) {
    return `${window.location.protocol}//${window.location.hostname}:5173/`
  }
  try {
    if (document.referrer) {
      const referrer = new URL(document.referrer)
      const base = referrer.pathname.replace(/\/platform-admin(?:\/.*)?$/, '') || '/'
      return `${referrer.origin}${base}${referrer.search || ''}`
    }
  } catch {
    // Fall back to same-origin workspace root below.
  }
  return `${window.location.origin}/`
})

const workspaceLoginUrl = computed(() => {
  if (typeof window === 'undefined') return '/login'
  try {
    const url = new URL(workspaceUrl.value, window.location.origin)
    const basePath = url.pathname.replace(/\/$/, '')
    url.pathname = `${basePath || ''}/login`
    url.search = ''
    url.hash = ''
    return url.toString()
  } catch {
    return '/login'
  }
})

const ICONS: Record<string, string> = {
  connection: '<path d="M9 12L11 14L15 10"/><path d="M21 12A9 9 0 1 1 12 3"/>',
  flask: '<path d="M9 3h6"/><path d="M10 3v6.5L6 17a2 2 0 0 0 1.7 3h8.6A2 2 0 0 0 18 17l-4-7.5V3"/><path d="M9 13h6"/>',
  logs: '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="17 10 12 15 7 10"/><line x1="12" y1="15" x2="12" y2="3"/>',
  building: '<path d="M4 21V5l8-3 8 3v16"/><path d="M9 9h.01M9 13h.01M9 17h.01M15 9h.01M15 13h.01M15 17h.01"/><path d="M4 21h16"/>',
  apps: '<path d="M3 5h7v7H3z"/><path d="M14 5h7v7h-7z"/><path d="M3 16h7v5H3z"/><path d="M14 16h7v5h-7z"/>',
  cpu: '<rect x="4" y="4" width="16" height="16" rx="2"/><rect x="9" y="9" width="6" height="6"/><line x1="9" y1="1" x2="9" y2="4"/><line x1="15" y1="1" x2="15" y2="4"/><line x1="9" y1="20" x2="9" y2="23"/><line x1="15" y1="20" x2="15" y2="23"/><line x1="20" y1="9" x2="23" y2="9"/><line x1="20" y1="14" x2="23" y2="14"/><line x1="1" y1="9" x2="4" y2="9"/><line x1="1" y1="14" x2="4" y2="14"/>',
  user: '<path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/>',
  back: '<polyline points="15 18 9 12 15 6"/>',
  logout: '<path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/><polyline points="16 17 21 12 16 7"/><line x1="21" y1="12" x2="9" y2="12"/>',
  shield: '<path d="M12 2 4 5v7c0 5 3.5 8.5 8 10 4.5-1.5 8-5 8-10V5z"/><path d="M9 12l2 2 4-4"/>',
  spark: '<path d="M12 3 14 9l6 2-6 2-2 6-2-6-6-2 6-2z"/>',
  sun: '<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4 12H2M22 12h-2M6.3 6.3 4.9 4.9M19.1 19.1l-1.4-1.4M6.3 17.7l-1.4 1.4M19.1 4.9l-1.4 1.4"/>',
  moon: '<path d="M21 13A9 9 0 0 1 11 3a9 9 0 1 0 10 10z"/>',
  chevronLeft: '<polyline points="15 18 9 12 15 6"/>',
  chevronRight: '<polyline points="9 18 15 12 9 6"/>',
  chevronDown: '<polyline points="6 9 12 15 18 9"/>',
  external: '<path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/><polyline points="15 3 21 3 21 9"/><line x1="10" y1="14" x2="21" y2="3"/>',
}

function renderIcon(name: string): string {
  const inner = ICONS[name] ?? ''
  return `<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">${inner}</svg>`
}
</script>

<style scoped>
/* ═══════════════════════════════════════════════════════════════════
 * v3 2026-05-20 FINAL — 1:1 复刻 frontend RailSidebar.vue 的所有值
 * 不再凭印象写 — 每一个 px / padding / font-size 都对照源文件
 * ═══════════════════════════════════════════════════════════════════ */

.admin-shell {
  height: 100vh;
  width: 100%;
  display: flex;
  background: #EFF6FF;
  color: var(--text);
  overflow: hidden;
  font-family: var(--font-sans, 'Inter', 'Noto Sans SC', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif);
}

.admin-main-col {
  flex: 1;
  min-width: 0;
  min-height: 0;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

/* ─── Rail (跟 frontend 1:1) ──────────────────────────────────── */
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

.rail-brand {
  min-height: 60px;
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 14px 16px 12px;
}

.rail-logo {
  position: relative;
  width: 28px;
  height: 28px;
  display: grid;
  place-items: center;
  flex-shrink: 0;
  background: rgba(255, 255, 255, 0.76);
  border: none;
  padding: 0;
  line-height: 0;
  appearance: none;
  border-radius: var(--r-2, 6px);
  box-shadow: var(--sh-2);
  cursor: pointer;
  transition: background 0.14s var(--ease, cubic-bezier(0.2, 0.8, 0.2, 1)),
              box-shadow 0.14s var(--ease, cubic-bezier(0.2, 0.8, 0.2, 1));
}

.rail-logo img {
  position: absolute;
  left: 50%;
  top: 50%;
  width: 23px;
  height: 23px;
  object-fit: contain;
  object-position: center;
  display: block;
  transform: translate(-50%, -50%);
}

.rail-logo:hover {
  background: rgba(255, 255, 255, 0.9);
  box-shadow: var(--sh-brand);
}

.rail-logo:focus-visible {
  outline: 2px solid var(--line-focus, var(--brand-ring));
  outline-offset: 2px;
}

.rail-brand-copy {
  min-width: 0;
  flex: 1;
}

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

.rail-collapse-top:hover,
.rail-expand-top:hover {
  background: var(--brand-soft);
  color: var(--brand);
  border-color: var(--brand-ring);
}

.rail-collapse-top:focus-visible,
.rail-expand-top:focus-visible {
  outline: 2px solid var(--line-focus, var(--brand-ring));
  outline-offset: 2px;
}

.rail-title {
  color: var(--text);
  font-size: 16px;
  font-weight: var(--fw-bold, 700);
  letter-spacing: 0;
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

/* ─── Nav (跟 frontend 1:1) ───────────────────────────────────── */
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
  transition: background 0.14s var(--ease, cubic-bezier(0.2, 0.8, 0.2, 1)),
              color 0.14s var(--ease, cubic-bezier(0.2, 0.8, 0.2, 1));
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
  min-width: 20px;
  height: 20px;
  display: inline-grid;
  place-items: center;
  flex-shrink: 0;
  border-radius: var(--r-full, 999px);
  background: var(--brand-soft-2);
  color: var(--brand);
  font-size: 11px;
  font-weight: var(--fw-bold, 700);
}

.rail-collapsed .rail-brand {
  justify-content: center;
  padding-left: 0;
  padding-right: 0;
}

.rail-collapsed .rail-scroll {
  padding: 8px 9px 10px;
  align-items: center;
}

.rail-collapsed .rail-item {
  width: 38px;
  height: 38px;
  min-height: 38px;
  justify-content: center;
  padding: 0;
  border-radius: var(--r-3, 8px);
}

.rail-collapsed .rail-item-icon {
  width: 18px;
  height: 18px;
}

/* ─── Rail foot ───────────────────────────────────────────────── */
.rail-foot {
  padding: 10px 10px 12px;
  border-top: 1px solid var(--line);
}

.rail-console {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.console-row {
  width: 100%;
  min-height: 34px;
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
  text-decoration: none;
  transition: background 0.14s var(--ease, cubic-bezier(0.2, 0.8, 0.2, 1)),
              color 0.14s var(--ease, cubic-bezier(0.2, 0.8, 0.2, 1));
}

.console-row:hover {
  color: var(--brand);
  background: var(--brand-soft);
}

.external-mark {
  display: grid;
  place-items: center;
  flex-shrink: 0;
  color: var(--text-3);
  margin-left: auto;
  opacity: 0.72;
}

.console-row-icon {
  display: grid;
  place-items: center;
  width: 14px;
  height: 14px;
  flex-shrink: 0;
}

/* ─── Theme toggle row — 整行可点击 ─────────────────────────── */
.theme-row {
  width: 100%;
  min-height: 32px;
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 0 10px;
  margin: 4px 0;
  color: var(--text-2);
  background: transparent;
  border: none;
  border-radius: var(--r-3, 8px);
  font-family: inherit;
  font-size: 12.5px;
  font-weight: var(--fw-medium, 500);
  text-align: left;
  cursor: pointer;
  transition: background 0.14s var(--ease, cubic-bezier(0.2, 0.8, 0.2, 1)),
              color 0.14s var(--ease, cubic-bezier(0.2, 0.8, 0.2, 1));
}

.theme-row:hover {
  color: var(--brand);
  background: var(--brand-soft);
}

.theme-row:focus-visible {
  outline: 2px solid var(--line-focus, var(--brand-ring));
  outline-offset: -2px;
}

.theme-row-icon {
  display: grid;
  place-items: center;
  width: 14px;
  height: 14px;
  flex-shrink: 0;
}

.theme-row-label {
  flex: 1;
  min-width: 0;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

/* ─── Account row ─────────────────────────────────────────────── */
.account-row {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 10px 4px;
  margin-top: 4px;
  border-top: 1px solid var(--line);
}

.rail-avatar {
  width: 28px;
  height: 28px;
  border-radius: 50%;
  background: var(--brand);
  color: var(--text-inverse, #fff);
  display: grid;
  place-items: center;
  font-size: 12px;
  font-weight: var(--fw-bold, 700);
  flex-shrink: 0;
}

.rail-user-info {
  flex: 1;
  min-width: 0;
}

.rail-user-name {
  color: var(--text);
  font-size: 12.5px;
  font-weight: var(--fw-semibold, 600);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.rail-user-status {
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: 10.5px;
  color: var(--text-3);
  margin-top: 1px;
}

.rail-user-status span {
  width: 5px;
  height: 5px;
  border-radius: 50%;
  background: var(--ok, #34D399);
}

.logout-icon-btn {
  width: 26px;
  height: 26px;
  border: 0;
  border-radius: var(--r-2, 6px);
  background: transparent;
  color: var(--text-3);
  cursor: pointer;
  display: grid;
  place-items: center;
  transition: all 0.14s var(--ease, cubic-bezier(0.2, 0.8, 0.2, 1));
}

.logout-icon-btn:hover {
  background: var(--err-soft, rgba(220, 38, 38, 0.1));
  color: var(--err, #B91C1C);
}

/* ─── TopBar (跟 frontend ShellTopBar 1:1) ──────────────────── */
.tabbar {
  display: flex;
  align-items: center;
  gap: 4px;
  min-height: 36px;
  padding: 4px 10px 0;
  background: var(--surface-2);
  border-bottom: 1px solid var(--line);
  position: relative;
  z-index: 5;
  flex-shrink: 0;
  overflow-x: auto;
  scrollbar-width: thin;
}

.tabbar::-webkit-scrollbar {
  height: 4px;
}

.tabbar::-webkit-scrollbar-thumb {
  background: var(--line);
  border-radius: var(--r-1, 4px);
}

.tab {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  max-width: 190px;
  min-width: 0;
  height: 32px;
  padding: 0 10px;
  border: 1px solid transparent;
  border-bottom: none;
  border-radius: var(--r-2, 6px) var(--r-2, 6px) 0 0;
  background: transparent;
  color: var(--text-2);
  font-family: inherit;
  font-size: 12.5px;
  font-weight: var(--fw-medium, 500);
  white-space: nowrap;
  cursor: pointer;
  margin-bottom: -1px;
  flex-shrink: 0;
  transition: background 0.12s var(--ease, cubic-bezier(0.2, 0.8, 0.2, 1)),
              color 0.12s var(--ease, cubic-bezier(0.2, 0.8, 0.2, 1));
}

.tab:hover {
  background: var(--surface);
  color: var(--text);
}

.tab.active {
  background: var(--surface);
  color: var(--brand);
  border-color: var(--line);
  font-weight: var(--fw-semibold, 600);
}

.tab:focus-visible {
  outline: 2px solid var(--line-focus, var(--brand-ring));
  outline-offset: -2px;
}

.tab-icon {
  display: grid;
  place-items: center;
  flex-shrink: 0;
}

.tab-label {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
}

.tab-close {
  width: 16px;
  height: 16px;
  display: inline-grid;
  place-items: center;
  flex-shrink: 0;
  border-radius: var(--r-1, 4px);
  color: var(--text-3);
  font-size: 14px;
  line-height: 1;
}

/* ─── 内容区 ──────────────────────────────────────────────── */
/* v3 2026-05-21 — admin-spa 跟 frontend 密度对齐第二轮
   .admin-content padding 24px 28px → 24px 32px 40px（跟 frontend Apps 一致段）
   下方 :deep 缩到最小：只保留 admin-spa 独有的 .page max-width 兜底，
   其余共性样式（h1 / card / table / button / tag / input）全移到
   density-align.css 全局生效，方便后续统一调。 */
.admin-content {
  flex: 1;
  min-width: 0;
  min-height: 0;
  padding: 24px 32px 40px;
  background: linear-gradient(180deg, #EEF5FF 0%, #F8FAFC 240px, #F8FAFC 100%);
  overflow-y: auto;
}

/* 仅保留 max-width 兜底（.page 可能被各 view 自己定义，density-align 用 !important
   覆盖；这里 fallback 给没显式 .page class 的容器） */
.admin-content :deep(.page),
.admin-content :deep(.llm-page),
.admin-content :deep(.mcp-page),
.admin-content :deep(.members-page) {
  max-width: 1280px;
  margin: 0 auto;
  color: var(--text);
}

.admin-content :deep(.page-actions) {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  justify-content: flex-end;
}

html[data-theme="dark"] .rail {
  background: var(--surface-2);
}
</style>
