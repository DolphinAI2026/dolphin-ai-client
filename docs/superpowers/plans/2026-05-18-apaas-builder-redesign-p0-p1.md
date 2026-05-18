# aPaaS Builder AI Redesign — P0 + P1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Land the architectural foundation (P0) and core build-path pages (P1) of the Claude Design aPaaS Builder redesign in the existing Vue 3 + Element Plus codebase, without breaking any existing functionality, across 6 review-checkpointed sessions.

**Architecture:** Add the design's indigo-violet (`--brand-*` #5B5BD6) and cyan (`--ai-*` #1D89A8) token system *additively* (scoped via a `[data-design="v2"]` opt-in attribute on the redesigned shell), so existing pages keep their current `--t-*` and oklch (`--bg`/`--fg`/`--brand`) tokens. New pages and rebuilt shells opt into v2 tokens; legacy pages keep working untouched. Project becomes a first-class container via a new `useProjectStore` + a `ProjectSwitcher` in `TopBar`, but route migration is non-destructive (existing `/project/:id` stays as alias). Sidebar `AppSidebar.vue` is restructured to the 4-group layout (`搭建 / 开发 / 知识 & 智能体 / 管理`) showing every menu for every user — no role-based filtering. The design's 14 routes are added with stub pages for P0; P1 fills in Landing, ChatPage shell, Apps refresh, Projects list/detail, and Specs.

**Tech Stack:** Vue 3 Composition API, TypeScript, Vue Router 4, Pinia, Element Plus, Vite, plain CSS custom properties. Source design lives at `/tmp/design-extract/apaas-builder-ai/project/design_handoff_apaas_builder/source/` (extracted from the Claude Design handoff bundle); refer to `styles.css`, `pages.css`, `pages2.css`, `pages3.css`, and the per-page `page-*.jsx` files for pixel-level visual reference.

**Reference paths used throughout this plan:**

- `DESIGN_SRC` = `/tmp/design-extract/apaas-builder-ai/project/design_handoff_apaas_builder/source`
- `DESIGN_README` = `/tmp/design-extract/apaas-builder-ai/project/design_handoff_apaas_builder/README.md`
- Repo root = `/Users/mars/Vibe Coding/apaas-builder-ai`
- Frontend root = `frontend/src/` (relative to repo root)

**Sessions in this plan:**

| Session | Scope | Risk | Files touched |
|---|---|---|---|
| 1 | Design token foundation (additive) | none | 2 |
| 2 | Sidebar + TopBar + project switcher + router additions | low | 6 |
| 3 | Projects (list + detail) + Project store | low | 5 |
| 4 | Landing redesign | medium (rewrites Landing.vue, ~2.5K lines) | 2 |
| 5 | ChatPage shell restructure (preserves all logic) | high (touches 13K-line file) | 3 |
| 6 | Specs page + Apps visual refresh + Deploy modal | low | 5 |

**Deferred to a follow-up plan (P2/P3):** `/agents`, `/coding` (睿鲸) rework to remove preview, `/vibe` real code-server embed, `/industry` Ontology SVG graph, `/runtime` 4-tab page, MCP page polish, Onboarding tour.

---

## Conventions for every session

- **Token namespace rule:** New design tokens go on `:root` as raw values (`--brand-500: #5B5BD6;`) so they don't collide. *Semantic aliases* that DO collide with existing names (`--brand`, `--surface`, `--text`, `--text-2`, etc.) are scoped under `[data-design="v2"]` only. The `[data-design="v2"]` attribute is set on the `<div class="app">` root of any redesigned shell. Pages outside that root inherit nothing new and continue to use `--t-*` / oklch tokens.
- **Class name rule:** Use the design's exact class names verbatim (`.rail`, `.rail-item`, `.topbar`, `.btn`, `.btn-primary`, `.card`, `.page`, `.page-pad`, `.section-title`, `.badge`, `.badge-brand`, etc.). They live in the new redesign stylesheet only; legacy code keeps its own classes.
- **No React-to-Vue mechanical translation.** Read the JSX for structure and the CSS for visuals. Re-express each piece as a Vue 3 SFC using `<script setup lang="ts">` + Element Plus where it cleanly maps (buttons, dialogs, tooltips, tables) and raw HTML where the design has bespoke chrome (sidebar, topbar, cmd+K, blueprint cards).
- **Pixel alignment:** Every padding, border-radius, font-size, color must match the design source `styles.css` and `pages*.css`. When in doubt, copy from those files literally.
- **i18n:** Strings stay Chinese to match the existing app.
- **Commits:** Each task ends with a commit. Branch off `local/cleanup-2026-05-16` (current branch).
- **Visual verification:** End each session by running `pnpm --filter frontend dev` (or `npm --prefix frontend run dev`), opening the changed page in browser, toggling light/dark via the existing `ThemeToggle`, screenshotting, and pasting the screenshot into the PR/handoff note. The repo has no frontend test suite — visual + manual interaction is the verification gate.

---

## Session 1 — Design Token Foundation

**Objective:** Make the indigo-violet brand + cyan AI accent + paired light/dark tokens available everywhere, scoped so no existing component changes color.

**Files:**

- Create: `frontend/src/styles/design-v2-tokens.css`
- Modify: `frontend/src/main.ts` (one import line)

### Task 1.1 — Create `design-v2-tokens.css`

- [ ] **Step 1: Create the file with raw palette + scoped semantic aliases**

Copy the palette block verbatim from `$DESIGN_SRC/styles.css` lines 6–41 (palette + fonts) as `:root` declarations. Then copy the light theme block (lines 44–97) into a `[data-design="v2"], [data-design="v2"][data-theme="light"]` selector, and the dark theme block (lines 100–153) into `[data-design="v2"][data-theme="dark"]`.

```css
/* frontend/src/styles/design-v2-tokens.css
 * Source-of-truth: design_handoff_apaas_builder/source/styles.css
 * Indigo-violet + cyan AI accent token system from the Claude Design handoff.
 * Scoped under [data-design="v2"] so it does not affect legacy components.
 */

:root {
  --brand-50: #F2F0FE;
  --brand-100: #E6E3FD;
  --brand-200: #CDC8FB;
  --brand-300: #ABA2F7;
  --brand-400: #847AF0;
  --brand-500: #5B5BD6;
  --brand-600: #4747C2;
  --brand-700: #38379E;
  --brand-800: #2D2C7B;

  --ai-50:  #ECF8FB;
  --ai-100: #D2EEF5;
  --ai-200: #A5DDEB;
  --ai-300: #6BC2DA;
  --ai-400: #34A4C2;
  --ai-500: #1D89A8;
  --ai-600: #156F8C;
  --ai-700: #105A73;

  --emerald-500: #10A37F;
  --emerald-soft: rgba(16, 163, 127, 0.10);
  --amber-500: #D97706;
  --amber-soft: rgba(217, 119, 6, 0.10);
  --rose-500: #DC2626;
  --rose-soft: rgba(220, 38, 38, 0.10);
  --sky-500: #0284C7;
  --sky-soft: rgba(2, 132, 199, 0.10);

  --d-font-sans: "Inter", "PingFang SC", -apple-system, "Helvetica Neue", system-ui, sans-serif;
  --d-font-mono: "JetBrains Mono", "SF Mono", "Menlo", "Consolas", monospace;
}

[data-design="v2"],
[data-design="v2"][data-theme="light"] {
  --bg-base: #F4F2F9;
  --bg-app: linear-gradient(180deg, #F6F4FB 0%, #F0EEF7 100%);
  --bg-rail: #EDEAF6;
  --surface: #FFFFFF;
  --surface-2: #FAF9FD;
  --surface-3: #F3F1F8;
  --surface-overlay: rgba(255, 255, 255, 0.78);
  --glass: rgba(255, 255, 255, 0.72);
  --glass-strong: rgba(255, 255, 255, 0.92);

  --border: rgba(58, 50, 121, 0.10);
  --border-strong: rgba(58, 50, 121, 0.18);
  --border-focus: rgba(91, 91, 214, 0.45);

  --text: #18152E;
  --text-2: #4F4A6E;
  --text-3: #837EA0;
  --text-4: #B5B1C9;
  --text-inverse: #FFFFFF;

  --brand: var(--brand-500);
  --brand-hover: var(--brand-600);
  --brand-text: var(--brand-700);
  --brand-soft: var(--brand-50);
  --brand-soft-2: var(--brand-100);
  --brand-ring: rgba(91, 91, 214, 0.18);

  --emerald: var(--emerald-500);
  --emerald-bg: var(--emerald-soft);
  --amber: var(--amber-500);
  --amber-bg: var(--amber-soft);
  --rose: var(--rose-500);
  --rose-bg: var(--rose-soft);
  --sky: var(--sky-500);
  --sky-bg: var(--sky-soft);

  --shadow-xs: 0 1px 2px rgba(28, 21, 73, 0.04);
  --shadow-sm: 0 1px 3px rgba(28, 21, 73, 0.06), 0 1px 2px rgba(28, 21, 73, 0.04);
  --shadow-md: 0 4px 12px rgba(28, 21, 73, 0.06), 0 2px 4px rgba(28, 21, 73, 0.04);
  --shadow-lg: 0 12px 32px rgba(28, 21, 73, 0.10), 0 4px 12px rgba(28, 21, 73, 0.06);
  --shadow-xl: 0 24px 60px rgba(28, 21, 73, 0.14), 0 8px 24px rgba(28, 21, 73, 0.08);

  --code-bg: #F6F4FB;
  --code-text: #38379E;

  --ai: var(--ai-500);
  --ai-hover: var(--ai-600);
  --ai-text: var(--ai-600);
  --ai-soft: var(--ai-50);
  --ai-soft-2: var(--ai-100);
  --ai-ring: rgba(29, 137, 168, 0.18);
}

[data-design="v2"][data-theme="dark"] {
  --bg-base: #0B0A14;
  --bg-app: linear-gradient(180deg, #0E0D1A 0%, #0A0913 100%);
  --bg-rail: #100E1C;
  --surface: #15131F;
  --surface-2: #1A1727;
  --surface-3: #211D31;
  --surface-overlay: rgba(21, 19, 31, 0.78);
  --glass: rgba(21, 19, 31, 0.78);
  --glass-strong: rgba(21, 19, 31, 0.92);

  --border: rgba(255, 255, 255, 0.07);
  --border-strong: rgba(255, 255, 255, 0.13);
  --border-focus: rgba(138, 138, 240, 0.55);

  --text: #F2F1F8;
  --text-2: #B8B4CB;
  --text-3: #837F9C;
  --text-4: #5A5670;
  --text-inverse: #0B0A14;

  --brand: #8A8AF0;
  --brand-hover: #A0A0F5;
  --brand-text: #B5B5F8;
  --brand-soft: rgba(138, 138, 240, 0.12);
  --brand-soft-2: rgba(138, 138, 240, 0.20);
  --brand-ring: rgba(138, 138, 240, 0.28);

  --emerald: #34D399;
  --emerald-bg: rgba(52, 211, 153, 0.14);
  --amber: #FBBF24;
  --amber-bg: rgba(251, 191, 36, 0.14);
  --rose: #F87171;
  --rose-bg: rgba(248, 113, 113, 0.14);
  --sky: #38BDF8;
  --sky-bg: rgba(56, 189, 248, 0.14);

  --shadow-xs: 0 1px 2px rgba(0, 0, 0, 0.3);
  --shadow-sm: 0 1px 3px rgba(0, 0, 0, 0.4);
  --shadow-md: 0 4px 12px rgba(0, 0, 0, 0.5);
  --shadow-lg: 0 12px 32px rgba(0, 0, 0, 0.6);
  --shadow-xl: 0 24px 60px rgba(0, 0, 0, 0.7);

  --code-bg: #1A1727;
  --code-text: #B5B5F8;

  --ai: #5BBBD7;
  --ai-hover: #7CCBE2;
  --ai-text: #8DD3E5;
  --ai-soft: rgba(91, 187, 215, 0.10);
  --ai-soft-2: rgba(91, 187, 215, 0.18);
  --ai-ring: rgba(91, 187, 215, 0.30);
}
```

- [ ] **Step 2: Import the stylesheet in `main.ts`**

Open `frontend/src/main.ts` and add `import './styles/design-v2-tokens.css'` immediately after the existing `theme-vars.css` import (find the line containing `theme-vars` and add the new import directly under it).

- [ ] **Step 3: Verify no existing page changed visually**

Run `npm --prefix frontend run dev`, open `http://localhost:5173/`, then `/apps`, then `/chat`, toggle theme. None of these should look different from before this commit (because no element has `[data-design="v2"]` yet).

- [ ] **Step 4: Manual smoke check with DevTools**

In the running app, in DevTools console: `getComputedStyle(document.documentElement).getPropertyValue('--brand-500')` should return `#5B5BD6`. `getComputedStyle(document.documentElement).getPropertyValue('--brand')` should still return the existing oklch/`#4f6ef7` value (because the v2 alias only applies inside `[data-design="v2"]`).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/styles/design-v2-tokens.css frontend/src/main.ts
git commit -m "feat(design): add v2 token namespace (indigo-violet + cyan AI), scoped via [data-design=\"v2\"]"
```

---

## Session 2 — Shell: Sidebar, TopBar, Project Switcher, Routes

**Objective:** Replace the global navigation chrome with the design's `rail` sidebar (4 groups, 13 items, all visible) and `topbar` (breadcrumb + ⌘K + theme + actions + project switcher). Add the 6 missing routes as empty stub views so navigation works end-to-end. Wrap the shell root in `[data-design="v2"]` to opt into the v2 tokens.

**Files:**

- Create: `frontend/src/components/v2/RailSidebar.vue`
- Create: `frontend/src/components/v2/ShellTopBar.vue`
- Create: `frontend/src/components/v2/ProjectSwitcher.vue`
- Create: `frontend/src/stores/project.ts`
- Modify: `frontend/src/router/index.ts` (add 6 routes)
- Create: `frontend/src/views/stubs/StubAgents.vue`, `StubSpecs.vue`, `StubIndustry.vue`, `StubRuntime.vue`, `StubMcp.vue`, `StubProjects.vue`
- Modify: `frontend/src/components/BuilderFrame.vue` (or `App.vue` — wherever the global shell currently lives — to swap rail/topbar for the v2 versions inside a `[data-design="v2"]` wrapper)

Before starting, run `rg -l 'GlobalNavRail\|AppSidebar\|BuilderNavRail' frontend/src` to find every place that mounts the sidebar — modifications converge in `BuilderFrame.vue` or the route layout component.

### Task 2.1 — Pinia `useProjectStore`

- [ ] **Step 1: Write `frontend/src/stores/project.ts`**

```ts
import { defineStore } from 'pinia'
import { computed, ref } from 'vue'

