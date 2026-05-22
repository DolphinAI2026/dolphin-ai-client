<template>
  <!-- v3 2026-05-20 FINAL FIX: 严格 mirror frontend/src/components/v2/RailSidebar.vue
       所有尺寸/padding/字号/字重 1:1 复刻，不再凭印象写。 -->
  <!-- v3 2026-05-20 fix (code review #P2-13): 去掉 :class admin-shell-embedded
       这个 class 没对应 CSS 选择器，是 v-class hook 没写完的 placeholder -->
  <div class="admin-shell">
    <!-- ═══════════ 左 RAIL ═══════════ -->
    <aside class="rail">
      <div class="rail-brand">
        <div class="rail-logo">
          <svg width="17" height="17" viewBox="0 0 24 24" fill="none">
            <rect x="3" y="3" width="8" height="8" rx="2.2" fill="white" />
            <rect x="13" y="3" width="8" height="8" rx="2.2" fill="rgba(255,255,255,0.68)" />
            <rect x="3" y="13" width="8" height="8" rx="2.2" fill="rgba(255,255,255,0.68)" />
            <rect x="13" y="13" width="8" height="8" rx="2.2" fill="white" />
          </svg>
        </div>
        <div class="rail-brand-copy">
          <div class="rail-title">睿鲸AI</div>
          <div class="rail-title-sub">平台管理</div>
        </div>
      </div>

      <nav class="rail-scroll" aria-label="平台管理导航">
        <!-- 2026-05-22: button → <a href> 让 cmd+click / 中键 / 右键"在新标签中打开" 真开 chrome tab.
             普通 click → 内部 openTab + router.push (走多 tab 体系). -->
        <a
          v-for="item in menus"
          :key="item.path"
          :href="resolveHref(item.path)"
          class="rail-item"
          :class="{ active: route.path === item.path }"
          :title="`${item.label} (Cmd+点 在新标签中打开)`"
          @click="onMenuClick($event, item)"
          @auxclick="onMenuClick($event, item)"
        >
          <span class="rail-item-icon" v-html="renderIcon(item.icon)" />
          <span class="rail-item-label">{{ item.label }}</span>
        </a>
      </nav>

      <div class="rail-foot">
        <div class="rail-console">
          <a
            v-if="embedded"
            class="console-row"
            href="javascript:void(0)"
            @click.prevent="returnWorkspace"
          >
            <span class="console-row-icon" v-html="renderIcon('back')" />
            <span>返回工作台</span>
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
      <header class="topbar">
        <div class="topbar-crumb">
          <span>aPaaS Builder</span>
          <span class="topbar-crumb-sep">/</span>
          <span class="topbar-crumb-mid">平台管理</span>
          <span class="topbar-crumb-sep">/</span>
          <span class="topbar-crumb-current">{{ currentTitle }}</span>
        </div>
      </header>

      <!-- 2026-05-22 多 tab 栏 — 跟工作台 frontend TabStrip 同款体验, 支持 cmd+click 开新 chrome tab -->
      <TabStrip />

      <main class="admin-content">
        <router-view />
      </main>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, onBeforeUnmount, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { useAdminTabsStore, type TabItem } from '@/stores/tabs'
import TabStrip from '@/components/TabStrip.vue'

const route  = useRoute()
const router = useRouter()
const auth   = useAuthStore()
const tabsStore = useAdminTabsStore()

interface MenuItem {
  path: string
  label: string
  icon: string
  closable?: boolean
}

const menus: MenuItem[] = [
  { path: '/status',      label: '系统状态',  icon: 'status', closable: false },
  { path: '/mcp',         label: 'MCP 接入',  icon: 'connection' },
  { path: '/tester',      label: 'MCP 测试',  icon: 'flask' },
  { path: '/logs',        label: '调用日志',  icon: 'logs' },
  { path: '/tenants',     label: 'aPaaS 租户', icon: 'building' },
  { path: '/llm-configs', label: 'LLM 配置',  icon: 'cpu' },
  { path: '/users',       label: 'aPaaS 用户', icon: 'user' },
]

// 2026-05-22 多 tab 体系: rail 点击 → openTab + router.push, 让用户能同时开多个管理界面
function resolveHref(path: string): string {
  try {
    return router.resolve(path).href
  } catch {
    return path
  }
}

function onMenuClick(e: MouseEvent, item: MenuItem) {
  // modifier / 中键 → 浏览器原生开新 chrome tab
  if (e.metaKey || e.ctrlKey || e.shiftKey || e.altKey || e.button !== 0) {
    return
  }
  e.preventDefault()
  // 普通 click → openTab + 切路由
  tabsStore.openTab({
    id: item.path,
    path: item.path,
    label: item.label,
    icon: item.icon,
    closable: item.closable !== false,
    kind: 'nav',
  })
  router.push(item.path)
}

// 路由变化 → 同步 active tab (浏览器后退 / deep link 启动场景)
watch(() => route.path, (path) => {
  tabsStore.syncFromRoute(path)
  // 当前路径不在 tabs 里 (deep link 直接进 /tenants) → 自动加进 tabs
  const hit = tabsStore.tabs.find(t => t.path === path || t.path.split('?')[0] === path.split('?')[0])
  if (!hit) {
    const menu = menus.find(m => m.path === path || m.path.split('?')[0] === path.split('?')[0])
    if (menu) {
      tabsStore.openTab({
        id: menu.path,
        path: menu.path,
        label: menu.label,
        icon: menu.icon,
        closable: menu.closable !== false,
        kind: 'nav',
      })
    }
  }
}, { immediate: true })

const currentTitle = computed(() => menus.find(m => m.path === route.path)?.label || '管理后台')

const embedded = computed(() => {
  const queryEmbedded = route.query.embed === '1' || route.query.embed === 'true'
  const framed = typeof window !== 'undefined' && window.self !== window.top
  return queryEmbedded || framed
})

// 主题切换（admin-spa 没 theme store，简单 localStorage + data-theme 接管）
// 2026-05-22: 跟 frontend themeStore 用同一个 localStorage key 'theme'
// (同 origin localStorage 共享) + 监听 storage event 实现 admin-spa ↔ 工作台
// 实时联动 — 工作台 (父 tab) 切 dark / admin-spa iframe 也变 dark, 反之亦然.
const isDark = ref<boolean>((() => {
  if (typeof window === 'undefined') return false
  const saved = localStorage.getItem('theme')
  return saved === 'dark'
})())

function applyTheme(dark: boolean, persist = true) {
  isDark.value = dark
  if (typeof document !== 'undefined') {
    document.documentElement.setAttribute('data-theme', dark ? 'dark' : 'light')
    if (dark) document.documentElement.classList.add('dark')
    else document.documentElement.classList.remove('dark')
  }
  if (persist && typeof localStorage !== 'undefined') {
    localStorage.setItem('theme', dark ? 'dark' : 'light')
  }
}

function toggleTheme() {
  applyTheme(!isDark.value)
}

// 2026-05-22 跨 SPA 主题联动: 监听 localStorage 'theme' 变化
// 工作台 (frontend SPA) 切 dark → 写 localStorage → 同 origin admin-spa 收到 storage event → 同步
function onStorageThemeChange(e: StorageEvent) {
  if (e.key !== 'theme') return
  const newTheme = e.newValue
  if (newTheme !== 'light' && newTheme !== 'dark') return
  const wantDark = newTheme === 'dark'
  if (wantDark !== isDark.value) {
    applyTheme(wantDark, false)  // 不持久化避免循环触发 storage event
  }
}

onMounted(async () => {
  // 初始化主题
  applyTheme(isDark.value, false)  // 初始化不需要写 localStorage

  // 跨 SPA 主题联动
  if (typeof window !== 'undefined') {
    window.addEventListener('storage', onStorageThemeChange)
  }

  if (auth.isAuthenticated && !auth.user) {
    await auth.fetchMe()
  }
})

onBeforeUnmount(() => {
  if (typeof window !== 'undefined') {
    window.removeEventListener('storage', onStorageThemeChange)
  }
})

function onLogout() {
  auth.logout()
  router.push('/login')
}

function returnWorkspace() {
  if (typeof window === 'undefined') return
  if (window.self !== window.top && window.top) {
    // 2026-05-21 修：之前先尝试 `window.top.location.href = '/ai-builder/'`
    // — **相对 URL** 不是按 top 的 origin 解析，而是按当前 iframe 的 origin 解析
    // (admin-spa dev :5174)，结果 top 被导航到 http://localhost:5174/ai-builder/
    // 整个 tab 跑到 admin-spa 端口去了。
    //
    // 修法：永远走 postMessage 让 parent (frontend :5173 + import.meta.env.BASE_URL)
    // 自己决定跳哪个 URL。原 catch 分支早就是这个逻辑，干脆把它提到默认路径。
    const parentOrigin = (() => {
      try {
        if (document.referrer) return new URL(document.referrer).origin
        if (window.location.ancestorOrigins?.length) return window.location.ancestorOrigins[0]
        return null
      } catch { return null }
    })()
    if (parentOrigin) {
      window.parent?.postMessage({ type: 'admin-return-workspace' }, parentOrigin)
    }
    // 父 origin 拿不到 → 静默 fail（不发 '*' 防止任意 iframe 接到）
  } else {
    // admin-spa 独立访问（非 iframe 嵌入），跳到 frontend 的工作台。
    // 注意 admin-spa router base 是 '/'，所以这里不能用 router.push 跳到
    // frontend SPA，直接 window.location.assign 到 frontend dev origin。
    if (typeof window !== 'undefined') {
      // dev: frontend 在 :5173，admin-spa 在 :5174；prod: 同 origin 不同 path
      const frontendOrigin = import.meta.env.DEV
        ? `${window.location.protocol}//${window.location.hostname}:5173`
        : window.location.origin
      window.location.assign(`${frontendOrigin}/ai-builder/`)
    }
  }
}

const ICONS: Record<string, string> = {
  connection: '<path d="M9 12L11 14L15 10"/><path d="M21 12A9 9 0 1 1 12 3"/>',
  flask: '<path d="M9 3h6"/><path d="M10 3v6.5L6 17a2 2 0 0 0 1.7 3h8.6A2 2 0 0 0 18 17l-4-7.5V3"/><path d="M9 13h6"/>',
  logs: '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="17 10 12 15 7 10"/><line x1="12" y1="15" x2="12" y2="3"/>',
  building: '<path d="M4 21V5l8-3 8 3v16"/><path d="M9 9h.01M9 13h.01M9 17h.01M15 9h.01M15 13h.01M15 17h.01"/><path d="M4 21h16"/>',
  cpu: '<rect x="4" y="4" width="16" height="16" rx="2"/><rect x="9" y="9" width="6" height="6"/><line x1="9" y1="1" x2="9" y2="4"/><line x1="15" y1="1" x2="15" y2="4"/><line x1="9" y1="20" x2="9" y2="23"/><line x1="15" y1="20" x2="15" y2="23"/><line x1="20" y1="9" x2="23" y2="9"/><line x1="20" y1="14" x2="23" y2="14"/><line x1="1" y1="9" x2="4" y2="9"/><line x1="1" y1="14" x2="4" y2="14"/>',
  user: '<path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/>',
  back: '<polyline points="15 18 9 12 15 6"/>',
  logout: '<path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/><polyline points="16 17 21 12 16 7"/><line x1="21" y1="12" x2="9" y2="12"/>',
  sun: '<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4 12H2M22 12h-2M6.3 6.3 4.9 4.9M19.1 19.1l-1.4-1.4M6.3 17.7l-1.4 1.4M19.1 4.9l-1.4 1.4"/>',
  moon: '<path d="M21 13A9 9 0 0 1 11 3a9 9 0 1 0 10 10z"/>',
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
  background: var(--bg, #F8FAFC);
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
  color: var(--text-inverse);
  background: var(--brand);
  border: none;
  border-radius: var(--r-2, 6px);
  box-shadow: var(--sh-2);
}

.rail-brand-copy { min-width: 0; }

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

/* ─── Rail foot ───────────────────────────────────────────────── */
.rail-foot {
  /* v3 2026-05-20 fix (code review #P2-7): padding 改 10px 跟 frontend RailSidebar 一致 */
  padding: 10px 10px 12px;
  border-top: 1px solid var(--line);
}

.rail-console {
  display: flex;
  flex-direction: column;
  gap: 4px;
  margin-top: 4px;
}

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
  text-decoration: none;
  transition: background 0.14s var(--ease, cubic-bezier(0.2, 0.8, 0.2, 1)),
              color 0.14s var(--ease, cubic-bezier(0.2, 0.8, 0.2, 1));
}

.console-row:hover {
  color: var(--brand);
  background: var(--brand-soft);
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
.topbar {
  display: flex;
  align-items: center;
  gap: 14px;
  padding: 0 20px;
  height: 48px;
  background: var(--surface);
  border-bottom: 1px solid var(--line);
  position: relative;
  z-index: 5;
  flex-shrink: 0;
}

.topbar-crumb {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
  color: var(--text-3);
  flex: 1;
  min-width: 0;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.topbar-crumb > span:first-child {
  color: var(--text-3);
  font-weight: var(--fw-medium, 500);
  letter-spacing: -0.005em;
}

.topbar-crumb-sep {
  color: var(--text-4);
  font-weight: 400;
}

.topbar-crumb-mid {
  color: var(--text-2);
}

.topbar-crumb-current {
  color: var(--text);
  font-weight: var(--fw-semibold, 600);
  letter-spacing: -0.005em;
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
  background: var(--bg, #F8FAFC);
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
