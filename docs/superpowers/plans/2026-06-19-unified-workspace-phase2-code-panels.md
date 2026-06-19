# 统一工作区 Phase 2(代码面板 + workspace 绑定)Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把代码工作流接进统一工作区:`/workspace/<ws_id>` 路由驱动 workspace 绑定 → 工具菜单点亮「代码」面板(文件树+代码/diff 查看器并排)→ 对话经 view_context 携带 ws_id 操作该 workspace。旧 /coding 不动(绞杀)。

**Architecture:** 单一 `useAiChatSession`(run_agent 已有全套 workspace 代码工具);路由驱动 `currentBinding`,不改后端;复用 `@/views/coding/` 的 `FileTree`/`CodeViewer` + `@/api/coding` 按 ws_id 渲染。可测逻辑(路由→binding、id 解析、workspace 文件加载)抽纯模块/composable。

**Tech Stack:** Vue 3 `<script setup>` + TS + Element Plus + vitest(`environment:'node'`)+ vite。

> **本计划对 spec 第 3 节的一处细化**:Files + CodeView **合成单个「代码」面板**(`CodeWorkspacePanel.vue`,树左+查看器右),而非两个独立注册面板——因 PanelHost 一次只显一个面板,树与代码需同屏(对齐 CodingPage 浏览器布局)。spec 其余不变。

## Global Constraints

- 决策(锁死):①单一 useAiChatSession 引擎,不切 useCodingPipeline ②路由驱动绑定 `/workspace/<ws_id>`,**不改后端 / 不改 AIChatSession schema**,ws_id 经 `useAiChatSession` 的 `viewContext` Ref → `sendMessage` 的 `view_context` 喂 run_agent ③Phase 2 面板 = 单个「代码」面板(文件树+查看器);Preview/Terminal 不做。
- 测试约定(硬):vitest `environment:'node'`、**无 DOM、不挂载组件**;纯逻辑/composable 测 `.ts` 模块,组件用 `.vue?raw` 源码字符串断言;`*.spec.ts` 与被测同目录。
- 跑测:`frontend/` 下 `npx vitest run <path>`;全量 `npm test`。编译门禁:`build`/vue-tsc 预存坏非 gate;用 `build:nocheck` + `build:desktop` + `vitest`。
- 代码风格:单引号、2 空格、**无行尾分号**;`@`=`frontend/src`。
- **KeepAlive 单例**:`/workspace*` 走 `workspace-singleton` key,切 `:id` **不 remount** → 路由参数必须 `watch(() => route.params.id)`,不能只 onMounted。
- 复用不重写:`FileTree.vue`(props `tree/changed:Set/changes?/selected/wsId?`,emits `select/select-line/accept-all`)、`CodeViewer.vue`(props `wsId/filePath/change?/focusLine?/dark?`,自调 read/diff API)、`@/views/coding/fileTree.ts`(`buildFileTree/compactTree/TreeNode`)、`@/api/coding`。
- workspaceId = 字符串(`'1_8ae94ab4'`);conversation/session id = number。别混。
- 旧 `/coding` 路由 + CodingPage 不动。每 Task 末尾一次 commit。

## 文件结构(Phase 2 新增 / 修改)

