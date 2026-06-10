# 原生代码工作区 Phase 1 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 CodingPage 里用原生「文件树 + 只读代码查看器」替换 code-server IDE iframe 抽屉,代码改动经现有 coding agent 对话完成,改动文件在树上标记并就地显示红绿 diff。

**Architecture:** 纯前端。复用后端已有 `/coding/workspace/{ws_id}/files`(扁平路径数组)、`/coding/workspace/{ws_id}/file`(`{path,content}`)、`FileCard.vue`(红绿 diff)、`useStreamMessages` 的 `streamMessages`(带 file_edit 的 oldContent/fileContent)。新增:2 个纯逻辑模块(建树 / 改动聚合,vitest TDD)、2 个 Vue 组件(FileTree / CodeViewer)、2 个 api 函数,并改 CodingPage 挂载点。Shiki 做只读高亮。

**Tech Stack:** Vue 3 + Vite + TypeScript + axios(`@/utils/request`)、Shiki(新增)、vitest(新增,仅测纯逻辑)、复用 Element Plus / 现有 composable。

**对应 spec:** `docs/superpowers/specs/2026-06-10-native-code-workspace-design.md`(Phase 1)。本计划不含 Phase 2 确认门,也不含 code-server 清理(均为后续独立计划)。

---

### Task 1: 加 vitest + Shiki 依赖

**Files:**
- Modify: `frontend/package.json`
- Create: `frontend/vitest.config.ts`

- [ ] **Step 1: 安装依赖**

Run:
```bash
cd "frontend" && npm i -D vitest && npm i shiki
```
Expected: 安装成功,`package.json` 出现 `vitest`(devDeps)与 `shiki`(deps)。

- [ ] **Step 2: 加 test 脚本**

Modify `frontend/package.json` 的 `scripts`,加一行(放在 `preview` 后):
```json
"test": "vitest run"
```

- [ ] **Step 3: 写 vitest 配置**

Create `frontend/vitest.config.ts`:
```ts
import { defineConfig } from 'vitest/config'
import { resolve } from 'path'

export default defineConfig({
  resolve: {
    alias: { '@': resolve(__dirname, 'src') },
  },
  test: {
    include: ['src/**/*.spec.ts'],
    environment: 'node',
  },
})
```

- [ ] **Step 4: 验证 vitest 能跑(无测试时不报错)**

Run: `cd "frontend" && npm run test`
Expected: 退出码 0,输出 "No test files found" 一类提示(无 `.spec.ts` 时 vitest run 视作通过)。

- [ ] **Step 5: Commit**
```bash
git add frontend/package.json frontend/package-lock.json frontend/vitest.config.ts
git commit -m "chore(frontend): 加 vitest(纯逻辑测试) + shiki(只读高亮) 依赖"
```

---

### Task 2: 文件树构建(纯逻辑,TDD)

把后端返回的扁平相对路径数组建成嵌套树。纯函数,先写测试。

**Files:**
- Create: `frontend/src/views/coding/fileTree.ts`
- Test: `frontend/src/views/coding/fileTree.spec.ts`

- [ ] **Step 1: 写失败测试**

Create `frontend/src/views/coding/fileTree.spec.ts`:
```ts
import { describe, it, expect } from 'vitest'
import { buildFileTree } from './fileTree'

describe('buildFileTree', () => {
  it('把扁平路径建成嵌套树,目录在前、同级按名排序', () => {
    const tree = buildFileTree(['src/index.vue', 'src/api.ts', 'package.json'])
    expect(tree.map(n => n.name)).toEqual(['src', 'package.json'])
    const src = tree[0]
    expect(src.isDir).toBe(true)
    expect(src.path).toBe('src')
    expect(src.children!.map(n => n.name)).toEqual(['api.ts', 'index.vue'])
    expect(src.children!.every(n => !n.isDir)).toBe(true)
    expect(src.children![0].path).toBe('src/api.ts')
  })

  it('支持多级嵌套目录', () => {
    const tree = buildFileTree(['a/b/c.ts', 'a/d.ts'])
    const a = tree[0]
    expect(a.children!.map(n => n.name)).toEqual(['b', 'd.ts'])
    expect(a.children![0].children![0].path).toBe('a/b/c.ts')
  })

  it('空数组返回空树', () => {
    expect(buildFileTree([])).toEqual([])
  })
})
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd "frontend" && npx vitest run src/views/coding/fileTree.spec.ts`
Expected: FAIL,报 `buildFileTree` 不存在 / 模块找不到。

