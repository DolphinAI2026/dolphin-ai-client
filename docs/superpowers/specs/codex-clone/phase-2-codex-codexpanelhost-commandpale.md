# Phase 2: Codex 风格右侧面板外壳 + 命令面板 (CodexPanelHost / CommandPalette)

## Phase 2 设计 Spec — Codex 风格右侧面板外壳 + 命令面板

### 0. 现状与目标
现状 CodingPage 右侧是 `.ws-pane`（`CodingPage.vue` 模板 344-388 行）：固定宽度可拖拽侧栏，内含 `.ws-pane-tabs` 两个 tab「文件 / 代码」「预览」+ 关闭按钮，body 是 `FileTree + CodeViewer`（files tab）和 `RunDebugPanel`（run tab）。状态 = `codePaneOpen: ref<boolean>` + `wsPaneTab: ref<'files'|'run'>`。

Codex 观感目标：
- 单面板宿主：一次只显示一个面板（审查 / 终端 / 浏览器 / 文件），顶部不是宽 tab，而是更紧凑的 Codex 段控/标题栏；面板间靠命令面板或顶栏图标切换。
- 命令面板浮层：⌘K 触发，列出 审查 ⌃⇧G / 终端 / 浏览器 ⌘T / 文件 ⌘P / 侧边聊天 ⌥⌘S，圆角行 + 右侧快捷键 chip，深底 hover 高亮。
- 会话头右上角布局切换按钮（分栏图标）：开/关右面板宿主。

**本 Phase 只做外壳 + 命令面板 + 切换 + 状态管理。** 四个面板的内容里：文件复用 `FileTree+CodeViewer`、浏览器复用 `RunDebugPanel`（serve URL iframe）。审查 / 终端为本 Phase 新增的轻面板（见 §4），但只接已有数据源（`wsGitChanges`、`serveLogsUrl` SSE），不写新后端。

### 1. 设计 token（落到 CodingPage.styles.css，沿用项目 --t-* 体系）
项目用 `--t-*` token（theme-vars.css），不直接用 mockup 的 `--bg-0` 等。`.code-first .ws-pane` 已在 `CodingPage.global.css` 里定义了一套局部 `--bg/--bg-sub/--bg-hover/--fg/--fg-muted/--line` 别名。**CodexPanelHost 复用同一套局部别名**，新增暗色基调对齐 mockup：

```
/* CodingPage.styles.css 内，scope 到 .codex-panel-host */
.codex-panel-host {
  --cph-bg:        var(--t-bg-panel);      /* 暗色 #111318，亮色 #fff */
  --cph-bg-sub:    var(--t-bg-code);       /* #0d1117 / #f5f7fc */
  --cph-border:    var(--t-border-subtle);
  --cph-border-hi: var(--t-border-strong);
  --cph-text-1:    var(--t-text-primary);
  --cph-text-2:    var(--t-text-secondary);
  --cph-text-3:    var(--t-text-muted);
  --cph-brand:     var(--t-brand);         /* #7c8cff 暗 */
  --cph-green:     var(--t-success);
  --cph-red:       var(--t-danger);
  --cph-mono: ui-monospace, SFMono-Regular, "SF Mono", Menlo, monospace;
}
```
命令面板浮层用更深的 mockup 风格底色（独立组件 scoped）：背景 `var(--t-bg-elevated)`、行 hover `var(--t-bg-panel-hover)`、快捷键 chip 边框 `var(--t-border-strong)` + mono 字体。圆角 `--t-radius-md(12px)`，浮层阴影 `--t-shadow-lg`。

### 2. 组件结构（新增 3 文件 + 1 composable）

```
views/coding/
  CodexPanelHost.vue        # 右侧单面板宿主：顶栏(段控/标题+关闭) + 面板插槽路由
  CommandPalette.vue        # ⌘K 浮层：搜索框 + 命令行列表 + 快捷键 chip
  panels/
    ReviewPanel.vue         # 审查：wsGitChanges 文件改动列表 + 复用 CodeViewer diff
    TerminalPanel.vue       # 终端：serveLogsUrl SSE 日志流（只读 xterm-lite/纯 pre）
  useCodexPanels.ts         # composable: 面板状态机 + 快捷键注册 + 命令注册表
```
（浏览器面板直接复用现有 `RunDebugPanel.vue`，文件面板复用 `FileTree + CodeViewer` 组合，不新建。）

#### 2.1 useCodexPanels.ts（状态机 + 快捷键）
单一真相源，避免 CodingPage 里散落 `codePaneOpen/wsPaneTab` 旧二元状态：