```
frontend/src/views/workspace/
├─ workspaceRoute.ts        新(纯): routeToBinding(id?) + parseSidebarSelect(id) → 路由/侧栏 id ↔ binding
├─ workspaceRoute.spec.ts
├─ useWorkspaceFiles.ts     新(composable): 按 wsId 拉 tree+changes + selected 状态(注入 codingApi 可测)
├─ useWorkspaceFiles.spec.ts
├─ panels/CodeWorkspacePanel.vue   新: FileTree(左)+ CodeViewer(右)+ useWorkspaceFiles, 读 binding.workspaceId
├─ panels/CodeWorkspacePanel.spec.ts
├─ panels.ts               改: 删 stub-code, 注册 code 面板(group context, availableWhen workspace)
├─ panels.spec.ts          改: 断言 code 面板 + 不再有 stub-code
├─ WorkspaceShell.vue      改: watch route.params.id → currentBinding + viewContext; 修 onSelect id 解析
├─ WorkspaceShell.spec.ts  改: 断言路由 watch + binding 驱动
├─ ChatPane.vue            改: 加 workspaceId prop → viewContext; 去重复头部按钮(历史/新建)
└─ ChatPane.spec.ts        改: 断言 viewContext 接线 + 去按钮
frontend/src/views/WorkspaceCatalogPage.vue   改: openWorkspace/openLocalFolder → push('/workspace/<ws_id>')
```

---

### Task 1: 路由/侧栏 id ↔ binding 纯逻辑 workspaceRoute.ts

**Files:** Create `frontend/src/views/workspace/workspaceRoute.ts` + `.spec.ts`

**Interfaces:**
- Consumes: `Binding`, `bindingKindFromId`, `rawId`(`./binding`,已存在)。
- Produces: `routeToBinding(id: string | undefined | null): Binding`、`parseSidebarSelect(prefixedId: string): { kind: BindingKind; sessionId: number | null; workspaceId: string | null }`。

- [ ] **Step 1: 写失败测试**

```ts
// workspaceRoute.spec.ts
import { describe, expect, it } from 'vitest'
import { routeToBinding, parseSidebarSelect } from './workspaceRoute'

describe('routeToBinding', () => {
  it('maps a route id to a workspace binding', () => {
    expect(routeToBinding('1_8ae94ab4')).toEqual({ kind: 'workspace', workspaceId: '1_8ae94ab4' })
  })
  it('maps empty/undefined route id to none (通用对话)', () => {
    expect(routeToBinding(undefined)).toEqual({ kind: 'none' })
    expect(routeToBinding('')).toEqual({ kind: 'none' })
  })
})

describe('parseSidebarSelect', () => {
  it('parses chat: prefix to a numeric session id', () => {
    expect(parseSidebarSelect('chat:123')).toEqual({ kind: 'none', sessionId: 123, workspaceId: null })
  })
  it('parses workspace: prefix to a string workspace id (NOT number)', () => {
    expect(parseSidebarSelect('workspace:1_8ae94ab4')).toEqual({ kind: 'workspace', sessionId: null, workspaceId: '1_8ae94ab4' })
  })
})
```

- [ ] **Step 2: 跑测看失败** — `cd frontend && npx vitest run src/views/workspace/workspaceRoute.spec.ts` → FAIL（模块不存在）

- [ ] **Step 3: 实现**

```ts
// workspaceRoute.ts
import type { Binding, BindingKind } from './binding'
import { bindingKindFromId, rawId } from './binding'

export function routeToBinding(id: string | undefined | null): Binding {
  if (!id) return { kind: 'none' }
  return { kind: 'workspace', workspaceId: id }
}

export function parseSidebarSelect(prefixedId: string): {
  kind: BindingKind
  sessionId: number | null
  workspaceId: string | null
} {
  const kind = bindingKindFromId(prefixedId)
  const raw = rawId(prefixedId)
  if (kind === 'workspace') return { kind, sessionId: null, workspaceId: raw }
  const n = Number(raw)
  return { kind, sessionId: Number.isFinite(n) ? n : null, workspaceId: null }
}
```

- [ ] **Step 4: 跑测看通过** → PASS
- [ ] **Step 5: 提交** — `git commit -m "feat(workspace): Phase2 路由/侧栏 id↔binding 纯逻辑 workspaceRoute"`

---

### Task 2: useWorkspaceFiles composable(按 ws_id 拉树+改动+选中)

**Files:** Create `frontend/src/views/workspace/useWorkspaceFiles.ts` + `.spec.ts`

