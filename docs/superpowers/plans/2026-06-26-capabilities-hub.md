# 「得小帆·共性能力」hub 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把技能库/知识库/MCP/AI 网关四个能力收进一个统一的「得小帆·共性能力」hub 页(顶部 4 tab),补齐当初规划但延后的完整 hub。

**Architecture:** 新建 hub 页 `/hub`(CapabilitiesHubPage),顶部 tab 条,`?tab=` 选择。技能库/知识库 tab 就地渲染现有原生组件(各自带 BuilderFrame);MCP/AI 网关 tab 用 iframe 内嵌 admin-spa 的平台版页(McpServices/LlmConfigs),并让 admin-spa 在新标志 `chromeless=1` 下去掉自己的侧栏/tab 条只渲染内容。tab 按 `isPlatformAdmin` + 桌面隐藏过滤。老 `/skills`、`/knowledge` 重定向到 hub tab。后端无改动。

**Tech Stack:** Vue 3 + TS(主 app `frontend/` + admin-spa `admin-spa/`),vitest,Element Plus。

## Global Constraints

- hub 路由只 `requiresAuth`,权限**在 tab 层**按 `isPlatformAdmin` 过滤(否则普通用户连技能库都进不去)。
- MCP/AI 网关用**平台版 admin-spa 页内嵌**(McpServices `/mcp` / LlmConfigs `/llm-configs`),不用原生 McpToolsPage / PlatformEnvs。
- 去 admin-spa 壳用**独立标志 `chromeless=1`**,**不复用** `embed=1`(现有 `/platform-admin/*` 整体内嵌依赖 `embed=1` 带壳,不能破坏)。
- 桌面端:tab 可见性含「非桌面隐藏」→ 桌面 hub 只显技能库。`isDesktop` 用编译期常量 `import { isDesktop } from '@/utils/desktop'`(`export const isDesktop = __DESKTOP__`)。
- 前端构建门:`npm run build:nocheck`(vite);全量 `npm run build`(vue-tsc)主 app 预存坏,不作门,只确认本改动不引入新类型错。
- 改 ChatPage 类巨型 SFC 的 TDZ 坑不适用此处,但**改 .vue / 路由后必 preview 真跑验证**(见 spec)。
- spec:`docs/superpowers/specs/2026-06-26-capabilities-hub-design.md`。

## 文件结构

主 app(`frontend/`):
- 新增 `src/composables/useCapabilitiesHub.ts` — 纯函数:tab 定义 + 可见过滤 + `?tab=` 回落 + 老路径映射。
- 新增 `src/composables/useCapabilitiesHub.spec.ts` — vitest。
- 新增 `src/components/common/AdminSpaEmbedFrame.vue` — adminPath → chromeless iframe。
- 新增 `src/views/CapabilitiesHubPage.vue` — hub 外壳:tab 条 + tab 内容分发。
- 改 `src/views/platformAdminEmbedState.ts` — `buildPlatformAdminIframeSrc` 加 `chromeless?` 参数。
- 改 `src/views/platformAdminEmbedState.spec.ts` — 加 chromeless 断言。
- 改 `src/router/index.ts` — 加 `/hub`;`/skills`、`/knowledge` 改 redirect。
- 改 `src/components/v2/RailSidebar.vue` — `hubNavItem.path`→`/hub`;删 `/knowledge` footer 入口。

admin-spa(`admin-spa/`):
- 改 `src/components/AdminLayout.vue` — `chromeless=1` 时藏 `<aside class="rail">` + `<TabStrip />`,只渲染 `.admin-content > <router-view>`。

---

### Task 1: useCapabilitiesHub 纯函数(tab 定义 + 可见过滤 + 回落 + 老路径映射)

**Files:**
- Create: `frontend/src/composables/useCapabilitiesHub.ts`
- Test: `frontend/src/composables/useCapabilitiesHub.spec.ts`

