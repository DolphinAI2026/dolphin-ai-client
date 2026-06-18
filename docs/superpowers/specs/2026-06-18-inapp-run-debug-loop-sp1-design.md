# 桌面端「运行/调试」闭环底座（SP1）— 设计文档

- 日期：2026-06-18
- 范围：SP1（共享调试底座），含 SP1-a（人工调试闭环）+ SP1-b（AI 自愈闭环）
- 后续：SP2（小程序 uni-app 工程化）、SP3（客户机交付运行时打包）各自独立 spec
- 关联图：见对话内「SP1 在 app 内的运行/调试闭环」架构图

## 1. 背景与问题

ai-builder 桌面端 = Tauri v2 外壳 + PyInstaller Python sidecar（`ruijing-sidecar`），前端 Vue SPA 由 sidecar 在 localhost 上 serve。

交付场景里有一类需求：PC 端用低代码平台搭管理后台，移动端要做小程序（如访客管理）。用户现在能在 app 里完整配置应用、生成小程序代码，也能做二次开发页面/组件，但**没法在 app 内调试**——只能把代码 download 下来用 VS Code 调，体验不闭环。

### 1.1 现状盘点（底座其实已具备大半）

后端已经会跑真实进程，只是没接成闭环：

- 已能起 dev server：`start_serve`/`stop_serve`/`is_serve_running`（`backend/app/coding/workspace.py:1758-1867`），前后端 API 齐（`backend/app/routes/coding.py:1434-1462`、`frontend/src/api/coding.ts:230-241`）。
- 已能跑命令/build：`run_command` 120s（`backend/app/coding/tools.py`），`df-apaas-cli build`（`workspace.py:1616`）。
- SSE 基建完备：`_event_stream_response` + 心跳 + `lastSeenSeq` 断线重连（`backend/app/routes/coding.py:103`、`backend/app/routes/sse.py:76`）。
- 已有 Playwright：`backend/app/coding/browser_service.py:181`（但硬编码 headless、不抓 console/network）。
- Tauri 侧 `WebviewWindow` 可用（`frontend/src/utils/openExternal.ts:24-45`）；capabilities 已放行 `http://localhost:*` / `http://127.0.0.1:*`（`src-tauri/capabilities/default.json`）。

### 1.2 真正缺的（SP1 要补的）

1. 进程输出没有实时流到 UI（现在是 `communicate()` buffer-only，跑完才捞）。
2. 没有把运行时 console/network 抓出来的能力（Playwright 不抓、puppeteer `start_debug` 把 stdout/stderr 丢弃，`workspace.py:2039`）。
3. serve 和 preview 是两个平行世界：`start_serve` 起的是 dev server，而预览 `CustomPagePreviewPanel.vue:71` 加载的是 build 出的 UMD 包 → 改一行要手动 rebuild + 刷新，无 HMR。
4. AI 改完代码是 fire-and-forget：`drive_coding_with_autofix` 只在注释/prompt 里，函数不存在（`backend/app/agents/coding/agent.py:240-264`、`prompts.py:21-23`）。

### 1.3 已确认的方向决策（来自 brainstorming）

- 交付场景：随 app 发给客户/实施同学用 → 不能假设客户机有 node、有微信开发者工具（→ 运行时打包归 SP3，但 SP1 的报错要为它埋口）。
- 小程序调试主路线：H5 内嵌为主（`dev:h5` 全 devtools + HMR），微信特有 API 再一键唤起微信工具（→ SP2）。
- 预览面方案：内置 Chromium + CDP（CDP 只能来自 Chromium，Tauri 的 macOS webview 是 WebKit、不说 CDP）。
- 预览呈现：嵌入 iframe（人快速看，真正在 app 内）+ 独立 CDP Chromium（抓 console/network + devtools），两个渲染器同源（同一 dev server URL）。
- SP1 spec 一次写全 SP1-a + SP1-b。

## 2. 目标 / 非目标