**Interfaces:**
- Consumes: `@/api/coding`(`listWorkspaceFiles`/`getWorkspaceChanges`)、`@/views/coding/fileTree`(`buildFileTree`/`TreeNode`)、`vue`(`ref`/`computed`)。
- Produces: `useWorkspaceFiles(wsId: Ref<string | null>)` 返回 `{ tree, changes, changed, selected, loading, error, load, select }`。`changed` = computed `Set<string>`(改动路径)。`select(path)` 设 selected。`load()` 拉 tree+changes(wsId 为空则清空)。
- 可测性:测试用 `vi.mock('@/api/coding', ...)` + `vi.mock('@/views/coding/fileTree', ...)`,被测 composable 用 `await import('./useWorkspaceFiles')` 动态引入(仓库范式)。

- [ ] **Step 1: 写失败测试**

```ts
// useWorkspaceFiles.spec.ts
import { describe, expect, it, vi, beforeEach } from 'vitest'
import { ref } from 'vue'

const api = vi.hoisted(() => ({
  listWorkspaceFiles: vi.fn(),
  getWorkspaceChanges: vi.fn(),
}))
vi.mock('@/api/coding', () => ({
  listWorkspaceFiles: api.listWorkspaceFiles,
  getWorkspaceChanges: api.getWorkspaceChanges,
}))
vi.mock('@/views/coding/fileTree', () => ({
  buildFileTree: (files: string[]) => files.map(f => ({ name: f, path: f, type: 'file' })),
}))

beforeEach(() => vi.clearAllMocks())

describe('useWorkspaceFiles', () => {
  it('loads tree + changes for a wsId and exposes changed paths', async () => {
    api.listWorkspaceFiles.mockResolvedValue(['a.ts', 'b.ts'])
    api.getWorkspaceChanges.mockResolvedValue({ enabled: true, files: [{ path: 'a.ts', status: 'M' }] })
    const { useWorkspaceFiles } = await import('./useWorkspaceFiles')
    const wsId = ref<string | null>('1_abc')
    const wf = useWorkspaceFiles(wsId)
    await wf.load()
    expect(api.listWorkspaceFiles).toHaveBeenCalledWith('1_abc')
    expect(wf.tree.value).toHaveLength(2)
    expect(wf.changed.value.has('a.ts')).toBe(true)
  })
  it('clears when wsId is null and never calls the api', async () => {
    const { useWorkspaceFiles } = await import('./useWorkspaceFiles')
    const wf = useWorkspaceFiles(ref<string | null>(null))
    await wf.load()
    expect(api.listWorkspaceFiles).not.toHaveBeenCalled()
    expect(wf.tree.value).toEqual([])
  })
  it('select(path) updates selected', async () => {
    const { useWorkspaceFiles } = await import('./useWorkspaceFiles')
    const wf = useWorkspaceFiles(ref<string | null>('1_abc'))
    wf.select('a.ts')
    expect(wf.selected.value).toBe('a.ts')
  })
})
```

- [ ] **Step 2: 跑测看失败** → FAIL

- [ ] **Step 3: 实现**

```ts
// useWorkspaceFiles.ts
import { ref, computed, type Ref } from 'vue'
import { listWorkspaceFiles, getWorkspaceChanges } from '@/api/coding'
import { buildFileTree, type TreeNode } from '@/views/coding/fileTree'

export function useWorkspaceFiles(wsId: Ref<string | null>) {
  const tree = ref<TreeNode[]>([])
  const changes = ref<any>(null)
  const selected = ref<string | null>(null)
  const loading = ref(false)
  const error = ref('')

  const changed = computed<Set<string>>(() => {
    const files = changes.value?.enabled ? (changes.value.files || []) : []
    return new Set(files.map((f: any) => f.path))
  })

  async function load() {
    const id = wsId.value
    if (!id) { tree.value = []; changes.value = null; return }
    loading.value = true; error.value = ''
    try {
      const [files, ch] = await Promise.all([
        listWorkspaceFiles(id),
        getWorkspaceChanges(id).catch(() => null),
      ])
      tree.value = buildFileTree(files || [])
      changes.value = ch
    } catch (e: any) {
      error.value = e?.message || '加载工作区失败'
      tree.value = []
    } finally {
      loading.value = false
    }
  }

  function select(path: string) { selected.value = path }

  return { tree, changes, changed, selected, loading, error, load, select }
}
```

