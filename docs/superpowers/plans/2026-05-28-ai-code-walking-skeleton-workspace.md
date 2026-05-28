# AI Code 主工作台 Walking Skeleton 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 ai-code 应用的工作台从"单列聊天沙箱"换成 PRD ②「左对话 + 右 6 标签」主工作台外壳，进度/预览/产出三个标签真接现有单 agent。

**Architecture:** 纯前端改造，复用搁置的 `AICodingWorkspace.vue` 左右布局脚手架。左栏直接复用现有 `VibeChatPanel`（自带聊天 + 输入 + sessionStorage 首条 prompt 自动发送）；右栏重建 `WorkspaceTabs` 为 6 个顶部标签。进度标签读 `vibeCodingChatApi.getThread` 的 `tool_calls`+`todos`，预览标签走 `onlineCodingApi` runtime，产出标签嵌 `getIdeUrl` 的 code-server iframe。**后端零改动**——所有接口已存在。

**Tech Stack:** Vue 3 `<script setup>` + TypeScript + Element Plus + Vue Router + 现有 `@/api/onlineCoding` & `@/api/vibeCodingChat`。

**验证方式（重要）:** 本仓 **前端无任何测试框架**（无 vitest/jest、0 个 spec 文件）。所以**不写前端单测**——每个任务靠 **dev server + 浏览器**（preview_* 工具）验证。需要后端的任务（建工作区/getThread/ide-url/preview）**前提：后端在 `localhost:8003` 跑着**（用户用 `cd backend && ./venv/bin/python run.py` 启）。前端 dev server 用 `preview_start`（frontend 目录，`pnpm dev`）。

**铁律:** 完全不碰 apaas/低代码。本计划**移除**搁置壳里对 `SpecChatPanel`、`SpecDesignPanel`（`@/components/v3/*`）的引用，以及旧 `PreviewTab.vue`（静态 HTML 原型）/`api/prototype.ts` 的使用 —— 但不动这些文件本身（清理放最后一步、确认无其他引用再删）。

**关于"底部全宽输入框"（方案 B）:** 本骨架**直接复用 VibeChatPanel 自带的输入框**（在左栏底部，即布局 A）。全宽底部 composer（B）需要改 1543 行的 VibeChatPanel 暴露 send，**故意推迟到 ④预览"点元素改"那一刀一起做**。这是对 spec 的有意偏离，已在交接里记明。

---

## 文件结构

**新增：**
- `frontend/src/views/AiCodeEntryPage.vue` — 极简想法输入页（建 workspace + 种 prompt + 跳转）
- `frontend/src/components/ai-coding/ProgressTab.vue` — 进度（tool_calls + todos）
- `frontend/src/components/ai-coding/RuntimePreviewTab.vue` — 预览（dev server runtime iframe）
- `frontend/src/components/ai-coding/OutputTab.vue` — 产出（code-server IDE iframe）

**修改：**
- `frontend/src/views/AICodingWorkspace.vue` — 重写：按 workspaceId 定位、左 VibeChatPanel、右新 WorkspaceTabs
- `frontend/src/components/ai-coding/WorkspaceTabs.vue` — 重建：props 改 workspaceId、6 标签接新组件
- `frontend/src/router/index.ts` — 路由 `/ai-coding/new` + `/ai-coding/:wsId`
- `frontend/src/views/Apps.vue` — ai-code 点击改指新壳 + 加「新建 AI 应用」按钮

**复用（不改）：** `VibeChatPanel.vue`、`@/api/onlineCoding.ts`、`@/api/vibeCodingChat.ts`、`BuilderFrame.vue`。

---

## 已确认的接口契约（执行时照抄，勿猜）