```ts
export type CodexPanelId = 'review' | 'terminal' | 'browser' | 'files'

export interface CodexCommand {
  id: CodexPanelId | 'sidechat'
  label: string          // '审查' '终端' '浏览器' '文件' '侧边聊天'
  icon: string           // AppIcon name: 'eye' 'terminal' 'globe' 'doc' 'message'
  hotkeyLabel?: string   // '⌃⇧G' '⌘T' '⌘P' '⌥⌘S'（终端无)
  match: (e: KeyboardEvent) => boolean  // 精确匹配
  panel?: CodexPanelId   // 命中即激活该面板；sidechat 无 panel(预留 §6)
}

export function useCodexPanels() {
  const open = ref(false)                        // 宿主是否展开(替换 codePaneOpen)
  const active = ref<CodexPanelId>('files')      // 当前激活面板(替换 wsPaneTab 升级版)
  const paletteOpen = ref(false)

  function show(id: CodexPanelId) { active.value = id; open.value = true }
  function toggleHost() { open.value = !open.value }
  function togglePalette() { paletteOpen.value = !paletteOpen.value }

  // 全局快捷键：⌘K 开/关命令面板；各命令直达面板；Esc 关浮层
  // 注册在 onMounted(window.addEventListener('keydown',...))，onUnmounted 注销
  // 防冲突：输入框聚焦时(e.target 是 textarea/input/contenteditable)只放行 ⌘K，其余直达键不抢焦点
  return { open, active, paletteOpen, commands, show, toggleHost, togglePalette }
}
```

**快捷键映射（match 实现，复用 RailSidebar.vue:41 的 metaKey||ctrlKey 跨平台写法）：**
| 命令 | 组合 | match |
|---|---|---|
| 命令面板 | ⌘K / Ctrl K | `(meta||ctrl) && key==='k' && !shift && !alt` |
| 审查 | ⌃⇧G | `ctrl && shift && key.toLowerCase()==='g'` |
| 文件 | ⌘P / Ctrl P | `(meta||ctrl) && key==='p' && !shift` → preventDefault(盖系统打印) |
| 浏览器 | ⌘T / Ctrl T | `(meta||ctrl) && key==='t' && !shift` → preventDefault(盖新标签页) |
| 终端 | （无默认键，仅命令面板/图标进） | — |
| 侧边聊天 | ⌥⌘S | `meta && alt && key.toLowerCase()==='s'`（预留，§6 暂禁用） |

输入框聚焦守卫：`const t=e.target; if (t instanceof HTMLElement && (t.tagName==='TEXTAREA'||t.tagName==='INPUT'||t.isContentEditable)) { 只处理 ⌘K，return }`。

#### 2.2 CodexPanelHost.vue
```
props: {
  wsId: string
  active: CodexPanelId
  dark: boolean
  gitChanges: WorkspaceChanges | null   // 审查面板用
  fileTree: TreeNode[]
  changedPaths: Set<string>
  selectedFile: string | null
  selectedGitChange / selectedDiff / viewerFocusLine  // 透传给 CodeViewer
}
emits: {
  'update:active' (id)        // 段控切换
  'close'                     // 关闭宿主(× / 布局键)
  'select-file' / 'select-line' / 'quote' / 'accept-change' / 'accept-all'  // 文件面板内事件冒泡回 CodingPage(沿用现有 handler)
  'open-palette'              // 顶栏「⌘K」入口
}
```
模板结构（替换原 ws-pane 内部）：
```
.codex-panel-host
  .cph-resizer        ← 沿用 onCodePaneResizeStart 拖宽 handle（左边界）
  .cph-topbar
    .cph-segments     ← 4 段：审查/终端/浏览器/文件，active 高亮（下划线/底色，非宽 tab）
      <button v-for="c in panelCommands" :class="{active:active===c.id}" @click="$emit('update:active',c.id)">
        <AppIcon :name="c.icon" :size="14"/>{{ c.label }}
      </button>
    .cph-topbar-actions
      <button @click="$emit('open-palette')" title="命令面板 ⌘K"><AppIcon name="more"/></button>
      <button class="cph-close" @click="$emit('close')"><AppIcon name="x" :size="15"/></button>
  .cph-body
    <ReviewPanel   v-show="active==='review'"   :changes="gitChanges" ... />
    <TerminalPanel v-show="active==='terminal'" :ws-id="wsId" :dark="dark" />
    <RunDebugPanel v-show="active==='browser'"  :ws-id="wsId" :dark="dark" />  ← 复用，浏览器=预览 iframe
    <div v-show="active==='files'" class="cph-files">  ← 复用 FileTree+CodeViewer 组合
      <FileTree ... /> <div class="tree-resizer".../> <CodeViewer ... />
    </div>
```
用 `v-show` 而非 `v-if`：终端 SSE / 浏览器 iframe 切走不该断流/重载（对齐 Codex 切面板不丢状态）。

