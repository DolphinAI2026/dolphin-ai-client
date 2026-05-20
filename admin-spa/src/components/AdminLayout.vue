<template>
  <!-- v3 2026-05-20 (FINAL): admin-spa AdminLayout 重写
       不再用 Element Plus el-container/el-aside/el-menu/el-header
       完全 mirror frontend/src/components/v2/RailSidebar.vue + ShellTopBar.vue 的
       DOM 结构和 class 命名，让两个 SPA 视觉完全一致
       -->
  <div class="admin-shell" :class="{ 'admin-shell-embedded': embedded }">
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
        <button
          v-for="item in menus"
          :key="item.path"
          type="button"
          class="rail-item"
          :class="{ active: route.path === item.path }"
          @click="router.push(item.path)"
        >
          <span class="rail-item-icon" v-html="renderIcon(item.icon)" />
          <span class="rail-item-label">{{ item.label }}</span>
        </button>
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

    <!-- ═══════════ 主区域 (顶 TopBar + Content) ═══════════ -->
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

      <main class="admin-content">
        <router-view />
      </main>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'

const route  = useRoute()
const router = useRouter()
const auth   = useAuthStore()

interface MenuItem {
  path: string
  label: string
  icon: string
}

// v3: 用 Lucide-style svg paths（跟 frontend RailSidebar 同款），不用 Element Plus icons
const menus: MenuItem[] = [
  { path: '/mcp',         label: 'MCP 接入',  icon: 'connection' },
  { path: '/tester',      label: 'MCP 测试',  icon: 'flask' },
  { path: '/logs',        label: '调用日志',  icon: 'logs' },
  { path: '/tenants',     label: 'aPaaS 租户', icon: 'building' },
  { path: '/llm-configs', label: 'LLM 配置',  icon: 'cpu' },
  { path: '/users',       label: 'aPaaS 用户', icon: 'user' },
]

const currentTitle = computed(() => menus.find(m => m.path === route.path)?.label || '管理后台')

const embedded = computed(() => {
  const queryEmbedded = route.query.embed === '1' || route.query.embed === 'true'
  const framed = typeof window !== 'undefined' && window.self !== window.top
  return queryEmbedded || framed
})

onMounted(async () => {
  if (auth.isAuthenticated && !auth.user) {
    await auth.fetchMe()
  }
})

function onLogout() {
  auth.logout()
  router.push('/login')
}

function returnWorkspace() {
  if (typeof window === 'undefined') return
  if (window.self !== window.top && window.top) {
    try {
      window.top.location.href = '/ai-builder/'
    } catch {
      window.parent?.postMessage({ type: 'admin-return-workspace' }, '*')
    }
  } else {
    router.push('/')
  }
}

// 与 frontend RailSidebar 同款 SVG icon library（feather/lucide style）
const ICONS: Record<string, string> = {
  connection: '<path d="M9 12L11 14L15 10"/><path d="M21 12A9 9 0 1 1 12 3"/>',
  flask: '<path d="M9 3h6"/><path d="M10 3v6.5L6 17a2 2 0 0 0 1.7 3h8.6A2 2 0 0 0 18 17l-4-7.5V3"/><path d="M9 13h6"/>',
  logs: '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="17 10 12 15 7 10"/><line x1="12" y1="15" x2="12" y2="3"/>',
  building: '<path d="M4 21V5l8-3 8 3v16"/><path d="M9 9h.01M9 13h.01M9 17h.01M15 9h.01M15 13h.01M15 17h.01"/><path d="M4 21h16"/>',
  cpu: '<rect x="4" y="4" width="16" height="16" rx="2"/><rect x="9" y="9" width="6" height="6"/><line x1="9" y1="1" x2="9" y2="4"/><line x1="15" y1="1" x2="15" y2="4"/><line x1="9" y1="20" x2="9" y2="23"/><line x1="15" y1="20" x2="15" y2="23"/><line x1="20" y1="9" x2="23" y2="9"/><line x1="20" y1="14" x2="23" y2="14"/><line x1="1" y1="9" x2="4" y2="9"/><line x1="1" y1="14" x2="4" y2="14"/>',
  user: '<path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/>',
  back: '<polyline points="15 18 9 12 15 6"/>',
  logout: '<path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/><polyline points="16 17 21 12 16 7"/><line x1="21" y1="12" x2="9" y2="12"/>',
}

function renderIcon(name: string): string {
  const inner = ICONS[name] ?? ''
  return `<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">${inner}</svg>`
}
</script>