**Interfaces:**
- Produces:
  - `type HubTabKey = 'skills' | 'knowledge' | 'mcp' | 'gateway'`
  - `interface HubTab { key: HubTabKey; label: string; kind: 'native' | 'embed'; adminPath?: string; access: 'all' | 'platformAdmin'; desktopHidden: boolean }`
  - `HUB_TABS: HubTab[]`
  - `visibleTabs(opts: { isPlatformAdmin: boolean; isDesktop: boolean }): HubTab[]`
  - `resolveActiveTab(requested: string | undefined, visible: HubTab[]): HubTabKey`
  - `LEGACY_PATH_TO_TAB: Record<string, HubTabKey>`

- [ ] **Step 1: 写失败的测试**

Create `frontend/src/composables/useCapabilitiesHub.spec.ts`:

```ts
import { describe, expect, it } from 'vitest'
import { visibleTabs, resolveActiveTab, HUB_TABS, LEGACY_PATH_TO_TAB } from './useCapabilitiesHub'

describe('useCapabilitiesHub', () => {
  it('普通用户(非管理员)只看到技能库', () => {
    expect(visibleTabs({ isPlatformAdmin: false, isDesktop: false }).map(t => t.key)).toEqual(['skills'])
  })
  it('平台管理员看到全部 4 个', () => {
    expect(visibleTabs({ isPlatformAdmin: true, isDesktop: false }).map(t => t.key))
      .toEqual(['skills', 'knowledge', 'mcp', 'gateway'])
  })
  it('桌面端(即便管理员)只看到技能库', () => {
    expect(visibleTabs({ isPlatformAdmin: true, isDesktop: true }).map(t => t.key)).toEqual(['skills'])
  })
  it('请求不可见 tab → 回落到第一个可见(技能库)', () => {
    const vis = visibleTabs({ isPlatformAdmin: false, isDesktop: false })
    expect(resolveActiveTab('knowledge', vis)).toBe('skills')
  })
  it('请求可见 tab → 命中', () => {
    const vis = visibleTabs({ isPlatformAdmin: true, isDesktop: false })
    expect(resolveActiveTab('mcp', vis)).toBe('mcp')
  })
  it('无请求 → 第一个可见', () => {
    const vis = visibleTabs({ isPlatformAdmin: true, isDesktop: false })
    expect(resolveActiveTab(undefined, vis)).toBe('skills')
  })
  it('embed tab 带 adminPath, native 不带', () => {
    const mcp = HUB_TABS.find(t => t.key === 'mcp')!
    expect(mcp.kind).toBe('embed'); expect(mcp.adminPath).toBe('/mcp')
    const skills = HUB_TABS.find(t => t.key === 'skills')!
    expect(skills.kind).toBe('native')
  })
  it('老路径映射', () => {
    expect(LEGACY_PATH_TO_TAB['/skills']).toBe('skills')
    expect(LEGACY_PATH_TO_TAB['/knowledge']).toBe('knowledge')
  })
})
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd frontend && npx vitest run src/composables/useCapabilitiesHub.spec.ts`
Expected: FAIL（`Cannot find module './useCapabilitiesHub'`）。

- [ ] **Step 3: 写实现**

Create `frontend/src/composables/useCapabilitiesHub.ts`:

