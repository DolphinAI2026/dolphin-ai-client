# 统一工作区 Phase 3(配置面板 + app 绑定)Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** `/workspace?app_id=N` 驱动 app 绑定 → 工具菜单点亮「配置」面板(菜单栏 + 表单/数据/流程/权限设计面板 + 深链)→ 对话经 useAiChatSession 锁定 app。旧 /chat 不动(绞杀)。

**Architecture:** app_id 是 createSession 一等参数,run_agent 自动注入 app 上下文(零新机制);复用 ChatPage 的 ApaasMenuSidebar + 4 设计面板 + OpenLowcodeBackendButton 组合成单个「配置」面板;路由 query 驱动绑定。

**Tech Stack:** Vue 3 `<script setup>` + TS + Element Plus + vitest(node)+ vite。

## Global Constraints

- 决策(锁死):①app 绑定=`useAiChatSession({appId})`,app_id=ai-builder 本地 Application.id(number),不改后端 ②路由 `/workspace?app_id=N`(query,不占 `:id`=ws_id)③配置面板=单个「配置」面板(菜单栏+子tab+4设计面板+深链),availableWhen app ④AI改配置自动刷新/menu-viewContext/CUSTOM嵌入 = 不做(手动刷新按钮即可)。
- 测试:vitest `environment:'node'` 无 DOM;纯逻辑测 `.ts`,组件 `.vue?raw` 源码断言;`*.spec.ts` 同目录。跑测 `frontend/` 下 `npx vitest run <path>`,全量 `npm test`。编译:`build:nocheck`+`build:desktop`+`vitest`(`build`/vue-tsc 非 gate)。
- 风格:单引号、2空格、无行尾分号;`@`=`frontend/src`。
- **KeepAlive 单例**:`/workspace*` 切 query 不 remount → 必须 `watch(() => route.query.app_id)`,不能只 onMounted。
- 复用不重写:`ApaasMenuSidebar`(`@/components/`)、`FormDesignerPanel`/`DataSchemaEditor`/`ProcessDesignerPanel`/`FormPermPanel`/`OpenLowcodeBackendButton`(`@/components/v3/`)、`resolveInitialAppId`(`@/views/chatPageRouteState`)。
- app_id=number;ws_id=string。旧 /chat + ChatPage 不动。每 Task 末尾 commit。

## 文件结构

```
frontend/src/views/workspace/
├─ workspaceRoute.ts/.spec.ts        改: routeToBinding(wsId, appIdRaw) 三态 + parseSidebarSelect app
├─ panels/ConfigWorkspacePanel.vue/.spec.ts   新: 菜单栏+子tab+4设计面板+深链+手动刷新
├─ panels.ts/.spec.ts                改: 注册 config 面板
├─ WorkspaceShell.vue/.spec.ts       改: watch route.query.app_id + appId→ChatPane + onSelect app
└─ ChatPane.vue/.spec.ts             改: appId 从 prop 取
frontend/src/views/Apps.vue          改: openApp → /workspace?app_id=N
```

---

### Task 1: routeToBinding/parseSidebarSelect 扩 app 态(纯)

**Files:** Modify `workspaceRoute.ts`、`workspaceRoute.spec.ts`

**Interfaces:** `routeToBinding(wsId: string|undefined|null, appIdRaw?: any): Binding`(新增可选第 2 参,复用 `resolveInitialAppId`);`parseSidebarSelect` 已有(Phase 2,app 分支已落 else→`{kind:'app',sessionId:Number(raw),workspaceId:null}`)——本 task 补 app 路由产出。

- [ ] **Step 1: 改测试**——加 app 用例:

```ts
// workspaceRoute.spec.ts 增
import { routeToBinding } from './workspaceRoute'
describe('routeToBinding app', () => {
  it('maps query app_id to an app binding when no wsId', () => {
    expect(routeToBinding(undefined, '7')).toEqual({ kind: 'app', appId: 7 })
    expect(routeToBinding('', '7')).toEqual({ kind: 'app', appId: 7 })
  })
  it('wsId takes precedence over app_id', () => {
    expect(routeToBinding('1_abc', '7')).toEqual({ kind: 'workspace', workspaceId: '1_abc' })
  })
  it('neither → none', () => {
    expect(routeToBinding(undefined, undefined)).toEqual({ kind: 'none' })
    expect(routeToBinding('', '0')).toEqual({ kind: 'none' })   // app_id 0/非正 → none
  })
})
```
(保留 Phase 2 的 workspace/chat 用例不变。)