export interface Project {
  id: string
  name: string
  customerName: string
  stage: '设计中' | '开发中' | '测试中' | '已上线' | '维护中'
  progress: number
  appCount: number
  deployCount: number
  memberCount: number
  envCount: number
  industryPackId?: string | null
}

const STORAGE_KEY = 'aPaaS:currentProjectId'

export const useProjectStore = defineStore('project', () => {
  const projects = ref<Project[]>([
    { id: 'p-default', name: '得帆云示例租户', customerName: '内部演示', stage: '已上线', progress: 100, appCount: 6, deployCount: 12, memberCount: 4, envCount: 3, industryPackId: null },
  ])
  const currentProjectId = ref<string>(localStorage.getItem(STORAGE_KEY) ?? 'p-default')

  const currentProject = computed<Project | null>(
    () => projects.value.find(p => p.id === currentProjectId.value) ?? projects.value[0] ?? null,
  )

  function setCurrent(id: string) {
    currentProjectId.value = id
    localStorage.setItem(STORAGE_KEY, id)
  }

  function setProjects(next: Project[]) {
    projects.value = next
  }

  return { projects, currentProjectId, currentProject, setCurrent, setProjects }
})
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/stores/project.ts
git commit -m "feat(store): add useProjectStore with persisted currentProjectId"
```

### Task 2.2 — `RailSidebar.vue`

- [ ] **Step 1: Build the sidebar matching `$DESIGN_SRC/shell.jsx` lines 82–252 and `$DESIGN_SRC/styles.css` lines 230–392**

Component contract:
- Renders the 4-group navigation defined in `shell.jsx` `NAV` constant (groups: `搭建`, `开发`, `知识 & 智能体`, `管理`). Item order, labels, paths, and badge counts copy from `NAV` verbatim.
- Active item is determined by `useRoute().path` startsWith match.
- Click navigates via `useRouter().push()`.
- Includes the bottom `rail-user` row showing user name + tenant from `useUserStore` (no role pill, per design decision #2 in `$DESIGN_README`).
- Supports collapsed state via a prop `collapsed?: boolean` (P0 hooks it up but the default UI doesn't expose a collapse toggle — that ships in a P2 polish session).

```vue
<!-- frontend/src/components/v2/RailSidebar.vue -->
<script setup lang="ts">
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useUserStore } from '@/stores/user'

interface NavItem { key: string; label: string; icon: string; path: string; badge?: number }
interface NavGroup { group: string; items: NavItem[] }

const NAV: NavGroup[] = [
  { group: '搭建', items: [
    { key: 'home',     label: '新建',           icon: 'home',  path: '/' },
    { key: 'projects', label: '项目',           icon: 'bldg',  path: '/projects', badge: 4 },
    { key: 'apps',     label: '应用',           icon: 'apps',  path: '/apps', badge: 6 },
    { key: 'chat',     label: '睿鲸 AI Builder', icon: 'chat', path: '/chat' },
  ]},
  { group: '开发', items: [
    { key: 'coding', label: '睿鲸 AI Coding', icon: 'whale', path: '/coding', badge: 1 },
    { key: 'vibe',   label: 'Vibe Coding',    icon: 'code',  path: '/vibe' },
  ]},
  { group: '知识 & 智能体', items: [
    { key: 'agents',      label: '智能体配置', icon: 'sparkle',  path: '/agents' },
    { key: 'specs',       label: '设计文档',   icon: 'doc',      path: '/specs' },
    { key: 'industry',    label: '行业知识库', icon: 'industry', path: '/industry' },
    { key: 'marketplace', label: '组件市场',   icon: 'store',    path: '/marketplace' },
    { key: 'mcp',         label: 'MCP 管理',   icon: 'mcp',      path: '/mcp', badge: 8 },
  ]},
  { group: '管理', items: [
    { key: 'runtime', label: '运行与发布', icon: 'cloud', path: '/runtime', badge: 3 },
    { key: 'admin',   label: '平台管理',   icon: 'admin', path: '/admin/tenants' },
  ]},
]

defineProps<{ collapsed?: boolean }>()
const route = useRoute()
const router = useRouter()
const user = useUserStore()

const isActive = (path: string) => {
  if (path === '/') return route.path === '/'
  return route.path === path || route.path.startsWith(path + '/')
}
const userName = computed(() => user.userInfo?.username || '未登录')
const tenantName = computed(() => user.userInfo?.tenant_name || '得帆云示例租户')
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

<script lang="ts">
// Icon set copied from $DESIGN_SRC/shell.jsx (lines 14-75). Keep stroke 1.6,
// 18px viewBox, no fill. Only inline the icons we actually reference in NAV.
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
export function renderIcon(name: string): string {
  const inner = ICONS[name] ?? ''
  return `<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round">${inner}</svg>`
}
</script>

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
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/components/v2/RailSidebar.vue
git commit -m "feat(v2): add RailSidebar with 4-group nav (13 items, all visible)"
```

### Task 2.3 — `ProjectSwitcher.vue`

- [ ] **Step 1: Implement project switcher (the violet bar on the left of the topbar)**

Spec from `shell.jsx` `ProjectSwitcher` component (search for `Project switcher` heading inside `shell.jsx`). Behavior: button with violet color-bar + current project name + chevron; click toggles a popover listing all projects with their `stage` chip; clicking a project calls `useProjectStore().setCurrent(id)`.

```vue
<!-- frontend/src/components/v2/ProjectSwitcher.vue -->
<script setup lang="ts">
import { ref } from 'vue'
import { useProjectStore } from '@/stores/project'

const store = useProjectStore()
const open = ref(false)

function pick(id: string) {
  store.setCurrent(id)
  open.value = false
}
const stageBadgeClass = (stage: string) => ({
  '已上线': 'badge-emerald',
  '开发中': 'badge-amber',
  '测试中': 'badge-sky',
  '设计中': 'badge-brand',
  '维护中': 'badge-outline',
}[stage] ?? 'badge-outline')
</script>

<template>
  <div class="proj-switch-wrap">
    <button class="proj-switch" @click="open = !open">
      <span class="proj-switch-bar" />
      <span class="proj-switch-name">{{ store.currentProject?.name ?? '未选择' }}</span>
      <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="m6 9 6 6 6-6" /></svg>
    </button>
    <div v-if="open" class="proj-pop" @click.self="open = false">
      <div class="proj-pop-panel">
        <div class="proj-pop-head">切换项目</div>
        <button v-for="p in store.projects" :key="p.id" class="proj-pop-item" :class="{ active: p.id === store.currentProjectId }" @click="pick(p.id)">
          <span class="proj-pop-bar" />
          <span class="proj-pop-name">{{ p.name }}</span>
          <span class="badge" :class="stageBadgeClass(p.stage)">{{ p.stage }}</span>
        </button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.proj-switch-wrap { position: relative; }
.proj-switch { display: inline-flex; align-items: center; gap: 8px; height: 30px; padding: 0 10px 0 6px; border: 1px solid var(--border); border-radius: 8px; background: var(--surface); color: var(--text); font-size: 13px; font-weight: 600; cursor: pointer; font-family: inherit; transition: border-color 0.12s, background 0.12s; }
.proj-switch:hover { border-color: var(--border-strong); background: var(--surface-2); }
.proj-switch-bar { display: inline-block; width: 3px; height: 14px; border-radius: 2px; background: var(--brand-500); }
.proj-switch-name { letter-spacing: -0.005em; }
.proj-pop { position: fixed; inset: 0; z-index: 200; }
.proj-pop-panel { position: absolute; top: 44px; left: 20px; width: 320px; background: var(--glass-strong); backdrop-filter: blur(20px); border: 1px solid var(--border-strong); border-radius: 12px; box-shadow: var(--shadow-lg); overflow: hidden; }
.proj-pop-head { font-size: 11px; font-weight: 600; letter-spacing: 0.10em; text-transform: uppercase; color: var(--text-3); padding: 10px 14px 6px; }
.proj-pop-item { width: 100%; display: flex; align-items: center; gap: 10px; padding: 8px 14px; background: transparent; border: none; color: var(--text); font-size: 13px; cursor: pointer; text-align: left; }
.proj-pop-item:hover, .proj-pop-item.active { background: var(--brand-soft); }
.proj-pop-bar { width: 3px; height: 14px; border-radius: 2px; background: var(--brand-500); }
.proj-pop-name { flex: 1; }
</style>
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/components/v2/ProjectSwitcher.vue
git commit -m "feat(v2): add ProjectSwitcher popover bound to useProjectStore"
```

### Task 2.4 — `ShellTopBar.vue`

- [ ] **Step 1: Build the topbar matching `$DESIGN_SRC/styles.css` lines 397–484 and the `TopBar` JSX block in `shell.jsx`**

Layout: `[ProjectSwitcher] · [Breadcrumb] · [grow] · [Search hint with ⌘K kbd] · [member-mgmt action] · [env-mgmt action] · [theme toggle] · [bell icon-btn]`. Wire the search hint to dispatch a synthetic ⌘K event that the existing `BuilderCommandPalette.vue` already listens for (verify by reading that file first; if it listens for a different event, emit that one).

```vue
<!-- frontend/src/components/v2/ShellTopBar.vue -->
<script setup lang="ts">
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useThemeStore } from '@/stores/theme'
import ProjectSwitcher from './ProjectSwitcher.vue'

const route = useRoute()
const router = useRouter()
const theme = useThemeStore()