```ts
export type HubTabKey = 'skills' | 'knowledge' | 'mcp' | 'gateway'

export interface HubTab {
  key: HubTabKey
  label: string
  /** native = 就地渲染原生组件；embed = AdminSpaEmbedFrame iframe */
  kind: 'native' | 'embed'
  /** kind=embed 时的 admin-spa 路径 */
  adminPath?: string
  access: 'all' | 'platformAdmin'
  /** 桌面 build 隐藏(admin-spa 不发 / 知识库 desktop:hidden) */
  desktopHidden: boolean
}

export const HUB_TABS: HubTab[] = [
  { key: 'skills',    label: '技能库',  kind: 'native', access: 'all',           desktopHidden: false },
  { key: 'knowledge', label: '知识库',  kind: 'native', access: 'platformAdmin', desktopHidden: true },
  { key: 'mcp',       label: 'MCP',     kind: 'embed',  adminPath: '/mcp',         access: 'platformAdmin', desktopHidden: true },
  { key: 'gateway',   label: 'AI 网关', kind: 'embed',  adminPath: '/llm-configs', access: 'platformAdmin', desktopHidden: true },
]

export function visibleTabs(opts: { isPlatformAdmin: boolean; isDesktop: boolean }): HubTab[] {
  return HUB_TABS.filter((t) => {
    if (t.access === 'platformAdmin' && !opts.isPlatformAdmin) return false
    if (opts.isDesktop && t.desktopHidden) return false
    return true
  })
}

export function resolveActiveTab(requested: string | undefined, visible: HubTab[]): HubTabKey {
  const hit = visible.find((t) => t.key === requested)
  return hit ? hit.key : (visible[0]?.key ?? 'skills')
}

export const LEGACY_PATH_TO_TAB: Record<string, HubTabKey> = {
  '/skills': 'skills',
  '/knowledge': 'knowledge',
}
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd frontend && npx vitest run src/composables/useCapabilitiesHub.spec.ts`
Expected: PASS（8 个用例）。

- [ ] **Step 5: Commit**

```bash
git add frontend/src/composables/useCapabilitiesHub.ts frontend/src/composables/useCapabilitiesHub.spec.ts
git commit -m "feat(hub): useCapabilitiesHub 纯函数(tab 定义+可见过滤+回落+老路径映射)"
```

---

### Task 2: buildPlatformAdminIframeSrc 加 chromeless 参数

**Files:**
- Modify: `frontend/src/views/platformAdminEmbedState.ts`
- Test: `frontend/src/views/platformAdminEmbedState.spec.ts`

**Interfaces:**
- Consumes: 无。
- Produces: `buildPlatformAdminIframeSrc` 新增可选 `chromeless?: boolean`;为真时拼接 `&chromeless=1`。其余签名不变,Task 3 用。

- [ ] **Step 1: 加失败的测试**

在 `frontend/src/views/platformAdminEmbedState.spec.ts` 的 describe 内追加:

```ts
  it('chromeless 时 URL 带 chromeless=1', () => {
    const src = buildPlatformAdminIframeSrc({
      origin: 'http://localhost:5173', baseUrl: '/ai-builder/',
      adminPath: '/mcp', token: 'tok-1', chromeless: true,
    })
    expect(src).toContain('chromeless=1')
    expect(src).toContain('embed=1')
    expect(src).toContain('handoff_token=tok-1')
  })
  it('不传 chromeless 时不带 chromeless 参数(回归)', () => {
    const src = buildPlatformAdminIframeSrc({
      origin: 'http://localhost:5173', baseUrl: '/ai-builder/', adminPath: '/status', token: 't',
    })
    expect(src).not.toContain('chromeless')
  })
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd frontend && npx vitest run src/views/platformAdminEmbedState.spec.ts`
Expected: FAIL（chromeless 用例:`chromeless=1` 未出现）。

- [ ] **Step 3: 改实现**

把 `frontend/src/views/platformAdminEmbedState.ts` 的 `buildPlatformAdminIframeSrc` 改为:

```ts
export function buildPlatformAdminIframeSrc(options: {
  origin: string
  baseUrl: string
  adminPath: string
  token?: string | null
  chromeless?: boolean
}): string {
  const params = new URLSearchParams({ embed: '1' })
  if (options.token) params.set('handoff_token', options.token)
  if (options.chromeless) params.set('chromeless', '1')

  const base = (options.baseUrl || '/').replace(/\/$/, '')
  const adminBase = `${options.origin}${base}/admin`.replace(/([^:]\/)\/+/g, '$1')
  return `${adminBase}${options.adminPath}?${params.toString()}`
}
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd frontend && npx vitest run src/views/platformAdminEmbedState.spec.ts`
Expected: PASS（原有 + 2 新用例)。

- [ ] **Step 5: Commit**

