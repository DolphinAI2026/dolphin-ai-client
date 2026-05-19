<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useUserStore } from '@/stores/user'
import { useMcpStore } from '@/stores/mcp'
import { useRuntimeDeploymentStore } from '@/stores/runtimeDeployment'

interface NavItem { key: string; label: string; icon: string; path: string; badge?: number }
interface NavGroup { group: string; items: NavItem[] }

defineProps<{ collapsed?: boolean }>()
const route = useRoute()
const router = useRouter()
const user = useUserStore()
const mcpStore = useMcpStore()
const runtimeStore = useRuntimeDeploymentStore()

// Lazy counts that don't have dedicated stores. undefined → hide badge.
const appCount = ref<number | undefined>(undefined)
const codingWorkspaceCount = ref<number | undefined>(undefined)

onMounted(async () => {
  // Hydrate stores that aren't already loaded. Use optional chaining so missing
  // actions (e.g. when a sibling agent hasn't added it yet) don't crash the rail.
  if (!mcpStore.servers.length) {
    try { await (mcpStore as any).fetchServers?.() } catch { /* badge stays 0 → hidden */ }
  }
  if (!runtimeStore.total) {
    try { await (runtimeStore as any).fetchDeployments?.() } catch { /* badge stays 0 → hidden */ }
  }
  // App count — dynamic import keeps initial bundle slim and avoids breaking if API surface shifts.
  try {
    const { applicationApi } = await import('@/api/application')
    const apps: any = (await applicationApi.list?.({ include_remote: false } as any)) ?? []
    appCount.value = Array.isArray(apps) ? apps.length : (apps?.items?.length ?? apps?.total ?? 0)
  } catch {
    appCount.value = undefined
  }
  // Coding workspaces — coding store keeps single active workspace, not a list. Hit the API directly.
  try {
    const { codingApi } = await import('@/api/coding')
    const wss: any = (await (codingApi as any).listWorkspaces?.()) ?? []
    codingWorkspaceCount.value = Array.isArray(wss) ? wss.length : (wss?.items?.length ?? wss?.total ?? 0)
  } catch {
    codingWorkspaceCount.value = undefined
  }
})

// `v-if="it.badge"` falsy-hides 0/undefined, so we feed `undefined` when there's nothing meaningful.
const NAV = computed<NavGroup[]>(() => [
  { group: '搭建', items: [
    { key: 'home',     label: '新建',            icon: 'home',  path: '/' },
    { key: 'apps',     label: '应用',            icon: 'apps',  path: '/apps', badge: appCount.value || undefined },
    { key: 'chat',     label: '睿鲸 AI Builder', icon: 'chat',  path: '/ai-chat?mode=requirements' },
  ]},
  { group: '开发', items: [
    { key: 'coding', label: '睿鲸 AI Coding', icon: 'whale', path: '/coding', badge: codingWorkspaceCount.value || undefined },
    { key: 'vibe',   label: 'Vibe Coding',    icon: 'code',  path: '/vibe' },
  ]},
  // 2026-05-19 用户拍板"先去掉" 智能体配置 / 设计文档 / 行业知识库 三项 —
  // 留 组件市场 + MCP 管理 在"知识 & 智能体"分组下。路由保留（admin 可手动访问）。
  { group: '知识 & 智能体', items: [
    { key: 'marketplace', label: '组件市场',   icon: 'store',    path: '/marketplace' },
    { key: 'mcp',         label: 'MCP 管理',   icon: 'mcp',      path: '/mcp', badge: mcpStore.total || undefined },
  ]},
  { group: '管理', items: [
    { key: 'runtime', label: '运行与发布', icon: 'cloud', path: '/runtime', badge: runtimeStore.total || undefined },
    { key: 'admin',   label: '平台管理',   icon: 'admin', path: '/admin/tenants' },
  ]},
])

const isActive = (path: string) => {
  // Strip query string for path comparison (e.g. '/ai-chat?mode=requirements' → '/ai-chat')
  const basePath = path.split('?')[0]
  if (basePath === '/') return route.path === '/'
  return route.path === basePath || route.path.startsWith(basePath + '/')
}
const userName = computed(() => user.user?.username || '未登录')
const tenantName = computed(() => user.user?.tenant_name || '得帆云示例租户')

