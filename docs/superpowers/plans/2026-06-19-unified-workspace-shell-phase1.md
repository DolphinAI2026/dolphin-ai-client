# 统一桌面工作区 Phase 1(外壳 + 工具面板框架)Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 ai-builder 前端搭一个统一工作区外壳(左会话/中对话/右面板/顶工具菜单),先承载「通用对话」跑通,并定死「面板注册表 + 会话绑定」契约,让后续期只 register 新面板不动外壳。

**Architecture:** 渐进绞杀——新建 `views/workspace/` 一套,复用现成组件(SessionSidebar / AgentConversation / UnifiedChatComposer / BuilderModelPicker / useAiChatSession composable / agentObservabilityApi),旧三页(AIChatPage/ChatPage/CodingPage)Phase 1 不动。核心可测逻辑(binding / panelRegistry / 工具菜单项 / 会话列表映射)抽成纯 TS 模块。

**Tech Stack:** Vue 3 `<script setup>` + TypeScript + Element Plus + vitest(`environment: 'node'`)+ vite。

## Global Constraints

- 测试约定(**硬**):仓库 vitest 是 `environment: 'node'`、**无 DOM、不挂载组件**。纯逻辑测独立 `.ts` 模块;组件只用 `import src from './X.vue?raw'` 做源码字符串断言。测试文件 `*.spec.ts` 与被测代码**同目录**,glob `src/**/*.spec.ts`。
- 跑测:`frontend/` 下 `npm test`(= `vitest run --passWithNoTests`);单文件 `npx vitest run <path>`。
- 编译门禁:`npm run build`(vue-tsc)**预存坏**(ChatPage ~388 类型错),**不作 gate**;用 `npm run build:nocheck` 验编译,`npm run build:desktop` 验桌面产物。
- 复用优先,绝不重写已成熟组件;`@` alias = `frontend/src`。
- 不动后端(后台任务读 API 已存在)。不动旧三页路由。
- 代码风格:单引号、2 空格、**无行尾分号**,行首 `(`/`globalThis` 前加前导 `;` 防 ASI。
- 提交粒度:每个 Task 末尾一次 commit。

## 文件结构(Phase 1 新增 / 修改)

```
frontend/src/views/workspace/                (新目录)
├─ binding.ts            纯: Binding 类型 + bindingBadge() 徽标映射
├─ binding.spec.ts
├─ panelRegistry.ts      纯: Panel 类型 + registry + isAvailable + buildToolMenuItems
├─ panelRegistry.spec.ts
├─ sessionList.ts        纯: timeGroup() + toWorkspaceSessionItems() 映射
├─ sessionList.spec.ts
├─ panels.ts             注册 Phase 1 面板(artifacts/bg-tasks/plan + stub)到 registry
├─ panels.spec.ts        断言注册结果(纯)
├─ ToolMenu.vue          顶部工具菜单(渲染 buildToolMenuItems, 灰显禁用, emit open)
├─ ToolMenu.spec.ts      ?raw 断言
├─ PanelHost.vue         右侧停靠容器(异步 panel + 失败降级)
├─ PanelHost.spec.ts     ?raw 断言
├─ ChatPane.vue          中央对话(镜像 AppAssistantPanel, 通用对话 appId=null)
├─ ChatPane.spec.ts      ?raw 断言
├─ WorkspaceShell.vue    五区宿主(组合上述)
├─ WorkspaceShell.spec.ts ?raw 断言
└─ panels/
   ├─ ArtifactPanel.vue       从 AppAssistantPanel 抽产物抽屉
   ├─ BackgroundTasksPanel.vue agentObservabilityApi.listRuns 列表
   └─ PlanPanel.vue            占位(P4 做实)
frontend/src/router/index.ts   修改: 加 /workspace/:id? 路由
frontend/src/App.vue           修改: /workspace* 纳入 KeepAlive singleton
```

复用映射:`@/components/common/SessionSidebar.vue`(会话列表)、`@/components/common/AgentConversation.vue`、`@/components/common/UnifiedChatComposer.vue`、`@/components/common/BuilderModelPicker.vue`、`@/composables/useAiChatSession.ts`(对话发动机)、`@/components/common/AgentRunTraceDrawer.vue`(trace)、`@/api/agentObservability.ts`(后台任务)、`@/components/v2/AppAssistantPanel.vue`(ChatPane/ArtifactPanel 抄它结构)。

---

### Task 1: 会话绑定模型 binding.ts(纯模块)

**Files:**
- Create: `frontend/src/views/workspace/binding.ts`
- Test: `frontend/src/views/workspace/binding.spec.ts`

**Interfaces:**
- Produces: `type Binding`、`type BindingKind`、`bindingBadge(b: Binding): { tone: string; label: string }`、`bindingKindFromId(id: string): BindingKind`、`prefixedId(kind, raw): string`、`rawId(id): string`。

- [ ] **Step 1: 写失败测试**

```ts
// binding.spec.ts
import { describe, expect, it } from 'vitest'
import { bindingBadge, bindingKindFromId, prefixedId, rawId } from './binding'

describe('binding', () => {
  it('maps each binding kind to a tone + label', () => {
    expect(bindingBadge({ kind: 'none' })).toEqual({ tone: 'chat', label: '对话' })
    expect(bindingBadge({ kind: 'app', appId: 7 })).toEqual({ tone: 'cowork', label: '应用' })
    expect(bindingBadge({ kind: 'workspace', workspaceId: 'ws1' })).toEqual({ tone: 'success', label: '代码' })
  })
  it('uses type-prefixed ids to avoid cross-source collision', () => {
    expect(prefixedId('app', 7)).toBe('app:7')
    expect(prefixedId('workspace', 'ws1')).toBe('workspace:ws1')
    expect(bindingKindFromId('app:7')).toBe('app')
    expect(bindingKindFromId('chat:12')).toBe('none')   // chat 前缀 = none 绑定
    expect(rawId('app:7')).toBe('7')
  })
  it('falls back to none for unknown id shapes', () => {
    expect(bindingKindFromId('garbage')).toBe('none')
  })
})
```