```bash
git add frontend/src/views/platformAdminEmbedState.ts frontend/src/views/platformAdminEmbedState.spec.ts
git commit -m "feat(hub): buildPlatformAdminIframeSrc 支持 chromeless=1"
```

---

### Task 3: AdminSpaEmbedFrame 组件(adminPath → chromeless iframe)

**Files:**
- Create: `frontend/src/components/common/AdminSpaEmbedFrame.vue`

**Interfaces:**
- Consumes: `buildPlatformAdminIframeSrc`(Task 2,带 chromeless)。
- Produces: 组件 `<AdminSpaEmbedFrame :admin-path="string" :title="string" />`,恒 chromeless 内嵌。Task 4 用。

- [ ] **Step 1: 写组件**(镜像 `views/PlatformAdminEmbed.vue` 的 iframe + loading,去掉 postMessage —— chromeless 下 admin-spa 无返回/退出按钮)

Create `frontend/src/components/common/AdminSpaEmbedFrame.vue`:

```vue
<template>
  <section class="admin-spa-embed">
    <iframe :key="iframeSrc" class="embed-frame" :src="iframeSrc" :title="title || '平台能力'" @load="loading = false" />
    <div v-if="loading" class="embed-loading">正在加载…</div>
  </section>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { buildPlatformAdminIframeSrc } from '@/views/platformAdminEmbedState'

const props = defineProps<{ adminPath: string; title?: string }>()
const loading = ref(true)

const iframeSrc = computed(() =>
  buildPlatformAdminIframeSrc({
    origin: window.location.origin,
    baseUrl: import.meta.env.BASE_URL || '/',
    adminPath: props.adminPath,
    token: localStorage.getItem('token') || '',
    chromeless: true,
  }),
)

watch(iframeSrc, () => { loading.value = true })
</script>

<style scoped>
.admin-spa-embed { position: relative; height: 100%; width: 100%; display: flex; flex-direction: column; background: var(--bg, #F8FAFC); }
.embed-frame { flex: 1; width: 100%; border: 0; display: block; background: var(--surface); }
.embed-loading { position: absolute; inset: 0; display: grid; place-items: center; color: var(--text-2); font-size: 13px; }
</style>
```

- [ ] **Step 2: 构建确认(组件本身无单测,靠 build + Task 8 真机)**

Run: `cd frontend && npm run build:nocheck`
Expected: vite build 成功。

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/common/AdminSpaEmbedFrame.vue
git commit -m "feat(hub): AdminSpaEmbedFrame 组件(chromeless 内嵌 admin-spa 页)"
```

---

### Task 4: CapabilitiesHubPage 页面(tab 条 + 内容分发)

**Files:**
- Create: `frontend/src/views/CapabilitiesHubPage.vue`

**Interfaces:**
- Consumes: `visibleTabs`/`resolveActiveTab`(Task 1)、`AdminSpaEmbedFrame`(Task 3)、`SkillLibraryPage`/`KnowledgeBasePage`(现有)、`useUserStore().isPlatformAdmin`、`isDesktop`。
- Produces: 路由 `/hub` 的组件(Task 5 挂)。

- [ ] **Step 1: 写页面**

Create `frontend/src/views/CapabilitiesHubPage.vue`:

```vue
<template>
  <div class="capabilities-hub">
    <div class="hub-tabs" role="tablist">
      <button
        v-for="t in tabs"
        :key="t.key"
        type="button"
        role="tab"
        class="hub-tab"
        :class="{ active: active === t.key }"
        :aria-selected="active === t.key"
        @click="select(t.key)"
      >{{ t.label }}</button>
    </div>
    <div class="hub-content">
      <SkillLibraryPage v-if="active === 'skills'" />
      <KnowledgeBasePage v-else-if="active === 'knowledge'" />
      <AdminSpaEmbedFrame v-else-if="active === 'mcp'" admin-path="/mcp" title="MCP" />
      <AdminSpaEmbedFrame v-else-if="active === 'gateway'" admin-path="/llm-configs" title="AI 网关" />
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useUserStore } from '@/stores/user'
import { isDesktop } from '@/utils/desktop'
import { visibleTabs, resolveActiveTab, type HubTabKey } from '@/composables/useCapabilitiesHub'
import SkillLibraryPage from './SkillLibraryPage.vue'
import KnowledgeBasePage from './KnowledgeBasePage.vue'
import AdminSpaEmbedFrame from '@/components/common/AdminSpaEmbedFrame.vue'