<style scoped>
/* ═══════════════════════════════════════════════════════════════════
 * v3 2026-05-20 — admin-spa AdminLayout 视觉跟 frontend 完全对齐
 *
 * 复制自 frontend/src/components/v2/RailSidebar.vue 关键样式：
 *   - .rail (224px width + surface-2 bg + line border)
 *   - .rail-brand (logo + title)
 *   - .rail-item (active brand-soft + 3px brand left bar)
 *   - .rail-foot console
 * 复制自 frontend/src/components/v2/ShellTopBar.vue：
 *   - .topbar (48px height + line border)
 *   - .topbar-crumb (text-3 + brand-final)
 *
 * Important: 不要用 Element Plus 的 el-aside/el-menu/el-header
 * 它们带自己的 chrome（border, padding, focus-shadow），即使 :deep 覆盖
 * 也无法跟 frontend custom DOM 完全一致。改用纯 HTML <aside><button><header>
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

/* ─── Rail (左 sidebar) ────────────────────────────────────────── */
.rail {
  width: 224px;
  height: 100%;
  display: flex;
  flex-direction: column;
  flex-shrink: 0;
  background: var(--surface-2);
  border-right: 1px solid var(--line);
  overflow: hidden;
}

.rail-brand {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 14px 14px;
  min-height: 56px;
}