const CRUMB_LABELS: Record<string, string> = {
  '/': '新建',
  '/projects': '项目',
  '/apps': '应用',
  '/chat': '睿鲸 AI Builder',
  '/coding': '睿鲸 AI Coding',
  '/vibe': 'Vibe Coding',
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

function openCmdK() {
  window.dispatchEvent(new CustomEvent('builder:command-palette:open'))
}
function toggleTheme() {
  theme.toggle()
}
const isDark = computed(() => theme.theme === 'dark')
</script>

<template>
  <div class="topbar">
    <ProjectSwitcher />
    <div class="topbar-crumb">
      <span>aPaaS Builder</span>
      <span class="topbar-crumb-sep">/</span>
      <span class="topbar-crumb-current">{{ crumbCurrent }}</span>
    </div>
    <button class="topbar-search" @click="openCmdK">
      <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><circle cx="11" cy="11" r="8"/><path d="m21 21-4.3-4.3"/></svg>
      <span>搜索 · 跳转 · 操作</span>
      <span class="topbar-search-kbd">⌘K</span>
    </button>
    <div class="topbar-actions">
      <button class="topbar-action" @click="router.push('/tenant-users')">成员管理</button>
      <button class="topbar-action" @click="router.push('/platform-envs')">平台环境</button>
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
.topbar-crumb-current { color: var(--text); font-weight: 600; }
.topbar-search { display: flex; align-items: center; gap: 8px; height: 30px; padding: 0 12px; border: 1px solid var(--border); border-radius: 8px; background: var(--surface-2); color: var(--text-3); font-size: 12.5px; cursor: pointer; min-width: 240px; transition: border-color 0.12s, background 0.12s; font-family: inherit; }
.topbar-search:hover { border-color: var(--border-strong); background: var(--surface); }
.topbar-search-kbd { margin-left: auto; display: inline-flex; align-items: center; gap: 2px; font-family: var(--d-font-mono); font-size: 10.5px; color: var(--text-3); padding: 1px 5px; border: 1px solid var(--border); border-radius: 4px; background: var(--surface); }
.topbar-actions { display: flex; align-items: center; gap: 4px; }
.topbar-action { display: inline-flex; align-items: center; gap: 6px; height: 30px; padding: 0 10px; border: 1px solid var(--border); border-radius: 8px; background: var(--surface); color: var(--text-2); font-size: 12.5px; font-weight: 500; cursor: pointer; font-family: inherit; transition: border-color 0.12s, background 0.12s, color 0.12s; }
.topbar-action:hover { color: var(--text); border-color: var(--border-strong); background: var(--surface-2); }
.icon-btn { width: 32px; height: 32px; border-radius: 8px; background: transparent; border: none; cursor: pointer; color: var(--text-2); display: grid; place-items: center; transition: background 0.12s, color 0.12s; }
.icon-btn:hover { background: var(--surface-2); color: var(--text); }
</style>
```

- [ ] **Step 2: Verify the existing command palette wakes up**

Open `frontend/src/components/BuilderCommandPalette.vue` and find the event it listens to. If it listens to `builder:command-palette:open` directly, no change needed. Otherwise update the `openCmdK` dispatch in `ShellTopBar.vue` to match (do not change the palette — touching the palette is a P2 task). Document the actual event name in this step's commit message.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/v2/ShellTopBar.vue
git commit -m "feat(v2): add ShellTopBar with project switcher, breadcrumb, cmd-k hint, theme toggle"
```

### Task 2.5 — Wire the new shell into `BuilderFrame.vue`

- [ ] **Step 1: Identify the global frame**

Run `rg -l "GlobalNavRail\|<router-view\|RouterView" frontend/src/components frontend/src/App.vue frontend/src/views | head`. The frame is wherever the existing `GlobalNavRail` is mounted alongside `<RouterView>`.

- [ ] **Step 2: Add a v2 wrapper around the existing frame**

In the discovered frame component, replace the existing rail + topbar with the v2 versions, wrapped in the `[data-design="v2"]` opt-in. Preserve the existing `<RouterView>` and any auth/skeleton wrappers. Example diff target:

```vue
<template>
  <div class="app" data-design="v2" :data-theme="theme.theme">
    <RailSidebar />
    <div class="workbench">
      <ShellTopBar />
      <RouterView />
    </div>
    <!-- keep any existing global overlays (toast, dialog host, BuilderCommandPalette) below -->
    <BuilderCommandPalette />
  </div>
</template>

<style scoped>
.app { width: 100%; height: 100vh; display: grid; grid-template-columns: 232px 1fr; grid-template-rows: 100vh; background: var(--bg-app); overflow: hidden; }
.workbench { min-width: 0; min-height: 0; display: grid; grid-template-rows: 48px 1fr; overflow: hidden; }
</style>
```

Notes: the design's stage uses fixed `1440x900` — production should be `100vh` and the inner content scrolls. Keep the existing `Login.vue` and `TenantSelect.vue` outside this frame (those routes already bypass the global shell).

- [ ] **Step 3: Verify navigation**

Run dev server. Click every item in the new sidebar. All 13 items navigate. The 6 not-yet-built routes (`/projects`, `/agents`, `/specs`, `/industry`, `/runtime`, `/vibe`) will 404 — that's fixed in the next task.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/BuilderFrame.vue   # or whichever frame file
git commit -m "feat(v2): mount RailSidebar + ShellTopBar inside [data-design=v2] frame"
```

### Task 2.6 — Add 6 missing routes with stub views

- [ ] **Step 1: Create 6 stub views**

Each stub renders a single `page-pad` heading. Identical template, swap title text.

```vue
<!-- frontend/src/views/stubs/StubAgents.vue (and similar files) -->
<script setup lang="ts">
const TITLE = '智能体配置'
const SUBTITLE = '即将在 P2 完成实现。当前仅占位以让导航生效。'
</script>
<template>
  <div class="page">
    <div class="page-pad">
      <div class="page-head">
        <div>
          <h1 class="page-title">{{ TITLE }}</h1>
          <div class="page-subtitle">{{ SUBTITLE }}</div>
        </div>
      </div>
    </div>
  </div>
</template>
<style scoped>
.page { overflow-y: auto; min-height: 0; background: var(--bg-app); height: 100%; }
.page-pad { padding: 28px 32px 40px; max-width: 1320px; margin: 0 auto; }
.page-head { display: flex; align-items: flex-end; justify-content: space-between; gap: 16px; margin-bottom: 22px; }
.page-title { font-size: 22px; font-weight: 600; color: var(--text); letter-spacing: -0.02em; line-height: 1.2; margin: 0; }
.page-subtitle { font-size: 13px; color: var(--text-2); margin-top: 4px; }
</style>
```

Create the same shape (different title/subtitle) for: `StubSpecs.vue` ("设计文档"), `StubIndustry.vue` ("行业知识库"), `StubRuntime.vue` ("运行与发布"), `StubMcp.vue` ("MCP 管理"), `StubProjects.vue` ("项目").

- [ ] **Step 2: Register routes in `router/index.ts`**

Add these route entries inside the existing `routes` array. Place them next to thematically similar existing routes:

```ts
{ path: '/projects', name: 'Projects', component: () => import('@/views/stubs/StubProjects.vue'), meta: { requiresAuth: true } },
{ path: '/agents', name: 'Agents', component: () => import('@/views/stubs/StubAgents.vue'), meta: { requiresAuth: true } },
{ path: '/specs', name: 'Specs', component: () => import('@/views/stubs/StubSpecs.vue'), meta: { requiresAuth: true } },
{ path: '/industry', name: 'Industry', component: () => import('@/views/stubs/StubIndustry.vue'), meta: { requiresAuth: true } },
{ path: '/runtime', name: 'Runtime', component: () => import('@/views/stubs/StubRuntime.vue'), meta: { requiresAuth: true } },
{ path: '/mcp', name: 'McpHub', component: () => import('@/views/stubs/StubMcp.vue'), meta: { requiresAuth: true } },
{ path: '/vibe', redirect: '/vibe-coding' },
```

Note `/vibe` is an alias redirect — existing `/vibe-coding` already works, and the design's nav uses `/vibe`. Don't duplicate the page.

- [ ] **Step 3: Verify all 13 sidebar items navigate to a valid view**

Click every item. None 404. Sidebar `active` state highlights correctly.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/views/stubs/ frontend/src/router/index.ts
git commit -m "feat(routes): add /projects /agents /specs /industry /runtime /mcp stubs + /vibe alias"
```

**Session 2 checkpoint:** Light + dark themes both render without breakage on every existing page AND the new sidebar/topbar. Project switcher dropdown opens and persists selection to localStorage. ⌘K opens the existing command palette via dispatched event.

---

## Session 3 — Projects (list + detail) + first real navigation off the rail

**Objective:** Replace the `/projects` stub with the real list grid, replace the `/project/:id` `ProjectOverview.vue` rendering with the new 5-tab detail, while keeping the existing project APIs and routes intact for backward compatibility.

**Files:**

- Create: `frontend/src/views/v2/ProjectsPage.vue` (replaces `StubProjects.vue` at `/projects`)
- Create: `frontend/src/views/v2/ProjectDetailPage.vue`
- Modify: `frontend/src/router/index.ts` (swap `/projects` to new page, alias `/projects/:id` to detail page)
- Modify: `frontend/src/stores/project.ts` (extend with `fetchProjects()` calling the existing `api/projects.ts` and richer `Project` fields: `members`, `industryPack`, `environments`, `milestones`, `activity`)

### Task 3.1 — `ProjectsPage.vue`

- [ ] **Step 1: Read the JSX reference**

Open `$DESIGN_SRC/page-projects.jsx` lines 1–200 and `$DESIGN_SRC/page-projects.css`. Note the card grid (3 columns at 1320px max width), avatar stack, stage chip color mapping, industry pack badge, and the top-right `+ 新建项目` button.

- [ ] **Step 2: Implement**

```vue
<!-- frontend/src/views/v2/ProjectsPage.vue -->
<script setup lang="ts">
import { computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { useProjectStore, type Project } from '@/stores/project'

const router = useRouter()
const store = useProjectStore()

onMounted(() => {
  // fetchProjects() will be added to the store in Task 3.4; until then the store
  // ships seed data and this no-ops.
  // store.fetchProjects()
})

const stageClass: Record<string, string> = {
  '已上线': 'badge-emerald',
  '开发中': 'badge-amber',
  '测试中': 'badge-sky',
  '设计中': 'badge-brand',
  '维护中': 'badge-outline',
}
function open(p: Project) { router.push(`/projects/${p.id}`) }
function newProject() { /* P2: open project create modal */ }
</script>

<template>
  <div class="page">
    <div class="page-pad">
      <div class="page-head">
        <div>
          <h1 class="page-title">项目</h1>
          <div class="page-subtitle">按客户实施分组的工作空间，每个项目包含多个应用、SPEC 版本、成员、行业包绑定与目标环境。</div>
        </div>
        <button class="btn btn-primary" @click="newProject">
          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 5v14"/><path d="M5 12h14"/></svg>
          新建项目
        </button>
      </div>

      <div class="proj-grid">
        <button v-for="p in store.projects" :key="p.id" class="card card-interactive proj-card" @click="open(p)">
          <div class="proj-card-head">
            <div class="proj-card-bar" />
            <div class="proj-card-name">{{ p.name }}</div>
            <span class="badge" :class="stageClass[p.stage]">{{ p.stage }}</span>
          </div>
          <div class="proj-card-customer">{{ p.customerName }}</div>
          <div class="proj-card-progress">
            <div class="proj-card-progress-track">
              <div class="proj-card-progress-fill" :style="{ width: p.progress + '%' }" />
            </div>
            <div class="proj-card-progress-text">{{ p.progress }}%</div>
          </div>
          <div class="proj-card-stats">
            <div><b>{{ p.appCount }}</b> 应用</div>
            <div><b>{{ p.deployCount }}</b> 部署</div>
            <div><b>{{ p.memberCount }}</b> 成员</div>
            <div><b>{{ p.envCount }}</b> 环境</div>
          </div>
        </button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.page { overflow-y: auto; min-height: 0; background: var(--bg-app); height: 100%; }
.page-pad { padding: 28px 32px 40px; max-width: 1320px; margin: 0 auto; }
.page-head { display: flex; align-items: flex-end; justify-content: space-between; gap: 16px; margin-bottom: 22px; }
.page-title { font-size: 22px; font-weight: 600; color: var(--text); letter-spacing: -0.02em; line-height: 1.2; margin: 0; }
.page-subtitle { font-size: 13px; color: var(--text-2); margin-top: 4px; max-width: 760px; }
.btn { display: inline-flex; align-items: center; justify-content: center; gap: 6px; height: 32px; padding: 0 14px; border-radius: 8px; font-size: 13px; font-weight: 500; cursor: pointer; border: 1px solid transparent; background: transparent; color: var(--text); transition: background 0.12s, border-color 0.12s, transform 0.12s, box-shadow 0.12s; white-space: nowrap; font-family: inherit; }
.btn-primary { background: var(--brand); color: #fff; box-shadow: 0 1px 2px rgba(28, 21, 73, 0.16), inset 0 -1px 0 rgba(0, 0, 0, 0.15); }
.btn-primary:hover { background: var(--brand-hover); box-shadow: 0 2px 6px var(--brand-ring); }
.proj-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 18px; }
.card { background: var(--surface); border: 1px solid var(--border); border-radius: 12px; box-shadow: var(--shadow-xs); padding: 18px; text-align: left; cursor: pointer; font-family: inherit; color: var(--text); width: 100%; }
.card-interactive { transition: border-color 0.14s, box-shadow 0.14s, transform 0.14s; }
.card-interactive:hover { border-color: var(--border-strong); box-shadow: var(--shadow-md); }
.proj-card-head { display: flex; align-items: center; gap: 8px; }
.proj-card-bar { width: 3px; height: 16px; border-radius: 2px; background: var(--brand-500); }
.proj-card-name { flex: 1; font-size: 14.5px; font-weight: 600; color: var(--text); letter-spacing: -0.01em; }
.proj-card-customer { font-size: 12px; color: var(--text-3); margin-top: 6px; }
.proj-card-progress { display: flex; align-items: center; gap: 10px; margin-top: 14px; }
.proj-card-progress-track { flex: 1; height: 4px; background: var(--surface-3); border-radius: 2px; overflow: hidden; }
.proj-card-progress-fill { height: 100%; background: var(--brand); border-radius: 2px; transition: width 0.3s var(--ease, ease-out); }
.proj-card-progress-text { font-size: 11.5px; font-family: var(--d-font-mono); color: var(--text-2); }
.proj-card-stats { display: grid; grid-template-columns: repeat(4, 1fr); gap: 8px; margin-top: 14px; font-size: 11.5px; color: var(--text-3); }
.proj-card-stats b { color: var(--text); font-weight: 600; }
.badge { display: inline-flex; align-items: center; gap: 4px; height: 20px; padding: 0 7px; border-radius: 5px; font-size: 11px; font-weight: 500; background: var(--surface-3); color: var(--text-2); border: 1px solid transparent; }
.badge-brand { background: var(--brand-soft); color: var(--brand-text); }
.badge-emerald { background: var(--emerald-bg); color: var(--emerald); }
.badge-amber { background: var(--amber-bg); color: var(--amber); }
.badge-sky { background: var(--sky-bg); color: var(--sky); }
.badge-outline { background: transparent; border-color: var(--border-strong); color: var(--text-2); }
</style>
```

- [ ] **Step 3: Seed 4 demo projects in the store**

Edit `frontend/src/stores/project.ts` to seed:

```ts
const projects = ref<Project[]>([
  { id: 'p-default',  name: '得帆云示例租户',  customerName: '内部演示', stage: '已上线', progress: 100, appCount: 6,  deployCount: 12, memberCount: 4, envCount: 3, industryPackId: null },
  { id: 'p-auto',     name: '某汽车制造客户',  customerName: '汽车制造业', stage: '开发中', progress: 62,  appCount: 4,  deployCount: 9,  memberCount: 6, envCount: 3, industryPackId: 'pack-mfg' },
  { id: 'p-retail',   name: '某连锁零售客户',  customerName: '连锁零售业', stage: '测试中', progress: 78,  appCount: 7,  deployCount: 14, memberCount: 5, envCount: 3, industryPackId: 'pack-ops' },
  { id: 'p-logistic', name: '某物流客户',      customerName: '物流业',     stage: '设计中', progress: 24,  appCount: 2,  deployCount: 1,  memberCount: 3, envCount: 2, industryPackId: null },
])
```

- [ ] **Step 4: Swap the route**

In `router/index.ts`, change `'/projects'` to point to `() => import('@/views/v2/ProjectsPage.vue')` and add `'/projects/:id'` → `ProjectDetailPage.vue` (built in next task).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/views/v2/ProjectsPage.vue frontend/src/stores/project.ts frontend/src/router/index.ts
git commit -m "feat(v2): real /projects list page with 4 seed projects and stage chips"
```

### Task 3.2 — `ProjectDetailPage.vue` with 5 tabs

- [ ] **Step 1: Build the detail page with `el-tabs`**

Reference `$DESIGN_SRC/page-projects.jsx` `ProjectDetail` function (around lines 200+) and `$DESIGN_SRC/page-projects.css`. The 5 tabs are: 概览 / 应用 / 成员与角色 / 行业包绑定 / 环境与部署. Each tab gets a dedicated `<section>` block; concrete content can be stubs ("即将在 P2 完成") for tabs 3-5; tab 1 and 2 must show real content.

```vue
<!-- frontend/src/views/v2/ProjectDetailPage.vue -->
<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useProjectStore } from '@/stores/project'