- [ ] **Step 2: 跑测看失败** — `cd frontend && npx vitest run src/views/workspace/workspaceRoute.spec.ts` → FAIL(routeToBinding 现只收 1 参)

- [ ] **Step 3: 改 routeToBinding**

```ts
import { resolveInitialAppId } from '@/views/chatPageRouteState'
// ...
export function routeToBinding(wsId: string | undefined | null, appIdRaw?: any): Binding {
  if (wsId) return { kind: 'workspace', workspaceId: wsId }
  const appId = resolveInitialAppId(appIdRaw)
  if (appId) return { kind: 'app', appId }
  return { kind: 'none' }
}
```
(`resolveInitialAppId` 签名:`(raw): number|null`,取数组首项/Number/>0。)

- [ ] **Step 4: 跑测看通过** → PASS（含 Phase 2 旧用例,因第 2 参可选不破）
- [ ] **Step 5: 提交** — `git commit -m "feat(workspace): Phase3 routeToBinding 扩 app 态(query app_id)"`

---

### Task 2: ConfigWorkspacePanel.vue(菜单栏 + 子tab + 4 设计面板 + 深链)

**Files:** Create `frontend/src/views/workspace/panels/ConfigWorkspacePanel.vue` + `.spec.ts`

**Interfaces:** Props(PanelHost 注入)`{ binding: Binding; sessionId?: number|null; artifact?: any }`。`appId = binding.kind==='app' ? binding.appId : null`。内部:ApaasMenuSidebar(左)+ 子 tab 行(表单/数据/流程/权限)+ 当前设计面板(右)+ 头部 OpenLowcodeBackendButton + 刷新按钮。

- [ ] **Step 1: 写失败测试(?raw)**

```ts
// ConfigWorkspacePanel.spec.ts
import { describe, expect, it } from 'vitest'
import src from './ConfigWorkspacePanel.vue?raw'
describe('ConfigWorkspacePanel', () => {
  it('reuses ApaasMenuSidebar + the four designer panels + deeplink (复用不重写)', () => {
    expect(src).toContain('ApaasMenuSidebar')
    expect(src).toContain('FormDesignerPanel')
    expect(src).toContain('DataSchemaEditor')
    expect(src).toContain('ProcessDesignerPanel')
    expect(src).toContain('FormPermPanel')
    expect(src).toContain('OpenLowcodeBackendButton')
  })
  it('derives appId from binding.appId', () => {
    expect(src).toMatch(/binding[\s\S]*appId/)
  })
  it('feeds selected menu (id/form/name) to the designer panels', () => {
    expect(src).toContain('@menu-selected')
    expect(src).toContain(':menu-id')
    expect(src).toContain(':form-id')
  })
  it('perm sub-tab is gated on form_id', () => {
    expect(src).toMatch(/perm[\s\S]*formId|formId[\s\S]*FormPermPanel/)
  })
})
```

- [ ] **Step 2: 跑测看失败** → FAIL

- [ ] **Step 3: 实现**(组合;**实现前读真实组件 defineProps 核对**,照 Phase 2 CodeWorkspacePanel 的范式)