- [ ] **Step 3: 写实现**

Create `frontend/src/views/coding/fileTree.ts`:
```ts
export interface TreeNode {
  name: string
  path: string
  isDir: boolean
  children?: TreeNode[]
}

export function buildFileTree(paths: string[]): TreeNode[] {
  const root: TreeNode[] = []
  for (const full of paths) {
    const parts = full.split('/').filter(Boolean)
    let level = root
    let acc = ''
    parts.forEach((part, i) => {
      acc = acc ? `${acc}/${part}` : part
      const isDir = i < parts.length - 1
      let node = level.find(n => n.name === part && n.isDir === isDir)
      if (!node) {
        node = { name: part, path: acc, isDir }
        if (isDir) node.children = []
        level.push(node)
      }
      if (isDir) level = node.children!
    })
  }
  sortTree(root)
  return root
}

function sortTree(nodes: TreeNode[]): void {
  nodes.sort((a, b) => {
    if (a.isDir !== b.isDir) return a.isDir ? -1 : 1
    return a.name.localeCompare(b.name)
  })
  for (const n of nodes) if (n.children) sortTree(n.children)
}
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd "frontend" && npx vitest run src/views/coding/fileTree.spec.ts`
Expected: PASS,3 个用例全绿。

- [ ] **Step 5: Commit**
```bash
git add frontend/src/views/coding/fileTree.ts frontend/src/views/coding/fileTree.spec.ts
git commit -m "feat(coding): 扁平路径建文件树纯函数 buildFileTree + 测试"
```

---

### Task 3: 改动文件聚合(纯逻辑,TDD)

从 `streamMessages` 里收集 agent 本轮改过哪些文件、各自的改前/改后内容,供文件树标记 + 查看器就地 diff。纯函数,与 composable 解耦。

**Files:**
- Create: `frontend/src/views/coding/workspaceChanges.ts`
- Test: `frontend/src/views/coding/workspaceChanges.spec.ts`

- [ ] **Step 1: 写失败测试**

Create `frontend/src/views/coding/workspaceChanges.spec.ts`:
```ts
import { describe, it, expect } from 'vitest'
import { collectChangedFiles } from './workspaceChanges'

describe('collectChangedFiles', () => {
  it('收集 file_write/file_edit 的改前改后,lastChangedFile 取最后一条', () => {
    const { changed, lastChangedFile } = collectChangedFiles([
      { type: 'thinking', content: 'x' },
      { type: 'file_write', fileName: 'src/a.ts', fileContent: 'A' },
      { type: 'file_edit', fileName: 'src/b.ts', oldContent: 'old', fileContent: 'new' },
    ])
    expect([...changed.keys()].sort()).toEqual(['src/a.ts', 'src/b.ts'])
    expect(changed.get('src/b.ts')).toEqual({ oldContent: 'old', fileContent: 'new' })
    expect(changed.get('src/a.ts')).toEqual({ oldContent: undefined, fileContent: 'A' })
    expect(lastChangedFile).toBe('src/b.ts')
  })

  it('同一文件多次改,后者覆盖前者', () => {
    const { changed } = collectChangedFiles([
      { type: 'file_edit', fileName: 'src/a.ts', oldContent: '1', fileContent: '2' },
      { type: 'file_edit', fileName: 'src/a.ts', oldContent: '2', fileContent: '3' },
    ])
    expect(changed.get('src/a.ts')).toEqual({ oldContent: '2', fileContent: '3' })
  })

  it('无文件改动时 lastChangedFile 为 null', () => {
    const { changed, lastChangedFile } = collectChangedFiles([{ type: 'status', content: 'ok' }])
    expect(changed.size).toBe(0)
    expect(lastChangedFile).toBeNull()
  })

  it('缺 fileName 的脏事件被跳过', () => {
    const { changed } = collectChangedFiles([{ type: 'file_write', fileContent: 'A' }])
    expect(changed.size).toBe(0)
  })
})
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd "frontend" && npx vitest run src/views/coding/workspaceChanges.spec.ts`
Expected: FAIL,`collectChangedFiles` 未定义。

- [ ] **Step 3: 写实现**