- [ ] **Step 2: 跑测看失败**

Run: `cd frontend && npx vitest run src/views/workspace/binding.spec.ts`
Expected: FAIL（`Cannot find module './binding'`）

- [ ] **Step 3: 实现**

```ts
// binding.ts
export type BindingKind = 'none' | 'app' | 'workspace'

export type Binding =
  | { kind: 'none' }
  | { kind: 'app'; appId: number }
  | { kind: 'workspace'; workspaceId: string; appId?: number }

// SessionSidebar.badgeTone 内置色: chat=靛蓝 / cowork=橙 / success=绿。复用之。
export function bindingBadge(b: Binding): { tone: string; label: string } {
  if (b.kind === 'app') return { tone: 'cowork', label: '应用' }
  if (b.kind === 'workspace') return { tone: 'success', label: '代码' }
  return { tone: 'chat', label: '对话' }
}

// 统一会话列表混多来源, 用「类型前缀:原始id」防数字 id 撞车。
// 约定前缀: chat(=none 绑定) / app / workspace。
export function prefixedId(kind: 'chat' | 'app' | 'workspace', raw: string | number): string {
  return `${kind}:${raw}`
}

export function bindingKindFromId(id: string): BindingKind {
  if (id.startsWith('app:')) return 'app'
  if (id.startsWith('workspace:')) return 'workspace'
  return 'none' // chat: 前缀或任何未知形状都按通用对话
}

export function rawId(id: string): string {
  const i = id.indexOf(':')
  return i >= 0 ? id.slice(i + 1) : id
}
```

- [ ] **Step 4: 跑测看通过**

Run: `cd frontend && npx vitest run src/views/workspace/binding.spec.ts`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add frontend/src/views/workspace/binding.ts frontend/src/views/workspace/binding.spec.ts
git commit -m "feat(workspace): 会话绑定模型 binding.ts(Phase1 地基)"
```

---

### Task 2: 面板注册表 panelRegistry.ts(纯模块,契约核心)

**Files:**
- Create: `frontend/src/views/workspace/panelRegistry.ts`
- Test: `frontend/src/views/workspace/panelRegistry.spec.ts`

**Interfaces:**
- Consumes: `Binding`(Task 1)。
- Produces: `interface Panel`、`registerPanel(p)`、`listPanels(): Panel[]`(注册顺序稳定)、`isAvailable(p, binding): boolean`、`buildToolMenuItems(binding): ToolMenuItem[]`、`resetРegistryForTest()`、`type ToolMenuItem = { id; label; icon; shortcut?; group; enabled }`。

- [ ] **Step 1: 写失败测试**

```ts
// panelRegistry.spec.ts
import { describe, expect, it, beforeEach } from 'vitest'
import { registerPanel, listPanels, isAvailable, buildToolMenuItems, resetRegistryForTest } from './panelRegistry'

const stubComp = {} as any

beforeEach(() => resetRegistryForTest())

describe('panelRegistry', () => {
  it('lists panels in registration order', () => {
    registerPanel({ id: 'a', label: 'A', icon: 'x', group: 'common', availableWhen: () => true, component: stubComp })
    registerPanel({ id: 'b', label: 'B', icon: 'y', group: 'context', availableWhen: () => false, component: stubComp })
    expect(listPanels().map(p => p.id)).toEqual(['a', 'b'])
  })

  it('isAvailable delegates to the panel predicate against the binding', () => {
    const p = { id: 'files', label: 'Files', icon: 'f', group: 'context' as const,
      availableWhen: (b: any) => b.kind === 'workspace', component: stubComp }
    expect(isAvailable(p, { kind: 'workspace', workspaceId: 'w' })).toBe(true)
    expect(isAvailable(p, { kind: 'none' })).toBe(false)
  })

  it('buildToolMenuItems renders the full set with enabled flags per binding', () => {
    registerPanel({ id: 'artifacts', label: '产物', icon: 'doc', group: 'common', availableWhen: () => true, component: stubComp })
    registerPanel({ id: 'files', label: 'Files', icon: 'f', group: 'context',
      availableWhen: (b) => b.kind === 'workspace', component: stubComp })
    const none = buildToolMenuItems({ kind: 'none' })
    expect(none.map(i => [i.id, i.enabled])).toEqual([['artifacts', true], ['files', false]])
    const ws = buildToolMenuItems({ kind: 'workspace', workspaceId: 'w' })
    expect(ws.find(i => i.id === 'files')!.enabled).toBe(true)
  })

  it('availableWhen throwing or unknown binding degrades to disabled, never throws', () => {
    registerPanel({ id: 'boom', label: 'B', icon: 'b', group: 'context',
      availableWhen: () => { throw new Error('x') }, component: stubComp })
    expect(() => buildToolMenuItems({ kind: 'none' })).not.toThrow()
    expect(buildToolMenuItems({ kind: 'none' })[0].enabled).toBe(false)
  })
})
```

- [ ] **Step 2: 跑测看失败**

Run: `cd frontend && npx vitest run src/views/workspace/panelRegistry.spec.ts`
Expected: FAIL（模块不存在）

- [ ] **Step 3: 实现**

```ts
// panelRegistry.ts
import type { Component } from 'vue'
import type { Binding } from './binding'