```ts
// @/api/onlineCoding.ts → onlineCodingApi
createWorkspace({ task?: string|null, repo_url?: string|null }): Promise<OnlineCodingWorkspace>   // {id: "oc_...", ...}
getIdeUrl(workspaceId, theme?: 'light'|'dark'): Promise<{ ide_url: string }>
detectPreviewRuntime(workspaceId): Promise<OnlinePreviewProject>   // {supported, status, reason?...}
startPreviewRuntime(workspaceId): Promise<{project, runtime}>      // timeout 360s
getPreviewRuntimeStatus(workspaceId): Promise<OnlinePreviewRuntime> // {status, preview_url?...}
// status: 'unsupported'|'detected'|'installing'|'starting'|'running'|'stopped'|'error'

// @/api/vibeCodingChat.ts → vibeCodingChatApi
getThread(workspaceId): Promise<VibeChatThreadDetail>
// VibeChatThreadDetail = { thread: { todos: {id,content,status:'pending'|'in_progress'|'completed'}[] }, messages, tool_calls }
// VibeChatToolCall = { id, tool_name, args_json, result_text, status:'pending'|'running'|'success'|'error'|'aborted', duration_ms, ... }

// VibeChatPanel.vue
// props: { workspaceId: string, wide?: boolean }
// 挂载时自动读取 sessionStorage['vibe_pending_prompt_'+workspaceId] 并发送首条（无历史消息时）
```

---

### Task 1: 重写外壳 `AICodingWorkspace.vue` + 路由按 workspaceId

**Files:**
- Modify: `frontend/src/views/AICodingWorkspace.vue`（整文件重写，150 行 → 见下）
- Modify: `frontend/src/router/index.ts:231-235`

- [ ] **Step 1: 重写 `AICodingWorkspace.vue`**（左 VibeChatPanel + 右暂用占位，先验证聊天可用）

```vue
<template>
  <BuilderFrame :breadcrumbs="[{ label: 'AI Coding' }, { label: wsId || '—' }]">
    <div v-if="!wsId" class="aic-empty">缺少工作区 ID（请从应用列表进入或新建 AI 应用）</div>
    <div v-else class="aic-shell">
      <section class="aic-chat" :style="{ flexBasis: chatWidth + 'px' }">
        <VibeChatPanel ref="chatRef" :workspace-id="wsId" />
        <div class="aic-resizer" @mousedown="startResize"></div>
      </section>
      <section class="aic-work">
        <div class="aic-work-placeholder">右侧 6 标签工作区（Task 2 接入）</div>
      </section>
    </div>
  </BuilderFrame>
</template>

<script setup lang="ts">
import { ref, computed, onUnmounted } from 'vue'
import { useRoute } from 'vue-router'
import BuilderFrame from '@/components/BuilderFrame.vue'
import VibeChatPanel from '@/components/vibe-coding/VibeChatPanel.vue'

const route = useRoute()
const wsId = computed<string>(() => String(route.params.wsId || ''))
const chatRef = ref<any>(null)

const chatWidth = ref(440)
let cleanupResize: (() => void) | null = null
function startResize(e: MouseEvent) {
  e.preventDefault()
  document.body.style.userSelect = 'none'
  document.body.style.cursor = 'ew-resize'
  const startX = e.clientX
  const startW = chatWidth.value
  const onMove = (ev: MouseEvent) => {
    chatWidth.value = Math.max(340, Math.min(720, startW + ev.clientX - startX))
  }
  const onUp = () => {
    window.removeEventListener('mousemove', onMove)
    window.removeEventListener('mouseup', onUp)
    document.body.style.userSelect = ''
    document.body.style.cursor = ''
    cleanupResize = null
  }
  cleanupResize = onUp
  window.addEventListener('mousemove', onMove)
  window.addEventListener('mouseup', onUp)
}
onUnmounted(() => cleanupResize?.())
</script>

<style scoped>
.aic-shell { display: flex; height: 100%; min-height: 0; flex: 1 1 auto; overflow: hidden; }
.aic-chat { position: relative; flex: 0 0 auto; border-right: 1px solid var(--line); display: flex; flex-direction: column; min-width: 0; overflow: hidden; }
.aic-resizer { position: absolute; top: 0; right: -3px; width: 6px; height: 100%; cursor: col-resize; z-index: 10; }
.aic-resizer:hover { background: var(--brand-soft); }
.aic-work { flex: 1 1 auto; min-width: 0; overflow: hidden; display: flex; flex-direction: column; }
.aic-work-placeholder { margin: auto; color: var(--text-4); font-size: 14px; }
.aic-empty { padding: 40px; color: var(--text-3); font-size: 14px; }
</style>
```

- [ ] **Step 2: 路由改成按 wsId（在 `router/index.ts` 把旧 `/ai-coding/:appId?` 那条替换）**