.rail-logo {
  width: 32px;
  height: 32px;
  border-radius: var(--r-2, 6px);
  display: grid;
  place-items: center;
  color: var(--text-inverse, #fff);
  background: linear-gradient(135deg, var(--blue-500, #3B82F6), var(--blue-800, #1E40AF));
  box-shadow: var(--sh-brand, 0 8px 22px -8px rgba(29, 78, 216, 0.32));
  flex-shrink: 0;
}

.rail-brand-copy { min-width: 0; }

.rail-title {
  color: var(--text);
  font-size: 13px;
  font-weight: var(--fw-bold, 700);
  line-height: 1.2;
  letter-spacing: -0.01em;
}

.rail-title-sub {
  color: var(--text-3);
  font-size: 10.5px;
  font-weight: var(--fw-medium, 500);
  margin-top: 2px;
  letter-spacing: 0.04em;
}

/* ─── Rail items (nav) ─────────────────────────────────────────── */
.rail-scroll {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: 10px 10px;
  overflow-y: auto;
}

.rail-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 0 12px;
  height: 36px;
  border: 0;
  border-radius: var(--r-3, 8px);
  background: transparent;
  color: var(--text-2);
  font-family: inherit;
  font-size: 13px;
  font-weight: var(--fw-medium, 500);
  text-align: left;
  cursor: pointer;
  transition: background 0.14s var(--ease, cubic-bezier(0.2, 0.8, 0.2, 1)),
              color 0.14s var(--ease, cubic-bezier(0.2, 0.8, 0.2, 1));
}

.rail-item:hover {
  background: var(--brand-soft);
  color: var(--brand);
}

.rail-item.active {
  background: var(--brand-soft);
  color: var(--brand);
  font-weight: var(--fw-semibold, 600);
  box-shadow: inset 3px 0 0 var(--brand);
}

.rail-item:focus-visible {
  outline: 2px solid var(--line-focus, var(--brand-ring));
  outline-offset: -2px;
}

.rail-item-icon {
  display: grid;
  place-items: center;
  width: 18px;
  height: 18px;
  flex-shrink: 0;
}

.rail-item-label {
  min-width: 0;
  flex: 1;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

/* ─── Rail foot (bottom console) ───────────────────────────────── */
.rail-foot {
  padding: 10px 10px 14px;
  border-top: 1px solid var(--line);
}

.rail-console {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.console-row {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 0 10px;
  min-height: 32px;
  border: 0;
  border-radius: var(--r-3, 8px);
  background: transparent;
  color: var(--text-2);
  font-family: inherit;
  font-size: 12.5px;
  font-weight: var(--fw-medium, 500);
  text-align: left;
  text-decoration: none;
  cursor: pointer;
  transition: background 0.14s var(--ease, cubic-bezier(0.2, 0.8, 0.2, 1)),
              color 0.14s var(--ease, cubic-bezier(0.2, 0.8, 0.2, 1));
}

.console-row:hover {
  background: var(--brand-soft);
  color: var(--brand);
}

.console-row-icon {
  display: grid;
  place-items: center;
  width: 14px;
  height: 14px;
  flex-shrink: 0;
}

.account-row {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 10px 4px;
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

/* ─── TopBar (复制自 ShellTopBar) ────────────────────────────── */
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
.admin-content {
  flex: 1;
  min-width: 0;
  min-height: 0;
  padding: 24px 28px;
  background: var(--bg, #F8FAFC);
  overflow-y: auto;
}

/* ─── Embedded（被 iframe 包时）──────────────────────────────
 * 之前 v-if="!embedded" 隐藏 sidebar/header — 现在永远显
 * embedded 时让"返回工作台"按钮在 sidebar 显出，hostname 跟父窗口走 */

/* ═══════════════════════════════════════════════════════════════════
 * page-level :deep — 让所有 admin-spa view 内部的 .page-header 等
 * 跟 frontend BuilderFrame + h1 一样的视觉风格
 * ═══════════════════════════════════════════════════════════════════ */
.admin-content :deep(.page) {
  max-width: 1280px;
  margin: 0 auto;
  padding: 0 0 40px;
  color: var(--text);
}

.admin-content :deep(.page-header) {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 20px;
  margin-bottom: 20px;
  flex-wrap: wrap;
}

.admin-content :deep(.page-header h1) {
  margin: 0;
  color: var(--text);
  font-size: 22px;
  line-height: 1.2;
  font-weight: var(--fw-bold, 700);
  letter-spacing: -0.02em;
}

.admin-content :deep(.page-header p) {
  max-width: 720px;
  margin: 6px 0 0;
  color: var(--text-3);
  font-size: 13.5px;
  line-height: 1.55;
}

.admin-content :deep(.page-actions) {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  justify-content: flex-end;
}

/* el-card 兼容 — 这次往 v3 v3 v3 token */
.admin-content :deep(.el-card) {
  border: 1px solid var(--line) !important;
  border-radius: var(--r-4, 12px) !important;
  background: var(--surface) !important;
  box-shadow: var(--sh-1) !important;
  overflow: hidden;
  margin-bottom: 16px;
}

.admin-content :deep(.el-card__header) {
  min-height: 48px;
  display: flex;
  align-items: center;
  padding: 12px 18px;
  border-bottom: 1px solid var(--line);
  background: var(--surface-2);
  color: var(--text);
  font-size: 14px;
  font-weight: var(--fw-semibold, 600);
}

.admin-content :deep(.el-card__body) {
  padding: 18px;
}

.admin-content :deep(.el-table) {
  --el-table-border-color: var(--line);
  --el-table-header-bg-color: var(--surface-2);
  --el-table-row-hover-bg-color: var(--surface-2);
  --el-table-bg-color: var(--surface);
  --el-table-text-color: var(--text);
  font-size: 13px;
  background: var(--surface);
}

.admin-content :deep(.el-table th.el-table__cell) {
  background: var(--surface-2) !important;
  color: var(--text-2);
  font-weight: var(--fw-semibold, 600);
  font-size: 11.5px;
  letter-spacing: 0.02em;
  padding: 10px 14px;
  border-bottom: 1px solid var(--line);
}

.admin-content :deep(.el-table--striped .el-table__body tr.el-table__row--striped td.el-table__cell) {
  background: var(--surface);
}

.admin-content :deep(.el-table tbody tr:hover > td.el-table__cell) {
  background: var(--surface-2);
}

.admin-content :deep(.el-button) {
  border-radius: var(--r-2, 6px);
  font-weight: var(--fw-semibold, 600);
  font-size: 12.5px;
  height: 30px;
}

.admin-content :deep(.el-button--primary) {
  border: 0;
  background: var(--brand);
  color: var(--text-inverse, #fff);
}

.admin-content :deep(.el-button--primary:hover) {
  background: var(--brand-hover);
}

.admin-content :deep(.el-button--danger) {
  border: 0;
  background: var(--err);
}

.admin-content :deep(.el-tag) {
  border: 0;
  border-radius: var(--r-1, 4px);
  font-weight: var(--fw-semibold, 600);
  font-size: 10.5px;
  letter-spacing: 0.02em;
  height: 20px;
  line-height: 20px;
  padding: 0 7px;
}

.admin-content :deep(.el-input__wrapper),
.admin-content :deep(.el-select__wrapper),
.admin-content :deep(.el-textarea__inner) {
  border-radius: var(--r-2, 6px);
  background: var(--surface) !important;
  box-shadow: 0 0 0 1px var(--line) inset !important;
}

.admin-content :deep(.el-input__wrapper.is-focus),
.admin-content :deep(.el-select__wrapper.is-focused) {
  box-shadow: 0 0 0 2px var(--brand) inset !important;
}

/* ─── Dark theme overrides ─────────────────────────────────────── */
html[data-theme="dark"] .rail {
  background: var(--surface-2);
}
</style>