export interface Panel {
  id: string
  label: string
  icon: string                 // AppIcon name 字符串
  shortcut?: string
  group: 'common' | 'context'  // common 永远在; context 按绑定亮/灰
  availableWhen: (binding: Binding) => boolean
  component: Component | (() => Promise<Component>)
}

export interface ToolMenuItem {
  id: string
  label: string
  icon: string
  shortcut?: string
  group: 'common' | 'context'
  enabled: boolean
}

const _panels: Panel[] = []

export function registerPanel(p: Panel): void {
  if (_panels.some(x => x.id === p.id)) return // 幂等, 防 HMR 重复注册
  _panels.push(p)
}

export function listPanels(): Panel[] {
  return [..._panels]
}

export function isAvailable(p: Panel, binding: Binding): boolean {
  try {
    return !!p.availableWhen(binding)
  } catch {
    return false // 谓词异常/未知绑定 → 禁用, 不崩菜单
  }
}

export function buildToolMenuItems(binding: Binding): ToolMenuItem[] {
  return _panels.map(p => ({
    id: p.id, label: p.label, icon: p.icon, shortcut: p.shortcut,
    group: p.group, enabled: isAvailable(p, binding),
  }))
}

export function getPanel(id: string): Panel | undefined {
  return _panels.find(p => p.id === id)
}

export function resetRegistryForTest(): void {
  _panels.length = 0
}
```

- [ ] **Step 4: 跑测看通过**

Run: `cd frontend && npx vitest run src/views/workspace/panelRegistry.spec.ts`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add frontend/src/views/workspace/panelRegistry.ts frontend/src/views/workspace/panelRegistry.spec.ts
git commit -m "feat(workspace): 面板注册表契约 panelRegistry(全集灰显/绑定驱动)"
```

---

### Task 3: 会话列表映射 sessionList.ts(纯模块)

**Files:**
- Create: `frontend/src/views/workspace/sessionList.ts`
- Test: `frontend/src/views/workspace/sessionList.spec.ts`

**Interfaces:**
- Consumes: `Binding`/`bindingBadge`/`prefixedId`(Task 1)。
- Produces: `timeGroup(iso): string`、`interface WorkspaceSession`、`toSessionItems(sessions, nowMs): SessionItem[]`。`SessionItem` 形状对齐 `SessionSidebar` 的 `export interface SessionItem`(id/title/badgeTone/badgeLabel/meta/group)。

- [ ] **Step 1: 写失败测试**

```ts
// sessionList.spec.ts
import { describe, expect, it } from 'vitest'
import { timeGroup, toSessionItems } from './sessionList'

const NOW = new Date('2026-06-19T12:00:00').getTime()

describe('timeGroup', () => {
  it('buckets by recency relative to now', () => {
    expect(timeGroup('2026-06-19T08:00:00', NOW)).toBe('今天')
    expect(timeGroup('2026-06-18T20:00:00', NOW)).toBe('昨天')
    expect(timeGroup('2026-06-15T10:00:00', NOW)).toBe('本周')
    expect(timeGroup(null, NOW)).toBe('更早')
  })
})

describe('toSessionItems', () => {
  it('sorts desc by updated_at, type-prefixes ids, sets badge tone by binding', () => {
    const items = toSessionItems([
      { id: 12, title: '旧对话', binding: { kind: 'none' }, updated_at: '2026-06-10T10:00:00' },
      { id: 7, title: '订单应用', binding: { kind: 'app', appId: 7 }, updated_at: '2026-06-19T09:00:00' },
    ], NOW)
    expect(items.map(i => i.id)).toEqual(['app:7', 'chat:12'])
    expect(items[0]).toMatchObject({ title: '订单应用', badgeTone: 'cowork', badgeLabel: '应用', group: '今天' })
    expect(items[1]).toMatchObject({ id: 'chat:12', badgeTone: 'chat', group: '本月' })
  })
})
```

- [ ] **Step 2: 跑测看失败**

Run: `cd frontend && npx vitest run src/views/workspace/sessionList.spec.ts`
Expected: FAIL

- [ ] **Step 3: 实现**

```ts
// sessionList.ts
import type { SessionItem } from '@/components/common/SessionSidebar.vue'
import type { Binding } from './binding'
import { bindingBadge, prefixedId } from './binding'

export interface WorkspaceSession {
  id: string | number
  title: string
  binding: Binding
  updated_at?: string | null
  created_at?: string | null
}

const DAY = 24 * 60 * 60 * 1000

export function timeGroup(iso: string | null | undefined, nowMs: number): string {
  if (!iso) return '更早'
  const t = new Date(iso).getTime()
  if (Number.isNaN(t)) return '更早'
  const now = new Date(nowMs)
  const today0 = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime()
  if (t >= today0) return '今天'
  if (t >= today0 - DAY) return '昨天'
  if (t >= today0 - 7 * DAY) return '本周'
  if (t >= today0 - 30 * DAY) return '本月'
  return '更早'
}

function idPrefix(b: Binding): 'chat' | 'app' | 'workspace' {
  return b.kind === 'app' ? 'app' : b.kind === 'workspace' ? 'workspace' : 'chat'
}

export function toSessionItems(sessions: WorkspaceSession[], nowMs: number): SessionItem[] {
  const sorted = [...sessions].sort((a, b) => {
    const ta = new Date(a.updated_at || a.created_at || 0).getTime()
    const tb = new Date(b.updated_at || b.created_at || 0).getTime()
    return tb - ta
  })
  return sorted.map(s => {
    const badge = bindingBadge(s.binding)
    return {
      id: prefixedId(idPrefix(s.binding), s.id),
      title: s.title,
      badgeTone: badge.tone,
      badgeLabel: badge.label,
      group: timeGroup(s.updated_at || s.created_at, nowMs),
    }
  })
}
```