把 `frontend/src/router/index.ts:231-235` 原来的：
```ts
{
  path: '/ai-coding/:appId?',
  name: 'AICoding',
  component: () => import('@/views/AICodingWorkspace.vue'),
  meta: { requiresAuth: true },
},
```
替换为（注意 `/ai-coding/new` 必须在 `:wsId` 之前，否则会被当成 wsId="new"）：
```ts
{
  path: '/ai-coding/new',
  name: 'AICodingNew',
  component: () => import('@/views/AiCodeEntryPage.vue'),
  meta: { requiresAuth: true },
},
{
  path: '/ai-coding/:wsId',
  name: 'AICodingWorkspace',
  component: () => import('@/views/AICodingWorkspace.vue'),
  meta: { requiresAuth: true, navExpanded: true },
},
```
> `AiCodeEntryPage.vue` 在 Task 6 才创建。本任务先把 `/ai-coding/new` 这条**临时注释掉**，只留 `/ai-coding/:wsId`，到 Task 6 再放开（避免 build 时引用不存在文件）。

- [ ] **Step 3: 浏览器验证**

前提：后端在跑 + 有一个现成 ai-code 工作区 id（如截图里的 `oc_ff81a7fb303b`）。
- `preview_start`（frontend，`pnpm dev`），`preview_eval` 导航到 `/ai-coding/oc_ff81a7fb303b`
- `preview_snapshot`：左侧应渲染出 VibeChatPanel（有历史消息/输入框），右侧显示占位文字
- `preview_console_logs`：无报错
- 拖左右分隔条，宽度在 340–720 间变化

- [ ] **Step 4: Commit**

```bash
git add frontend/src/views/AICodingWorkspace.vue frontend/src/router/index.ts
git commit -m "feat(ai-coding): 重写主工作台外壳 — 按 workspaceId + 复用 VibeChatPanel 左栏"
```

---

### Task 2: 重建 `WorkspaceTabs.vue`（6 标签 + 接入外壳）

**Files:**
- Modify: `frontend/src/components/ai-coding/WorkspaceTabs.vue`（整文件重写）
- Modify: `frontend/src/views/AICodingWorkspace.vue`（右栏占位换成 WorkspaceTabs）

- [ ] **Step 1: 重写 `WorkspaceTabs.vue`**（先全部占位，Task 3-5 再填 progress/preview/output）

```vue
<template>
  <div class="wt-root">
    <nav class="wt-tabs">
      <button
        v-for="t in tabs" :key="t.key"
        class="wt-tab" :class="{ active: active === t.key }"
        @click="active = t.key"
      >{{ t.label }}</button>
    </nav>
    <div class="wt-body">
      <div class="wt-placeholder">「{{ activeLabel }}」建设中（后续切片接入）</div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'
defineProps<{ workspaceId: string }>()
const tabs = [
  { key: 'requirement', label: '需求' },
  { key: 'progress',    label: '进度' },
  { key: 'preview',     label: '预览' },
  { key: 'output',      label: '产出' },
  { key: 'tools',       label: '工具链' },
  { key: 'observe',     label: '可观测' },
]
const active = ref('progress')
const activeLabel = computed(() => tabs.find(t => t.key === active.value)?.label ?? '')
</script>

<style scoped>
.wt-root { display: flex; flex-direction: column; height: 100%; }
.wt-tabs { display: flex; gap: 4px; padding: 8px; border-bottom: 1px solid var(--line); flex-shrink: 0; overflow-x: auto; }
.wt-tab { border: 0; background: transparent; padding: 8px 14px; border-radius: 8px; color: var(--text-3); cursor: pointer; font-size: 13px; white-space: nowrap; transition: background .15s, color .15s; }
.wt-tab:hover { background: var(--surface-3); color: var(--text-2); }
.wt-tab.active { background: var(--brand-soft); color: var(--brand); font-weight: 600; }
.wt-body { flex: 1 1 auto; min-height: 0; overflow: auto; }
.wt-placeholder { padding: 48px; text-align: center; color: var(--text-4); }
</style>
```

- [ ] **Step 2: 外壳右栏接入** —— 在 `AICodingWorkspace.vue` 顶部加 `import WorkspaceTabs from '@/components/ai-coding/WorkspaceTabs.vue'`，把 `.aic-work` 里的占位 div 换成：
```html
<WorkspaceTabs :workspace-id="wsId" />
```