骨架(布局:菜单栏左 + 设计区右,设计区 = 子tab 行 + 当前面板):
```vue
<template>
  <div class="config-ws-panel">
    <ApaasMenuSidebar class="cwp-menus" :app-id="appId" :selected-menu-id="menuId"
      @menu-selected="onMenuSelected" @menus-loaded="onMenusLoaded" />
    <div class="cwp-main">
      <header class="cwp-bar">
        <nav class="cwp-subtabs">
          <button v-for="t in subtabs" :key="t.key" :class="{ on: sub===t.key }"
            :disabled="t.key==='perm' && !formId" @click="sub=t.key">{{ t.label }}</button>
        </nav>
        <div class="cwp-bar-right">
          <button class="cwp-refresh" title="刷新" @click="refreshNonce++">刷新</button>
          <OpenLowcodeBackendButton v-if="appId" :app-id="appId" menu-type="MODEL"
            :menu-id="menuId || ''" :form-id="formId || null" />
        </div>
      </header>
      <div class="cwp-body">
        <div v-if="!appId" class="cwp-empty">未绑定应用</div>
        <div v-else-if="menuType==='CUSTOM'" class="cwp-empty">自定义页菜单请到低代码后台编辑</div>
        <FormDesignerPanel v-else-if="sub==='form'" :key="`form-${menuId}`"
          :app-id="appId" :menu-id="menuId" :menu-name="menuName" :form-id="formId" :refresh-nonce="refreshNonce" />
        <DataSchemaEditor v-else-if="sub==='data'" :key="`data-${menuId}`"
          :app-id="appId" :menu-id="menuId" :menu-name="menuName" :form-id="formId" :refresh-nonce="refreshNonce" />
        <ProcessDesignerPanel v-else-if="sub==='process'" :key="`proc-${menuId}-${refreshNonce}`"
          :app-id="appId" :menu-id="menuId" :menu-name="menuName" :form-id="formId" :hide-lowcode-btn="true" />
        <FormPermPanel v-else-if="sub==='perm' && formId" :app-id="appId" :form-id="formId" :menu-name="menuName" />
      </div>
    </div>
  </div>
</template>
<script setup lang="ts">
import { computed, ref } from 'vue'
import ApaasMenuSidebar from '@/components/ApaasMenuSidebar.vue'
import FormDesignerPanel from '@/components/v3/FormDesignerPanel.vue'
import DataSchemaEditor from '@/components/v3/DataSchemaEditor.vue'
import ProcessDesignerPanel from '@/components/v3/ProcessDesignerPanel.vue'
import FormPermPanel from '@/components/v3/FormPermPanel.vue'
import OpenLowcodeBackendButton from '@/components/v3/OpenLowcodeBackendButton.vue'
import type { Binding } from '../binding'
const props = defineProps<{ binding: Binding; sessionId?: number | null; artifact?: any }>()
const appId = computed(() => (props.binding.kind === 'app' ? props.binding.appId : null))
const subtabs = [{ key: 'form', label: '表单' }, { key: 'data', label: '数据' }, { key: 'process', label: '流程' }, { key: 'perm', label: '权限' }]
const sub = ref<'form' | 'data' | 'process' | 'perm'>('form')
const menuId = ref<string | null>(null)
const menuName = ref('')
const formId = ref('')
const menuType = ref('')
const refreshNonce = ref(0)
function onMenuSelected(menu: any) {
  menuId.value = menu.menu_id; menuName.value = menu.menu_name
  formId.value = String(menu.form_id || ''); menuType.value = menu.menu_type || ''
  if (sub.value === 'perm' && !formId.value) sub.value = 'form'
}
function onMenusLoaded(_menus: any[], firstFormMenu: any | null) {
  if (firstFormMenu && !menuId.value) onMenuSelected(firstFormMenu)
}
</script>
<style scoped>
.config-ws-panel { display: flex; height: 100%; min-height: 0; }
.cwp-menus { width: 200px; min-width: 180px; border-right: 1px solid var(--line); overflow: auto; flex-shrink: 0; }
.cwp-main { flex: 1; min-width: 0; display: flex; flex-direction: column; }
.cwp-bar { display: flex; align-items: center; justify-content: space-between; gap: 8px; padding: 6px 10px; border-bottom: 1px solid var(--line); flex-shrink: 0; }
.cwp-subtabs { display: flex; gap: 2px; }
.cwp-subtabs button { padding: 4px 10px; border: 0; background: transparent; cursor: pointer; border-radius: 6px; color: var(--text-3); }
.cwp-subtabs button.on { background: var(--brand-soft, rgba(99,102,241,.1)); color: var(--brand); }
.cwp-subtabs button:disabled { opacity: .4; cursor: not-allowed; }
.cwp-bar-right { display: flex; align-items: center; gap: 6px; }
.cwp-body { flex: 1; min-height: 0; overflow: auto; }
.cwp-empty { padding: 24px; opacity: .5; }
</style>
```