> 注:`listWorkspaceFiles`/`getWorkspaceChanges` 的确切导出形态实现前在 `@/api/coding` 核对(采集report列为 codingApi 成员或独立导出——以源码为准,必要时 `codingApi.listWorkspaceFiles`)。

- [ ] **Step 4: 跑测看通过** → PASS
- [ ] **Step 5: 提交** — `git commit -m "feat(workspace): useWorkspaceFiles composable(按 ws_id 拉树/改动/选中)"`

---

### Task 3: CodeWorkspacePanel.vue(文件树 + 代码/diff 查看器)

**Files:** Create `frontend/src/views/workspace/panels/CodeWorkspacePanel.vue` + `.spec.ts`

**Interfaces:**
- Consumes: `FileTree`(`@/views/coding/FileTree.vue`)、`CodeViewer`(`@/views/coding/CodeViewer.vue`)、`useWorkspaceFiles`(Task 2)、`Binding`。
- Props(PanelHost 注入):`{ binding: Binding; sessionId: number | null; artifact?: any }`。从 `binding.workspaceId` 取 wsId。
- 布局:左 FileTree(~40%)+ 右 CodeViewer(~60%),flex 行,height 100%。

- [ ] **Step 1: 写失败测试(?raw)**

```ts
// CodeWorkspacePanel.spec.ts
import { describe, expect, it } from 'vitest'
import src from './CodeWorkspacePanel.vue?raw'

describe('CodeWorkspacePanel', () => {
  it('composes FileTree + CodeViewer (复用, 不重写)', () => {
    expect(src).toContain('FileTree')
    expect(src).toContain('CodeViewer')
    expect(src).toContain('useWorkspaceFiles')
  })
  it('derives wsId from binding.workspaceId', () => {
    expect(src).toMatch(/binding[\s\S]*workspaceId/)
  })
  it('wires FileTree select → CodeViewer 当前文件', () => {
    expect(src).toContain('@select')
    expect(src).toContain(':file-path')
  })
})
```

- [ ] **Step 2: 跑测看失败** → FAIL

