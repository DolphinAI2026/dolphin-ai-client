# Code 模式 Codex 化 · Phase 3：终端面板 + 浏览器面板

## 背景与现状（已核验代码）

- `CodingPage.vue`(2019 行) 右侧代码栏 `wsPaneTab` 当前只有两态 `'files' | 'run'`，`'run'` 渲染 `RunDebugPanel.vue`。
- `RunDebugPanel.vue` 现在是「预览 iframe + 运行时报错列表」混在一个面板里：顶部工具条有「启动预览/刷新/停止」+ devUrl 文本，body 是 iframe，底部塞了运行时报错小列表 + 「抓取不可用」降级条。**它把"浏览器"和"终端报错"混为一谈。**
- `/serve-logs` SSE **后端已就绪但前端无消费者**：`buildServeLogsUrl` 在 `CodingPage.vue` 第 3 行 import 但全文件未使用；`codingApi.serveLogsUrl(wsId, lastSeenSeq)` 已封好（token 走 query）。SSE event 名 `log`，data = `{seq:int, stream:'stdout'|'stderr', line:string}`，断线靠 `last_seen_seq` 补发。
- 运行时报错两路：①SSE/CDP 经 `activePreview.errors`；②预览 harness `postMessage({source:'ruijing-preview', type:'runtime-error', payload:{kind, message, source, line, status, url}})`，`RunDebugPanel` 监听并 `codingApi.ingestRuntimeErrors(wsId, [payload])` 上报。`kind` 取值实测：`js-error / unhandledrejection / console.error / network`。
- serve API：`startServe(wsId)` 返回 `{status:'ok'|'starting'|'error', url?, port?, message?}`；`stopServe(wsId)`；`getServeStatus(wsId)` 返回 `{running, url?}`；`ingestRuntimeErrors`。`activePreview` 存在 `codingStore`，含 `{source, dev_url, status, errors, capture_available, round}`。
- 设计 token（来自 `frontend/dist/aichat-mockup.html`，照搬）：`--bg-0:#0a0a0c --bg-1:#111114 --bg-2:#16171b --bg-3:#1d1e23 --border:rgba(255,255,255,.06) --border-hi:rgba(255,255,255,.1) --text-1:#e8eaed --text-2:#a1a4ad --text-3:#6c707a --brand:#5a78ff --accent:#f0824a --green:#34d399 --red:#f87171 --mono:ui-monospace,SFMono-Regular,"SF Mono",Menlo,monospace`。CSS 按项目惯例外置（与 ChatPage/CodingPage CSS 外置一致）。

## 总体方案

把单一 `'run'` tab 拆成三态 Codex 式 pane tab：`'files' | 'terminal' | 'browser'`（保留 `'files'`）。两个新面板各自独立组件、各自只读一种关注点：

1. **TerminalPanel**（终端）= serve 进程日志流 + 运行时报错，等宽、自动滚、分色。**纯只读输出**，不接受输入命令（后端无交互式 PTY，照实现做，不画假终端输入框以免空头支票）。
2. **BrowserPanel**（浏览器）= 地址栏 + 内嵌 iframe，地址可手输，一键带入当前 dev_url。

`RunDebugPanel.vue` 的预览 iframe 能力迁入 `BrowserPanel`，运行时报错能力迁入 `TerminalPanel`；`RunDebugPanel` 退役（或保留为薄包装过渡，见风险）。两块共享一个轻量 composable 管 serve 生命周期，避免两面板各自 startServe 打架。

---

## Phase 3A — 终端面板 TerminalPanel.vue

### 布局（Codex 终端观感）
```
┌─ 终端栏 ────────────────────────────────────┐
│ ● 运行中  npm run serve · :5173    [清空] [自动滚 ⏸] [停止] │  ← 顶栏 32px, bg-2
├──────────────────────────────────────────────┤
│ 12:03:21  webpack compiled successfully        │  ← 日志流, mono 12px, bg-0
│ 12:03:21  App running at http://127.0.0.1:5173 │
│ 12:03:25 ⚠ [stderr] Deprecation warning ...    │  ← stderr 橙 (--accent)
│ 12:03:30 ✕ [runtime js-error] xxx @ App.vue:42 │  ← runtime 红 (--red)
│ ▌                                              │  ← 末尾光标/到底锚点
└──────────────────────────────────────────────┘
```

### 行分色规则（关键，照后端 stream 字段 + runtime kind）
- `stream==='stdout'` → 默认色 `--text-2`，正文行；命中 `error|fail|✖|ERROR` 关键字的 stdout 行 → 升级为 `--red`（webpack 把编译错误打在 stdout）。
- `stream==='stderr'` → `--accent`（橙，warning/deprecation 噪声），行首 `⚠`。
- 运行时报错（来自 `activePreview.errors` + harness postMessage）→ `--red`，行首 `✕`，标签 `[runtime <kind>]`，格式复用 `RunDebugPanel._fmtRuntimeError`：`[kind] message @ source:line`。
- 时间戳列 `--text-3`，等宽对齐。ANSI 已在后端 `_strip_serve_ansi` 去掉，前端不必再处理。