const route = useRoute()
const router = useRouter()
const user = useUserStore()

const tabs = computed(() => visibleTabs({ isPlatformAdmin: user.isPlatformAdmin, isDesktop }))
const active = computed(() => resolveActiveTab(route.query.tab as string | undefined, tabs.value))

function select(key: HubTabKey) {
  if (key === active.value) return
  router.replace({ path: '/hub', query: { tab: key } })
}
</script>

<style scoped>
.capabilities-hub { height: 100%; min-height: 0; display: flex; flex-direction: column; background: var(--bg, #F8FAFC); }
.hub-tabs { flex-shrink: 0; display: flex; gap: 4px; padding: 8px 16px 0; border-bottom: 1px solid var(--line); background: var(--surface); }
.hub-tab {
  padding: 8px 16px; border: none; background: transparent; cursor: pointer;
  font-size: 14px; font-weight: 500; color: var(--text-2); border-bottom: 2px solid transparent;
}
.hub-tab.active { color: var(--brand); border-bottom-color: var(--brand); font-weight: 600; }
.hub-content { flex: 1; min-width: 0; min-height: 0; overflow: hidden; display: flex; flex-direction: column; }
/* SkillLibraryPage/KnowledgeBasePage 的 BuilderFrame 是 height:100% → 填满 .hub-content;
   AdminSpaEmbedFrame 也是 height:100%。避免双滚动。 */
.hub-content > * { flex: 1; min-height: 0; }
</style>
```

- [ ] **Step 2: 构建确认**

Run: `cd frontend && npm run build:nocheck`
Expected: vite build 成功。

Run: `cd frontend && npx vue-tsc --noEmit -p tsconfig.json 2>&1 | grep -E "CapabilitiesHubPage|useCapabilitiesHub|AdminSpaEmbedFrame"`
Expected: 无输出(本改动相关符号零类型错)。

- [ ] **Step 3: Commit**

```bash
git add frontend/src/views/CapabilitiesHubPage.vue
git commit -m "feat(hub): CapabilitiesHubPage(tab 条 + 4 能力分发)"
```

---

### Task 5: 路由 — 加 /hub + 老路径重定向

**Files:**
- Modify: `frontend/src/router/index.ts`(`/skills` ~88-92;`/knowledge` ~187-192)

**Interfaces:**
- Consumes: `CapabilitiesHubPage`(Task 4)。
- Produces: `/hub` 路由可达;`/skills`、`/knowledge` 重定向到 hub tab。

- [ ] **Step 1: 加 /hub 路由 + 改 /skills /knowledge 为 redirect**

把 `/skills` 那条(`path: '/skills'` … 整块)替换为:

```ts
    {
      path: '/hub',
      name: 'CapabilitiesHub',
      component: () => import('@/views/CapabilitiesHubPage.vue'),
      meta: { requiresAuth: true, navExpanded: true },
    },
    {
      path: '/skills',
      name: 'Skills',
      redirect: { path: '/hub', query: { tab: 'skills' } },
    },
```

把 `/knowledge` 那条(`path: '/knowledge'` … 整块)替换为:

```ts
    {
      path: '/knowledge',
      name: 'knowledge-base',
      redirect: { path: '/hub', query: { tab: 'knowledge' } },
    },
```

> 注:`/skills/:name/workspace`(SkillWorkspace 路由,~94-97)**不动** —— 技能工作区仍独立路由,只是技能库列表进了 hub。

- [ ] **Step 2: 构建确认**

Run: `cd frontend && npm run build:nocheck`
Expected: vite build 成功。

- [ ] **Step 3: preview 验证重定向**

启动 preview(`preview_start frontend`,或 dev server 已在 :5173),登录态下:
- 访问 `/ai-builder/skills` → URL 落 `/ai-builder/hub?tab=skills`,显技能库。
- 访问 `/ai-builder/knowledge` → 落 `/ai-builder/hub?tab=knowledge`(管理员显知识库)。
- 访问 `/ai-builder/hub` → 显技能库(默认)。
Expected: 三条都不白屏、不 404。

- [ ] **Step 4: Commit**

```bash
git add frontend/src/router/index.ts
git commit -m "feat(hub): /hub 路由 + /skills /knowledge 重定向到 hub tab"
```

---

### Task 6: RailSidebar — 入口改链 /hub + 删独立知识库入口

**Files:**
- Modify: `frontend/src/components/v2/RailSidebar.vue`(`hubNavItem` ~130;知识库 footer 入口 ~479-490)

**Interfaces:**
- Consumes: `/hub` 路由(Task 5)。
- Produces: 无(导航)。

- [ ] **Step 1: hubNavItem 改链 /hub**

把 `frontend/src/components/v2/RailSidebar.vue:130`:

```ts
const hubNavItem: NavItem = { key: 'hub', label: '得小帆·共性能力', icon: 'spark', path: '/skills' }
```

改为:

```ts
const hubNavItem: NavItem = { key: 'hub', label: '得小帆·共性能力', icon: 'spark', path: '/hub' }
```

- [ ] **Step 2: 删独立「平台知识库」footer 入口**

删除 `frontend/src/components/v2/RailSidebar.vue` 中这一整块(~479-490):

```html
        <a
          v-if="user.isPlatformAdmin && !desktopHidden('/knowledge')"
          class="console-row"
          :class="{ active: route.path.startsWith('/knowledge') }"
          :href="resolveHref('/knowledge')"
          title="平台知识库"
          @click.prevent="go('/knowledge')"
        >
          <span class="console-row-icon" v-html="renderIcon('store')" />
          <span>平台知识库</span>
        </a>
```

(知识库已并入 hub 的 tab,不再单列。)

- [ ] **Step 3: 构建确认**

Run: `cd frontend && npm run build:nocheck`
Expected: vite build 成功。

- [ ] **Step 4: preview 验证**

preview 登录态:左栏「得小帆·共性能力」点击 → 进 `/hub`;footer 不再有单独「平台知识库」条。
Expected: 入口进 hub;无残留知识库入口;无 console 报错。

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/v2/RailSidebar.vue
git commit -m "feat(hub): 侧栏「得小帆·共性能力」改链 /hub + 删独立知识库入口"
```

---

### Task 7: admin-spa AdminLayout — chromeless 去壳

**Files:**
- Modify: `admin-spa/src/components/AdminLayout.vue`(template `<aside class="rail">` ~8、`<TabStrip />` ~102;script ~118)

**Interfaces:**
- Consumes: iframe URL 的 `?chromeless=1`(Task 2/3 传)。admin-spa 守卫清 query 时只删 `handoff_token`、保留其余 → `route.query.chromeless` 在 replace 后仍在。
- Produces: chromeless 时只渲染 `.admin-content > <router-view>`,无侧栏/tab 条。

- [ ] **Step 1: script 加 chromeless computed**

在 `admin-spa/src/components/AdminLayout.vue` script 内(`const route = useRoute()` 之后)加:

```ts
const chromeless = computed(() => route.query.chromeless === '1')
```

- [ ] **Step 2: template 按 chromeless 藏壳**

把 `<aside class="rail" :class="{ 'rail-collapsed': railCollapsed }">` 起始标签改为:

```html
    <aside v-if="!chromeless" class="rail" :class="{ 'rail-collapsed': railCollapsed }">
```

把 `<TabStrip />`(~102)改为:

```html
      <TabStrip v-if="!chromeless" />
```

(`.admin-shell` 是 flex,藏掉 `<aside>` 后 `.admin-main-col` 自然占满;`.admin-content > <router-view>` 照常渲染目标页。)

- [ ] **Step 3: admin-spa 构建确认**

Run: `cd admin-spa && npm run build 2>&1 | tail -3`(若 admin-spa 无 build:nocheck 则用 build;如 vue-tsc 报与本改动无关的预存错,确认不涉及 AdminLayout)
Expected: 构建成功 / AdminLayout 无新错。

- [ ] **Step 4: preview 验证 chromeless**

需 admin-spa 也在本地可服务(dev: admin-spa 单独 dev server,或经主后端 /admin)。直接访问
`{admin-spa origin}/mcp?embed=1&chromeless=1`(或经主 app /hub 的 MCP tab):
Expected: 只显 McpServices 内容,**无** admin-spa 左侧栏 + 顶部 tab 条;`?embed=1`(不带 chromeless,即老 `/platform-admin` 路径)仍**带壳**。

- [ ] **Step 5: Commit**

```bash
git add admin-spa/src/components/AdminLayout.vue
git commit -m "feat(hub): admin-spa AdminLayout 支持 chromeless=1 去壳(给 hub 内嵌用)"
```

---

### Task 8: 端到端 preview 验收

**Files:** 无(验证)。

- [ ] **Step 1: 全量前端单测回归**

Run: `cd frontend && npx vitest run src/composables/useCapabilitiesHub.spec.ts src/views/platformAdminEmbedState.spec.ts`
Expected: 全 PASS。

- [ ] **Step 2: preview 端到端(登录态,平台管理员)**

主 app preview(:5173,base `/ai-builder/`)+ admin-spa 可服务。点左栏「得小帆·共性能力」进 `/hub`,逐项核对:
- 管理员:tab 条有 **技能库 / 知识库 / MCP / AI 网关** 4 个。
- 技能库 tab:就地渲染技能库(BuilderFrame 头 + 列表),无双滚动。
- 知识库 tab:就地渲染知识库(7 篇 seed,若已 seed)。
- MCP tab:iframe 内嵌 McpServices,**无 admin-spa 侧栏/tab 条**(chromeless 生效),免登可操作。
- AI 网关 tab:iframe 内嵌 LlmConfigs,同样无壳免登。
- `?tab=` 切换 URL 同步;刷新保持当前 tab。
截图存证。

- [ ] **Step 3: 普通用户 / 桌面降级(条件允许)**

- 普通(非平台管理员)账号:`/hub` 只显技能库 tab;手敲 `?tab=knowledge` 回落技能库。
- 桌面包(若打):hub 只显技能库;`/platform-admin` 整体入口仍带壳正常(回归)。

- [ ] **Step 4: 回归 — 老路径 + 老平台管理入口**

- `/ai-builder/skills`、`/ai-builder/knowledge` 重定向进对应 hub tab。
- 左栏「平台管理」(`/platform-admin`)整体内嵌**仍带 admin-spa 壳**(没被 chromeless 误伤)。

## Self-Review 记录

- **Spec 覆盖**:§1 形态/路由→Task 4+5;§2 四 tab 内容/权限→Task 1(过滤)+Task 4(渲染);§3 chromeless 内嵌→Task 2+3+7;§4 桌面降级→Task 1(desktopHidden)+Task 8;入口收口→Task 6;向后兼容→Task 5;测试→各任务 + Task 8。无遗漏。
- **占位符**:无 TBD;所有代码步骤给完整代码 + 确切命令/预期;admin-spa build 步骤对「无 build:nocheck」给了兜底说明。
- **类型一致**:`HubTab`/`HubTabKey`/`visibleTabs`/`resolveActiveTab`/`LEGACY_PATH_TO_TAB` 在 Task 1 定义、Task 4 使用一致;`buildPlatformAdminIframeSrc(..., chromeless)` Task 2 定义、Task 3 调用一致;`adminPath` `/mcp`、`/llm-configs` 与 admin-spa 路由一致。
