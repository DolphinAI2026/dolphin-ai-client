<script setup lang="ts">
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useThemeStore } from '@/stores/theme'
import { useUserStore } from '@/stores/user'

interface BreadcrumbItem {
  label: string
  to?: string
  href?: string
}

const props = defineProps<{
  breadcrumbs?: BreadcrumbItem[]
}>()

const route = useRoute()
const router = useRouter()
const theme = useThemeStore()
const user = useUserStore()

const CRUMB_LABELS: Record<string, string> = {
  '/': '新建',
  '/apps': '应用',
  '/chat': '睿鲸 AI Builder',
  '/coding': '睿鲸 AI Coding',
  '/vibe': 'Vibe Coding',
  '/vibe-coding': 'Vibe Coding',
  '/agents': '智能体配置',
  '/specs': '设计文档',
  '/industry': '行业知识库',
  '/marketplace': '组件市场',
  '/mcp': 'MCP 管理',
  '/runtime': '运行与发布',
  '/admin/tenants': '平台管理',
}
const crumbCurrent = computed(() => {
  const exact = CRUMB_LABELS[route.path]
  if (exact) return exact
  const segs = Object.keys(CRUMB_LABELS).filter(k => route.path.startsWith(k) && k !== '/').sort((a, b) => b.length - a.length)
  return CRUMB_LABELS[segs[0]] ?? '页面'
})

// Pages that wrap themselves in BuilderFrame can pass an explicit breadcrumb
// array (e.g. `:breadcrumbs="[{ label: '设置' }, { label: '成员管理' }]"`).
// When non-empty, prefer those over the route-derived label so per-page
// hierarchy (e.g. 设置 / 成员管理) is preserved.
const hasCustomCrumbs = computed(() => Array.isArray(props.breadcrumbs) && props.breadcrumbs.length > 0)

// Dispatches the event BuilderCommandPalette.vue listens for (see its
// onMounted -> window.addEventListener('builder:open-command', show)).
function openCmdK() {
  window.dispatchEvent(new CustomEvent('builder:open-command'))
}
function toggleTheme() {
  theme.toggle()
}
const isDark = computed(() => theme.mode === 'dark')
</script>

<template>
  <div class="topbar">
    <div class="topbar-crumb">
      <span>aPaaS Builder</span>
      <template v-if="hasCustomCrumbs">
        <template v-for="(item, idx) in (props.breadcrumbs as BreadcrumbItem[])" :key="idx">
          <span class="topbar-crumb-sep">/</span>
          <span
            :class="idx === (props.breadcrumbs as BreadcrumbItem[]).length - 1 ? 'topbar-crumb-current' : 'topbar-crumb-mid'"
          >{{ item.label }}</span>
        </template>
      </template>
      <template v-else>
        <span class="topbar-crumb-sep">/</span>
        <span class="topbar-crumb-current">{{ crumbCurrent }}</span>
      </template>
    </div>
    <button class="topbar-search" @click="openCmdK">
      <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><circle cx="11" cy="11" r="8"/><path d="m21 21-4.3-4.3"/></svg>
      <span>搜索 · 跳转 · 操作</span>
      <span class="topbar-search-kbd">⌘K</span>
    </button>
    <!-- Per-page action surface. BuilderFrame forwards its `#actions` slot here
         so pages (Apps / TenantUsers / PlatformTenants / PlatformEnvs /
         McpToolsPage / OnlineCodingPage / OnlineCodingWorkspacePage) keep
         their toolbars rendered in the topbar. -->
    <div class="topbar-page-actions">
      <slot name="actions" />
    </div>
    <div class="topbar-actions">
      <button v-if="user.isTenantAdmin" class="topbar-action" @click="router.push('/tenant-users')">成员管理</button>
      <button v-if="user.isTenantAdmin" class="topbar-action" @click="router.push('/platform-envs')">平台环境</button>
      <button class="icon-btn" @click="toggleTheme" :aria-label="isDark ? '切换浅色主题' : '切换深色主题'">
        <svg v-if="isDark" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M21 13A9 9 0 0 1 11 3a9 9 0 1 0 10 10z"/></svg>
        <svg v-else width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4 12H2M22 12h-2M6.3 6.3 4.9 4.9M19.1 19.1l-1.4-1.4M6.3 17.7l-1.4 1.4M19.1 4.9l-1.4 1.4"/></svg>
      </button>
      <button class="icon-btn" aria-label="通知">
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M6 8a6 6 0 1 1 12 0c0 7 3 9 3 9H3s3-2 3-9"/><path d="M10 21a2 2 0 0 0 4 0"/></svg>
      </button>
    </div>
  </div>
</template>

<style scoped>
/* Verbatim from $DESIGN_SRC/styles.css lines 397-484. */
.topbar { display: flex; align-items: center; gap: 12px; padding: 0 20px; height: 48px; background: var(--surface); border-bottom: 1px solid var(--border); position: relative; z-index: 5; }
.topbar-crumb { display: flex; align-items: center; gap: 6px; font-size: 13px; color: var(--text-2); flex: 1; min-width: 0; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.topbar-crumb-sep { color: var(--text-4); }
.topbar-crumb-mid { color: var(--text-2); }
.topbar-crumb-current { color: var(--text); font-weight: 600; }
/* Holds per-page action buttons forwarded from BuilderFrame's #actions slot.
   Sits between the search input and the global icon cluster so page-level
   buttons (e.g. "新建应用", workspace view-toggle) stay visually grouped. */
.topbar-page-actions { display: flex; align-items: center; gap: 6px; }
.topbar-page-actions:empty { display: none; }
.topbar-search { display: flex; align-items: center; gap: 8px; height: 30px; padding: 0 12px; border: 1px solid var(--border); border-radius: 8px; background: var(--surface-2); color: var(--text-3); font-size: 12.5px; cursor: pointer; min-width: 240px; transition: border-color 0.12s, background 0.12s; font-family: inherit; }
.topbar-search:hover { border-color: var(--border-strong); background: var(--surface); }
.topbar-search-kbd { margin-left: auto; display: inline-flex; align-items: center; gap: 2px; font-family: var(--d-font-mono); font-size: 10.5px; color: var(--text-3); padding: 1px 5px; border: 1px solid var(--border); border-radius: 4px; background: var(--surface); }
.topbar-actions { display: flex; align-items: center; gap: 4px; }
.topbar-action { display: inline-flex; align-items: center; gap: 6px; height: 30px; padding: 0 10px; border: 1px solid var(--border); border-radius: 8px; background: var(--surface); color: var(--text-2); font-size: 12.5px; font-weight: 500; cursor: pointer; font-family: inherit; transition: border-color 0.12s, background 0.12s, color 0.12s; }
.topbar-action:hover { color: var(--text); border-color: var(--border-strong); background: var(--surface-2); }
.icon-btn { width: 32px; height: 32px; border-radius: 8px; background: transparent; border: none; cursor: pointer; color: var(--text-2); display: grid; place-items: center; transition: background 0.12s, color 0.12s; }
.icon-btn:hover { background: var(--surface-2); color: var(--text); }
</style>