#### 2.3 CommandPalette.vue
```
props: { open: boolean; commands: CodexCommand[] }
emits: { 'select'(id); 'close' }
```
- Teleport to body（浮层），遮罩半透明，居中卡片 width 480px，圆角 12px，阴影 lg。
- 顶部搜索 `input`（autofocus），下方 `commands.filter(byQuery)` 列表。
- 每行：左 AppIcon + label，右 `.cmd-hotkey` chip（mono，多个键拆成多个小 chip：⌃ ⇧ G）。hover/方向键高亮 `.is-active`。
- 键盘：↑↓ 移动高亮、Enter 选中、Esc 关闭。点击行 = `emit('select', id)`。
- 选中后宿主 `show(id)` 并关闭浮层。

#### 2.4 ReviewPanel.vue（审查，接已有 /changes 数据）
数据 = CodingPage 已有的 `wsGitChanges`（`getWorkspaceChanges`）。布局对齐 Codex diff 卡：
```
.review-panel
  .rv-summary  「已编辑 N 个文件 +X -Y」+ 右侧「全部接受」按钮(→ emit accept-all，复用 acceptAllWorkspaceChanges)
  .rv-files    每个改动文件一行：路径 + 绿 +adds / 红 -dels + 状态徽标(M/A/D)，点击 → emit('select-file', path)（CodingPage 选中后 CodeViewer 进 diff 对比）
  .rv-empty    无改动时「本轮暂无文件改动」
```
不重写 diff 渲染——点文件后切到 files 面板用 CodeViewer 的 diff 模式（`selectedGitChange`）。审查面板本身只做「文件清单 + 摘要 + 接受」。

#### 2.5 TerminalPanel.vue（终端，接 serve-logs SSE）
```
props: { wsId: string; dark: boolean }
```
- onMounted 若 wsId 存在：`new EventSource(codingApi.serveLogsUrl(wsId, lastSeq))`，逐行 append 到 `lines: ref<string[]>`（环形 buffer 上限 2000 行）。
- 渲染：`.term-body` 是等宽 `<pre>` 滚动区（mono、深底 `--cph-bg-sub`），自动滚到底；顶部 `.term-toolbar`「serve 日志」+ 清屏 + 重连按钮。
- 无 serve 在跑时显示空态「启动预览后这里出现构建/运行日志」（与 RunDebugPanel 空态文案呼应）。
- onUnmounted close EventSource。lastSeq 沿用 `serveLogsUrl(wsId, lastSeenSeq)` 签名做断点续传。

### 3. CodingPage.vue 接线改动（协调/替换现有 ws-pane）
1. **删除** `codePaneOpen`/`wsPaneTab` 两个裸 ref，改为 `const { open: panelOpen, active: activePanel, paletteOpen, commands, show, toggleHost } = useCodexPanels()`。
2. **模板**：用 `<CodexPanelHost>` 替换 344-388 行整个 `.ws-pane` 块；保留外层 `:style="{flex:'0 0 '+codePaneWidth+'px'}"` 与 `onCodePaneResizeStart`（拖宽逻辑不变，handle 移进 CodexPanelHost 内部 `.cph-resizer`）。
3. **会话头布局切换按钮**：在 `.coding-chat-actions`（CodingPage.vue 87-122 行）追加一个按钮，`:class="{active:panelOpen}"`，`@click="toggleHost"`，icon 用分栏图标（`AppIcon name="coding"` 已被「代码」按钮占用 → 布局按钮用 `'square'` 或新增 `'columns'` icon；本 Phase 复用现有 `'expand'`/`'square'` 避免动 icons.ts）。原「代码 / 文件」按钮（119 行）改成 `@click="show('files')"`。
4. **挂 `<CommandPalette :open="paletteOpen" :commands="commands" @select="onPaletteSelect" @close="paletteOpen=false"/>`** 在 BuilderFrame 内顶层。`onPaletteSelect(id)` = `id==='sidechat' ? (§6 暂 noop/提示) : show(id)` 后关浮层。
5. **现有自动行为迁移**（保持不回归）：
   - `focusPreview()` / 对话点 localhost 链接 / `previewEpoch` watch（CodingPage 1090-1125 行）原本 `wsPaneTab.value='run'; codePaneOpen.value=true` → 改 `show('browser')`。
   - `openFileFromChat` / `lastChangedFile` watch → 改 `show('files')`。
   - `ensureCodePaneData` 的 `watch(codePaneOpen,...)` → 改 watch `panelOpen`。