- [ ] **Step 4: 跑测看通过**

Run: `cd frontend && npx vitest run src/views/workspace/sessionList.spec.ts`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add frontend/src/views/workspace/sessionList.ts frontend/src/views/workspace/sessionList.spec.ts
git commit -m "feat(workspace): 统一会话列表映射 sessionList(时间分组+绑定徽标)"
```

---

### Task 4: 通用面板三件 + 注册 panels.ts

**Files:**
- Create: `frontend/src/views/workspace/panels/ArtifactPanel.vue`(从 `AppAssistantPanel.vue` L292-354 state + L580-602 template + L861-899 style 抽出,props `{ sessionId: number|null; artifact: any }`,调 `aiChatApi.getArtifact`)
- Create: `frontend/src/views/workspace/panels/BackgroundTasksPanel.vue`(调 `agentObservabilityApi.listRuns({ limit: 50 })`,列 run,点开 `AgentRunTraceDrawer`)
- Create: `frontend/src/views/workspace/panels/PlanPanel.vue`(占位,显「Plan 模式 · Phase 4」)
- Create: `frontend/src/views/workspace/panels.ts`(register 三件 + 一个测试可见的 stub context 面板)
- Test: `frontend/src/views/workspace/panels.spec.ts`

**Interfaces:**
- Consumes: `registerPanel`(Task 2)。
- Produces: `registerPhase1Panels()`(幂等,WorkspaceShell onMounted 调一次)。注册:`artifacts`(common,always)、`background-tasks`(common,always)、`plan`(common,always)、`stub-code`(context,binding.kind==='workspace',仅为验证 registry 驱动,P2 替换)。

- [ ] **Step 1: 写失败测试(纯,验注册结果)**

```ts
// panels.spec.ts
import { describe, expect, it, beforeEach } from 'vitest'
import { resetRegistryForTest, buildToolMenuItems } from './panelRegistry'
import { registerPhase1Panels } from './panels'

beforeEach(() => resetRegistryForTest())

describe('registerPhase1Panels', () => {
  it('registers common panels always-on and the stub code panel only for workspace binding', () => {
    registerPhase1Panels()
    const none = buildToolMenuItems({ kind: 'none' })
    const byId = Object.fromEntries(none.map(i => [i.id, i.enabled]))
    expect(byId['artifacts']).toBe(true)
    expect(byId['background-tasks']).toBe(true)
    expect(byId['plan']).toBe(true)
    expect(byId['stub-code']).toBe(false)               // none 绑定 → 代码面板灰
    const ws = buildToolMenuItems({ kind: 'workspace', workspaceId: 'w' })
    expect(ws.find(i => i.id === 'stub-code')!.enabled).toBe(true)  // workspace → 亮
  })
  it('is idempotent (safe to call twice / HMR)', () => {
    registerPhase1Panels(); registerPhase1Panels()
    const ids = buildToolMenuItems({ kind: 'none' }).map(i => i.id)
    expect(new Set(ids).size).toBe(ids.length)
  })
})
```

- [ ] **Step 2: 跑测看失败**

Run: `cd frontend && npx vitest run src/views/workspace/panels.spec.ts`
Expected: FAIL

- [ ] **Step 3: 实现 panels.ts(组件用 defineAsyncComponent 懒加载)**

```ts
// panels.ts
import { defineAsyncComponent } from 'vue'
import { registerPanel } from './panelRegistry'

export function registerPhase1Panels(): void {
  registerPanel({ id: 'artifacts', label: '产物 / 设计文档', icon: 'file', group: 'common',
    availableWhen: () => true, component: defineAsyncComponent(() => import('./panels/ArtifactPanel.vue')) })
  registerPanel({ id: 'background-tasks', label: '后台任务', icon: 'activity', group: 'common',
    availableWhen: () => true, component: defineAsyncComponent(() => import('./panels/BackgroundTasksPanel.vue')) })
  registerPanel({ id: 'plan', label: 'Plan', icon: 'list', group: 'common',
    availableWhen: () => true, component: defineAsyncComponent(() => import('./panels/PlanPanel.vue')) })
  // stub: 仅验证 registry 按绑定点亮/置灰; Phase 2 用真 Files/Diff/... 替换。
  registerPanel({ id: 'stub-code', label: '代码(P2)', icon: 'code', group: 'context',
    availableWhen: (b) => b.kind === 'workspace', component: defineAsyncComponent(() => import('./panels/PlanPanel.vue')) })
}
```

- [ ] **Step 4: 实现三个面板组件**

PlanPanel.vue（占位,最简）:
```vue
<template>
  <div class="plan-panel-placeholder" style="padding:24px;opacity:.7">
    <p>Plan 模式将在 Phase 4 做实(agent 提计划 → 审批 → 执行)。</p>
  </div>
</template>
<script setup lang="ts"></script>
```

BackgroundTasksPanel.vue（列 agent runs;**逐字镜像** AgentRunTraceDrawer 的取数法,数据源 `agentObservabilityApi.listRuns`）:
```vue
<template>
  <div class="bg-tasks-panel" style="padding:12px;overflow:auto">
    <div v-if="loading">加载中…</div>
    <div v-else-if="error" class="is-error">{{ error }}</div>
    <ul v-else class="run-list">
      <li v-for="r in runs" :key="r.run_id" class="run-item" @click="openTrace(r.run_id)">
        <span class="run-status" :class="'st-' + r.status">{{ r.status }}</span>
        <span class="run-type">{{ r.agent_type }}</span>
        <span class="run-tokens">{{ r.total_tokens }} tok</span>
      </li>
    </ul>
    <AgentRunTraceDrawer v-model="traceVisible" :session-id="null" :prefer-run-id="activeRunId" />
  </div>