const route = useRoute()
const router = useRouter()
const store = useProjectStore()
const activeTab = ref<'overview' | 'apps' | 'members' | 'industry' | 'env'>('overview')

const project = computed(() => store.projects.find(p => p.id === route.params.id))

watch(() => route.params.id, (id) => {
  if (typeof id === 'string') store.setCurrent(id)
}, { immediate: true })

const milestones = computed(() => ([
  { title: '需求确认', status: 'done', date: '2026-04-10' },
  { title: 'SPEC v1 完成', status: 'done', date: '2026-04-22' },
  { title: '测试环境上线', status: 'doing', date: '2026-05-12' },
  { title: '生产上线', status: 'planned', date: '2026-06-05' },
]))
const activity = computed(() => ([
  { who: 'mars', what: '提交 SPEC v3 草稿', when: '2 分钟前' },
  { who: '客户业务方', what: '审批通过资产报废流程', when: '今天 09:32' },
  { who: '陈青羽', what: '更新设备模型字段', when: '昨天 17:45' },
]))
</script>

<template>
  <div class="page">
    <div class="page-pad">
      <div class="page-head">
        <div>
          <div class="page-crumb"><a @click.prevent="router.push('/projects')">项目</a> · <b>{{ project?.name ?? '未找到' }}</b></div>
          <h1 class="page-title">{{ project?.name ?? '未找到项目' }}</h1>
          <div class="page-subtitle">{{ project?.customerName }}</div>
        </div>
        <div class="page-head-actions">
          <button class="btn btn-secondary">项目设置</button>
          <button class="btn btn-primary">进入对话</button>
        </div>
      </div>

      <div class="tabs">
        <button v-for="t in [
          { k: 'overview', l: '概览' },
          { k: 'apps',     l: '应用' },
          { k: 'members',  l: '成员与角色' },
          { k: 'industry', l: '行业包绑定' },
          { k: 'env',      l: '环境与部署' },
        ]" :key="t.k" class="tab" :class="{ active: activeTab === t.k }" @click="activeTab = t.k as any">{{ t.l }}</button>
      </div>

      <section v-if="activeTab === 'overview'" class="tab-pane">
        <div class="overview-grid">
          <div class="card card-pad">
            <div class="section-title">里程碑</div>
            <div class="milestones">
              <div v-for="m in milestones" :key="m.title" class="milestone" :class="m.status">
                <div class="milestone-dot" />
                <div class="milestone-body"><div class="milestone-title">{{ m.title }}</div><div class="milestone-date">{{ m.date }}</div></div>
              </div>
            </div>
          </div>
          <div class="card card-pad">
            <div class="section-title">最近活动</div>
            <div class="activity">
              <div v-for="a in activity" :key="a.who + a.what" class="activity-row">
                <div class="activity-avatar">{{ a.who.slice(0, 1) }}</div>
                <div class="activity-body"><div><b>{{ a.who }}</b> {{ a.what }}</div><div class="activity-when">{{ a.when }}</div></div>
              </div>
            </div>
          </div>
        </div>
      </section>

      <section v-else-if="activeTab === 'apps'" class="tab-pane">
        <div class="card card-pad">
          <div class="section-title">本项目下的应用 <span class="section-title-count">{{ project?.appCount ?? 0 }}</span></div>
          <div class="page-subtitle">即将在 P1 后期接入 <code>api/application.ts</code> 实际数据，并按 <code>project_id</code> 过滤。</div>
        </div>
      </section>

      <section v-else-if="activeTab === 'members'" class="tab-pane">
        <div class="card card-pad">
          <div class="section-title">成员与项目角色 <span class="section-title-count">{{ project?.memberCount ?? 0 }}</span></div>
          <div class="page-subtitle">项目角色（项目负责人 / 实施顾问 / 前端 / 后端 / 客户业务方 / 客户 IT / 观察员）用于权限和通知，不影响 UI 隐藏。完整成员管理在 P2 完成。</div>
        </div>
      </section>

      <section v-else-if="activeTab === 'industry'" class="tab-pane">
        <div class="card card-pad">
          <div class="section-title">行业包绑定</div>
          <div class="page-subtitle">绑定后 AI Builder 在新建应用时会优先复用包内业务对象 / 流程 / 字典。当前绑定：{{ project?.industryPackId ?? '未绑定' }}。完整绑定 UI 在 P3 完成。</div>
        </div>
      </section>

      <section v-else-if="activeTab === 'env'" class="tab-pane">
        <div class="card card-pad">
          <div class="section-title">平台环境</div>
          <div class="page-subtitle">本项目使用 {{ project?.envCount ?? 0 }} 个环境（开发 / 测试 / 生产）。完整环境状态与部署历史在 <a @click.prevent="router.push('/runtime')">/运行与发布</a> 维护。</div>
        </div>
      </section>
    </div>
  </div>
</template>