// Icon set copied from $DESIGN_SRC/shell.jsx (lines 14-75). Keep stroke 1.6,
// 24 viewBox, no fill. Only inline the icons we actually reference in NAV.
const ICONS: Record<string, string> = {
  home:     '<path d="M3 11.5 12 4l9 7.5V20a1 1 0 0 1-1 1h-5v-6h-6v6H4a1 1 0 0 1-1-1z"/>',
  apps:     '<path d="M3 5h7v7H3z"/><path d="M14 5h7v7h-7z"/><path d="M3 16h7v5H3z"/><path d="M14 16h7v5h-7z"/>',
  chat:     '<path d="M21 12a8 8 0 0 1-11.9 7L4 21l1.6-4.4A8 8 0 1 1 21 12z"/>',
  doc:      '<path d="M7 3h8l4 4v13a1 1 0 0 1-1 1H7a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1z"/><path d="M14 3v5h5"/><path d="M9 13h6"/><path d="M9 17h4"/>',
  code:     '<path d="m9 17-5-5 5-5"/><path d="m15 7 5 5-5 5"/><path d="m13 5-2 14"/>',
  store:    '<path d="M3 9 5 4h14l2 5"/><path d="M4 9v10a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1V9"/><path d="M3 9h18"/>',
  admin:    '<path d="M12 2 4 5v7c0 5 3.5 8.5 8 10 4.5-1.5 8-5 8-10V5z"/><path d="M9 12l2 2 4-4"/>',
  sparkle:  '<path d="M12 3 14 9l6 2-6 2-2 6-2-6-6-2 6-2z"/><path d="M19 17l1 3 3 1-3 1-1 3-1-3-3-1 3-1z"/>',
  bldg:     '<path d="M4 21V5l8-3 8 3v16"/><path d="M9 9h.01M9 13h.01M9 17h.01M15 9h.01M15 13h.01M15 17h.01"/><path d="M4 21h16"/>',
  cloud:    '<path d="M18 18a4 4 0 0 0 0-8 6 6 0 0 0-12 1 4 4 0 0 0 0 8z"/>',
  whale:    '<path d="M5 3c-1.5 0-2.2 1.2-2.2 2.4v3l-1.4 1 1.4 1v3.2c0 1.2.7 2.4 2.2 2.4"/><path d="M19 3c1.5 0 2.2 1.2 2.2 2.4v3l1.4 1-1.4 1v3.2c0 1.2-.7 2.4-2.2 2.4"/>',
  industry: '<path d="M3 21V11l6-4v4l6-4v4l6-4v14H3z"/><path d="M7 17h2M11 17h2M15 17h2"/>',
  mcp:      '<path d="M12 3 4 7v5c0 4 3.4 7.4 8 9 4.6-1.6 8-5 8-9V7z"/><path d="M8.5 11l2.5 2.5L15.5 9"/>',
}
function renderIcon(name: string): string {
  const inner = ICONS[name] ?? ''
  return `<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round">${inner}</svg>`
}
</script>

<template>
  <aside class="rail" :class="{ 'rail-collapsed': collapsed }">
    <div class="rail-brand">
      <button class="rail-logo" @click="router.push('/')" aria-label="aPaaS Builder">
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none">
          <rect x="3" y="3" width="8" height="8" rx="2" fill="white" />
          <rect x="13" y="3" width="8" height="8" rx="2" fill="rgba(255,255,255,0.6)" />
          <rect x="3" y="13" width="8" height="8" rx="2" fill="rgba(255,255,255,0.6)" />
          <rect x="13" y="13" width="8" height="8" rx="2" fill="white" />
        </svg>
      </button>
      <div v-if="!collapsed">
        <div class="rail-title">aPaaS Builder</div>
        <div class="rail-title-sub">AI · 低代码 · 全代码</div>
      </div>
    </div>

    <div class="rail-scroll">
      <div v-for="g in NAV" :key="g.group" class="rail-group">
        <div class="rail-group-label">{{ g.group }}</div>
        <button
          v-for="it in g.items"
          :key="it.key"
          class="rail-item"
          :class="{ active: isActive(it.path) }"
          @click="router.push(it.path)"
        >
          <span class="rail-item-icon" v-html="renderIcon(it.icon)" />
          <span class="rail-item-label">{{ it.label }}</span>
          <span v-if="it.badge" class="rail-item-badge">{{ it.badge }}</span>
        </button>
      </div>
    </div>

    <div class="rail-foot">
      <button class="rail-user">
        <div class="rail-avatar">{{ userName.slice(0, 1).toUpperCase() }}</div>
        <div class="rail-user-info">
          <div class="rail-user-name">{{ userName }}</div>
          <div class="rail-user-tenant">{{ tenantName }}</div>
        </div>
      </button>
    </div>
  </aside>