> 实现前务必读 `ApaasMenuSidebar.vue`/`FormDesignerPanel.vue`/`DataSchemaEditor.vue`/`ProcessDesignerPanel.vue`/`FormPermPanel.vue`/`OpenLowcodeBackendButton.vue` 的真实 defineProps,按真实 prop 名(kebab)接,别盲抄。ApaasMenuSidebar `selected-menu-id` 传 `menuId`。

- [ ] **Step 4: 跑测看通过 + 编译** — `npx vitest run src/views/workspace/panels/ConfigWorkspacePanel.spec.ts && npm run build:nocheck` → PASS / 成功
- [ ] **Step 5: 提交** — `git commit -m "feat(workspace): ConfigWorkspacePanel(菜单栏+表单/数据/流程/权限+深链)"`

---

### Task 3: panels.ts 注册 config 面板

**Files:** Modify `panels.ts`、`panels.spec.ts`

- [ ] **Step 1: 改 panels.spec.ts** 增:

```ts
  it('registers the config panel for app binding', () => {
    registerPhase1Panels()
    const none = buildToolMenuItems({ kind: 'none' })
    expect(none.find(i => i.id === 'config')!.enabled).toBe(false)
    const app = buildToolMenuItems({ kind: 'app', appId: 7 })
    expect(app.find(i => i.id === 'config')!.enabled).toBe(true)
    const ws = buildToolMenuItems({ kind: 'workspace', workspaceId: 'w' })
    expect(ws.find(i => i.id === 'config')!.enabled).toBe(false)   // workspace 态配置面板灰
  })
```
(保留 Phase 2 的 code 面板测试 + idempotency。)

- [ ] **Step 2: 跑测看失败** → FAIL

- [ ] **Step 3: 改 panels.ts** 在 code 面板后加:

```ts
  registerPanel({ id: 'config', label: '配置', icon: 'settings', group: 'context',
    availableWhen: (b) => b.kind === 'app', component: defineAsyncComponent(() => import('./panels/ConfigWorkspacePanel.vue')) })
```

- [ ] **Step 4: 跑测看通过 + 编译** → PASS / 成功
- [ ] **Step 5: 提交** — `git commit -m "feat(workspace): 注册 config 面板(app 绑定)"`

---

### Task 4: WorkspaceShell watch query.app_id + appId→ChatPane + onSelect app

**Files:** Modify `WorkspaceShell.vue`、`WorkspaceShell.spec.ts`

- [ ] **Step 1: 改测试** 增:

```ts
  it('watches route.query.app_id for app binding', () => {
    expect(src).toMatch(/route\.query\.app_id/)
  })
  it('feeds appId to ChatPane', () => { expect(src).toContain(':app-id') })
  it('onSelect pushes /workspace?app_id for app sessions', () => {
    expect(src).toMatch(/app_id:/)
  })
```
(保留 Phase 1/2 断言。)

- [ ] **Step 2: 跑测看失败** → FAIL

- [ ] **Step 3: 改 WorkspaceShell.vue**:
  - watch 改双源:`watch([() => route.params.id, () => route.query.app_id], ([id, appIdRaw]) => { const s = typeof id === 'string' ? id : Array.isArray(id) ? (id[0]||'') : ''; currentBinding.value = routeToBinding(s, appIdRaw) }, { immediate: true })`。
  - 加 `const appId = computed(() => (currentBinding.value.kind === 'app' ? currentBinding.value.appId : null))`;ChatPane 加 `:app-id="appId"`(Task 5 ChatPane 加 prop)。
  - `onSelect` 的 `parseSidebarSelect` 结果 `kind==='app'` 分支:`router.push({ path: '/workspace', query: { app_id: String(<解析出的 app rawId>) } })`。注意 parseSidebarSelect 对 app 返回 `sessionId:Number(raw)`(raw 是 app id 数字串)——用它当 app_id。
  - 保留 Phase 1/2 一切接线/布局。

- [ ] **Step 4: 跑测看通过 + 编译** → PASS / 成功
- [ ] **Step 5: 提交** — `git commit -m "feat(workspace): WorkspaceShell watch app_id query + 喂 ChatPane appId"`

---

### Task 5: ChatPane appId 从 prop 取(锁 app)

**Files:** Modify `ChatPane.vue`、`ChatPane.spec.ts`

- [ ] **Step 1: 改测试** 增/改:

