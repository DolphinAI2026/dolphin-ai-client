<script setup lang="ts">
import { computed } from 'vue'
import { useRoute } from 'vue-router'

interface BreadcrumbItem {
  label: string
  to?: string
  href?: string
}

const props = defineProps<{
  breadcrumbs?: BreadcrumbItem[]
}>()

const route = useRoute()

const CRUMB_LABELS: Record<string, string> = {
  '/': '新建',
  '/apps': '应用',
  '/chat': '睿鲸 AI Builder',
  '/ai-chat': '睿鲸 AI Builder',
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
  '/db-connections': '数据库连接',
  '/quick-db': 'DB 问数',
  // v3 2026-05-20 fix: 之前 CRUMB_LABELS 写的 '/sandbox-monitor' / '/platform-tenants'
  // 跟 router/index.ts 的真实 path 不匹配，永远不命中 → fall through 显 "页面"。
  // 改成真路径：SandboxMonitor 是 /vibe-coding/sandboxes，PlatformTenants 是 /admin/tenants
  '/vibe-coding/sandboxes': '沙箱监控',
  '/tenant-users': '成员管理',
  '/platform-envs': '平台环境',
  '/admin/tenants': '租户管理',
  '/platform-admin': '平台管理',
  '/devops': 'DevOps',
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
    <!-- Per-page action surface. BuilderFrame forwards its `#actions` slot here
         so pages (Apps / TenantUsers / PlatformTenants / PlatformEnvs /
         McpToolsPage / OnlineCodingPage / OnlineCodingWorkspacePage) keep
         their toolbars rendered in the topbar. -->
    <div class="topbar-page-actions">
      <slot name="actions" />
    </div>
  </div>
</template>

<style scoped>
/* v3 redesign · 2026-05-20 — visual refresh only, template/script untouched.
   Preserved (don't change):
     - 48px height
     - #actions slot transfer mechanism (BuilderFrame → topbar-page-actions)
     - All class names (no external CSS depends on these because scoped)
     - position/z-index for sticky stacking
   Refreshed:
     - --border → --line (intent clarity; same color via v2→v3 alias)
     - action button radius 8 → 6 (matches v3 r-2 token system)
     - hover bg: surface-2 → brand-soft (subtle blue hint vs deadgrey)
     - hover color: text → brand (signals interactivity)
     - added :focus-visible ring for a11y
     - tightened gap rhythm (12→14 outer, 6→8 crumb)
*/
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
  font-weight: 500;
  letter-spacing: -0.005em;
}
.topbar-crumb-sep { color: var(--text-4); font-weight: 400; }
.topbar-crumb-mid { color: var(--text-2); }
.topbar-crumb-current {
  color: var(--text);
  font-weight: 600;
  letter-spacing: -0.005em;
}

/* Holds per-page action buttons forwarded from BuilderFrame's #actions slot. */
.topbar-page-actions { display: flex; align-items: center; gap: 6px; }
.topbar-page-actions:empty { display: none; }

.topbar-actions { display: flex; align-items: center; gap: 6px; }

.topbar-action {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  height: 30px;
  padding: 0 12px;
  border: 1px solid var(--line);
  border-radius: var(--r-2, 6px);
  background: var(--surface);
  color: var(--text-2);
  font-size: 12.5px;
  font-weight: 500;
  cursor: pointer;
  font-family: inherit;
  transition: border-color 0.14s var(--ease, cubic-bezier(0.2, 0.8, 0.2, 1)),
              background 0.14s var(--ease, cubic-bezier(0.2, 0.8, 0.2, 1)),
              color 0.14s var(--ease, cubic-bezier(0.2, 0.8, 0.2, 1));
}
.topbar-action:hover {
  color: var(--brand);
  border-color: var(--brand-ring);
  background: var(--brand-soft);
}
.topbar-action:focus-visible {
  outline: 2px solid var(--line-focus, var(--brand-ring));
  outline-offset: 2px;
}

.icon-btn {
  width: 32px;
  height: 32px;
  border-radius: var(--r-2, 6px);
  background: transparent;
  border: none;
  cursor: pointer;
  color: var(--text-3);
  display: grid;
  place-items: center;
  transition: background 0.14s var(--ease, cubic-bezier(0.2, 0.8, 0.2, 1)),
              color 0.14s var(--ease, cubic-bezier(0.2, 0.8, 0.2, 1));
}
.icon-btn:hover {
  background: var(--brand-soft);
  color: var(--brand);
}
.icon-btn:focus-visible {
  outline: 2px solid var(--line-focus, var(--brand-ring));
  outline-offset: 2px;
}

html[data-theme="dark"] .topbar-action:hover,
html[data-theme="dark"] .icon-btn:hover {
  background: var(--brand-soft);
  color: var(--brand);
}
</style>