</template>
<script setup lang="ts">
import { ref, onMounted } from 'vue'
import AgentRunTraceDrawer from '@/components/common/AgentRunTraceDrawer.vue'
import { agentObservabilityApi, type AgentRunSummary } from '@/api/agentObservability'
const runs = ref<AgentRunSummary[]>([])
const loading = ref(true)
const error = ref('')
const traceVisible = ref(false)
const activeRunId = ref<string | null>(null)
async function load() {
  loading.value = true; error.value = ''
  try { runs.value = (await agentObservabilityApi.listRuns({ limit: 50 })).runs }
  catch (e: any) { error.value = e?.message || '加载失败' }
  finally { loading.value = false }
}
function openTrace(id: string) { activeRunId.value = id; traceVisible.value = true }
onMounted(load)
</script>
```

ArtifactPanel.vue：把 `AppAssistantPanel.vue` 的产物抽屉抽出。props `{ sessionId: number | null; artifact: any }`,onMounted/watch 按 `artifact.storage` 分流:`'file'` 提示下载(用 `aiChatApi.artifactDownloadUrl`),否则 `aiChatApi.getArtifact(sessionId, artifact.filename, version)` 取 `.content` 再 `v-html="renderMd(content)"`。**逐字参照** AppAssistantPanel L298-329 `onOpenArtifact` 取数逻辑 + L580-602 模板 + L861-899 样式。HTML 产物 iframe **绝不给 `allow-scripts`**。

- [ ] **Step 5: 跑测看通过 + 编译**

Run: `cd frontend && npx vitest run src/views/workspace/panels.spec.ts && npm run build:nocheck`
Expected: 测试 PASS;build:nocheck 成功(无新增编译错)

- [ ] **Step 6: 提交**

```bash
git add frontend/src/views/workspace/panels.ts frontend/src/views/workspace/panels.spec.ts frontend/src/views/workspace/panels/
git commit -m "feat(workspace): Phase1 通用面板(产物/后台任务/Plan占位)+ 注册"
```

---

### Task 5: ToolMenu.vue 顶部工具菜单

**Files:**
- Create: `frontend/src/views/workspace/ToolMenu.vue`
- Test: `frontend/src/views/workspace/ToolMenu.spec.ts`

**Interfaces:**
- Consumes: `buildToolMenuItems`(Task 2)、`Binding`(Task 1)、`AppIcon`。
- Produces: 组件 props `{ binding: Binding }`,emit `(e:'open', panelId:string)`。禁用项不可点。

- [ ] **Step 1: 写失败测试(?raw 断言结构)**

```ts
// ToolMenu.spec.ts
import { describe, expect, it } from 'vitest'
import src from './ToolMenu.vue?raw'