### 目标
- 在 app 内对**二次开发页面/组件**形成可用的运行/调试闭环：起服务 → 看实时日志 → 看预览（HMR）→ 看控制台/网络 → 开 devtools（SP1-a）。
- AI 改代码后能「看到」运行时报错并自愈重试（SP1-b）。
- 底座可复用：SP2 的小程序只需把目标命令换成 `dev:h5`、把工程类型接进来即可。

### 非目标（明确排除）
- SP2：小程序 uni-app 工程化（生成从「对话产物」导成真实可运行工程、vendored uni-app 模板）。
- SP3：客户机运行时打包（内置 portable Node、离线依赖含私有 `@x-apaas`、Chromium 随包、微信工具检测降级）。
- 微信开发者工具的 CLI/automator 联动（属 SP2/SP3）。
- 断点级 step-debug（变量栈帧）；SP1 的「调试」= 运行时可观测（日志/console/network/HMR 预览/devtools），不含断点调试器。

## 3. 架构总览

```
前端 CodingPage · 运行/调试面板
  [运行/停止] [实时日志] [预览 iframe] [控制台/网络] [在 DevTools 打开]
        │            ▲           ▲              ▲
        │ start/stop │ SSE       │ HMR          │ console/network
        ▼            │           │              │
后端 sidecar
  运行会话管理(扩 start_serve) ──spawn──▶ Dev server(vue-cli serve / 后续 dev:h5)
                                              ▲ 加载 URL
  CDP 抓取引擎(扩 Playwright, 非headless) ────┘──▶ console/network ──▶ 面板 + AI 自愈循环(SP1-b)
```

## 4. 组件设计

### C1 · 运行会话编排 + 流式日志（后端）

- 现状：`start_serve` 用 `asyncio.create_subprocess_exec` 起进程，输出 `communicate()` 一次性捞（`workspace.py:911-931` 同款 buffer 模式）。
- 改造：
  - 引入 `RunSession` 抽象（per workspace）：`{ status, port, kind, started_at, log_ring, last_seq }`。沿用现有 `_serve_processes` dict 作为承载，扩字段。
  - 起进程后用 `readline` 循环异步读 stdout/stderr，逐行写入 `log_ring`（环形缓冲，定上限如 2000 行），每行带递增 `seq`。
  - 新端点 `GET /workspace/{ws_id}/serve-logs?last_seen_seq=N`（SSE）：复用 `_event_stream_response` + 心跳；连接时先补发 `> last_seen_seq` 的历史行，再实时推。断线重连靠 `last_seen_seq`（对齐 `sse.py:76-85`）。
  - `kind` 参数预留（`web`/`mobile`/后续 `h5`），让 SP2 复用同一编排。
- 不变：端口分配、活性轮询、kill（SIGTERM→SIGKILL）逻辑沿用 `workspace.py:1768-1835`。

接口契约：
- `start_serve(ws_id, kind="web") -> {status, port, message}`（沿用）
- `stop_serve(ws_id) -> {status}`（沿用）
- `get_serve_logs(ws_id, after_seq) -> AsyncIterator[{seq, stream, line}]`（新增）

### C2 · CDP 抓取引擎（后端）

- 现状：`browser_service.py:181-199` 硬编码 `headless=True`，只有 screenshot/交互，不抓 console/network。
- 改造：
  - `headless` 改为可配（默认仍 headless；抓取场景可非 headless 供人看，但 SP1 主预览走 iframe，所以抓取实例默认 headless 即可，devtools 场景再非 headless）。
  - `BrowserSession` 加监听：`page.on("console", ...)`、`page.on("response", ...)`、`page.on("pageerror", ...)`，写入两个 ring buffer（console / network）。
  - 用 Playwright 自带 Chromium（`playwright install`），不依赖私有 `@x-apaas` 源（对 SP3 客户交付友好）。
  - 新方法：`get_console_logs(after_seq)`、`get_network_requests(after_seq)`（network 只记 status>=400 与失败，避免噪音）。
  - 新端点（`backend/app/routes/browser.py` 一带）暴露 console/network；供 C4 面板与 C5 自愈消费。