### 数据来源（全部复用，零新后端）
- **serve 日志**：`new EventSource(codingApi.serveLogsUrl(wsId, lastSeenSeq))`，监听 `addEventListener('log', ...)`，`JSON.parse(e.data)` → `{seq, stream, line}`，push 进 `logLines` ring（封顶 1000 行，对齐后端 `_SERVE_LOG_RING_MAX`）。记录 `lastSeenSeq = max(seq)` 供断线重连。`heartbeat` event 忽略。组件卸载 / 切 wsId / 停止预览时 `es.close()`。
- **运行时报错**：监听 `window` 的 `message`（迁移自 RunDebugPanel `onPreviewMessage`），合并 `activePreview.errors`，统一转成红色 runtime 行 push 进同一 `logLines` 流（用 `entry.type:'runtime'` 标记，便于分色 + 「仅看报错」过滤）。harness postMessage 仍 `codingApi.ingestRuntimeErrors` 上报后端供 agent 读取（**保留此行为，是 agent 自愈的信号源，不能删**）。

### 交互
- **自动滚动**：默认开。新行到达若用户已在底部则 `scrollTop=scrollHeight`；用户手动上滚则暂停自动滚 + 顶栏「自动滚」按钮变 ⏸；点该按钮或滚回底部恢复。用 `ResizeObserver`/scroll 事件判断 `isAtBottom`（阈值 32px）。
- **清空**：清本地 `logLines`（不影响后端 ring；切回会经 `last_seen_seq=0`? — 不，清空只重置视图，`lastSeenSeq` 保留，避免重复拉历史）。
- **过滤 chip**（Codex 风轻量）：`全部 / stderr / 报错`三段，纯前端过滤 `logLines`。默认「全部」。
- **状态点**：复用 `getServeStatus` + `activePreview.status`：`running`→绿点「运行中」+ 进程名/端口；`starting`→蓝点脉冲「编译中」；无 serve→灰点「未运行」+ 提示「去浏览器面板启动预览，或在对话里说"跑一下"」。
- **停止**：调 `codingApi.stopServe(wsId)` + 清 `activePreview`（与 BrowserPanel 共享 serve composable，停止后两面板同步回未运行态）。

### 空态
未启动 serve：居中 `--text-3` 文案「还没有运行的开发服务器。在「浏览器」面板点启动预览，日志会实时出现在这里。」

---

## Phase 3B — 浏览器面板 BrowserPanel.vue

### 布局（Codex 内嵌浏览器观感）
```
┌─ 地址栏 ────────────────────────────────────────┐
│ ‹ ›  ⟳  [ http://127.0.0.1:5173/        ] [↗]  [▶启动预览] │  ← 36px, bg-2
├──────────────────────────────────────────────────┤
│                                                    │
│           <iframe src=当前地址>                     │  ← bg 白(预览本体)
│                                                    │
└──────────────────────────────────────────────────┘
```

### 地址栏组件
- 输入框：`addressInput`(ref string)，mono 字体，placeholder「输入地址，或点启动预览带入 dev 地址」。回车 / 点 ⟳ → 设 `iframeSrc = normalize(addressInput)`（自动补 `http://`、容忍尾斜杠）。
- **一键带入 dev 地址**：「▶启动预览」按钮——若 serve 未起，调共享 composable `startPreview()`(=`codingApi.startServe`)；返回后把 `dev_url`(或 `http://127.0.0.1:${port}/`) 灌进 `addressInput` + `iframeSrc`。serve 已起时按钮变「⟳ 刷新」（reloadKey++）。沿用 RunDebugPanel 的 `status==='starting'` → 3s 后自动 reload 逻辑（首屏编译中防白屏）。
- `‹ › ⟳`：iframe 无法跨域读 history → `‹ ›` 默认禁用（灰），仅当 `iframeSrc` 同源(127.0.0.1 dev) 时尝试 `iframe.contentWindow.history.back()`，失败静默；`⟳` 永远可用(reloadKey++)。**诚实降级，不画不能用的按钮。**
- `↗`：`openExternal(iframeSrc)`（桌面 Tauri 外开系统浏览器，复用 `@/utils/desktop` 的 `openExternal`，已在 CodingPage import）。
- 「⚠ 完全访问」橙 chip / 模型选择器 **不在本面板**（那是输入区的事，属 Phase 别处），本面板地址栏只放浏览器控件。