<style scoped>
.page { overflow-y: auto; min-height: 0; background: var(--bg-app); height: 100%; }
.page-pad { padding: 28px 32px 40px; max-width: 1320px; margin: 0 auto; }
.page-head { display: flex; align-items: flex-end; justify-content: space-between; gap: 16px; margin-bottom: 22px; }
.page-crumb { font-size: 12px; color: var(--text-3); margin-bottom: 4px; }
.page-crumb a { color: var(--text-2); cursor: pointer; }
.page-crumb a:hover { color: var(--brand-text); }
.page-crumb b { color: var(--text); font-weight: 600; }
.page-title { font-size: 24px; font-weight: 600; color: var(--text); letter-spacing: -0.02em; line-height: 1.2; margin: 0; }
.page-subtitle { font-size: 13px; color: var(--text-2); margin-top: 4px; max-width: 760px; }
.page-head-actions { display: flex; gap: 8px; }
.tabs { display: flex; gap: 4px; border-bottom: 1px solid var(--border); margin: 4px 0 18px; }
.tab { height: 36px; padding: 0 14px; background: transparent; border: none; border-bottom: 2px solid transparent; color: var(--text-2); font-size: 13px; font-weight: 500; cursor: pointer; font-family: inherit; }
.tab:hover { color: var(--text); }
.tab.active { color: var(--brand-text); border-bottom-color: var(--brand); }
.tab-pane { display: flex; flex-direction: column; gap: 18px; }
.card { background: var(--surface); border: 1px solid var(--border); border-radius: 12px; box-shadow: var(--shadow-xs); }
.card-pad { padding: 18px; }
.section-title { font-size: 14px; font-weight: 600; color: var(--text); display: flex; align-items: center; gap: 8px; margin-bottom: 10px; }
.section-title-count { font-size: 12px; color: var(--text-3); font-weight: 500; }
.btn { display: inline-flex; align-items: center; justify-content: center; gap: 6px; height: 32px; padding: 0 14px; border-radius: 8px; font-size: 13px; font-weight: 500; cursor: pointer; border: 1px solid transparent; background: transparent; color: var(--text); font-family: inherit; }
.btn-primary { background: var(--brand); color: #fff; }
.btn-primary:hover { background: var(--brand-hover); }
.btn-secondary { background: var(--surface); color: var(--text); border-color: var(--border-strong); box-shadow: var(--shadow-xs); }
.btn-secondary:hover { background: var(--surface-2); }
.overview-grid { display: grid; grid-template-columns: 2fr 1fr; gap: 18px; }
.milestones { display: flex; flex-direction: column; gap: 10px; }
.milestone { display: flex; align-items: center; gap: 12px; padding: 8px 4px; }
.milestone-dot { width: 10px; height: 10px; border-radius: 50%; background: var(--surface-3); border: 2px solid var(--border-strong); flex-shrink: 0; }
.milestone.done .milestone-dot { background: var(--emerald); border-color: var(--emerald); }
.milestone.doing .milestone-dot { background: var(--amber); border-color: var(--amber); animation: pulse 1.6s infinite; }
.milestone-body { flex: 1; }
.milestone-title { font-size: 13px; font-weight: 500; color: var(--text); }
.milestone-date { font-size: 11.5px; color: var(--text-3); font-family: var(--d-font-mono); margin-top: 2px; }
@keyframes pulse { 0%, 100% { box-shadow: 0 0 0 0 var(--amber-bg); } 50% { box-shadow: 0 0 0 8px transparent; } }
.activity { display: flex; flex-direction: column; gap: 12px; }
.activity-row { display: flex; gap: 10px; align-items: flex-start; }
.activity-avatar { width: 24px; height: 24px; border-radius: 50%; background: linear-gradient(135deg, var(--brand-400), var(--brand-600)); color: #fff; font-size: 11px; font-weight: 600; display: grid; place-items: center; flex-shrink: 0; }
.activity-body { font-size: 12.5px; color: var(--text); line-height: 1.5; }
.activity-when { font-size: 11px; color: var(--text-3); margin-top: 2px; }
</style>
```

- [ ] **Step 2: Verify clicking a project card opens its detail; tab switching works**

- [ ] **Step 3: Commit**

```bash
git add frontend/src/views/v2/ProjectDetailPage.vue frontend/src/router/index.ts
git commit -m "feat(v2): /projects/:id detail page with 5-tab shell (overview + apps live, others stubbed)"
```

**Session 3 checkpoint:** Sidebar → 项目 → list → click card → detail → tabs all work. Project switcher in topbar reflects current selection. Existing `/project/:id` (singular) route untouched and still loads `ProjectOverview.vue`.

---

## Session 4 — Landing Redesign

**Objective:** Rewrite `Landing.vue` to the design's centered AI hub + 3-mode picker (AI 对话 / 睿鲸 AI Coding / Vibe Coding) + 4-stat strip + recent-apps strip + 4-step relationship flow.

**Files:**

- Modify: `frontend/src/views/Landing.vue` (full rewrite, ~2500 → ~700 lines)
- Create: `frontend/src/components/v2/LandingComposer.vue` (the colored composer that swaps style per selected mode)

### Task 4.1 — Read the design

- [ ] **Step 1: Read `$DESIGN_SRC/page-landing.jsx` (257 lines) and `$DESIGN_SRC/pages.css` (the Landing-specific block)**

Confirm: 3 mode pills, each color-toned (cyan for AI 对话, indigo-violet for 睿鲸 AI Coding, emerald for Vibe Coding). Selecting a mode changes (a) the composer's top color strip, (b) the placeholder text, (c) the CTA button label, (d) the visible secondary actions (only AI Coding shows "选择 MCP"; only Vibe shows "选择仓库"). Composer is a centered card max-width 720px, ~140px tall.

### Task 4.2 — Implement `LandingComposer.vue`

- [ ] **Step 1: Build the composer**

```vue
<!-- frontend/src/components/v2/LandingComposer.vue -->
<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRouter } from 'vue-router'

type Mode = 'builder' | 'coding' | 'vibe'
const MODES: { id: Mode; label: string; sub: string; tone: 'ai' | 'brand' | 'emerald' }[] = [
  { id: 'builder', label: 'AI 对话',          sub: '描述需求 → SPEC → 部署',           tone: 'ai' },
  { id: 'coding',  label: '睿鲸 AI Coding',   sub: '聊天驱动生成低代码组件',           tone: 'brand' },
  { id: 'vibe',    label: 'Vibe Coding',     sub: '浏览器 VS Code 全代码 + AI 协助',  tone: 'emerald' },
]

const mode = ref<Mode>('builder')
const text = ref('')
const router = useRouter()

const placeholder = computed(() => ({
  builder: '说说你想做什么。例：管理我们部门 200 台设备的领用、归还和报废…',
  coding:  '描述要生成的低代码组件或页面。例：做一个支持多选 + 异步加载的客户树组件…',
  vibe:    '描述你想做的代码任务，进入 Vibe Coding 工作区继续。',
}[mode.value]))
const cta = computed(() => ({ builder: '开始对话', coding: '开始生成', vibe: '打开工作区' }[mode.value]))

function submit() {
  if (!text.value.trim()) return
  if (mode.value === 'builder') router.push({ path: '/chat', query: { from: 'landing', prompt: text.value } })
  else if (mode.value === 'coding') router.push({ path: '/coding', query: { prompt: text.value } })
  else router.push({ path: '/vibe-coding', query: { prompt: text.value } })
}
</script>

<template>
  <div class="composer">
    <div class="composer-modes">
      <button v-for="m in MODES" :key="m.id" class="mode-pill" :class="['tone-' + m.tone, { active: mode === m.id }]" @click="mode = m.id">
        <div class="mode-pill-label">{{ m.label }}</div>
        <div class="mode-pill-sub">{{ m.sub }}</div>
      </button>
    </div>
    <div class="composer-card" :data-tone="MODES.find(m => m.id === mode)?.tone">
      <div class="composer-strip" />
      <textarea v-model="text" class="composer-input" :placeholder="placeholder" rows="3" />
      <div class="composer-foot">
        <div class="composer-tools">
          <button v-if="mode === 'builder'" class="btn btn-ghost btn-sm">📎 上传 .md 文档</button>
          <button v-if="mode === 'coding'"  class="btn btn-ghost btn-sm">🔌 选择 MCP</button>
          <button v-if="mode === 'vibe'"    class="btn btn-ghost btn-sm">📁 选择仓库</button>
        </div>
        <button class="btn btn-primary" :disabled="!text.trim()" @click="submit">{{ cta }}</button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.composer { width: 100%; max-width: 760px; margin: 0 auto; }
.composer-modes { display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px; margin-bottom: 14px; }
.mode-pill { padding: 12px 14px; border: 1px solid var(--border); border-radius: 12px; background: var(--surface); cursor: pointer; font-family: inherit; text-align: left; transition: border-color 0.14s, box-shadow 0.14s, background 0.14s; }
.mode-pill-label { font-size: 13.5px; font-weight: 600; color: var(--text); letter-spacing: -0.005em; }
.mode-pill-sub { font-size: 11.5px; color: var(--text-3); margin-top: 3px; }
.mode-pill.active { border-color: currentColor; box-shadow: 0 0 0 3px var(--ring, var(--brand-ring)); }
.mode-pill.tone-ai.active     { color: var(--ai-text);   background: var(--ai-soft);    --ring: var(--ai-ring); }
.mode-pill.tone-brand.active  { color: var(--brand-text); background: var(--brand-soft); --ring: var(--brand-ring); }
.mode-pill.tone-emerald.active{ color: var(--emerald);    background: var(--emerald-bg);--ring: rgba(16, 163, 127, 0.2); }
.composer-card { position: relative; background: var(--surface); border: 1px solid var(--border-strong); border-radius: 16px; box-shadow: var(--shadow-md); overflow: hidden; }
.composer-strip { height: 3px; }
.composer-card[data-tone="ai"] .composer-strip      { background: var(--ai); }
.composer-card[data-tone="brand"] .composer-strip   { background: var(--brand); }
.composer-card[data-tone="emerald"] .composer-strip { background: var(--emerald); }
.composer-input { width: 100%; min-height: 84px; padding: 14px 16px; border: none; outline: none; resize: none; background: transparent; color: var(--text); font-size: 14px; line-height: 1.55; font-family: inherit; }
.composer-foot { display: flex; align-items: center; justify-content: space-between; padding: 8px 12px 12px; gap: 8px; }
.composer-tools { display: flex; gap: 6px; }
.btn { display: inline-flex; align-items: center; gap: 6px; height: 32px; padding: 0 14px; border-radius: 8px; font-size: 13px; font-weight: 500; cursor: pointer; border: 1px solid transparent; background: transparent; color: var(--text); font-family: inherit; transition: background 0.12s, border-color 0.12s; }
.btn-sm { height: 26px; padding: 0 10px; font-size: 12px; border-radius: 6px; }
.btn-primary { background: var(--brand); color: #fff; }
.btn-primary:disabled { opacity: 0.5; cursor: not-allowed; }
.btn-primary:not(:disabled):hover { background: var(--brand-hover); }
.btn-ghost { color: var(--text-2); }
.btn-ghost:hover { background: var(--surface-2); color: var(--text); }
</style>
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/components/v2/LandingComposer.vue
git commit -m "feat(v2): LandingComposer with 3-mode picker (AI 对话 / 睿鲸 / Vibe)"
```

### Task 4.3 — Rewrite `Landing.vue`

- [ ] **Step 1: Replace the page**

Read existing `frontend/src/views/Landing.vue` to identify any imports/stores it currently uses (file upload, app list). Preserve those bindings — feed them into the new layout. New layout:

```
[ Hero: cyan AI badge "APAAS CHAT AI · DESIGN + BUILD" + headline + subtitle ]
[ LandingComposer (above) ]
[ 4-stat strip: 应用数 / SPEC 版本 / 部署次数 / 行业包 ]
[ 4-step relationship flow chip strip ]
[ Recent apps mini-list (last 5) ]
```

Backing data: pull stats from existing `useAppStore` (or whichever store currently powers Landing — discover via `rg "useAppStore\|api/application" frontend/src/views/Landing.vue`).

```vue
<!-- frontend/src/views/Landing.vue (replaces existing) -->
<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import LandingComposer from '@/components/v2/LandingComposer.vue'

// TODO during execution: re-import whatever store Landing.vue previously used
// for `apps` and `stats`. If unsure, run:
//   rg "import .* from '@/" frontend/src/views/Landing.vue
// on the version at HEAD before replacement, and bring those imports here.

const router = useRouter()
const stats = ref({ apps: 6, specs: 17, deploys: 32, packs: 4 })
const recent = ref<{ id: string; name: string; updatedAt: string }[]>([])

const FLOW_STEPS = [
  { n: '01', label: '描述需求',         tone: 'ai' },
  { n: '02', label: '生成 SPEC',        tone: 'brand' },
  { n: '03', label: '复用行业沉淀',     tone: 'emerald' },
  { n: '04', label: '部署上线',         tone: 'amber' },
]

onMounted(() => {
  // TODO: hydrate `recent` and `stats` from API
})
</script>

<template>
  <div class="page landing">
    <div class="page-pad">
      <div class="hero">
        <div class="ai-badge">
          <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3 14 9l6 2-6 2-2 6-2-6-6-2 6-2z"/><path d="M19 17l1 3 3 1-3 1-1 3-1-3-3-1 3-1z"/></svg>
          <span>AI</span>
        </div>
        <div class="eyebrow">APAAS CHAT AI · DESIGN + BUILD</div>
        <h1 class="hero-title">把<span class="hl">想法或材料</span>给 AI，<br/>它来搭<span class="hl">应用</span>。</h1>
        <div class="hero-sub">支持 .md 设计文档 · .doc / .docx · .pdf · 直接对话需求 · 复用行业包 · 部署到得帆云</div>
      </div>

      <LandingComposer />

      <div class="strip stats">
        <div class="stat"><div class="stat-num">{{ stats.apps }}</div><div class="stat-lbl">应用</div></div>
        <div class="stat"><div class="stat-num">{{ stats.specs }}</div><div class="stat-lbl">SPEC 版本</div></div>
        <div class="stat"><div class="stat-num">{{ stats.deploys }}</div><div class="stat-lbl">部署次数</div></div>
        <div class="stat"><div class="stat-num">{{ stats.packs }}</div><div class="stat-lbl">行业包</div></div>
      </div>

      <div class="flow">
        <div v-for="(s, i) in FLOW_STEPS" :key="s.n" class="flow-step" :class="'tone-' + s.tone">
          <div class="flow-num">{{ s.n }}</div>
          <div class="flow-label">{{ s.label }}</div>
          <svg v-if="i < FLOW_STEPS.length - 1" class="flow-arrow" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M5 12h14"/><path d="m13 5 7 7-7 7"/></svg>
        </div>
      </div>

      <div class="section-head">
        <div class="section-title">最近应用 <span class="section-title-count">{{ recent.length }}</span></div>
        <button class="section-action" @click="router.push('/apps')">查看全部 →</button>
      </div>
      <div class="recent" v-if="recent.length">
        <button v-for="r in recent.slice(0, 5)" :key="r.id" class="recent-row" @click="router.push(`/chat?app_id=${r.id}`)">
          <div class="recent-name">{{ r.name }}</div>
          <div class="recent-when">{{ r.updatedAt }}</div>
        </button>
      </div>
      <div v-else class="recent-empty">还没有应用 — 上面输入框开始描述需求，或者 <a @click.prevent="router.push('/apps')">浏览应用</a>。</div>
    </div>
  </div>
</template>

<style scoped>
.landing { overflow-y: auto; height: 100%; background: var(--bg-app); }
.page-pad { padding: 48px 32px 80px; max-width: 960px; margin: 0 auto; }
.hero { text-align: center; margin-bottom: 36px; }
.ai-badge { display: inline-flex; align-items: center; gap: 6px; height: 38px; padding: 0 14px; border-radius: 999px; background: var(--ai-soft); color: var(--ai-text); font-weight: 700; font-size: 14px; letter-spacing: 0.02em; border: 1px solid var(--ai-soft-2); margin-bottom: 14px; }
.eyebrow { font-size: 11px; font-weight: 600; letter-spacing: 0.20em; text-transform: uppercase; color: var(--ai-text); margin-bottom: 16px; }
.hero-title { font-size: 38px; font-weight: 700; color: var(--text); letter-spacing: -0.025em; line-height: 1.15; margin: 0 0 14px; }
.hero-title .hl { color: var(--ai-text); }
.hero-sub { font-size: 13.5px; color: var(--text-2); max-width: 600px; margin: 0 auto; line-height: 1.6; }
.strip.stats { display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; margin: 32px 0 22px; }
.stat { background: var(--surface); border: 1px solid var(--border); border-radius: 12px; padding: 16px; text-align: center; box-shadow: var(--shadow-xs); }
.stat-num { font-size: 26px; font-weight: 600; color: var(--text); letter-spacing: -0.02em; line-height: 1; }
.stat-lbl { font-size: 12px; color: var(--text-3); margin-top: 4px; }
.flow { display: flex; align-items: center; justify-content: center; gap: 8px; padding: 14px; background: var(--surface-2); border: 1px solid var(--border); border-radius: 12px; margin-bottom: 28px; }
.flow-step { display: inline-flex; align-items: center; gap: 8px; padding: 6px 12px; border-radius: 999px; background: var(--surface); border: 1px solid var(--border); }
.flow-step.tone-ai      { color: var(--ai-text);     background: var(--ai-soft); }
.flow-step.tone-brand   { color: var(--brand-text);  background: var(--brand-soft); }
.flow-step.tone-emerald { color: var(--emerald);     background: var(--emerald-bg); }
.flow-step.tone-amber   { color: var(--amber);       background: var(--amber-bg); }
.flow-num { font-family: var(--d-font-mono); font-size: 11px; font-weight: 700; }
.flow-label { font-size: 12.5px; font-weight: 500; }
.flow-arrow { color: var(--text-4); margin: 0 -2px; }
.section-head { display: flex; align-items: center; justify-content: space-between; gap: 12px; margin: 24px 0 12px; }
.section-title { font-size: 14px; font-weight: 600; color: var(--text); display: flex; align-items: center; gap: 8px; }
.section-title-count { font-size: 12px; color: var(--text-3); font-weight: 500; }
.section-action { font-size: 12.5px; color: var(--brand-text); font-weight: 500; background: none; border: none; cursor: pointer; padding: 4px 8px; border-radius: 6px; font-family: inherit; }
.section-action:hover { background: var(--brand-soft); }
.recent { display: flex; flex-direction: column; gap: 4px; background: var(--surface); border: 1px solid var(--border); border-radius: 12px; padding: 6px; }
.recent-row { display: flex; align-items: center; justify-content: space-between; padding: 8px 12px; border-radius: 8px; cursor: pointer; background: transparent; border: none; color: var(--text); font-family: inherit; }
.recent-row:hover { background: var(--surface-2); }
.recent-name { font-size: 13px; font-weight: 500; }
.recent-when { font-size: 11px; color: var(--text-3); }
.recent-empty { background: var(--surface); border: 1px dashed var(--border-strong); border-radius: 12px; padding: 24px; text-align: center; color: var(--text-3); font-size: 13px; }
.recent-empty a { color: var(--brand-text); cursor: pointer; }
</style>
```

- [ ] **Step 2: Re-introduce existing data hookups**

In the new file's `<script setup>`, replace the seed `stats` and `recent` with the actual store calls the previous Landing used. Before deleting old Landing logic, run `git show HEAD:frontend/src/views/Landing.vue | head -200` and pull the relevant imports/onMounted into the new file. Preserve any upload-and-jump-to-chat flow (the existing app uses `from=upload` query for this — look at the route guard in `router/index.ts:30-42`).

- [ ] **Step 3: Visual verification in browser**

Light + dark both rendered correctly, mode picker swaps composer color, CTA disabled until text typed, click CTA navigates to `/chat?from=landing&prompt=...`.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/views/Landing.vue
git commit -m "feat(v2): Landing redesign — cyan AI hub + 3-mode composer + 4-stat + flow strip"
```

**Session 4 checkpoint:** Landing matches the design pixel-aligned in light/dark. All three modes route to the correct existing page. Existing upload-to-chat flow still works.

---

## Session 5 — ChatPage Layout Restructure (preserves all existing logic)

**Objective:** Reshape `ChatPage.vue` to the design's 3-column layout (left: conversation list + meta · center: messages + composer · right: app blueprint scrolling panel) without rewriting the conversation/SSE/SPEC parsing logic. This is a high-risk task because `ChatPage.vue` is ~13k lines.

**Strategy:** Use the existing file as a black box. Wrap or split the top-level template into three columns, but keep every existing reactive ref, every SSE handler, every streaming logic intact. The right column is a NEW component `AppBlueprintPanel.vue` that receives the parsed SPEC as a prop.

**Files:**

- Modify: `frontend/src/views/ChatPage.vue` (top-level template restructure only, no logic changes)
- Create: `frontend/src/components/v2/AppBlueprintPanel.vue`
- Create: `frontend/src/components/v2/ChatConversationList.vue` (left rail, extracted from existing AppSidebar conversations OR built fresh from existing `useConversationStore`)

### Task 5.1 — Reconnaissance

- [ ] **Step 1: Map the current ChatPage template root**

```bash
sed -n '1,200p' "/Users/mars/Vibe Coding/apaas-builder-ai/frontend/src/views/ChatPage.vue"
```

Identify the outermost `<template>` block and the top-level layout containers (likely a flex row with sidebar + main). Note all child components imported and used in the top layer.

- [ ] **Step 2: Identify SPEC source**

Find the reactive that holds the parsed SPEC (search for `structuredDoc`, `parsedSpec`, `spec`, `blueprint`). The blueprint panel will read from this same source. Document the variable name in this task's commit message.

### Task 5.2 — `AppBlueprintPanel.vue`

- [ ] **Step 1: Build the right-side blueprint panel**

The panel renders 6 collapsible sections from the parsed SPEC: 数据模型 / 表单 / 流程 / 角色权限 / 字典 / 概览. Reference `$DESIGN_SRC/page-chat.jsx` lines ~250-600 for the exact card structure, and `$DESIGN_SRC/pages2.css` for the visual rules.

```vue
<!-- frontend/src/components/v2/AppBlueprintPanel.vue -->
<script setup lang="ts">
import { computed, ref } from 'vue'

interface SpecModel { name: string; code: string; fields: { name: string; code: string; type: string; required?: boolean; unique?: boolean; isNew?: boolean }[] }
interface SpecForm  { name: string; backingModel: string; sections: { title: string; fields: string[] }[] }
interface SpecFlow  { name: string; trigger: string; nodes: { role: string; action: string; sla?: string }[] }
interface SpecRole  { name: string; scope: string }
interface SpecDict  { name: string; entries: { code: string; label: string }[] }

const props = defineProps<{
  models: SpecModel[]
  forms: SpecForm[]
  flows: SpecFlow[]
  roles: SpecRole[]
  dicts: SpecDict[]
  industryPackName?: string | null
  industryObjectCount?: number
}>()
const emit = defineEmits<{ (e: 'deploy'): void }>()

const open = ref<Record<string, boolean>>({ models: true, forms: true, flows: false, roles: false, dicts: false })

const counts = computed(() => ({
  models: props.models.length,
  forms: props.forms.length,
  flows: props.flows.length,
  roles: props.roles.length,
  dicts: props.dicts.length,
  fields: props.models.reduce((acc, m) => acc + m.fields.length, 0),
}))

function toggle(k: string) { open.value[k] = !open.value[k] }
</script>

<template>
  <aside class="blueprint">
    <div v-if="industryPackName" class="bp-knowledge">
      <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M3 21V11l6-4v4l6-4v4l6-4v14H3z"/></svg>
      <span>本会话引用 <b>{{ industryPackName }}</b><span v-if="industryObjectCount"> ({{ industryObjectCount }} 业务对象)</span></span>
      <button class="bp-knowledge-link" @click="$router.push('/agents')">查看 Agent 配置 →</button>
    </div>

    <div class="bp-head">
      <div class="bp-title">应用蓝图</div>
      <div class="bp-stats">
        <span><b>{{ counts.models }}</b> 模型</span><span>·</span>
        <span><b>{{ counts.forms }}</b> 表单</span><span>·</span>
        <span><b>{{ counts.flows }}</b> 流程</span><span>·</span>
        <span><b>{{ counts.roles }}</b> 角色</span><span>·</span>
        <span><b>{{ counts.dicts }}</b> 字典</span><span>·</span>
        <span><b>{{ counts.fields }}</b> 字段</span>
      </div>
      <button class="btn btn-primary btn-sm" @click="emit('deploy')">🚀 部署到平台</button>
    </div>

    <div class="bp-scroll">
      <section class="bp-section">
        <button class="bp-section-head" @click="toggle('models')">
          <span>数据模型 <span class="muted">({{ counts.models }})</span></span>
          <svg :class="{ rot: open.models }" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="m6 9 6 6 6-6"/></svg>
        </button>
        <div v-show="open.models" class="bp-section-body">
          <div v-for="m in models" :key="m.code" class="bp-card">
            <div class="bp-card-head">
              <span class="bp-card-name">{{ m.name }}</span>
              <span class="badge badge-outline mono">{{ m.code }}</span>
            </div>
            <div class="bp-fields">
              <div v-for="f in m.fields" :key="f.code" class="bp-field" :class="{ 'is-new': f.isNew }">
                <span class="bp-field-name">{{ f.name }}</span>
                <span class="bp-field-code mono">{{ f.code }}</span>
                <span class="bp-field-type mono">{{ f.type }}</span>
                <span v-if="f.required" class="badge badge-amber">必填</span>
                <span v-if="f.unique" class="badge badge-brand">唯一</span>
                <span v-if="f.isNew" class="badge badge-brand">NEW</span>
              </div>
            </div>
          </div>
        </div>
      </section>

      <section class="bp-section">
        <button class="bp-section-head" @click="toggle('forms')">
          <span>表单 <span class="muted">({{ counts.forms }})</span></span>
          <svg :class="{ rot: open.forms }" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="m6 9 6 6 6-6"/></svg>
        </button>
        <div v-show="open.forms" class="bp-section-body">
          <div v-for="f in forms" :key="f.name" class="bp-card">
            <div class="bp-card-head"><span class="bp-card-name">{{ f.name }}</span><span class="bp-card-meta mono">← {{ f.backingModel }}</span></div>
            <div v-for="sec in f.sections" :key="sec.title" class="bp-form-section"><div class="bp-form-section-title">{{ sec.title }}</div><div class="bp-form-fields">{{ sec.fields.join(' · ') }}</div></div>
          </div>
        </div>
      </section>

      <!-- flows / roles / dicts follow the same pattern; stub with summaries here, fill in detail iteratively -->
      <section class="bp-section">
        <button class="bp-section-head" @click="toggle('flows')"><span>流程 <span class="muted">({{ counts.flows }})</span></span><svg :class="{ rot: open.flows }" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="m6 9 6 6 6-6"/></svg></button>
        <div v-show="open.flows" class="bp-section-body"><div v-for="fl in flows" :key="fl.name" class="bp-card"><div class="bp-card-head"><span class="bp-card-name">{{ fl.name }}</span><span class="bp-card-meta">触发：{{ fl.trigger }}</span></div><div class="bp-flow-chain">{{ fl.nodes.map(n => n.role + ' → ' + n.action).join('  →  ') }}</div></div></div>
      </section>
      <section class="bp-section">
        <button class="bp-section-head" @click="toggle('roles')"><span>角色 <span class="muted">({{ counts.roles }})</span></span><svg :class="{ rot: open.roles }" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="m6 9 6 6 6-6"/></svg></button>
        <div v-show="open.roles" class="bp-section-body"><div v-for="r in roles" :key="r.name" class="bp-card"><div class="bp-card-head"><span class="bp-card-name">{{ r.name }}</span><span class="bp-card-meta">范围：{{ r.scope }}</span></div></div></div>
      </section>
      <section class="bp-section">
        <button class="bp-section-head" @click="toggle('dicts')"><span>字典 <span class="muted">({{ counts.dicts }})</span></span><svg :class="{ rot: open.dicts }" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="m6 9 6 6 6-6"/></svg></button>
        <div v-show="open.dicts" class="bp-section-body"><div v-for="d in dicts" :key="d.name" class="bp-card"><div class="bp-card-head"><span class="bp-card-name">{{ d.name }}</span></div><div class="bp-dict">{{ d.entries.map(e => e.label + '(' + e.code + ')').join(' · ') }}</div></div></div>
      </section>
    </div>
  </aside>
</template>

<style scoped>
.blueprint { width: 420px; flex-shrink: 0; background: var(--surface); border-left: 1px solid var(--border); display: flex; flex-direction: column; height: 100%; overflow: hidden; }
.bp-knowledge { display: flex; align-items: center; gap: 8px; padding: 10px 14px; background: var(--ai-soft); color: var(--ai-text); font-size: 12px; border-bottom: 1px solid var(--ai-soft-2); }
.bp-knowledge b { color: var(--ai-text); font-weight: 600; }
.bp-knowledge-link { margin-left: auto; background: none; border: none; color: var(--ai-text); font-size: 11.5px; cursor: pointer; font-family: inherit; }
.bp-head { padding: 14px 16px; border-bottom: 1px solid var(--border); display: flex; flex-direction: column; gap: 8px; }
.bp-title { font-size: 14px; font-weight: 600; color: var(--text); }
.bp-stats { display: flex; align-items: center; gap: 6px; font-size: 11.5px; color: var(--text-3); flex-wrap: wrap; }
.bp-stats b { color: var(--text); font-weight: 600; }
.btn { display: inline-flex; align-items: center; gap: 6px; height: 32px; padding: 0 14px; border-radius: 8px; font-size: 13px; font-weight: 500; cursor: pointer; border: 1px solid transparent; background: transparent; color: var(--text); font-family: inherit; }
.btn-sm { height: 26px; padding: 0 10px; font-size: 12px; border-radius: 6px; align-self: flex-end; }
.btn-primary { background: var(--brand); color: #fff; }
.btn-primary:hover { background: var(--brand-hover); }
.bp-scroll { flex: 1; overflow-y: auto; padding: 8px; }
.bp-section { margin-bottom: 4px; }
.bp-section-head { width: 100%; display: flex; align-items: center; justify-content: space-between; padding: 8px 10px; border-radius: 8px; background: transparent; border: none; color: var(--text); font-size: 13px; font-weight: 600; cursor: pointer; font-family: inherit; }
.bp-section-head:hover { background: var(--surface-2); }
.bp-section-head .muted { color: var(--text-3); font-weight: 500; }
.bp-section-head svg { transition: transform 0.15s; }
.bp-section-head svg.rot { transform: rotate(180deg); }
.bp-section-body { padding: 4px 6px 8px; display: flex; flex-direction: column; gap: 8px; }
.bp-card { background: var(--surface-2); border: 1px solid var(--border); border-radius: 10px; padding: 10px 12px; }
.bp-card-head { display: flex; align-items: center; justify-content: space-between; gap: 8px; margin-bottom: 6px; }
.bp-card-name { font-size: 13px; font-weight: 600; color: var(--text); }
.bp-card-meta { font-size: 11px; color: var(--text-3); }
.mono { font-family: var(--d-font-mono); }
.bp-fields { display: flex; flex-direction: column; gap: 4px; }
.bp-field { display: flex; align-items: center; gap: 8px; padding: 4px 6px; border-radius: 6px; font-size: 11.5px; color: var(--text-2); }
.bp-field.is-new { background: var(--brand-soft); color: var(--brand-text); }
.bp-field-name { flex: 1; color: var(--text); font-weight: 500; }
.bp-field-code { color: var(--text-3); font-size: 11px; }
.bp-field-type { color: var(--brand-text); font-size: 11px; }
.badge { display: inline-flex; align-items: center; gap: 4px; height: 18px; padding: 0 6px; border-radius: 4px; font-size: 10.5px; font-weight: 500; background: var(--surface-3); color: var(--text-2); border: 1px solid transparent; }
.badge-amber { background: var(--amber-bg); color: var(--amber); }
.badge-brand { background: var(--brand-soft); color: var(--brand-text); }
.badge-outline { background: transparent; border-color: var(--border-strong); color: var(--text-2); }
.bp-flow-chain { font-size: 11.5px; color: var(--text-2); line-height: 1.6; }
.bp-form-section { margin-top: 6px; }
.bp-form-section-title { font-size: 11.5px; font-weight: 600; color: var(--text); }
.bp-form-fields { font-size: 11px; color: var(--text-3); margin-top: 2px; }
.bp-dict { font-size: 11px; color: var(--text-2); line-height: 1.6; }
</style>
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/components/v2/AppBlueprintPanel.vue
git commit -m "feat(v2): add AppBlueprintPanel — collapsible SPEC blueprint with knowledge chip"
```

### Task 5.3 — Restructure ChatPage template

- [ ] **Step 1: Wrap the current page in the 3-column layout**

Open `ChatPage.vue` and locate the outermost `<template>` content. Wrap it in:

```vue
<template>
  <div class="chat-shell">
    <ChatConversationList :conversations="conversations" :current-id="currentConversationId" @open="openConversation" />

    <main class="chat-main">
      <!-- KEEP every existing element from the old template here, untouched -->
    </main>

    <AppBlueprintPanel
      :models="spec.models"
      :forms="spec.forms"
      :flows="spec.flows"
      :roles="spec.roles"
      :dicts="spec.dicts"
      :industry-pack-name="currentIndustryPack?.name"
      :industry-object-count="currentIndustryPack?.objectCount"
      @deploy="openDeployModal"
    />
  </div>
</template>
```

Map `spec.models` etc. to whatever the existing reactive is (from Task 5.1 reconnaissance). If the existing `parsedSpec` doesn't have these shapes, write a `computed()` that adapts whatever's there into the panel's expected shape — do NOT change the parser.

`openDeployModal` is wired to the existing deploy button handler. If no deploy modal exists yet, leave the emit as a no-op for this session (it's wired in Session 6).

- [ ] **Step 2: Add the wrapper styles at the bottom of `ChatPage.vue`**

```css
.chat-shell { display: flex; height: 100%; min-height: 0; background: var(--bg-app); }
.chat-main { flex: 1; min-width: 0; display: flex; flex-direction: column; }
```

- [ ] **Step 3: Verify nothing regresses**

Open `/chat?from=upload&...` and `/chat?app_id=...` and `/chat?conversation_id=...`. Send a message. Confirm streaming still works. Confirm right panel renders (may be empty if no SPEC parsed yet — that's fine).

- [ ] **Step 4: Commit**

```bash
git add frontend/src/views/ChatPage.vue
git commit -m "refactor(chat): restructure to 3-column layout; preserves all logic; blueprint panel mounted"
```

### Task 5.4 — `ChatConversationList.vue`

- [ ] **Step 1: Build a slim conversation list for the left column**

```vue
<!-- frontend/src/components/v2/ChatConversationList.vue -->
<script setup lang="ts">
defineProps<{ conversations: { id: string; title: string; updatedAt: string }[]; currentId?: string }>()
defineEmits<{ (e: 'open', id: string): void }>()
</script>
<template>
  <nav class="conv-list">
    <div class="conv-head">最近对话</div>
    <button v-for="c in conversations" :key="c.id" class="conv-row" :class="{ active: c.id === currentId }" @click="$emit('open', c.id)">
      <div class="conv-title">{{ c.title }}</div>
      <div class="conv-when">{{ c.updatedAt }}</div>
    </button>
    <div v-if="!conversations.length" class="conv-empty">还没有对话</div>
  </nav>
</template>
<style scoped>
.conv-list { width: 240px; flex-shrink: 0; background: var(--surface-2); border-right: 1px solid var(--border); padding: 12px 8px; overflow-y: auto; height: 100%; }
.conv-head { font-size: 11px; font-weight: 600; letter-spacing: 0.10em; text-transform: uppercase; color: var(--text-3); padding: 4px 10px 8px; }
.conv-row { width: 100%; display: flex; flex-direction: column; gap: 2px; padding: 8px 10px; border-radius: 8px; background: transparent; border: none; cursor: pointer; text-align: left; color: var(--text); font-family: inherit; }
.conv-row:hover { background: var(--surface); }
.conv-row.active { background: var(--brand-soft); color: var(--brand-text); }
.conv-title { font-size: 12.5px; font-weight: 500; line-height: 1.35; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.conv-when { font-size: 10.5px; color: var(--text-3); font-family: var(--d-font-mono); }
.conv-empty { font-size: 12px; color: var(--text-3); padding: 12px 10px; }
</style>
```

- [ ] **Step 2: Wire it to existing conversation source in `ChatPage.vue`**

Find the existing conversations reactive in `ChatPage.vue` (commonly `conversations.value`). Pass it to `<ChatConversationList>`. The `@open` handler calls the existing function that loads a conversation by id.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/v2/ChatConversationList.vue frontend/src/views/ChatPage.vue
git commit -m "feat(v2): ChatConversationList in left column, bound to existing conversation store"
```

**Session 5 checkpoint:** /chat renders 3 columns. Existing SSE / SPEC parsing / deploy / handoff flows all unchanged. Blueprint panel populates when SPEC is parsed. No console errors.

---

## Session 6 — SPEC page + Apps visual refresh + Deploy confirm modal

**Objective:** Replace `/specs` stub with the real Specs page, give the existing Apps page the visual refresh (cards/colors only — keep all filter/list logic), build the deploy confirm modal as a reusable Element Plus dialog that ChatPage's deploy button opens.

**Files:**

- Create: `frontend/src/views/v2/SpecsPage.vue` (replaces `StubSpecs.vue`)
- Modify: `frontend/src/router/index.ts` (swap `/specs` to new page)
- Modify: `frontend/src/views/Apps.vue` (visual refresh — wrap existing template in `[data-design="v2"]` styles; or add design-aligned card classes alongside existing ones — do NOT rewrite logic)
- Create: `frontend/src/components/v2/DeployConfirmModal.vue`
- Modify: `frontend/src/views/ChatPage.vue` (wire `openDeployModal` to mount the modal)

### Task 6.1 — `SpecsPage.vue`

- [ ] **Step 1: Read the design**

`$DESIGN_SRC/page-specs.jsx` + `$DESIGN_SRC/page-specs.css`. Layout: left list of SPECs with diff badges; right detail with version timeline + section grid + markdown excerpt + 3 action buttons (导出 .md / 在 Builder 打开 / 基于此部署). Top of page has a 4-step origin flow strip ("标准模板 → 行业知识库 → AI Builder 对话产出 → 部署到 aPaaS").

- [ ] **Step 2: Build with seed data**

Use seed data for v2 SPECs (the real `api/specs.ts` doesn't exist yet; backend work is out-of-scope for this plan). Document this in a comment block at the top.

```vue
<!-- frontend/src/views/v2/SpecsPage.vue -->
<script setup lang="ts">
/* Seed data until backend api/specs.ts exists. */
import { ref } from 'vue'

interface SpecVersion { v: number; status: 'draft' | 'test' | 'prod' | 'archived'; note: string; author: string; date: string }
interface Spec { id: string; appName: string; latest: number; diff: { add: number; mod: number }; origin: string; versions: SpecVersion[]; sections: { name: string; count: number }[]; excerpt: string }

const specs = ref<Spec[]>([
  { id: 's1', appName: '资产管理系统', latest: 3, diff: { add: 2, mod: 4 }, origin: '基于 标准模板 + 制造装备包 v2.1', versions: [
    { v: 3, status: 'draft', note: '加保修截止日期 / 采购来源', author: 'mars', date: '2026-05-18' },
    { v: 2, status: 'test',  note: '加财务审批分支', author: 'mars', date: '2026-05-15' },
    { v: 1, status: 'prod',  note: '首版上线', author: '陈青羽', date: '2026-05-08' },
  ], sections: [
    { name: '需求摘要', count: 1 }, { name: '数据模型', count: 6 }, { name: '表单', count: 6 }, { name: '流程', count: 2 }, { name: '角色权限', count: 3 }, { name: '字典', count: 6 },
  ], excerpt: '| 字段 | 类型 | 必填 | 备注 |\n|---|---|---|---|\n| 资产名称 | String(120) | 是 | |\n| 保修截止 | Date | 否 | NEW |' },
])
const selected = ref<Spec | null>(specs.value[0])
const ORIGIN_STEPS = ['标准模板', '行业知识库', '睿鲸 AI Builder 对话产出', '部署到 aPaaS 平台']
const statusBadgeClass: Record<string, string> = { draft: 'badge-amber', test: 'badge-sky', prod: 'badge-emerald', archived: 'badge-outline' }
const statusLabel: Record<string, string> = { draft: '草稿', test: '已部署测试', prod: '已部署生产', archived: '归档' }
</script>

<template>
  <div class="page">
    <div class="page-pad">
      <div class="page-head">
        <div>
          <h1 class="page-title">设计文档</h1>
          <div class="page-subtitle">每个应用一份多版本 SPEC，版本时间线决定环境部署与回滚。</div>
        </div>
      </div>
      <div class="origin-strip">
        <span v-for="(s, i) in ORIGIN_STEPS" :key="s">
          <span class="origin-step">{{ s }}</span>
          <span v-if="i < ORIGIN_STEPS.length - 1" class="origin-arrow">→</span>
        </span>
      </div>

      <div class="specs-layout">
        <aside class="specs-list">
          <button v-for="s in specs" :key="s.id" class="spec-row" :class="{ active: selected?.id === s.id }" @click="selected = s">
            <div class="spec-row-name">{{ s.appName }}</div>
            <div class="spec-row-meta">
              <span class="badge badge-brand">v{{ s.latest }}</span>
              <span class="badge badge-emerald">+{{ s.diff.add }}</span>
              <span class="badge badge-amber">~{{ s.diff.mod }}</span>
            </div>
            <div class="spec-row-origin">{{ s.origin }}</div>
          </button>
        </aside>

        <main class="spec-detail" v-if="selected">
          <div class="card card-pad">
            <div class="spec-head">
              <div>
                <div class="spec-head-app">{{ selected.appName }}</div>
                <div class="spec-head-sub">最新 v{{ selected.latest }} · {{ selected.origin }}</div>
              </div>
              <div class="spec-head-actions">
                <button class="btn btn-secondary btn-sm">导出 .md</button>
                <button class="btn btn-secondary btn-sm">在 Builder 打开</button>
                <button class="btn btn-primary btn-sm">基于此部署</button>
              </div>
            </div>

            <div class="section-head"><div class="section-title">版本时间线</div></div>
            <ol class="versions">
              <li v-for="v in selected.versions" :key="v.v" :class="v.status">
                <div class="ver-dot" />
                <div class="ver-body">
                  <div><b>v{{ v.v }}</b> <span class="badge" :class="statusBadgeClass[v.status]">{{ statusLabel[v.status] }}</span></div>
                  <div class="ver-note">{{ v.note }}</div>
                  <div class="ver-meta mono">{{ v.author }} · {{ v.date }}</div>
                </div>
              </li>
            </ol>

            <div class="section-head"><div class="section-title">章节</div></div>
            <div class="spec-sections-grid">
              <div v-for="sec in selected.sections" :key="sec.name" class="spec-section-card">
                <div class="spec-section-name">{{ sec.name }}</div>
                <div class="spec-section-count">{{ sec.count }}</div>
              </div>
            </div>

            <div class="section-head"><div class="section-title">Markdown 摘录</div></div>
            <pre class="md-excerpt"><code>{{ selected.excerpt }}</code></pre>
          </div>
        </main>
      </div>
    </div>
  </div>
</template>

<style scoped>
.page { overflow-y: auto; min-height: 0; background: var(--bg-app); height: 100%; }
.page-pad { padding: 28px 32px 40px; max-width: 1320px; margin: 0 auto; }
.page-head { margin-bottom: 14px; }
.page-title { font-size: 22px; font-weight: 600; color: var(--text); letter-spacing: -0.02em; margin: 0; }
.page-subtitle { font-size: 13px; color: var(--text-2); margin-top: 4px; }
.origin-strip { display: flex; align-items: center; gap: 8px; padding: 10px 14px; background: var(--surface-2); border: 1px solid var(--border); border-radius: 10px; font-size: 12px; color: var(--text-2); margin-bottom: 18px; }
.origin-step { padding: 4px 10px; background: var(--surface); border: 1px solid var(--border); border-radius: 999px; }
.origin-arrow { color: var(--text-4); }
.specs-layout { display: grid; grid-template-columns: 320px 1fr; gap: 18px; }
.specs-list { display: flex; flex-direction: column; gap: 8px; }
.spec-row { background: var(--surface); border: 1px solid var(--border); border-radius: 10px; padding: 12px 14px; text-align: left; cursor: pointer; font-family: inherit; color: var(--text); transition: border-color 0.14s, box-shadow 0.14s; }
.spec-row:hover { border-color: var(--border-strong); }
.spec-row.active { border-color: var(--brand); box-shadow: 0 0 0 3px var(--brand-ring); }
.spec-row-name { font-size: 13.5px; font-weight: 600; }
.spec-row-meta { display: flex; gap: 4px; margin-top: 6px; }
.spec-row-origin { font-size: 11px; color: var(--text-3); margin-top: 6px; }
.card { background: var(--surface); border: 1px solid var(--border); border-radius: 12px; box-shadow: var(--shadow-xs); }
.card-pad { padding: 18px; }
.spec-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; margin-bottom: 14px; }
.spec-head-app { font-size: 17px; font-weight: 600; color: var(--text); letter-spacing: -0.01em; }
.spec-head-sub { font-size: 12px; color: var(--text-3); margin-top: 3px; }
.spec-head-actions { display: flex; gap: 6px; }
.btn { display: inline-flex; align-items: center; gap: 6px; height: 32px; padding: 0 14px; border-radius: 8px; font-size: 13px; font-weight: 500; cursor: pointer; border: 1px solid transparent; background: transparent; color: var(--text); font-family: inherit; }
.btn-sm { height: 26px; padding: 0 10px; font-size: 12px; border-radius: 6px; }
.btn-primary { background: var(--brand); color: #fff; }
.btn-secondary { background: var(--surface); border-color: var(--border-strong); }
.section-head { margin: 16px 0 8px; }
.section-title { font-size: 13px; font-weight: 600; color: var(--text); }
.versions { list-style: none; padding: 0; margin: 0; display: flex; flex-direction: column; gap: 12px; }
.versions li { display: flex; gap: 12px; align-items: flex-start; padding: 8px 4px; }
.ver-dot { width: 10px; height: 10px; border-radius: 50%; background: var(--surface-3); border: 2px solid var(--border-strong); flex-shrink: 0; margin-top: 5px; }
.versions li.draft .ver-dot { background: var(--amber); border-color: var(--amber); animation: pulse 1.6s infinite; }
.versions li.test  .ver-dot { background: var(--sky);    border-color: var(--sky); }
.versions li.prod  .ver-dot { background: var(--emerald);border-color: var(--emerald); }
@keyframes pulse { 0%, 100% { box-shadow: 0 0 0 0 var(--amber-bg); } 50% { box-shadow: 0 0 0 8px transparent; } }
.ver-body { font-size: 13px; }
.ver-note { color: var(--text-2); margin-top: 2px; }
.ver-meta { font-size: 11px; color: var(--text-3); margin-top: 2px; }
.spec-sections-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 8px; }
.spec-section-card { background: var(--surface-2); border: 1px solid var(--border); border-radius: 8px; padding: 10px 12px; }
.spec-section-name { font-size: 12px; color: var(--text-2); }
.spec-section-count { font-size: 17px; font-weight: 600; color: var(--text); letter-spacing: -0.01em; margin-top: 2px; }
.md-excerpt { background: var(--code-bg); border: 1px solid var(--border); border-radius: 8px; padding: 10px 14px; overflow-x: auto; color: var(--code-text); font-family: var(--d-font-mono); font-size: 11.5px; line-height: 1.5; }
.badge { display: inline-flex; align-items: center; gap: 4px; height: 20px; padding: 0 7px; border-radius: 5px; font-size: 11px; font-weight: 500; background: var(--surface-3); color: var(--text-2); border: 1px solid transparent; }
.badge-brand { background: var(--brand-soft); color: var(--brand-text); }
.badge-emerald { background: var(--emerald-bg); color: var(--emerald); }
.badge-amber { background: var(--amber-bg); color: var(--amber); }
.badge-sky { background: var(--sky-bg); color: var(--sky); }
.badge-outline { background: transparent; border-color: var(--border-strong); }
.mono { font-family: var(--d-font-mono); }
</style>
```

- [ ] **Step 3: Swap router**

In `router/index.ts`, change `/specs` to point at the new component.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/views/v2/SpecsPage.vue frontend/src/router/index.ts
git commit -m "feat(v2): /specs page with origin flow, version timeline, section grid, md excerpt"
```

### Task 6.2 — Apps.vue visual refresh

- [ ] **Step 1: Read the design**

`$DESIGN_SRC/page-apps.jsx` + relevant CSS in `pages.css`. Confirm cards have `rounded-12 + 1px hairline + shadow-xs + hover shadow-md` and a `filter strip` at top.

- [ ] **Step 2: Add v2 styling without rewriting logic**

Open `frontend/src/views/Apps.vue`. Add a `data-design-v2` attribute to the root element. Add a scoped `<style>` block at the bottom that defines `.card`, `.btn`, `.input`, `.badge` classes matching the v2 token rules (copy from any earlier session's task — they're the same). Then update only the *class names* in the template to use these new classes, preserving every `v-if`/`v-for`/`@click` handler exactly.

This is a visual-only refactor — diff lines should be limited to template class swaps + appended `<style scoped>` rules. No JS/TS changes.

If `Apps.vue` is too tangled to refresh in one task, do the page header + the empty state in this commit and defer the table/grid styling to a follow-up.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/views/Apps.vue
git commit -m "style(apps): adopt v2 card/badge/btn styling, no logic change"
```

### Task 6.3 — DeployConfirmModal

- [ ] **Step 1: Read `$DESIGN_SRC/enhancements.jsx` `DeployModal` function**

Identify the 3-step state machine: `pickEnv` → `confirmDiff` → `running` → `success` (or `failure`). For production env, the diff step shows a red warning bar and requires typing the app code as a confirmation token before the Confirm button enables.

- [ ] **Step 2: Build as `el-dialog` wrapper**

```vue
<!-- frontend/src/components/v2/DeployConfirmModal.vue -->
<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { ElDialog, ElButton } from 'element-plus'

const props = defineProps<{
  modelValue: boolean
  appName: string
  appCode: string
  changes: { kind: '+' | '~' | '-'; what: string }[]
  impacts: { affectedUsers: number; addedFlows: number; needMigration: boolean; etaMinutes: number }
}>()
const emit = defineEmits<{ (e: 'update:modelValue', v: boolean): void; (e: 'confirm', env: 'dev' | 'test' | 'prod'): void }>()

const ENVS = [
  { id: 'dev',  label: '开发',  tone: 'outline' },
  { id: 'test', label: '测试',  tone: 'sky', isDefault: true },
  { id: 'prod', label: '生产',  tone: 'rose' },
] as const

const env = ref<'dev' | 'test' | 'prod'>('test')
const confirmCode = ref('')
const phase = ref<'pickEnv' | 'confirm' | 'running' | 'success'>('pickEnv')

watch(() => props.modelValue, (v) => { if (v) { phase.value = 'pickEnv'; env.value = 'test'; confirmCode.value = '' } })

const isProd = computed(() => env.value === 'prod')
const canConfirm = computed(() => !isProd.value || confirmCode.value === props.appCode)

function go() {
  if (phase.value === 'pickEnv') phase.value = 'confirm'
  else if (phase.value === 'confirm' && canConfirm.value) {
    phase.value = 'running'
    emit('confirm', env.value)
    setTimeout(() => { phase.value = 'success' }, 2500)
  }
}
function close() { emit('update:modelValue', false) }
</script>

<template>
  <el-dialog
    :model-value="modelValue"
    @update:model-value="(v: any) => emit('update:modelValue', v)"
    width="640px"
    :show-close="phase !== 'running'"
    :title="phase === 'success' ? '部署成功' : '部署到平台'"
  >
    <div v-if="phase === 'pickEnv'" class="dep">
      <div class="dep-section-title">1 · 选择目标环境</div>
      <div class="env-row">
        <button v-for="e in ENVS" :key="e.id" class="env-card" :class="['tone-' + e.tone, { active: env === e.id }]" @click="env = e.id">
          <div class="env-name">{{ e.label }}</div>
          <div class="env-default" v-if="e.isDefault">默认</div>
        </button>
      </div>
      <div v-if="isProd" class="warn-bar">⚠️ 生产环境部署不可逆，提交前需输入应用编码确认</div>
    </div>

    <div v-else-if="phase === 'confirm'" class="dep">
      <div class="dep-section-title">2 · 变更预览</div>
      <ul class="diff">
        <li v-for="c in changes" :key="c.what" :class="'diff-' + c.kind">
          <span class="diff-kind">{{ c.kind }}</span>
          <span class="diff-what">{{ c.what }}</span>
        </li>
      </ul>
      <div class="dep-section-title">3 · 影响范围</div>
      <div class="impact-row">
        <div class="impact-card"><div class="impact-num">{{ impacts.affectedUsers }}</div><div class="impact-lbl">用户受影响</div></div>
        <div class="impact-card"><div class="impact-num">{{ impacts.addedFlows }}</div><div class="impact-lbl">流程新增</div></div>
        <div class="impact-card"><div class="impact-num">{{ impacts.needMigration ? '是' : '否' }}</div><div class="impact-lbl">数据迁移</div></div>
        <div class="impact-card"><div class="impact-num">{{ impacts.etaMinutes }}m</div><div class="impact-lbl">预计耗时</div></div>
      </div>
      <div v-if="isProd" class="prod-confirm">
        <label>输入应用编码 <code>{{ appCode }}</code> 以确认：</label>
        <input v-model="confirmCode" class="input" :placeholder="appCode" />
      </div>
      <div class="safety">✓ 部署前自动备份 · 失败可一键回滚</div>
    </div>

    <div v-else-if="phase === 'running'" class="dep dep-center">
      <div class="loader" />
      <div>正在部署到 <b>{{ env }}</b>...</div>
    </div>

    <div v-else class="dep dep-center">
      <div class="success-mark">✓</div>
      <div>已部署到 <b>{{ env }}</b></div>
    </div>

    <template #footer>
      <div class="dep-foot">
        <el-button v-if="phase !== 'running'" @click="close">{{ phase === 'success' ? '关闭' : '取消' }}</el-button>
        <el-button v-if="phase === 'pickEnv'" type="primary" @click="go">下一步</el-button>
        <el-button v-else-if="phase === 'confirm'" type="primary" :disabled="!canConfirm" @click="go">{{ isProd ? '确认部署到生产' : '确认部署' }}</el-button>
        <el-button v-else-if="phase === 'success'" type="primary" @click="close">完成</el-button>
      </div>
    </template>
  </el-dialog>
</template>

<style scoped>
.dep { display: flex; flex-direction: column; gap: 14px; font-size: 13px; color: var(--text); }
.dep-section-title { font-size: 12px; font-weight: 600; letter-spacing: 0.04em; color: var(--text-3); text-transform: uppercase; }
.env-row { display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px; }
.env-card { padding: 14px; border-radius: 10px; border: 1px solid var(--border); background: var(--surface); cursor: pointer; text-align: left; font-family: inherit; color: var(--text); }
.env-card.active { border-color: currentColor; box-shadow: 0 0 0 3px var(--ring, var(--brand-ring)); }
.env-card.tone-outline.active { color: var(--text-2); --ring: rgba(0, 0, 0, 0.06); }
.env-card.tone-sky.active     { color: var(--sky);   --ring: var(--sky-bg); }
.env-card.tone-rose.active    { color: var(--rose);  --ring: var(--rose-bg); }
.env-name { font-size: 14px; font-weight: 600; }
.env-default { font-size: 11px; color: var(--text-3); margin-top: 2px; }
.warn-bar { padding: 10px 12px; border-radius: 8px; background: var(--rose-bg); color: var(--rose); font-size: 12.5px; }
.diff { list-style: none; padding: 0; margin: 0; display: flex; flex-direction: column; gap: 4px; }
.diff li { display: flex; gap: 8px; align-items: center; padding: 6px 10px; border-radius: 6px; font-size: 12.5px; }
.diff-\+ { background: var(--emerald-bg); color: var(--emerald); }
.diff-\~ { background: var(--amber-bg); color: var(--amber); }
.diff-\- { background: var(--rose-bg); color: var(--rose); }
.diff-kind { font-family: var(--d-font-mono); font-weight: 700; width: 14px; }
.impact-row { display: grid; grid-template-columns: repeat(4, 1fr); gap: 8px; }
.impact-card { background: var(--surface-2); border: 1px solid var(--border); border-radius: 8px; padding: 10px; text-align: center; }
.impact-num { font-size: 18px; font-weight: 600; color: var(--text); }
.impact-lbl { font-size: 11px; color: var(--text-3); margin-top: 2px; }
.prod-confirm { display: flex; flex-direction: column; gap: 6px; }
.prod-confirm label { font-size: 12px; color: var(--text-2); }
.prod-confirm code { font-family: var(--d-font-mono); background: var(--code-bg); padding: 0 6px; border-radius: 4px; color: var(--code-text); }
.input { height: 34px; padding: 0 12px; border: 1px solid var(--border-strong); border-radius: 8px; background: var(--surface); color: var(--text); font-size: 13px; outline: none; }
.input:focus { border-color: var(--brand); box-shadow: 0 0 0 3px var(--brand-ring); }
.safety { font-size: 12px; color: var(--emerald); padding-top: 4px; }
.dep-center { align-items: center; padding: 24px 0; gap: 14px; }
.loader { width: 36px; height: 36px; border: 3px solid var(--surface-3); border-top-color: var(--brand); border-radius: 50%; animation: spin 0.8s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }
.success-mark { width: 48px; height: 48px; border-radius: 50%; background: var(--emerald-bg); color: var(--emerald); display: grid; place-items: center; font-size: 24px; font-weight: 600; }
.dep-foot { display: flex; gap: 8px; justify-content: flex-end; }
</style>
```

- [ ] **Step 2: Wire it in `ChatPage.vue`**

Add to the imports: `import DeployConfirmModal from '@/components/v2/DeployConfirmModal.vue'`. Add a reactive `const deployOpen = ref(false)`. Find the existing deploy handler (search for the existing deploy button click — likely calls a `deploy()` function). Replace that direct call with `deployOpen.value = true`. Inside the existing `deploy()` function logic, gate it behind `phase === 'running'` of the modal — meaning the modal's `@confirm` event triggers the original deploy logic.

```vue
<DeployConfirmModal
  v-model="deployOpen"
  :app-name="currentApp?.name ?? ''"
  :app-code="currentApp?.code ?? ''"
  :changes="deployChanges"
  :impacts="deployImpacts"
  @confirm="(env) => runDeploy(env)"
/>
```

Where `deployChanges` is a `computed()` derived from the existing SPEC diff data, and `runDeploy(env)` is what the old click handler used to do directly.

- [ ] **Step 3: Verify**

In `/chat`, click "部署到平台" (or the blueprint panel's deploy button) → modal opens. Pick production → must type app code → confirm enables. Confirm triggers existing deploy behavior. Close after success.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/v2/DeployConfirmModal.vue frontend/src/views/ChatPage.vue
git commit -m "feat(v2): deploy confirm modal — env select + diff preview + prod 2nd confirm + impact"
```

**Session 6 checkpoint:** SPEC page renders with seed data. Apps page header + empty state use v2 styling. Deploy modal works end-to-end from ChatPage's deploy button without breaking the existing deploy flow.

---

## Cross-cutting deferred items (NOT in this plan)

Confirm these are explicitly out of scope before claiming P0+P1 done:

- `/agents` real implementation (Skills + MCP + Knowledge bindings UI) — needs `api/agents.ts`
- `/coding` (睿鲸) rewrite to remove preview and show artifact list + integration guide
- `/vibe` real code-server iframe embed + MiniMax chat sidebar
- `/industry` Ontology SVG graph + industry pack derivation flow
- `/runtime` 4-tab (sandboxes / pipelines / environments / deployments)
- MCP page polish from `StubMcp.vue` to the full design
- Onboarding 3-step tour + localStorage gate
- Cmd+K palette rebuild to match design (existing palette is reused via event)
- Apps table/grid full v2 styling (only header + empty state styled in this plan)
- ProjectDetail tabs 3-5 with real members / industry / env content

---

## Self-Review

**Spec coverage:**
- ✅ P0 design tokens — Session 1
- ✅ P0 Sidebar 4-group restructure — Session 2.2
- ✅ P0 TopBar + project switcher — Sessions 2.3, 2.4, 2.5
- ✅ P0 Router additions (6 routes + /vibe alias) — Session 2.6
- ✅ Role filtering removed (sidebar shows all 13 items, no role pill) — Session 2.2 (built without role filter)
- ✅ P1 Landing redesign — Session 4
- ✅ P1 ChatPage 3-column + blueprint panel — Session 5
- ✅ P1 Apps visual refresh — Session 6.2 (header + empty state, table deferred)
- ✅ P1 Projects list + detail — Session 3
- ✅ P1 Specs page — Session 6.1
- ✅ Deploy confirm modal — Session 6.3 (P1 because it gates ChatPage deploy)
- ✅ Project as first-class container + store + persistence — Session 2.1 + 3
- ❌ Onboarding — explicitly deferred above
- ❌ Industry knowledge → AI Builder loop (the cyan chip is rendered, but the actual binding API is deferred)

**Placeholder scan:** No "TBD", no "implement later" without a deferred-list reference. All code blocks complete. The only "TODO" comments left in the plan are explicit hookup points where the executing engineer must wire to a store discovered at runtime (Landing.vue store imports, ChatPage SPEC variable name) — those have explicit `rg` commands to discover the answer.

**Type consistency:** `Project` interface is identical in Sessions 2.1 and 3. `SpecVersion`, `Spec` shapes are only defined in Session 6.1 and not referenced elsewhere. `AppBlueprintPanel` prop names (`models / forms / flows / roles / dicts / industryPackName / industryObjectCount`) are referenced consistently in Session 5.2 and 5.3.

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-05-18-apaas-builder-redesign-p0-p1.md`. Two execution options:

1. **Subagent-Driven (recommended)** — Dispatch a fresh subagent per session, review between sessions. Fast iteration, isolated context per session.
2. **Inline Execution** — Execute sessions sequentially in this conversation with checkpoint reviews between each session.

Which approach?