Create `frontend/src/views/coding/workspaceChanges.ts`:
```ts
export interface FileChangeMsg {
  type: string
  fileName?: string
  fileContent?: string
  oldContent?: string
}

export interface FileChange {
  oldContent?: string
  fileContent?: string
}

export interface ChangedFiles {
  changed: Map<string, FileChange>
  lastChangedFile: string | null
}

const FILE_TYPES = new Set(['file_write', 'file_edit'])

export function collectChangedFiles(messages: FileChangeMsg[]): ChangedFiles {
  const changed = new Map<string, FileChange>()
  let lastChangedFile: string | null = null
  for (const m of messages) {
    if (!FILE_TYPES.has(m.type) || !m.fileName) continue
    changed.set(m.fileName, { oldContent: m.oldContent, fileContent: m.fileContent })
    lastChangedFile = m.fileName
  }
  return { changed, lastChangedFile }
}
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd "frontend" && npx vitest run src/views/coding/workspaceChanges.spec.ts`
Expected: PASS,4 个用例全绿。

- [ ] **Step 5: Commit**
```bash
git add frontend/src/views/coding/workspaceChanges.ts frontend/src/views/coding/workspaceChanges.spec.ts
git commit -m "feat(coding): 从流消息聚合改动文件 collectChangedFiles + 测试"
```

---

### Task 4: 加列文件 / 读文件 api 函数

**Files:**
- Modify: `frontend/src/api/coding.ts`(在文件末尾、`export` 区域追加)

- [ ] **Step 1: 加两个 api 函数**

在 `frontend/src/api/coding.ts` 末尾追加(文件顶部已有 `import request from '@/utils/request'`):
```ts
/** 列出工作区文件(扁平相对路径,已排除 node_modules/隐藏文件) */
export function listWorkspaceFiles(wsId: string): Promise<string[]> {
  return request.get(`/coding/workspace/${wsId}/files`)
}

/** 读取工作区单文件内容 */
export function readWorkspaceFile(
  wsId: string,
  filePath: string,
): Promise<{ path: string; content: string }> {
  return request.get(`/coding/workspace/${wsId}/file`, { params: { file_path: filePath } })
}
```

- [ ] **Step 2: 类型校验(确认接口签名编译通过)**

Run: `cd "frontend" && npx vue-tsc -p tsconfig.app.json --noEmit 2>&1 | grep -E "api/coding" || echo "coding.ts 无新增类型错误"`
Expected: 输出 "coding.ts 无新增类型错误"(全量 vue-tsc 有预存错误,只确认本文件不新增)。

- [ ] **Step 3: Commit**
```bash
git add frontend/src/api/coding.ts
git commit -m "feat(coding): api 加 listWorkspaceFiles / readWorkspaceFile"
```

---

### Task 5: FileTree.vue 组件

只读文件树:吃树节点 + 改动路径集合 + 选中路径,点文件 emit select,改动文件打圆点。可视行为走 preview 验证。

**Files:**
- Create: `frontend/src/views/coding/FileTree.vue`

- [ ] **Step 1: 写组件**

Create `frontend/src/views/coding/FileTree.vue`:
```vue
<template>
  <div class="ws-file-tree">
    <FileTreeNode
      v-for="node in tree"
      :key="node.path"
      :node="node"
      :changed="changed"
      :selected="selected"
      @select="$emit('select', $event)"
    />
  </div>
</template>

<script setup lang="ts">
import type { TreeNode } from './fileTree'
import FileTreeNode from './FileTreeNode.vue'

defineProps<{
  tree: TreeNode[]
  changed: Set<string>
  selected: string | null
}>()
defineEmits<{ (e: 'select', path: string): void }>()
</script>

<style scoped>
.ws-file-tree { font-size: 13px; padding: 6px 4px; overflow: auto; }
</style>
```

- [ ] **Step 2: 写递归节点组件**