- devtools：SP1-a 的「在 DevTools 打开」= 让该 CDP Chromium 实例以非 headless + `--auto-open-devtools-for-tabs` 打开同一 URL（独立窗口）。

接口契约：
- `launch_capture(url) -> session_id`
- `get_console_logs(session_id, after_seq) -> [{seq, level, text, location}]`
- `get_network_requests(session_id, after_seq) -> [{seq, url, status, method, failed}]`
- `open_devtools(session_id)`、`close_capture(session_id)`

### C3 · serve↔preview 接通（前后端）

干掉「两个平行世界」：开发态预览直接吃 dev server（带 HMR），不再走 UMD 包。

- 现状：`CustomPagePreviewPanel.vue:71` 的 `hostUrl` 指向 `/api/applications/{app_id}/custom-page-host`（`section_content.py:1224-1342` 生成 Vue2+ElementUI host HTML，加载 UMD + 注入 `$request`/`window.df` shim）。
- 改造：
  - 预览源在「开发态」（serve 运行中）切到 dev server URL；「已部署/只读态」仍走 UMD host（保留作回退）。
  - dev server 页面需要 `$request`/`window.df` shim 与 `/apaas/backend` 数据代理（带平台 auth，沿用 `runtime_proxy.py`）。注入方式（实现期定，见 §8 未决）：优先在工作区 dev 模板的 index.html 注入 shim；备选用一层薄 proxy 在 dev server 响应里注入。
  - 面板内嵌 iframe 指向「带 shim 的 dev server URL」；同一 URL 也喂给 C2 的 CDP 抓取实例（双面同源）。
- Tauri：iframe 加载 `http://127.0.0.1:{port}` 已被 capabilities 放行，无需新增 shell 权限（进程都在 sidecar 里 spawn）。

### C4 · 运行/调试面板（前端）

- 落点：CodingPage 右栏（现 FileTree + CodeViewer 容器，`CodingPage.vue:312-340`）新增「运行/调试」tab（与文件树、Diff 并列，可拖宽）。
- 内容：
  - 运行/停止按钮 → `codingApi.startServe/stopServe`（`coding.ts:230-241`），状态查 `getServeStatus`。
  - 实时日志：订阅 C1 的 `serve-logs` SSE，带自动滚动 + 错误高亮。
  - 预览 iframe：指向 C3 的带 shim dev server URL；HMR 生效（改一行即时变）。
  - 控制台/网络面板：拉 C2 的 console/network。
  - 「在 DevTools 打开」：触发 C2 `open_devtools`（独立 Chromium 窗口）。
- D1 落实：iframe（人看，嵌在 app 内）+ CDP Chromium（抓取 + devtools），两者同 URL。

### C5 · AI 自愈循环 `drive_coding_with_autofix`（后端，SP1-b）

- 现状：仅注释（`agent.py:203-204`、`prompts.py:21-23`），函数不存在，改完即终止（`should_terminate` 见 `agent.py:240-264`）。
- 实现：在 coding agent 外层包一个驱动循环：
  1. agent 改文件（write/edit）。
  2. 自动跑：build 或 serve + C2 加载预览 URL。
  3. 收集失败信号：build 报错 + C2 的 `console.error`/`pageerror` + network ≥400/失败。
  4. 有信号 → 组装 `fix_hint` 塞回 `ctx.input`，重新进 agent 一轮。
  5. 无信号或达上限 → 结束。
- 防死循环：`max_autofix_rounds`（如 3）、同一报错重复出现即停并如实上报、计入 token 预算。
- 复用 Agent Observability（若已埋点）记录每轮 fix_hint 与结果。

## 5. 关键时序

### 5.1 人工调试（SP1-a）
1. 用户在运行/调试面板点「运行」→ `start_serve` 起 dev server，返回 port。
2. 面板订阅 `serve-logs` SSE（实时日志）；iframe 加载带 shim 的 dev server URL；C2 起 CDP 抓取同 URL。
3. 用户/AI 改一行 → vue-cli HMR 热更新 → iframe 即时变 + 日志流出 + 控制台/网络面板更新。
4. 需要深查 → 「在 DevTools 打开」。