- [ ] **Step 3: 浏览器验证** —— 导航 `/ai-coding/oc_ff81a7fb303b`，右侧出现 6 个标签，默认停在「进度」，点击切换显示对应"建设中"占位，无 console 报错。

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/ai-coding/WorkspaceTabs.vue frontend/src/views/AICodingWorkspace.vue
git commit -m "feat(ai-coding): 重建 WorkspaceTabs 6 标签骨架 + 接入外壳"
```

---

### Task 3: 进度标签 `ProgressTab.vue`（真接 tool_calls + todos）

**Files:**
- Create: `frontend/src/components/ai-coding/ProgressTab.vue`
- Modify: `frontend/src/components/ai-coding/WorkspaceTabs.vue`（progress 分支接入）

- [ ] **Step 1: 创建 `ProgressTab.vue`**

```vue
<template>
  <div class="pg">
    <div class="pg-head">
      <span class="pg-title">执行进度</span>
      <button class="pg-refresh" @click="refresh">刷新</button>
    </div>

    <div v-if="todos.length" class="pg-section">
      <div class="pg-label">任务清单</div>
      <div v-for="t in todos" :key="t.id" class="pg-todo" :class="t.status">
        <span class="pg-ic">{{ todoIcon(t.status) }}</span><span>{{ t.content }}</span>
      </div>
    </div>

    <div v-if="toolCalls.length" class="pg-section">
      <div class="pg-label">执行步骤</div>
      <ol class="pg-steps">
        <li v-for="tc in toolCalls" :key="tc.id" class="pg-step" :class="tc.status">
          <span class="pg-ic">{{ toolIcon(tc.status) }}</span>
          <code class="pg-tool">{{ tc.tool_name }}</code>
          <span class="pg-arg">{{ argSummary(tc.args_json) }}</span>
          <span v-if="tc.duration_ms != null" class="pg-dur">{{ tc.duration_ms }}ms</span>
        </li>
      </ol>
    </div>

    <div v-if="!toolCalls.length && !todos.length" class="pg-empty">
      还没有执行记录 —— 去左边跟 AI 说说要做啥
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, onUnmounted } from 'vue'
import { vibeCodingChatApi, type VibeChatToolCall } from '@/api/vibeCodingChat'

const props = defineProps<{ workspaceId: string }>()
const toolCalls = ref<VibeChatToolCall[]>([])
const todos = ref<Array<{ id: string; content: string; status: string }>>([])
let timer: ReturnType<typeof setInterval> | null = null

async function refresh() {
  if (!props.workspaceId) return
  try {
    const d = await vibeCodingChatApi.getThread(props.workspaceId)
    toolCalls.value = d.tool_calls || []
    todos.value = (d.thread?.todos as any) || []
  } catch (_) { /* 静默：工作区可能还没线程 */ }
}
function busy() {
  return toolCalls.value.some(t => t.status === 'running' || t.status === 'pending')
    || todos.value.some(t => t.status === 'in_progress' || t.status === 'pending')
}
onMounted(() => {
  refresh()
  timer = setInterval(() => { if (busy()) refresh() }, 2000)
})
onUnmounted(() => { if (timer) clearInterval(timer) })

function toolIcon(s: string) { return ({ success: '✓', error: '✗', running: '⟳', pending: '○', aborted: '⊘' } as any)[s] || '•' }
function todoIcon(s: string) { return ({ completed: '✓', in_progress: '⟳', pending: '○' } as any)[s] || '•' }
function argSummary(a: Record<string, any>) {
  const s = JSON.stringify(a || {})
  return s === '{}' ? '' : (s.length > 64 ? s.slice(0, 64) + '…' : s)
}
</script>