Create `frontend/src/views/coding/FileTreeNode.vue`:
```vue
<template>
  <div class="ftn">
    <div
      class="ftn-row"
      :class="{ selected: !node.isDir && selected === node.path }"
      :style="{ paddingLeft: depth * 12 + 8 + 'px' }"
      @click="onClick"
    >
      <span v-if="node.isDir" class="ftn-caret">{{ open ? '▾' : '▸' }}</span>
      <span class="ftn-name">{{ node.name }}</span>
      <span v-if="!node.isDir && changed.has(node.path)" class="ftn-dot" />
    </div>
    <template v-if="node.isDir && open">
      <FileTreeNode
        v-for="child in node.children"
        :key="child.path"
        :node="child"
        :changed="changed"
        :selected="selected"
        :depth="depth + 1"
        @select="$emit('select', $event)"
      />
    </template>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import type { TreeNode } from './fileTree'

const props = withDefaults(defineProps<{
  node: TreeNode
  changed: Set<string>
  selected: string | null
  depth?: number
}>(), { depth: 0 })
const emit = defineEmits<{ (e: 'select', path: string): void }>()

const open = ref(true)
function onClick() {
  if (props.node.isDir) open.value = !open.value
  else emit('select', props.node.path)
}
</script>

<style scoped>
.ftn-row { display: flex; align-items: center; gap: 4px; padding: 3px 4px; border-radius: 4px; cursor: pointer; white-space: nowrap; }
.ftn-row:hover { background: var(--ac-bg-hover, rgba(0,0,0,.04)); }
.ftn-row.selected { background: var(--ac-bg-active, rgba(64,128,255,.12)); }
.ftn-caret { width: 10px; color: var(--ac-text-secondary, #888); }
.ftn-name { overflow: hidden; text-overflow: ellipsis; }
.ftn-dot { width: 6px; height: 6px; border-radius: 50%; background: var(--ac-warning, #e6a23c); margin-left: auto; flex: none; }
</style>
```

- [ ] **Step 3: 编译校验**

Run: `cd "frontend" && npx vue-tsc -p tsconfig.app.json --noEmit 2>&1 | grep -E "FileTree" || echo "FileTree 无类型错误"`
Expected: 输出 "FileTree 无类型错误"。

- [ ] **Step 4: Commit**
```bash
git add frontend/src/views/coding/FileTree.vue frontend/src/views/coding/FileTreeNode.vue
git commit -m "feat(coding): 原生只读文件树 FileTree + 递归节点(改动文件打点)"
```

> 可视验证统一放在 Task 7 接入 CodingPage 后用 preview 做(单独渲染组件无数据源)。

---

### Task 6: CodeViewer.vue 组件

只读代码查看器:有 diff(该文件本轮被 agent 改过)→ 复用 `FileCard` 渲染红绿 diff;无 diff → 拉 `/file` 内容用 Shiki 只读高亮。

**Files:**
- Create: `frontend/src/views/coding/CodeViewer.vue`
- Create: `frontend/src/views/coding/shikiHighlight.ts`

- [ ] **Step 1: 写 Shiki 单例高亮辅助**

Create `frontend/src/views/coding/shikiHighlight.ts`:
```ts
import { createHighlighter, type Highlighter } from 'shiki'

const LANGS = ['vue', 'typescript', 'javascript', 'json', 'html', 'css', 'less', 'markdown', 'bash', 'python']
const THEMES = ['github-light', 'github-dark']

let hlPromise: Promise<Highlighter> | null = null
function getHighlighter(): Promise<Highlighter> {
  if (!hlPromise) hlPromise = createHighlighter({ themes: THEMES, langs: LANGS })
  return hlPromise
}

const EXT_LANG: Record<string, string> = {
  vue: 'vue', ts: 'typescript', tsx: 'typescript', js: 'javascript', jsx: 'javascript',
  json: 'json', html: 'html', css: 'css', less: 'less', md: 'markdown',
  sh: 'bash', bash: 'bash', py: 'python',
}

export function langForPath(path: string): string {
  const ext = path.split('.').pop()?.toLowerCase() || ''
  return EXT_LANG[ext] || 'text'
}

const MAX_HIGHLIGHT_BYTES = 400_000

export async function highlightCode(code: string, path: string, dark: boolean): Promise<string> {
  const theme = dark ? 'github-dark' : 'github-light'
  if (code.length > MAX_HIGHLIGHT_BYTES) {
    const esc = code.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    return `<pre class="shiki-plain"><code>${esc}</code></pre>`
  }
  const hl = await getHighlighter()
  const lang = hl.getLoadedLanguages().includes(langForPath(path) as any) ? langForPath(path) : 'text'
  return hl.codeToHtml(code, { lang, theme })
}
```

- [ ] **Step 2: 写 CodeViewer 组件**