### 5.2 AI 自愈（SP1-b）
1. AI edit_file。
2. 驱动循环跑 build/serve + CDP 加载。
3. CDP 抓到 `console.error: xxx is not a function` / network 500。
4. 组 `fix_hint`「运行时报错：…，请修复」回灌 → AI 再改 → 再跑 → 干净则止。

## 6. 错误处理与边界

- node/npm 找不到（`runtime_env.py:24-54` 探不到）：明确报「请在环境里安装 Node ≥ X」人话，不静默失败。这条是 SP3 内置 node 的前置。
- 端口冲突：沿用 socket 探活换端口。
- 进程清理：会话结束/切应用/停止 → kill dev server + CDP 实例（沿用 `_serve_processes` kill + 新增 CDP `close_capture`）。
- 私有 `@x-apaas` 依赖：二次开发组件 `df-apaas-cli` 这条仅在能连私有源的环境完整；SP1 不解决离线（SP3），但要把「依赖装失败」大声报出来，别像现在掩盖。
- CDP Chromium 缺失：SP1 在开发机上用 Playwright 自带 Chromium；客户机随包归 SP3，缺失时降级为「仅日志 + iframe 预览，无 console/network 抓取」。

## 7. 测试策略

- 单测：日志流 readline→ring buffer→seq 推送；CDP console/network 监听 hook 解析；serve↔preview URL 拼装 + shim 注入点。
- 集成：`start_serve` → `serve-logs` SSE 收到行 → CDP launch_capture 收到 console → `stop_serve` 清理干净。
- 端到端（开发机）：真实跑一个二次开发组件 —— 改一行 → HMR → iframe 变 → 控制台看到注入的报错；SP1-b 造一个运行时错让 AI 自愈一轮修好。
- 回归：原有 `start_serve`/`stop_serve`/部署预览路径不被破坏。

## 8. 与 SP2 / SP3 的接口

- 复用点：`RunSession` 编排（`kind` 扩 `h5`）、`serve-logs` SSE、CDP 抓取引擎、运行/调试面板。
- SP2：把小程序生成导成真实 uni-app 工程后，`start_serve(kind="h5")` 跑 `dev:h5`，预览 iframe 直连（uni-app H5 不需要 apaas shim），其余复用。
- SP3：内置 portable Node、离线依赖（含私有源处理）、Chromium 随包、微信工具检测降级。SP1 的「node 缺失明确报错」「CDP 缺失降级」是其落点。

## 9. 风险与未决问题（实现期验证）

1. shim 注入方式：vue-cli serve 的 dev 页面如何稳定带上 `$request`/`window.df` + `/apaas/backend` 代理 —— 默认走「dev 模板 index.html 注入」（改动最小、不引代理层）；若 HMR 被破坏再退「薄 proxy 注入」。实现期用一个真实二次开发组件验证两种各能否保住 HMR。
2. iframe 鉴权：dev server localhost 无 auth，但其数据调用要经 `runtime_proxy` 带平台 token；确认 shim 里 `$request` 正确指向带 auth 的后端代理。
3. CDP 抓取实例与 iframe 同源但是两个进程，确认两边 HMR 状态一致（同一 dev server，理论一致）。
4. SP1-b 自愈循环与现有 coding pipeline 的衔接点（在哪层包驱动循环、如何不破坏现有 SSE 事件流），需对照 `agent.py` 退出点谨慎接入。
5. Playwright 非 headless Chromium 在打包后能否定位到（开发机 OK；客户机归 SP3）。

## 10. 实现顺序建议（供 plan 细化）

- SP1-a：C1（流式日志）→ C2（CDP 抓取）→ C3（serve↔preview）→ C4（面板）。
- SP1-b：C5（自愈循环，依赖 C2）。