- [ ] **Step 3: 实现**(树左+查看器右;wsId 从 binding 取;FileTree select → selected → CodeViewer）

```vue
<template>
  <div class="code-ws-panel">
    <div class="cwp-tree">
      <FileTree
        :tree="wf.tree.value" :changed="wf.changed.value" :changes="wf.changes.value"
        :selected="wf.selected.value" :ws-id="wsId || ''"
        @select="wf.select" @select-line="(p) => wf.select(p.path)" />
    </div>
    <div class="cwp-view">
      <CodeViewer
        v-if="wf.selected.value && wsId"
        :ws-id="wsId" :file-path="wf.selected.value"
        :change="selectedChange" />
      <div v-else class="cwp-empty">选择左侧文件查看代码 / 改动</div>
    </div>
  </div>
</template>
<script setup lang="ts">
import { computed, watch, onMounted } from 'vue'
import FileTree from '@/views/coding/FileTree.vue'
import CodeViewer from '@/views/coding/CodeViewer.vue'
import { useWorkspaceFiles } from '../useWorkspaceFiles'
import type { Binding } from '../binding'
const props = defineProps<{ binding: Binding; sessionId?: number | null; artifact?: any }>()
const wsId = computed(() => (props.binding.kind === 'workspace' ? props.binding.workspaceId : null))
const wf = useWorkspaceFiles(wsId)
const selectedChange = computed(() => {
  const files = wf.changes.value?.files || []
  return files.find((f: any) => f.path === wf.selected.value) || null
})
watch(wsId, () => wf.load(), { immediate: false })
onMounted(() => wf.load())
</script>
<style scoped>
.code-ws-panel { display: flex; height: 100%; min-height: 0; }
.cwp-tree { width: 40%; min-width: 220px; max-width: 360px; border-right: 1px solid var(--line); overflow: auto; }
.cwp-view { flex: 1; min-width: 0; overflow: auto; }
.cwp-empty { padding: 24px; opacity: .5; }
</style>
```

> 注:`FileTree` props 在 `<script setup>` 里访问 `wf.tree.value`(模板里 Vue 自动解包,但本组件用 composable 返回的 ref,模板写 `.value` 显式更稳;实现时按 vue-tsc 是否报错调整为自动解包)。`CodeViewer` 的 `change` prop 类型 = `WorkspaceChangeEntry | null`,从 changes.files 找当前路径项。

- [ ] **Step 4: 跑测看通过 + 编译** — `npx vitest run src/views/workspace/panels/CodeWorkspacePanel.spec.ts && npm run build:nocheck` → PASS / 成功
- [ ] **Step 5: 提交** — `git commit -m "feat(workspace): CodeWorkspacePanel(文件树+代码/diff 查看器)"`

---

### Task 4: panels.ts 注册 code 面板(替换 stub-code)

**Files:** Modify `panels.ts`、`panels.spec.ts`

- [ ] **Step 1: 改测试(panels.spec.ts)**——把 `stub-code` 断言换成 `code`:

```ts
  it('registers the code panel for workspace binding (replaces stub)', () => {
    registerPhase1Panels()
    const none = buildToolMenuItems({ kind: 'none' })
    const byId = Object.fromEntries(none.map(i => [i.id, i.enabled]))
    expect('stub-code' in byId).toBe(false)
    expect(byId['code']).toBe(false)                 // none 绑定 → 代码面板灰
    const ws = buildToolMenuItems({ kind: 'workspace', workspaceId: 'w' })
    expect(ws.find(i => i.id === 'code')!.enabled).toBe(true)  // workspace → 亮
  })
```
（保留 idempotency 测试不变。）

- [ ] **Step 2: 跑测看失败** → FAIL（仍是 stub-code）

- [ ] **Step 3: 改 panels.ts**——把 stub-code 那条换成:

```ts
  // 代码面板(文件树 + 查看器): 仅 workspace 绑定可用
  registerPanel({ id: 'code', label: '代码', icon: 'coding', group: 'context',
    availableWhen: (b) => b.kind === 'workspace', component: defineAsyncComponent(() => import('./panels/CodeWorkspacePanel.vue')) })
```

- [ ] **Step 4: 跑测看通过 + 编译** — `npx vitest run src/views/workspace/panels.spec.ts && npm run build:nocheck` → PASS / 成功
- [ ] **Step 5: 提交** — `git commit -m "feat(workspace): 注册 code 面板替换 stub-code"`

---

### Task 5: WorkspaceShell 路由驱动 binding + viewContext + id 解析

**Files:** Modify `WorkspaceShell.vue`、`WorkspaceShell.spec.ts`

**Interfaces:** Consumes `routeToBinding`/`parseSidebarSelect`(Task 1)、`useRoute`。`currentBinding` 由 `route.params.id` 驱动;把 ws_id 作 `viewContext` 传 ChatPane。

- [ ] **Step 1: 改测试(WorkspaceShell.spec.ts)** 增断言:

```ts
  it('drives currentBinding from route.params.id (KeepAlive → watch)', () => {
    expect(src).toContain('useRoute')
    expect(src).toContain('routeToBinding')
    expect(src).toMatch(/watch\([\s\S]*route\.params\.id/)
  })
  it('feeds workspace context to ChatPane', () => {
    expect(src).toContain(':workspace-id')
  })
  it('parses sidebar select via parseSidebarSelect (workspace id 不被 Number 化)', () => {
    expect(src).toContain('parseSidebarSelect')
  })
```
（保留 Phase 1 的五区/registerPhase1Panels 断言。）

- [ ] **Step 2: 跑测看失败** → FAIL

- [ ] **Step 3: 改 WorkspaceShell.vue**:
  - import `useRoute` + `routeToBinding`/`parseSidebarSelect`。
  - `const route = useRoute()`;`currentBinding` 改成 `ref`,`watch(() => route.params.id, (id) => { currentBinding.value = routeToBinding(typeof id === 'string' ? id : Array.isArray(id) ? id[0] : '') }, { immediate: true })`。
  - `wsId` computed = `currentBinding.value.kind==='workspace' ? currentBinding.value.workspaceId : null`。
  - ChatPane 加 `:workspace-id="wsId"`。
  - `onSelect` 改用 `parseSidebarSelect`:workspace → `router.push('/workspace/'+encodeURIComponent(workspaceId))`;none → `currentSessionId.value = sessionId`(原逻辑)。
  - `wsSessions` 的 binding 暂仍 `{kind:'none'}`(会话列表 binding 持久化非本期;注释说明)。

- [ ] **Step 4: 跑测看通过 + 编译** → PASS / 成功
- [ ] **Step 5: 提交** — `git commit -m "feat(workspace): WorkspaceShell 路由驱动 workspace binding + 喂 ChatPane viewContext"`

---

### Task 6: ChatPane 接 workspaceId→viewContext + 去重复头部按钮

**Files:** Modify `ChatPane.vue`、`ChatPane.spec.ts`

**Interfaces:** 加 prop `workspaceId?: string | null`;构造 `viewContext` Ref 传给 `useAiChatSession`(workspace 态注入「在 workspace <ws_id> 做二次开发,代码工具用此 ws_id」)。去掉头部「历史(openDrawer)」「新建(onNewSession)」按钮 + 历史抽屉(外壳 SessionSidebar 已接管);产物按钮去掉(ToolMenu 接管);保留标题 + trace 按钮。

- [ ] **Step 1: 改测试(ChatPane.spec.ts)** 增/改:

```ts
  it('passes a workspace viewContext into useAiChatSession when bound', () => {
    expect(src).toContain('workspaceId')
    expect(src).toContain('viewContext')
  })
  it('drops shell-owned header buttons (history / new / artifact list)', () => {
    expect(src).not.toContain('openDrawer')
    expect(src).not.toContain('el-drawer')   // 历史抽屉移除
  })
```
（保留「复用 useAiChatSession/AgentConversation/UnifiedChatComposer」「appId ref」断言;`emit('open-artifact'` 仍在——产物事件仍抛给外壳,只是去掉 ChatPane 自己的产物计数按钮。）

- [ ] **Step 2: 跑测看失败** → FAIL

- [ ] **Step 3: 改 ChatPane.vue**:
  - `defineProps` 加 `workspaceId?: string | null`。
  - 构造 `const viewContext = computed(() => props.workspaceId ? '当前在代码工作区 ' + props.workspaceId + ' 做二次开发。需要读/改/运行代码时,workspace 工具一律用此 ws_id。' : null)`,传 `useAiChatSession({ appId, selectedLlmId, viewContext })`。
  - 删除头部 `cp-top-actions` 里的「产物计数按钮」「历史按钮」「新建按钮」(保留 trace 按钮);删除 `el-drawer` 历史抽屉 + `openDrawer`/`onSelectSession`/`onDeleteSession`/`onNewSession`/`drawerOpen`/`fmtSessionTime` 等仅服务该抽屉的代码。`@open-artifact` 透传保留(产物卡仍可点)。
  - 保留 `loadSessions`(WorkspaceShell 仍调它的 emit 链)。

- [ ] **Step 4: 跑测看通过 + 编译** — `npx vitest run src/views/workspace/ChatPane.spec.ts && npm run build:nocheck` → PASS / 成功
- [ ] **Step 5: 提交** — `git commit -m "feat(workspace): ChatPane 接 workspace viewContext + 去外壳已接管的重复按钮"`

---

### Task 7: 资产库入口改指 /workspace + 集成/绞杀验证

**Files:** Modify `frontend/src/views/WorkspaceCatalogPage.vue`;Create `frontend/src/views/workspace/phase2-strangler.spec.ts`

- [ ] **Step 1: 改 WorkspaceCatalogPage.openWorkspace / openLocalFolder** → push 到统一壳:

```ts
function openWorkspace(ws: WorkspaceInfo) {
  router.push('/workspace/' + encodeURIComponent(ws.id)).catch(() => {})
}
// openLocalFolder 内: const ws = await codingApi.openLocalFolder(picked)
//   router.push('/workspace/' + encodeURIComponent(ws.ws_id)).catch(() => {})
```

- [ ] **Step 2: 写绞杀守卫测试**

```ts
// phase2-strangler.spec.ts
import { describe, expect, it } from 'vitest'
import routerSrc from '@/router/index.ts?raw'
import catalogSrc from '@/views/WorkspaceCatalogPage.vue?raw'

describe('phase2 strangler', () => {
  it('keeps /coding route + CodingPage intact', () => {
    expect(routerSrc).toContain("'@/views/CodingPage.vue'")
  })
  it('catalog opens workspaces in the unified shell (/workspace), not /coding', () => {
    expect(catalogSrc).toContain("'/workspace/'")
    expect(catalogSrc).not.toMatch(/push\(\{\s*path:\s*'\/coding'/)
  })
})
```

- [ ] **Step 3: 跑测看通过** — `npx vitest run src/views/workspace/phase2-strangler.spec.ts` → PASS

- [ ] **Step 4: 全量 + 双产物**

Run: `cd frontend && npm test && npm run build:nocheck && npm run build:desktop`
Expected: vitest 全绿(workspace/* 全过,失败只可能是预存 useCodingPipeline 间歇);两 build ✓

- [ ] **Step 5: 提交** — `git commit -m "feat(workspace): 资产库 openWorkspace 改指 /workspace + Phase2 绞杀守卫"`

---

## Self-Review(已对 spec 核查)

- **spec 覆盖**:路由驱动 binding(T1,T5)/ workspace 文件加载(T2)/ 代码面板 树+查看器(T3,合并 spec 的 files+code-view)/ 注册替换 stub(T4)/ ws_id→viewContext 喂 run_agent(T5,T6)/ 去重复按钮(T6)/ 资产库改指(T7)/ 绞杀 /coding 不动(T7)。Preview/Terminal 明确不做(spec 非目标)。
- **placeholder 扫描**:纯模块/composable 给全码;组件给可执行模板 + ?raw 断言 + 复用源指针(FileTree/CodeViewer 契约来自采集)。两处 `>注` 是「实现前按源码核对 API 导出形态/vue-tsc 解包」的真实校验提示,非占位。
- **类型一致**:`Binding`/`bindingKindFromId`/`rawId`(Phase 1)→ workspaceRoute(T1)→ WorkspaceShell(T5)一致;`useWorkspaceFiles` 返回的 `tree/changed/changes/selected/load/select` 跨 T2→T3 一致;`code` 面板 id 跨 T3→T4→ToolMenu 一致;ChatPane `workspaceId`/`viewContext` 跨 T5→T6 一致。
- **已知 live-verify(非自动测)**:对话经 viewContext 真让 run_agent 代码工具落到该 ws_id(机制存在,效果需真机验,验收第 2 条)。