Create `frontend/src/views/coding/CodeViewer.vue`:
```vue
<template>
  <div class="code-viewer">
    <div class="cv-path">{{ filePath || '未选择文件' }}</div>
    <div class="cv-body">
      <FileCard
        v-if="diff"
        action="edit"
        :file-name="filePath || ''"
        :file-content="diff.fileContent"
        :old-content="diff.oldContent"
      />
      <div v-else-if="loading" class="cv-hint">加载中…</div>
      <div v-else-if="error" class="cv-hint cv-error">{{ error }} <button @click="load">重试</button></div>
      <div v-else-if="filePath" class="cv-code" v-html="html" />
      <div v-else class="cv-hint">从左侧选择文件查看</div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, watch } from 'vue'
import FileCard from '@/components/FileCard.vue'
import { readWorkspaceFile } from '@/api/coding'
import { highlightCode } from './shikiHighlight'
import type { FileChange } from './workspaceChanges'

const props = defineProps<{
  wsId: string
  filePath: string | null
  diff?: FileChange | null
  dark?: boolean
}>()

const html = ref('')
const loading = ref(false)
const error = ref('')

async function load() {
  html.value = ''
  error.value = ''
  if (props.diff || !props.filePath || !props.wsId) return
  loading.value = true
  try {
    const res = await readWorkspaceFile(props.wsId, props.filePath)
    html.value = await highlightCode(res.content, props.filePath, !!props.dark)
  } catch (e: any) {
    error.value = e?.response?.data?.detail || '读取文件失败'
  } finally {
    loading.value = false
  }
}

watch(() => [props.wsId, props.filePath, props.diff, props.dark], load, { immediate: true })
</script>

<style scoped>
.code-viewer { display: flex; flex-direction: column; height: 100%; min-width: 0; }
.cv-path { padding: 6px 12px; border-bottom: 0.5px solid var(--ac-border, rgba(0,0,0,.1)); font-family: monospace; font-size: 12px; color: var(--ac-text-secondary, #888); }
.cv-body { flex: 1; overflow: auto; padding: 8px 0; }
.cv-code :deep(pre) { margin: 0; padding: 0 12px; font-size: 12px; line-height: 1.7; background: transparent !important; }
.cv-hint { padding: 16px; color: var(--ac-text-secondary, #888); font-size: 13px; }
.cv-error { color: var(--ac-danger, #f56c6c); }
</style>
```

- [ ] **Step 3: 编译校验**

Run: `cd "frontend" && npx vue-tsc -p tsconfig.app.json --noEmit 2>&1 | grep -E "CodeViewer|shikiHighlight" || echo "CodeViewer 无类型错误"`
Expected: 输出 "CodeViewer 无类型错误"。

- [ ] **Step 4: Commit**
```bash
git add frontend/src/views/coding/CodeViewer.vue frontend/src/views/coding/shikiHighlight.ts
git commit -m "feat(coding): 只读代码查看器 CodeViewer(Shiki 高亮 + 复用 FileCard diff)"
```

---

### Task 7: 接入 CodingPage,替换 IDE 抽屉

把 IDE iframe `<el-drawer>`(254-287)替换为「文件树 + 查看器」两栏;用 `collectChangedFiles(streamMessages)` 驱动树标记 + 自动打开最后改动文件。

**Files:**
- Modify: `frontend/src/views/CodingPage.vue`

- [ ] **Step 1: 引入新模块 + 派生状态**

在 `CodingPage.vue` `<script setup>` 顶部 import 区加:
```ts
import FileTree from './coding/FileTree.vue'
import CodeViewer from './coding/CodeViewer.vue'
import { buildFileTree, type TreeNode } from './coding/fileTree'
import { collectChangedFiles } from './coding/workspaceChanges'
import { listWorkspaceFiles } from '@/api/coding'
```

在 `streamMessages` 解构之后加状态与派生(用现有 `codingStore.workspace`、`streamMessages`、主题 `isDark`——若本文件已有暗色变量沿用,否则用 `false`):
```ts
const wsFileTree = ref<TreeNode[]>([])
const selectedFile = ref<string | null>(null)

async function loadWsFileTree() {
  const id = codingStore.workspace?.id
  if (!id) { wsFileTree.value = []; return }
  try { wsFileTree.value = buildFileTree(await listWorkspaceFiles(id)) }
  catch { wsFileTree.value = [] }
}

const wsChanges = computed(() => collectChangedFiles(streamMessages.value as any))
const changedPaths = computed(() => new Set(wsChanges.value.changed.keys()))
const selectedDiff = computed(() =>
  selectedFile.value ? wsChanges.value.changed.get(selectedFile.value) || null : null,
)

// agent 改完单文件 → 自动打开它(+ 刷新文件树以纳入新建文件)
watch(() => wsChanges.value.lastChangedFile, (p) => {
  if (p) { selectedFile.value = p; void loadWsFileTree() }
})
// 切换工作区 → 重载文件树
watch(() => codingStore.workspace?.id, () => { selectedFile.value = null; void loadWsFileTree() }, { immediate: true })
```