</template>

<style scoped>
/* Visual rules copied verbatim from $DESIGN_SRC/styles.css lines 230-392.
   Component-scoped so they only apply within this rail. */
.rail { display: flex; flex-direction: column; background: var(--bg-rail); border-right: 1px solid var(--border); overflow: hidden; position: relative; width: 232px; flex-shrink: 0; height: 100%; }
.rail-collapsed { width: 56px; }
.rail-brand { display: flex; align-items: center; gap: 10px; padding: 14px 16px 12px; min-height: 56px; border-bottom: 1px solid var(--border); }
.rail-logo { width: 30px; height: 30px; border-radius: 9px; background: linear-gradient(135deg, var(--brand-500), var(--brand-700)); display: grid; place-items: center; color: #fff; flex-shrink: 0; box-shadow: 0 4px 12px var(--brand-ring), inset 0 -1px 0 rgba(255,255,255,0.15); border: none; cursor: pointer; }
.rail-title { font-size: 14px; font-weight: 600; color: var(--text); letter-spacing: -0.01em; white-space: nowrap; overflow: hidden; }
.rail-title-sub { font-size: 10.5px; font-weight: 500; color: var(--text-3); letter-spacing: 0.08em; text-transform: uppercase; margin-top: 1px; }
.rail-scroll { flex: 1; min-height: 0; overflow-y: auto; padding: 8px 8px 4px; }
.rail-group { padding: 10px 8px 4px; }
.rail-group-label { font-size: 10.5px; font-weight: 600; color: var(--text-3); letter-spacing: 0.10em; text-transform: uppercase; padding: 4px 8px; margin-bottom: 2px; }
.rail-collapsed .rail-group-label { opacity: 0; height: 0; padding: 0; margin: 0; overflow: hidden; }
.rail-item { width: 100%; display: flex; align-items: center; gap: 10px; padding: 7px 10px; border: none; background: transparent; border-radius: 8px; cursor: pointer; font-size: 13px; font-weight: 500; color: var(--text-2); text-align: left; transition: background 0.12s, color 0.12s; position: relative; }
.rail-item:hover { background: var(--brand-soft); color: var(--text); }
.rail-item.active { background: var(--brand-soft-2); color: var(--brand-text); }
.rail-item.active::before { content: ''; position: absolute; left: -10px; top: 8px; bottom: 8px; width: 3px; border-radius: 2px; background: var(--brand); }
.rail-item-icon { width: 18px; height: 18px; flex-shrink: 0; display: grid; place-items: center; color: currentColor; }
.rail-item-icon :deep(svg) { width: 18px; height: 18px; }
.rail-item-label { flex: 1; white-space: nowrap; overflow: hidden; }
.rail-item-badge { font-size: 10.5px; font-weight: 600; padding: 1px 6px; border-radius: 999px; background: var(--surface); color: var(--text-3); border: 1px solid var(--border); }
.rail-item.active .rail-item-badge { background: var(--brand); color: #fff; border-color: var(--brand); }
.rail-collapsed .rail-item { justify-content: center; padding: 8px; }
.rail-collapsed .rail-item-label, .rail-collapsed .rail-item-badge, .rail-collapsed .rail-title, .rail-collapsed .rail-title-sub { display: none; }
.rail-foot { padding: 8px; border-top: 1px solid var(--border); display: flex; flex-direction: column; gap: 4px; }
.rail-user { display: flex; align-items: center; gap: 10px; padding: 8px 10px; border-radius: 10px; cursor: pointer; transition: background 0.12s; background: transparent; border: none; width: 100%; text-align: left; }
.rail-user:hover { background: var(--brand-soft); }
.rail-avatar { width: 28px; height: 28px; border-radius: 50%; background: linear-gradient(135deg, var(--brand-400), var(--brand-600)); color: #fff; font-size: 12px; font-weight: 600; display: grid; place-items: center; flex-shrink: 0; }
.rail-user-info { flex: 1; min-width: 0; }
.rail-user-name { font-size: 13px; font-weight: 600; color: var(--text); line-height: 1.2; }
.rail-user-tenant { font-size: 11px; color: var(--text-3); line-height: 1.2; margin-top: 1px; }
.rail-collapsed .rail-user-info { display: none; }
</style>