6. **embedMode/embeddedAppId** 下不渲染 CodexPanelHost/命令面板（沿用 `v-if="!embeddedAppId"` 等现有条件）。

### 4. 状态管理总览（哪个面板激活）
单一来源 `useCodexPanels`：
- `panelOpen`（bool）：宿主整体显隐 = 替换 `codePaneOpen`。布局键 / × / 命令面板选中均经它。
- `activePanel`（'review'|'terminal'|'browser'|'files'）：当前面板 = 升级 `wsPaneTab`（从 2 值扩到 4 值）。
- `paletteOpen`（bool）：命令面板浮层。
- 切面板恒「打开宿主 + 切 active」(`show(id)`)；面板内子状态（终端 SSE / 浏览器 iframe / 文件选中）各自保活，用 `v-show`。
- 持久化：`activePanel` 不持久化（每会话默认 files）；`codePaneWidth` 沿用现有 `usePanelResize('coding:code-pane-width')`。可选把上次面板存 `localStorage('coding:codex-panel')`（非必须）。

### 5. 交互 / 动效
- 命令面板：⌘K 淡入(150ms opacity+translateY)，遮罩点击关闭，Esc 关闭，↑↓Enter 键盘可达。
- 段控切换：active 段 200ms 下划线滑动（或底色），icon+label。
- 面板宿主开/关：宽度 0↔codePaneWidth 不做动画（拖拽体验优先），或简单 200ms（与现有保持一致，现无动画 → 保持无动画）。
- 终端自动滚到底，新行 append。

### 6. 侧边聊天（⌥⌘S）— 本 Phase 留桩
命令存在但 `panel` 为空：选中时暂 `ElMessage.info('侧边聊天即将上线')` 或 noop，键位注册但 Phase 2 不实现真功能（避免与现有对话主列冲突，留给后续 Phase）。命令面板里照常列出 + 显示 ⌥⌘S chip，符合 Codex 观感。

### 7. 验收标准
1. ⌘K 弹出命令面板，列 5 行（审查 ⌃⇧G / 终端 / 浏览器 ⌘T / 文件 ⌘P / 侧边聊天 ⌥⌘S），右侧快捷键 chip 正确，↑↓Enter/点击可选，Esc 关闭。
2. ⌃⇧G→审查、⌘P→文件、⌘T→浏览器 三个直达键各自打开宿主并切到对应面板；输入框聚焦时这些键不抢焦点（仍能在输入框打字），但 ⌘K 仍可用。
3. 审查面板显示 `wsGitChanges` 的文件清单（路径 + 绿+/红- + M/A/D 徽标）+「已编辑 N 文件 +X -Y」摘要，点文件切到文件面板并 CodeViewer 进 diff 对比；「全部接受」走现有 acceptAll。
4. 终端面板订阅 serve-logs SSE 实时滚动日志；切走再切回不断流（v-show）；无 serve 时空态。
5. 浏览器面板即现有 RunDebugPanel（启动预览 + iframe + 运行时报错），功能不回归；对话点 localhost 链接 / 预览 epoch 仍自动切到浏览器面板。
6. 文件面板即现有 FileTree+CodeViewer，选中/引用/接受变更/拖宽 全部不回归。
7. 会话头布局切换按钮开/关宿主，active 态高亮。
8. 暗色 / 亮色两套主题下 token 正确（沿用 --t-* + .code-first 局部别名），与 mockup 暗底观感一致。
9. embed 模式不渲染宿主与命令面板。
10. `npm run build:nocheck` 通过；新增 useCodexPanels.ts / codingLayout 风格的纯函数（快捷键 match、命令注册表）有单测（对齐现有 `codingLayout.spec.ts` / `serveLogsUrl.spec.ts` 习惯）。

### 8. 风险已知点
- ⌘P/⌘T 会与浏览器/系统默认冲突 → 必须 `preventDefault`；Tauri 桌面壳里通常安全，但 Web 预览下要测。
- SSE 终端在桌面包内 serve-logs 是否可达需真机验（RunDebugPanel 注释提到桌面包 CDP 不可用，但 serve-logs 是后端 SSE 应可达）。
- 不要破坏现有「切会话 detach/attach run」「懒加载 ensureCodePaneData」逻辑——`panelOpen` 必须语义等价替换 `codePaneOpen`，否则懒加载/串台守卫回归。