> 说明:`streamMessages` 已由现有 `useStreamMessages()` 解构得到;`computed`/`ref`/`watch` 文件里已在用。`isDark` 若本文件无现成变量,Step 2 模板里 `:dark` 传 `false` 即可(暗色可后续接主题 store)。

- [ ] **Step 2: 替换 IDE 抽屉模板**

把 `CodingPage.vue` 第 254-287 行的整段 IDE `<el-drawer>`(含 `ide-pane`/`<iframe>`/loading overlay)替换为:
```vue
<div class="ws-pane">
  <FileTree
    class="ws-pane-tree"
    :tree="wsFileTree"
    :changed="changedPaths"
    :selected="selectedFile"
    @select="selectedFile = $event"
  />
  <CodeViewer
    class="ws-pane-viewer"
    :ws-id="codingStore.workspace?.id || ''"
    :file-path="selectedFile"
    :diff="selectedDiff"
    :dark="false"
  />
</div>
```
加配套样式(在 `<style>` 区):
```css
.ws-pane { display: flex; height: 100%; min-height: 0; border-left: 0.5px solid var(--ac-border, rgba(0,0,0,.1)); }
.ws-pane-tree { width: 200px; flex: none; border-right: 0.5px solid var(--ac-border, rgba(0,0,0,.1)); }
.ws-pane-viewer { flex: 1; min-width: 0; }
```

> `.ws-pane` 放进原 IDE 抽屉所在的右侧区域容器;若原抽屉是覆盖层而非常驻栏,改为常驻在主区右侧(与聊天并列)。具体挂载位置依本文件三栏容器实际结构微调,目标:左聊天/中或右工作区两栏可见。

- [ ] **Step 3: 暂时保留 useIdeManager 引用不删(避免编译断)**

本任务**只新增可见的原生工作区**,不删 `useIdeManager`/`openIdeDrawer`/FileCard import 等(清理留给后续独立计划)。确认替换后 `openIdeDrawer` 等若变成未引用,加 `// eslint-disable` 或保留按钮入口均可,优先保证编译通过。

- [ ] **Step 4: 编译校验**

Run: `cd "frontend" && npm run build:nocheck`
Expected: 构建成功(`build:nocheck` 跳过 vue-tsc;全量 `build` 有预存类型错误,不作为门)。

- [ ] **Step 5: preview 端到端验证**

用 preview 工具(非手测):
1. preview_start 启 frontend + backend。
2. 打开 `/ai-builder/`,进 CodingPage(/coding),选一个工作区。
3. preview_snapshot:确认左侧出现文件树、点一个文件 → 右侧 CodeViewer 显示高亮代码。
4. 在聊天发「给某文件加点东西」让 agent 改 → preview_snapshot 确认:被改文件在树上出现圆点、查看器自动打开并显示红绿 diff。
5. preview_console_logs 确认无报错。
6. preview_screenshot 留证。

- [ ] **Step 6: Commit**
```bash
git add frontend/src/views/CodingPage.vue
git commit -m "feat(coding): CodingPage 用原生文件树+代码查看器替换 IDE 抽屉(Phase 1)"
```

---

## 自检与后续

- **spec 覆盖**:文件树(Task 2/5)、只读查看器+高亮(Task 6)、就地 diff(Task 6 复用 FileCard)、改动标记+自动打开(Task 3/7)、复用 /files・/file・streamMessages・FileCard——均落到任务。Phase 1 不含确认门/清理,符合 spec 的阶段划分。
- **类型一致**:`TreeNode`(Task 2)、`FileChange`/`collectChangedFiles`(Task 3)、`listWorkspaceFiles`/`readWorkspaceFile`(Task 4)在 Task 5/6/7 引用名一致。
- **后续计划(不在本计划)**:Phase 2 确认门(后端 HITL);code-server 清理(删 useIdeManager/WorkspaceIdeDrawer/补丁脚本/部署 code-server)。各自单独 plan。
- **已知边界**:`isDark` 暂传 false(暗色高亮待接主题 store);`.ws-pane` 的精确挂载位置依 CodingPage 三栏容器实测微调(Task 7 Step 2 已注明)。