### iframe
- 复用 RunDebugPanel iframe 写法：`<iframe :key="reloadKey" :src="iframeSrc" sandbox="allow-same-origin allow-scripts allow-forms allow-popups allow-modals">`（对齐 CustomPagePreviewPanel 的 sandbox 集）。
- iframe 仍注入/监听 harness postMessage（运行时报错），但**报错展示已挪到终端面板**，BrowserPanel 不再显示报错列表（消除原 RunDebugPanel 底部那坨噪音）。
- 错误态：startServe 返回 `status:'error'` → 地址栏下方红条显 `message`，**绝不拼假地址当成功**（沿用 RunDebugPanel 第 96-99 行的铁律，避免白屏吞错）。

### 空态
无 serve 且地址栏空：居中卡片「点「启动预览」运行此工作区，或手动输入要预览的地址。」

---

## 与现有预览组件的协调（重要）

| 组件 | 处置 |
|---|---|
| `RunDebugPanel.vue` | **退役**。其 iframe → BrowserPanel；其运行时报错 → TerminalPanel；其 startServe/stop/booting 逻辑 → 共享 composable。CodingPage 第 383 行 `<RunDebugPanel>` 替换为 `<BrowserPanel>` + 新 `<TerminalPanel>`，按 `wsPaneTab` 切换显示。 |
| `CustomPagePreviewPanel.vue`(v3) | **不动**。它服务的是「应用配置-自开发整页菜单预览」场景（apaas CUSTOM 菜单 UMD host / dev server 自动探测），与 Code 模式工作区预览是两个入口。BrowserPanel 是「工作区开发预览」，二者并存、各管各的。仅在文档注明边界，避免后人误合。 |
| `codingStore.activePreview` | **保留为单一真相源**。agent 驱动的 `run_workspace_preview` / 自愈轮仍写它；BrowserPanel `startPreview()` 也写它（`source:'panel'`）。两面板都从它派生 devUrl/status/errors → agent 跑预览时浏览器面板自动带地址、终端自动收报错。`watch(previewEpoch)` 现切到 `'run'`，改为切到 `'browser'`。 |

### 共享 composable：`useWorkspaceServe(wsId)`（新增，~80 行）
抽出 serve 生命周期，避免 Terminal/Browser 各自 startServe 冲突：
- 暴露 `status`(computed from activePreview+getServeStatus), `devUrl`, `startPreview()`, `stop()`, `reloadKey`, `booting`。
- 内部封 RunDebugPanel 现有的 start/stop/booting 重试逻辑（原样搬，已 live 验证过）。
- TerminalPanel 用它读 status + stop；BrowserPanel 用它 start/reload/stop + devUrl。

---

## Pane tab 切换（CodingPage 改动）
- `wsPaneTab` 类型 `'files' | 'run'` → `'files' | 'terminal' | 'browser'`。
- `.ws-pane-tabs`（第 350-354 行）三 tab：`文件 / 代码`、`终端`、`浏览器`。Codex 风：底部下划线高亮 active（`--brand`），inactive `--text-3`。
- 行为：agent 跑预览(`previewEpoch`)→自动切 `'browser'`+开 `codePaneOpen`；终端有新报错时 tab 上加红点角标（未读报错提示，对齐 Codex 的状态点心智）。
- 命令面板（若 Phase 1 已建）「终端 / 浏览器 ⌘T」条目分别 `wsPaneTab='terminal'/'browser'`+`codePaneOpen=true`——本 Phase 只需暴露这两个切换函数供其调用，不实现命令面板本体。

---

## 验收标准
1. 启动预览后，**终端面板**实时滚动出 `npm run serve` 的 stdout 行（mono 等宽），stderr 橙、运行时报错红、stdout 默认色；自动滚到底，手动上滚暂停、回底恢复。
2. 断开（切 tab 再回 / 网络抖动）后 SSE 凭 `last_seen_seq` 补发缺失行，不重复、不丢。
3. **浏览器面板**地址栏可手输任意地址回车加载；点「启动预览」自动带入 dev_url 并渲染 iframe；`↗` 外开系统浏览器；`⟳` 刷新。
4. startServe 返回 error 时浏览器面板显真实 message，不白屏不拼假地址。
5. 运行时报错只在终端面板出现一次（不再在浏览器/预览区重复显示）；harness postMessage 仍上报后端（`ingestRuntimeErrors` 调用保留，agent `get_runtime_errors` 可读到）。
6. 同一时刻 Terminal 与 Browser 对 serve 状态认知一致（共享 composable）：一处停止，两处同步回未运行态。
7. 视觉对齐 mockup token（深底 #0a0a0c、brand 蓝紫、accent 橙、绿红状态色、mono 字体）；暗色经 `themeStore.isDark` 透传（沿用 RunDebugPanel `:dark` prop 模式）。
8. 不新增任何后端端点；不触碰 `CustomPagePreviewPanel`。