```ts
  it('takes appId from prop (not hardcoded null) to lock the app', () => {
    expect(src).toContain('appId')
    expect(src).not.toMatch(/const appId = ref<number \| null>\(null\)/)   // 不再写死 null
  })
  it('resets session when app binding changes', () => {
    expect(src).toMatch(/watch[\s\S]*newSession/)
  })
```
(保留「复用 useAiChatSession/appId 入参/workspaceId/viewContext」断言。)

- [ ] **Step 2: 跑测看失败** → FAIL

- [ ] **Step 3: 改 ChatPane.vue**:
  - `defineProps` 加 `appId?: number | null`(与已有 sessionId/workspaceId 并列)。
  - 把内部 `const appId = ref<number|null>(null)` 改成 `const appId = computed(() => props.appId ?? null)`(或保留 ref 但 watch props.appId 同步)。computed 更简:`useAiChatSession({ appId: computed(()=>props.appId ?? null), ... })`——注意 useAiChatSession 入参要 Ref,computed 是 Ref,OK。
  - 切 app 重置会话:`watch(() => props.appId, () => { newSession(); void loadSessions() })`(对齐 AppAssistantPanel)。
  - 保留 workspaceId→viewContext(Phase 2)、其余不动。

- [ ] **Step 4: 跑测看通过 + 编译** — `npx vitest run src/views/workspace/ChatPane.spec.ts && npm run build:nocheck` → PASS / 成功
- [ ] **Step 5: 提交** — `git commit -m "feat(workspace): ChatPane appId 从 prop 取(锁应用) + 切 app 重置会话"`

---

### Task 6: Apps.vue 改指 /workspace + 绞杀验证

**Files:** Modify `frontend/src/views/Apps.vue`;Create `frontend/src/views/workspace/phase3-strangler.spec.ts`

- [ ] **Step 1: 改 Apps.vue.openApp** → `router.push({ path: '/workspace', query: appWorkspaceQuery(app) })`(原 `/chat`)。**只改 openApp 的 path('/chat'→'/workspace'),保留 appWorkspaceQuery 不动、其余去 /chat 的入口(openSpec/buildApp/openConversation 等)Phase 3 不动**(Phase 4 再统一)。

- [ ] **Step 2: 写绞杀守卫**

```ts
// phase3-strangler.spec.ts
import { describe, expect, it } from 'vitest'
import routerSrc from '@/router/index.ts?raw'
import appsSrc from '@/views/Apps.vue?raw'
describe('phase3 strangler', () => {
  it('keeps /chat route + ChatPage intact', () => {
    expect(routerSrc).toContain("'@/views/ChatPage.vue'")
  })
  it('Apps.openApp opens the unified workspace', () => {
    expect(appsSrc).toMatch(/openApp[\s\S]*path:\s*'\/workspace'/)
  })
})
```

- [ ] **Step 3: 跑测看通过** — `npx vitest run src/views/workspace/phase3-strangler.spec.ts` → PASS

- [ ] **Step 4: 全量 + 双产物** — `cd frontend && npm test && npm run build:nocheck && npm run build:desktop` → vitest 全绿 + 两 build ✓

- [ ] **Step 5: 提交** — `git commit -m "feat(workspace): Apps.openApp 改指 /workspace?app_id + Phase3 绞杀守卫"`

---

## Self-Review

- **spec 覆盖**:app 绑定路由(T1,T4)/ ChatPane 锁 app(T5)/ 配置面板组合(T2)/ 注册(T3)/ 入口改指(T6)/ 绞杀 /chat(T6)。AI自动刷新/menu-viewContext/CUSTOM嵌入明确不做。
- **placeholder**:纯模块全码;ConfigWorkspacePanel 给可执行骨架 + ?raw 断言 + 「实现前读真实组件 defineProps」校验提示(同 Phase 2 范式,非占位)。
- **类型一致**:`Binding`/`routeToBinding`/`resolveInitialAppId`(number)跨 T1→T4;`appId`(number)跨 T4→T5→ConfigWorkspacePanel;config 面板 id 跨 T2→T3→ToolMenu。
- **live-verify**:对话锁 app 后 run_agent 真注入 app 上下文(机制存在,真机验,验收第 2 条)。