describe('ToolMenu', () => {
  it('renders the full panel set from buildToolMenuItems and disables unavailable items', () => {
    expect(src).toContain('buildToolMenuItems')
    expect(src).toContain("emit('open'")
    expect(src).toContain(':disabled')          // 禁用态绑定
    expect(src).toContain('is-disabled')        // 灰显 class
  })
  it('does not emit open for disabled items', () => {
    // 守卫: 点击 handler 必须先判 item.enabled
    expect(src).toMatch(/if\s*\(\s*!?\s*item\.enabled/)
  })
})
```

- [ ] **Step 2: 跑测看失败** — `npx vitest run src/views/workspace/ToolMenu.spec.ts` → FAIL

- [ ] **Step 3: 实现(EP dropdown 风格,对齐截图)**

```vue
<template>
  <el-dropdown trigger="click" @command="onCommand">
    <button class="tool-menu-trigger" title="工具面板"><AppIcon name="layout" :size="16" /></button>
    <template #dropdown>
      <el-dropdown-menu>
        <el-dropdown-item
          v-for="item in items" :key="item.id"
          :command="item.id" :disabled="!item.enabled"
          :class="{ 'is-disabled': !item.enabled }">
          <AppIcon :name="item.icon" :size="14" /> {{ item.label }}
          <span class="sc" v-if="item.shortcut">{{ item.shortcut }}</span>
        </el-dropdown-item>
      </el-dropdown-menu>
    </template>
  </el-dropdown>
</template>
<script setup lang="ts">
import { computed } from 'vue'
import AppIcon from '@/components/common/AppIcon.vue'
import { buildToolMenuItems } from './panelRegistry'
import type { Binding } from './binding'
const props = defineProps<{ binding: Binding }>()
const emit = defineEmits<{ (e: 'open', panelId: string): void }>()
const items = computed(() => buildToolMenuItems(props.binding))
function onCommand(id: string) {
  const item = items.value.find(i => i.id === id)
  if (!item || !item.enabled) return   // 守卫: 禁用项不触发
  emit('open', id)
}
</script>
```

- [ ] **Step 4: 跑测看通过** — `npx vitest run src/views/workspace/ToolMenu.spec.ts` → PASS

- [ ] **Step 5: 提交**

```bash
git add frontend/src/views/workspace/ToolMenu.vue frontend/src/views/workspace/ToolMenu.spec.ts
git commit -m "feat(workspace): ToolMenu 顶部工具菜单(全集渲染+禁用守卫)"
```

---

### Task 6: PanelHost.vue 右侧停靠容器

**Files:**
- Create: `frontend/src/views/workspace/PanelHost.vue`
- Test: `frontend/src/views/workspace/PanelHost.spec.ts`

**Interfaces:**
- Consumes: `getPanel`(Task 2)、`Binding`。
- Produces: props `{ activePanelId: string | null; binding: Binding; sessionId: number | null }`、emit `(e:'close')`。空态(activePanelId=null)显占位;异步组件加载失败显降级。

- [ ] **Step 1: 写失败测试(?raw)**

```ts
// PanelHost.spec.ts
import { describe, expect, it } from 'vitest'
import src from './PanelHost.vue?raw'

describe('PanelHost', () => {
  it('renders the active panel component from the registry', () => {
    expect(src).toContain('getPanel')
    expect(src).toContain(':is=')                 // 动态组件
  })
  it('has an empty state and an error fallback (never crashes the shell)', () => {
    expect(src).toContain('panel-empty')
    expect(src).toContain('onErrorCaptured')      // 捕获 panel 渲染/加载错
    expect(src).toContain('panel-error')
  })
})
```

- [ ] **Step 2: 跑测看失败** → FAIL

- [ ] **Step 3: 实现**

```vue
<template>
  <section class="panel-host">
    <header v-if="active" class="panel-host-head">
      <span>{{ active.label }}</span>
      <button @click="emit('close')" title="关闭面板"><AppIcon name="x" :size="14" /></button>
    </header>
    <div v-if="!active" class="panel-empty" style="padding:24px;opacity:.5">从右上角工具菜单打开一个面板</div>
    <div v-else-if="failed" class="panel-error" style="padding:24px;color:#dc2626">面板加载失败,请重试</div>
    <component v-else :is="active.component" :session-id="sessionId" :artifact="artifact" :binding="binding" />
  </section>
</template>
<script setup lang="ts">
import { computed, ref, watch, onErrorCaptured } from 'vue'
import AppIcon from '@/components/common/AppIcon.vue'
import { getPanel } from './panelRegistry'
import type { Binding } from './binding'
const props = defineProps<{ activePanelId: string | null; binding: Binding; sessionId: number | null; artifact?: any }>()
const emit = defineEmits<{ (e: 'close'): void }>()
const active = computed(() => (props.activePanelId ? getPanel(props.activePanelId) : undefined))
const failed = ref(false)
watch(() => props.activePanelId, () => { failed.value = false })
onErrorCaptured(() => { failed.value = true; return false })  // 降级, 不冒泡崩外壳
</script>
```

- [ ] **Step 4: 跑测看通过** → PASS

- [ ] **Step 5: 提交**

```bash
git add frontend/src/views/workspace/PanelHost.vue frontend/src/views/workspace/PanelHost.spec.ts
git commit -m "feat(workspace): PanelHost 停靠容器(空态+加载失败降级)"
```

---

### Task 7: ChatPane.vue 中央对话(镜像 AppAssistantPanel,通用对话)

**Files:**
- Create: `frontend/src/views/workspace/ChatPane.vue`
- Test: `frontend/src/views/workspace/ChatPane.spec.ts`

**Interfaces:**
- Consumes: `useAiChatSession`、`AgentConversation`、`UnifiedChatComposer`、`BuilderModelPicker`、`AgentRunTraceDrawer`、`listSkills`、`llmConfigApi`。
- Produces: props `{ sessionId: number | null }`、emits `(e:'open-artifact', a)`、`(e:'session-changed', id)`。通用对话:`useAiChatSession({ appId: ref(null) })`。

- [ ] **Step 1: 写失败测试(?raw,锁住关键复用与契约)**

```ts
// ChatPane.spec.ts
import { describe, expect, it } from 'vitest'
import src from './ChatPane.vue?raw'

describe('ChatPane', () => {
  it('reuses the existing chat engine + components (does not reimplement SSE)', () => {
    expect(src).toContain("useAiChatSession")
    expect(src).toContain('AgentConversation')
    expect(src).toContain('UnifiedChatComposer')
    expect(src).toContain('BuilderModelPicker')
  })
  it('runs as a general (unbound) chat — appId is null', () => {
    expect(src).toMatch(/appId:\s*ref\(null\)|appId:\s*computed/)
  })
  it('surfaces artifacts to the shell via open-artifact (panel lives in PanelHost)', () => {
    expect(src).toContain("emit('open-artifact'")
    expect(src).toContain('@open-artifact')
  })
})
```

- [ ] **Step 2: 跑测看失败** → FAIL

- [ ] **Step 3: 实现** — **逐字镜像 `@/components/v2/AppAssistantPanel.vue` 的 script/template**,差异:
  - `useAiChatSession({ appId: ref(null), viewContext: ref(null) })`(通用对话,不锁 app)。
  - 产物不在本组件开抽屉,改为 `@open-artifact="(a) => emit('open-artifact', a)"`(抽屉在 PanelHost 的 ArtifactPanel)。
  - 模型选择 `llmConfigApi.listOptions('builder')` + `BuilderModelPicker`(同 AppAssistantPanel)。
  - 输入区 `UnifiedChatComposer` 全套(attachments/stop/@skill,同 AppAssistantPanel L511-535)。
  - watch `props.sessionId` → `loadSession(id)`(切会话不重挂,composable 内部 abort 旧流)。
  本体是组合现成件,不新写 SSE/composable。

- [ ] **Step 4: 跑测看通过 + 编译** — `npx vitest run src/views/workspace/ChatPane.spec.ts && npm run build:nocheck` → PASS / 成功

- [ ] **Step 5: 提交**

```bash
git add frontend/src/views/workspace/ChatPane.vue frontend/src/views/workspace/ChatPane.spec.ts
git commit -m "feat(workspace): ChatPane 中央对话(复用 useAiChatSession+AppAssistantPanel 结构)"
```

---

### Task 8: WorkspaceShell.vue 五区宿主

**Files:**
- Create: `frontend/src/views/workspace/WorkspaceShell.vue`
- Test: `frontend/src/views/workspace/WorkspaceShell.spec.ts`

**Interfaces:**
- Consumes: 全部上述 + `SessionSidebar`、`toSessionItems`(Task 3)、`registerPhase1Panels`(Task 4)、`useAiChatSession`(取会话列表)。
- 自身状态:`currentSessionId`、`activePanelId`、`openArtifact`、`currentBinding`(Phase 1 通用对话恒 `{kind:'none'}`)。

- [ ] **Step 1: 写失败测试(?raw)**

```ts
// WorkspaceShell.spec.ts
import { describe, expect, it } from 'vitest'
import src from './WorkspaceShell.vue?raw'

describe('WorkspaceShell', () => {
  it('composes the five regions', () => {
    expect(src).toContain('SessionSidebar')
    expect(src).toContain('ToolMenu')
    expect(src).toContain('PanelHost')
    expect(src).toContain('ChatPane')
  })
  it('registers Phase1 panels on mount and wires ToolMenu open → PanelHost', () => {
    expect(src).toContain('registerPhase1Panels')
    expect(src).toContain('@open=')          // ToolMenu open
    expect(src).toContain(':active-panel-id')// 传给 PanelHost
  })
  it('passes current binding to ToolMenu (none in Phase 1)', () => {
    expect(src).toContain(':binding')
  })
})
```

- [ ] **Step 2: 跑测看失败** → FAIL

- [ ] **Step 3: 实现(五区布局 + 串联)**

```vue
<template>
  <div class="workspace-shell">
    <SessionSidebar
      module-name="工作区" brand-color="#f59e0b"
      :sessions="sessionItems" :active-id="activeSidebarId"
      collapse-key="workspace:aside-collapsed" new-label="+ 新会话"
      empty-hint="暂无会话,点上方新建"
      @select="onSelect" @create="onCreate"
      @rename="onRename" @delete="onDelete" @collapse-change="(v) => (asideCollapsed = v)" />
    <main class="ws-main">
      <header class="ws-top">
        <ToolMenu :binding="currentBinding" @open="onOpenPanel" />
      </header>
      <div class="ws-body" :class="{ 'has-panel': activePanelId }">
        <ChatPane :session-id="currentSessionId"
          @open-artifact="onOpenArtifact" @session-changed="onSessionChanged" />
        <PanelHost v-if="activePanelId" :active-panel-id="activePanelId"
          :binding="currentBinding" :session-id="currentSessionId" :artifact="openArtifact"
          @close="activePanelId = null" />
      </div>
    </main>
  </div>
</template>
<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import SessionSidebar from '@/components/common/SessionSidebar.vue'
import ToolMenu from './ToolMenu.vue'
import PanelHost from './PanelHost.vue'
import ChatPane from './ChatPane.vue'
import { registerPhase1Panels } from './panels'
import { toSessionItems, type WorkspaceSession } from './sessionList'
import { rawId } from './binding'
import type { Binding } from './binding'
import { useAiChatSession } from '@/composables/useAiChatSession'

registerPhase1Panels()
const { sessions, loadSessions, currentSession } = useAiChatSession({ appId: ref(null) })

const currentSessionId = ref<number | null>(null)
const activePanelId = ref<string | null>(null)
const openArtifact = ref<any>(null)
const asideCollapsed = ref(false)
// Phase 1 仅通用对话; Phase 2/3 由会话真实 binding 驱动
const currentBinding = ref<Binding>({ kind: 'none' })

const wsSessions = computed<WorkspaceSession[]>(() =>
  sessions.value.map(s => ({ id: s.id, title: s.title, binding: { kind: 'none' },
    updated_at: s.updated_at, created_at: s.created_at })))
const sessionItems = computed(() => toSessionItems(wsSessions.value, Date.now()))
const activeSidebarId = computed(() => (currentSessionId.value ? `chat:${currentSessionId.value}` : null))

function onOpenPanel(id: string) { activePanelId.value = id }
function onOpenArtifact(a: any) { openArtifact.value = a; activePanelId.value = 'artifacts' }
function onSelect(id: string | number) { currentSessionId.value = Number(rawId(String(id))) }
function onSessionChanged(id: number) { currentSessionId.value = id; loadSessions() }
function onCreate() { currentSessionId.value = null }   // ChatPane 首条消息触发 ensureSession
function onRename() { /* Phase 1 复用 aiChatApi.updateSession, 接 SessionSidebar rename */ }
function onDelete() { /* Phase 1 复用 aiChatApi.deleteSession */ }
onMounted(loadSessions)
</script>
```

> 注:`Date.now()` 在组件运行时可用(非测试);`sessionList` 把 nowMs 作参是为了纯函数可测。

- [ ] **Step 4: 跑测看通过 + 编译** — `npx vitest run src/views/workspace/WorkspaceShell.spec.ts && npm run build:nocheck` → PASS / 成功

- [ ] **Step 5: 提交**

```bash
git add frontend/src/views/workspace/WorkspaceShell.vue frontend/src/views/workspace/WorkspaceShell.spec.ts
git commit -m "feat(workspace): WorkspaceShell 五区宿主(串联会话/对话/工具菜单/面板)"
```

---

### Task 9: 路由 /workspace + App.vue KeepAlive singleton

**Files:**
- Modify: `frontend/src/router/index.ts`(加路由)
- Modify: `frontend/src/App.vue`(纳入 KeepAlive)
- Test: `frontend/src/views/workspace/route.spec.ts`(?raw 断言两个文件接好了)

**Interfaces:**
- Consumes: `WorkspaceShell.vue`。

- [ ] **Step 1: 写失败测试**

```ts
// route.spec.ts
import { describe, expect, it } from 'vitest'
import routerSrc from '@/router/index.ts?raw'
import appSrc from '@/App.vue?raw'

describe('workspace route wiring', () => {
  it('registers /workspace/:id? pointing at WorkspaceShell with requiresAuth', () => {
    expect(routerSrc).toContain("path: '/workspace/:id?'")
    expect(routerSrc).toContain('WorkspaceShell.vue')
    expect(routerSrc).toContain("name: 'Workspace'")
  })
  it('keeps /workspace* alive as a singleton (SSE survives :id switch)', () => {
    expect(appSrc).toMatch(/\/workspace/)
    expect(appSrc).toContain('workspace-singleton')
  })
})
```

- [ ] **Step 2: 跑测看失败** → FAIL

- [ ] **Step 3a: 加路由(`router/index.ts` routes 数组里,`/workspace-catalog` 附近)**

```ts
    {
      path: '/workspace/:id?',
      name: 'Workspace',
      component: () => import('@/views/workspace/WorkspaceShell.vue'),
      meta: { requiresAuth: true, navExpanded: true }
    },
```

- [ ] **Step 3b: 纳入 KeepAlive(`App.vue`)** — 扩 `isAiChatRoute` 为「需 singleton 的路由」并加 workspace 分支。改 template:

```html
  <RouterView v-slot="{ Component }">
    <KeepAlive v-if="isAiChatRoute($route)">
      <component :is="Component" key="ai-chat-singleton" />
    </KeepAlive>
    <KeepAlive v-else-if="isWorkspaceRoute($route)">
      <component :is="Component" key="workspace-singleton" />
    </KeepAlive>
    <component v-else :is="Component" :key="$route.fullPath" />
  </RouterView>
```
script 加:
```ts
function isWorkspaceRoute(r: RouteLocationNormalized): boolean {
  return r.path === '/workspace' || r.path.startsWith('/workspace/')
}
```

- [ ] **Step 4: 跑测看通过 + 双产物编译**

Run: `cd frontend && npx vitest run src/views/workspace/route.spec.ts && npm run build:nocheck && npm run build:desktop`
Expected: PASS;两个 build 成功

- [ ] **Step 5: 提交**

```bash
git add frontend/src/router/index.ts frontend/src/App.vue frontend/src/views/workspace/route.spec.ts
git commit -m "feat(workspace): 挂 /workspace 路由 + KeepAlive singleton(SSE 存活)"
```

---

### Task 10: 集成验证 + 绞杀守卫

**Files:**
- Test: `frontend/src/views/workspace/strangler.spec.ts`

**Interfaces:** 无新增产物,验收整体。

- [ ] **Step 1: 写绞杀守卫测试(旧三页路由未被破坏)**

```ts
// strangler.spec.ts
import { describe, expect, it } from 'vitest'
import routerSrc from '@/router/index.ts?raw'

describe('strangler: old pages untouched in Phase 1', () => {
  it('keeps AIChatPage / ChatPage / CodingPage routes intact', () => {
    expect(routerSrc).toContain("'@/views/AIChatPage.vue'")
    expect(routerSrc).toContain("'@/views/ChatPage.vue'")
    expect(routerSrc).toContain("'@/views/CodingPage.vue'")
  })
})
```

- [ ] **Step 2: 跑全量前端测试**

Run: `cd frontend && npm test`
Expected: 全绿(新增的 workspace specs 全过;预存的 `useCodingPipeline.spec.ts` 2 个失败是 base 已有、非本计划引入——确认失败数不增即可)

- [ ] **Step 3: 编译双产物**

Run: `cd frontend && npm run build:nocheck && npm run build:desktop`
Expected: 均成功;web 包无新增问题

- [ ] **Step 4: 人工冒烟(本地 preview / 桌面包)**

清单:
1. 访问 `/workspace`:左会话列表渲染、能新建、发消息流式、出产物卡。
2. 点产物卡 → 右侧 ArtifactPanel 开、显内容。
3. 工具菜单:`产物/后台任务/Plan` 亮、`代码(P2)` 灰(none 绑定)。
4. 后台任务面板:列出近期 agent runs(至少 ai_builder 类型),点开 trace 抽屉。
5. 旧页 `/ai-chat`、`/chat`、`/coding` 仍正常。

- [ ] **Step 5: 提交**

```bash
git add frontend/src/views/workspace/strangler.spec.ts
git commit -m "test(workspace): 绞杀守卫(旧三页路由不被 Phase1 破坏)+ Phase1 验收"
```

---

## Self-Review(已对 spec 核查)

- **spec 覆盖**:外壳五区(T8)/ panelRegistry 契约(T2)/ binding 模型(T1)/ 统一会话列表+徽标(T3,T8)/ 通用对话跑通(T7)/ 通用面板 产物·后台任务·Plan(T4)/ 全集灰显菜单(T2,T5)/ 新路由+绞杀(T9,T10)/ 测试(每 Task)——spec 各节均有对应 Task。
- **placeholder 扫描**:纯模块给全量代码;组件给可执行模板/?raw 断言 + 明确「逐字镜像 AppAssistantPanel/AgentRunTraceDrawer 的哪段」,无「TODO/类似上文」。ArtifactPanel/ChatPane 的「镜像现有组件」是复用指令(指明确切源行号),非占位。
- **类型一致**:`Binding`(T1)→ panelRegistry.availableWhen(T2)/ sessionList(T3)/ ToolMenu/PanelHost/Shell 一致;`buildToolMenuItems`/`ToolMenuItem`/`getPanel`/`registerPanel`/`resetRegistryForTest` 跨 Task 名字一致;`SessionItem` 复用 SessionSidebar 导出类型;`AgentRunSummary`/`listRuns` 复用 agentObservability.ts。
- **已知偏差**:`stub-code` 面板是测试脚手架(P2 替换,已注明);后台任务目前只 ai_builder 链路有数据(已注明,不影响框架)。