<style scoped>
.pg { padding: 16px; display: flex; flex-direction: column; gap: 16px; }
.pg-head { display: flex; align-items: center; justify-content: space-between; }
.pg-title { font-size: 14px; font-weight: 600; color: var(--text-2); }
.pg-refresh { border: 1px solid var(--line); background: transparent; color: var(--text-3); border-radius: 6px; padding: 3px 10px; font-size: 12px; cursor: pointer; }
.pg-refresh:hover { background: var(--surface-3); }
.pg-label { font-size: 11px; text-transform: uppercase; letter-spacing: .04em; color: var(--text-4); margin-bottom: 8px; }
.pg-todo { display: flex; gap: 8px; align-items: center; padding: 5px 0; font-size: 13px; color: var(--text-2); }
.pg-todo.completed { color: var(--text-4); text-decoration: line-through; }
.pg-todo.in_progress { color: var(--brand); }
.pg-steps { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 6px; }
.pg-step { display: flex; gap: 8px; align-items: baseline; font-size: 13px; padding: 6px 8px; border-radius: 6px; background: var(--surface-3); }
.pg-step.running { background: var(--brand-soft); }
.pg-step.error { background: rgba(220, 80, 80, .12); }
.pg-ic { flex: 0 0 auto; width: 14px; text-align: center; }
.pg-tool { font-family: monospace; color: var(--text-2); }
.pg-arg { color: var(--text-4); font-size: 12px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.pg-dur { margin-left: auto; color: var(--text-4); font-size: 11px; }
.pg-empty { padding: 48px; text-align: center; color: var(--text-4); }
</style>
```

- [ ] **Step 2: WorkspaceTabs 接入** —— `import ProgressTab from './ProgressTab.vue'`，把 `.wt-body` 改成：
```html
<div class="wt-body">
  <ProgressTab v-if="active === 'progress'" :workspace-id="workspaceId" />
  <div v-else class="wt-placeholder">「{{ activeLabel }}」建设中（后续切片接入）</div>
</div>
```

- [ ] **Step 3: 浏览器验证** —— 在左栏跟 AI 发一句"做个待办列表"，切到「进度」：应**实时滚出** tool_call 步骤（read/write/command 带 ✓/⟳ 状态）+ todos。`preview_screenshot` 留证。每 2s 自动刷新（busy 时）。

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/ai-coding/ProgressTab.vue frontend/src/components/ai-coding/WorkspaceTabs.vue
git commit -m "feat(ai-coding): 进度标签 — 真接 getThread 的 tool_calls + todos"
```

---

### Task 4: 预览标签 `RuntimePreviewTab.vue`（dev server iframe）

**Files:**
- Create: `frontend/src/components/ai-coding/RuntimePreviewTab.vue`
- Modify: `frontend/src/components/ai-coding/WorkspaceTabs.vue`（preview 分支接入）

- [ ] **Step 1: 创建 `RuntimePreviewTab.vue`**

```vue
<template>
  <div class="rp">
    <div class="rp-bar">
      <span class="rp-status" :class="runtime?.status">{{ statusLabel }}</span>
      <button class="rp-btn" :disabled="starting" @click="onStart">
        {{ starting ? '启动中…' : (runtime?.preview_url ? '重启预览' : '启动预览') }}
      </button>
      <a v-if="runtime?.preview_url" class="rp-open" :href="runtime.preview_url" target="_blank">新窗口打开 ↗</a>
    </div>
    <iframe v-if="runtime?.preview_url" class="rp-frame" :src="runtime.preview_url"></iframe>
    <div v-else class="rp-empty">
      <p v-if="project && !project.supported">该工作区暂不支持自动预览：{{ project.reason || '未检测到可运行项目' }}</p>
      <p v-else>点上面「启动预览」跑起 dev server</p>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { onlineCodingApi, type OnlinePreviewProject, type OnlinePreviewRuntime } from '@/api/onlineCoding'

const props = defineProps<{ workspaceId: string }>()
const project = ref<OnlinePreviewProject | null>(null)
const runtime = ref<OnlinePreviewRuntime | null>(null)
const starting = ref(false)

const statusLabel = computed(() => ({
  unsupported: '不支持', detected: '已检测', installing: '安装依赖中',
  starting: '启动中', running: '运行中', stopped: '已停止', error: '出错',
} as any)[runtime.value?.status || project.value?.status || ''] || '未知')

async function detect() {
  try { project.value = await onlineCodingApi.detectPreviewRuntime(props.workspaceId) } catch (_) {}
}
async function pollStatus() {
  try {
    runtime.value = await onlineCodingApi.getPreviewRuntimeStatus(props.workspaceId)
    if (runtime.value?.preview_url) return
  } catch (_) {}
}
async function onStart() {
  starting.value = true
  try {
    const r = await onlineCodingApi.startPreviewRuntime(props.workspaceId)
    runtime.value = r.runtime
    project.value = r.project
    if (!r.runtime?.preview_url) ElMessage.info('已触发启动，稍后点状态刷新或重启')
  } catch (e: any) {
    ElMessage.error('启动预览失败：' + (e?.message || e))
  } finally {
    starting.value = false
  }
}
onMounted(async () => { await detect(); await pollStatus() })
</script>

<style scoped>
.rp { display: flex; flex-direction: column; height: 100%; }
.rp-bar { display: flex; align-items: center; gap: 12px; padding: 8px 12px; border-bottom: 1px solid var(--line); flex-shrink: 0; }
.rp-status { font-size: 12px; color: var(--text-3); padding: 2px 8px; border-radius: 10px; background: var(--surface-3); }
.rp-status.running { color: #16a34a; }
.rp-status.error { color: #dc4040; }
.rp-btn { border: 1px solid var(--brand); background: var(--brand-soft); color: var(--brand); border-radius: 6px; padding: 4px 12px; font-size: 13px; cursor: pointer; }
.rp-btn:disabled { opacity: .6; cursor: default; }
.rp-open { margin-left: auto; font-size: 12px; color: var(--text-3); }
.rp-frame { flex: 1 1 auto; width: 100%; border: 0; background: #fff; }
.rp-empty { flex: 1 1 auto; display: flex; align-items: center; justify-content: center; color: var(--text-4); padding: 24px; text-align: center; }
</style>
```

- [ ] **Step 2: WorkspaceTabs 接入** —— `import RuntimePreviewTab from './RuntimePreviewTab.vue'`，在 progress 分支后加：
```html
<RuntimePreviewTab v-else-if="active === 'preview'" :workspace-id="workspaceId" />
```

- [ ] **Step 3: 浏览器验证** —— 选一个已生成过代码的工作区，切「预览」→ 点「启动预览」→ 等 runtime running → iframe 出现跑起来的应用。`preview_screenshot` 留证。（启动慢、360s 超时属正常。）

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/ai-coding/RuntimePreviewTab.vue frontend/src/components/ai-coding/WorkspaceTabs.vue
git commit -m "feat(ai-coding): 预览标签 — 复用 online-coding runtime 跑 dev server"
```

---

### Task 5: 产出标签 `OutputTab.vue`（code-server IDE iframe）

**Files:**
- Create: `frontend/src/components/ai-coding/OutputTab.vue`
- Modify: `frontend/src/components/ai-coding/WorkspaceTabs.vue`（output 分支接入）

- [ ] **Step 1: 创建 `OutputTab.vue`**

```vue
<template>
  <div class="ot">
    <div v-if="loading" class="ot-empty">加载代码编辑器…</div>
    <div v-else-if="error" class="ot-empty">打开 IDE 失败：{{ error }} <button class="ot-retry" @click="load">重试</button></div>
    <iframe v-else-if="ideUrl" :key="ideUrl" class="ot-frame" :src="ideUrl"></iframe>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { onlineCodingApi } from '@/api/onlineCoding'
import { useThemeStore } from '@/stores/theme'

const props = defineProps<{ workspaceId: string }>()
const themeStore = useThemeStore()
const ideUrl = ref('')
const loading = ref(false)
const error = ref('')

async function load() {
  loading.value = true; error.value = ''
  try {
    const r = await onlineCodingApi.getIdeUrl(props.workspaceId, themeStore.isDark ? 'dark' : 'light')
    ideUrl.value = r.ide_url
  } catch (e: any) {
    error.value = e?.message || String(e)
  } finally {
    loading.value = false
  }
}
onMounted(load)
</script>

<style scoped>
.ot { height: 100%; display: flex; }
.ot-frame { flex: 1 1 auto; width: 100%; border: 0; background: #1e1e1e; }
.ot-empty { margin: auto; color: var(--text-4); font-size: 14px; }
.ot-retry { margin-left: 8px; border: 1px solid var(--line); background: transparent; color: var(--text-3); border-radius: 6px; padding: 2px 10px; cursor: pointer; }
</style>
```

- [ ] **Step 2: WorkspaceTabs 接入** —— `import OutputTab from './OutputTab.vue'`，在 preview 分支后加：
```html
<OutputTab v-else-if="active === 'output'" :workspace-id="workspaceId" />
```

- [ ] **Step 3: 浏览器验证** —— 切「产出」→ code-server IDE iframe 加载出工作区文件树。`preview_screenshot` 留证。

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/ai-coding/OutputTab.vue frontend/src/components/ai-coding/WorkspaceTabs.vue
git commit -m "feat(ai-coding): 产出标签 — 嵌 code-server IDE"
```

---

### Task 6: 想法入口页 `AiCodeEntryPage.vue` + 入口按钮

**Files:**
- Create: `frontend/src/views/AiCodeEntryPage.vue`
- Modify: `frontend/src/router/index.ts`（放开 Task 1 注释掉的 `/ai-coding/new`）
- Modify: `frontend/src/views/Apps.vue`（工具栏加「新建 AI 应用」按钮）

- [ ] **Step 1: 创建 `AiCodeEntryPage.vue`**

```vue
<template>
  <BuilderFrame :breadcrumbs="[{ label: 'AI Coding' }, { label: '新建' }]">
    <div class="ace">
      <h1 class="ace-title">想做个什么应用？</h1>
      <p class="ace-sub">一句话描述你的想法，AI 帮你从零搭起来。</p>
      <textarea
        v-model="idea" class="ace-input" rows="4" :disabled="creating"
        placeholder="例如：做一个报销系统，员工提交报销单、主管审批、财务打款，带统计看板"
        @keydown.meta.enter="onCreate" @keydown.ctrl.enter="onCreate"
      ></textarea>
      <div class="ace-actions">
        <button class="ace-go" :disabled="!idea.trim() || creating" @click="onCreate">
          {{ creating ? '创建中…' : '开始构建 →' }}
        </button>
        <span class="ace-hint">⌘/Ctrl + Enter</span>
      </div>
    </div>
  </BuilderFrame>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import BuilderFrame from '@/components/BuilderFrame.vue'
import { onlineCodingApi } from '@/api/onlineCoding'

const router = useRouter()
const idea = ref('')
const creating = ref(false)

async function onCreate() {
  const task = idea.value.trim()
  if (!task || creating.value) return
  creating.value = true
  try {
    const ws = await onlineCodingApi.createWorkspace({ task })
    // 种首条 prompt：VibeChatPanel 挂载时自动读 sessionStorage 并发送
    sessionStorage.setItem(`vibe_pending_prompt_${ws.id}`, task)
    router.push(`/ai-coding/${ws.id}`)
  } catch (e: any) {
    ElMessage.error('创建失败：' + (e?.message || e))
    creating.value = false
  }
}
</script>

<style scoped>
.ace { max-width: 680px; margin: 8vh auto 0; padding: 0 24px; display: flex; flex-direction: column; }
.ace-title { font-size: 28px; font-weight: 700; color: var(--text-1); margin: 0 0 8px; }
.ace-sub { color: var(--text-3); margin: 0 0 24px; }
.ace-input { width: 100%; border: 1px solid var(--line); border-radius: 12px; padding: 14px 16px; font-size: 15px; line-height: 1.6; background: var(--surface-2); color: var(--text-1); resize: vertical; font-family: inherit; }
.ace-input:focus { outline: none; border-color: var(--brand); }
.ace-actions { display: flex; align-items: center; gap: 12px; margin-top: 16px; }
.ace-go { border: 0; background: var(--brand); color: #fff; border-radius: 10px; padding: 10px 22px; font-size: 15px; font-weight: 600; cursor: pointer; }
.ace-go:disabled { opacity: .5; cursor: default; }
.ace-hint { color: var(--text-4); font-size: 12px; }
</style>
```
> 注：`createWorkspace` 后端会自动 `_register_ai_code_app` 登记 ai-code Application，无需前端额外建应用。`--text-1`/`--surface-2` 若本仓无该变量，回退用 `--text-2`/`--surface-3`（执行时 grep `:root` 确认变量名）。

- [ ] **Step 2: 放开路由** —— 取消 Task 1 里 `/ai-coding/new` 那条的注释。

- [ ] **Step 3: Apps.vue 加入口按钮** —— 在工具栏（`Apps.vue:33` 那个 `apps-toolbar-action` 附近）加一个按钮：
```html
<button class="btn btn-primary apps-toolbar-action" type="button" @click="router.push('/ai-coding/new')">+ 新建 AI 应用</button>
```

- [ ] **Step 4: 浏览器验证** —— 访问 `/ai-coding/new` → 输入"做个待办应用" → 点「开始构建」→ 应跳到 `/ai-coding/oc_xxx` 新壳，且左栏 VibeChatPanel **自动发出**这句话、「进度」开始滚动。`preview_screenshot` 留证。

- [ ] **Step 5: Commit**

```bash
git add frontend/src/views/AiCodeEntryPage.vue frontend/src/router/index.ts frontend/src/views/Apps.vue
git commit -m "feat(ai-coding): 极简想法入口页 — 建工作区+种首条 prompt 自动发送"
```

---

### Task 7: 应用列表点 ai-code → 进新壳

**Files:**
- Modify: `frontend/src/views/Apps.vue:420-431`

- [ ] **Step 1: 改分流目标** —— 把 ai-code 分支里的 `/vibe-coding/workspaces/${wid}` 改为 `/ai-coding/${wid}`。两处（`tabsStore.openTab({ path })` 和 `router.push`）都改：
```ts
if (app.app_type === 'ai-code' && app.source_workspace_id) {
  const wid = app.source_workspace_id
  tabsStore.openTab({
    // ...其余字段保持不变...
    path: `/ai-coding/${wid}`,
  })
  router.push(`/ai-coding/${wid}`)
  return
}
```
> 保留 `/vibe-coding/workspaces/:id`（OnlineCodingWorkspacePage）路由作为过渡 fallback，不删。

- [ ] **Step 2: 浏览器验证** —— 应用列表点一个 ai-code 应用（如 CRM/报销系统）→ 落到新 6 标签工作台（不再是旧沙箱）。`preview_screenshot` 留证。

- [ ] **Step 3: Commit**

```bash
git add frontend/src/views/Apps.vue
git commit -m "feat(ai-coding): 应用列表点 ai-code 应用 → 进新 6 标签工作台"
```

---

### Task 8: 端到端验证 + 清理

**Files:**
- 可能 Delete: `frontend/src/components/ai-coding/PreviewTab.vue`、`frontend/src/api/prototype.ts`（旧静态 HTML 原型，确认无引用再删）

- [ ] **Step 1: 端到端走查（浏览器）** —— 后端在跑前提下：
  1. `/ai-coding/new` 输入想法 → 进新壳
  2. 左栏 AI 自动接到首条、开始干活
  3. 「进度」实时滚 tool_calls + todos
  4. AI 干完 → 「预览」启动 → 看到跑起来的应用
  5. 「产出」打开 IDE 看代码
  6. 回应用列表点该 ai-code 应用 → 重新进同一新壳
  每步 `preview_screenshot` + `preview_console_logs` 确认无报错。

- [ ] **Step 2: 清理孤儿** —— `grep -rn "ai-coding/PreviewTab\|api/prototype\|components/v3/SpecChatPanel" frontend/src`：
  - 若 `PreviewTab.vue` / `prototype.ts` 已无任何引用 → 删除（含后端 `routes/applications/prototype.py` + `models/app_prototype.py` 是否还被 mount，谨慎，单独确认）。
  - `SpecChatPanel`/`SpecDesignPanel`（低代码）应只剩低代码侧引用 → **不动**。

- [ ] **Step 3: Commit**

```bash
git add -A
git commit -m "chore(ai-coding): 清理 walking skeleton 遗留孤儿 + 端到端验证通过"
```

---

## 自查（Self-Review）

**Spec 覆盖：**
- ① 想法入口 → Task 6 ✓
- ② 6 标签外壳 → Task 1+2 ✓
- ⑤ 进度（真事件）→ Task 3 ✓
- ④ 预览（复用）→ Task 4 ✓
- ⑥ 产出（IDE）→ Task 5 ✓
- ③需求/⑦工具链/⑧可观测 占位 → Task 2（默认占位）✓
- ai-code 应用进新壳 → Task 7 ✓
- 后端零改动 → 全程无 backend 任务 ✓
- 铁律不碰低代码 → 移除 v3/Spec* 引用，Task 8 确认 ✓

**偏离 spec（已记明）：** 底部全宽输入框（B）推迟 —— 骨架复用 VibeChatPanel 自带输入（A），随 ④ 深做时再做 B。

**类型一致性：** `workspaceId: string` 全程一致；`VibeChatThreadDetail.thread.todos` / `.tool_calls` 字段名对齐 `@/api/vibeCodingChat.ts`；`onlineCodingApi` 方法名对齐 `@/api/onlineCoding.ts`。

**无占位符：** 所有组件给了完整代码；CSS 变量名留了"执行时 grep 确认"的兜底说明（`--text-1`/`--surface-2`）。
