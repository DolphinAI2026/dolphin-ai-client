# 对话驱动「运行/调试」— 设计文档

- 日期：2026-06-18
- 关系：**重做 SP1 的 C4 呈现层**（手动「运行/调试」tab → 对话驱动）。C1（流式日志）/C2（CDP 抓取）/C3（serve↔preview）/C5（自愈循环）引擎**保留复用**。
- 前序：`docs/superpowers/specs/2026-06-18-inapp-run-debug-loop-sp1-design.md`（SP1 原设计）

## 1. 背景与动机

SP1 把「运行/调试」做成 CodingPage 右栏一个独立 tab + 手动「运行」按钮（传统 IDE 面板）。用户装包实测后反馈两点：

1. **体验方向错**：要的是 Claude Code 那种——在对话里说「跑一下/调一下」，或 agent 改完代码自己跑+验证+报错自愈，过程和结果在对话流里，而不是一个手动 tab+按钮。
2. **登录跳转 bug**：点「运行」→ 被踢到登录页。根因（已查实）：`RunDebugPanel.start()` 修好预览后触发 `captureStart` → 打到 `/browser/capture/start`，该路由挂在老 IDE 浏览器路由上、要求 `ide_access` token；面板用的是普通用户 JWT，`type` 不符 → 后端 403 → 前端全局拦截器（`request.ts:62`）清 token + 跳 `/login`。

本设计同时解决两者：把触发收回对话（agent 进程内调用，绕开 HTTP capture 路由 → 403 消失），把呈现改成「对话出卡 + 对话驱动预览位」。

## 2. 已确认决策

- 方向：**对话驱动**（agent 在对话里驱动跑/调），手动 tab 按钮删除。
- 触发：**两者都要** —— ① agent 改完一轮代码自动跑+验证+自愈（开 C5，默认开）；② 用户在对话里说「跑/调」即时触发。
- 呈现：**混合** —— 对话流出一张紧凑「运行结果」卡 + 一个被对话驱动的「预览位」（复用现右栏区域，无手动按钮）。
- 触发机制：**新 agent 工具**（不复用 run_command，后者一次性、接不上预览位）。
- 预览位：右栏 tab「运行/调试」→「预览」，对话驱动，无手动运行按钮（留「停止」收 dev server）。
- 范围：只做 CodingPage 二次开发组件这条对话；小程序工程化仍是 SP2。

## 3. 目标 / 非目标

### 目标
- coding agent 能在一轮对话里：起 dev server、（有 CDP 时）抓运行时报错、把结果以「运行结果」卡 + 预览位呈现。
- agent 改完代码自动跑+自愈（C5 默认开），用户也能即时「跑一下」。
- 删除手动 tab 的运行/捕获路径 → 登录跳转 bug 消失。

### 非目标
- SP2：小程序 uni-app 工程化。
- SP3：客户机运行时打包（内置 Node/Chromium/playwright 冻结）。**本设计在包内 CDP 仍降级**（见 §7）。
- 不新增 LLM 意图路由：LLM 靠工具描述自行决定何时调 `run_workspace_preview`。

## 4. 架构总览

```
对话(CodingPage 右栏 chat)
  用户「跑一下」 ──▶ LLM 调 run_workspace_preview 工具 ─┐
  agent 改完一轮代码 ──▶ C5 drive_coding_with_autofix ─┤
                                                       ▼
            后端(进程内,不走 HTTP capture 路由)
              start_serve(RunSession, C1) + launch_capture(BrowserService, C2)
                                                       │ 统一 payload
                                                       ▼
                              run_result 事件(SSE)
                                   │                       │
                          对话流「运行结果」卡        驱动「预览位」(iframe→dev_url
                          (状态/URL/报错/自愈轮)        + console/network 面板)
```

## 5. 组件设计

### B1 · 新 agent 工具 `run_workspace_preview`（后端）
- 位置：`backend/app/agents/coding/tools.py`（注册）+ `backend/app/agents/coding/tool_registry.yaml`（必加 entry，否则 agent 不可见——见项目记忆）。
- 入参：可选 `kind`（web/h5，默认 web）；workspace 取 `ctx.workspace_id`。
- 行为（进程内）：
  1. `WorkspaceManager().start_serve(ws_id, kind)` → port → `dev_url=http://127.0.0.1:{port}/`（复用 C1）。
  2. CDP 可用时（playwright 可 import）：`BrowserService.get_instance().launch_capture(dev_url)` → 等待 domcontentloaded → `get_console_logs/get_network_requests`（复用 C2）；不可用则跳过（降级）。
  3. 读 RunSession 日志尾（C1 ring 最近 N 行）。
  4. 返回结构化 dict：`{dev_url, status, log_tail: [str], console_errors: [str], network_errors: [str], capture_available: bool}`。
- 该工具结果即 agent 的 tool_result；pipeline 把它归一成 `run_result` payload（见 B3）。

### B2 · 打开 C5 自愈（后端）
- `CODING_AUTOFIX_ENABLED` 默认改为开（对话驱动下 agent 改完一轮自动 build/serve+抓错+回灌 fix_hint 重跑）。复用已建好的 `drive_coding_with_autofix`（C5）。
- C5 的 `autofix_round` 事件归一进 `run_result` payload（同 B3）。
- 包内降级：C5 在无 CDP 时只做 build 报错自愈（`build_project` 不依赖 playwright），运行时抓取跳过——已是 C5 现有行为。

### B3 · 统一 `run_result` 事件（后端 pipeline）
- 定义一个前端可识别的事件载荷：`{type:"run_result", source:"manual"|"autofix", dev_url, status, log_tail, console_errors, network_errors, capture_available, round?}`。
- 两个来源都产出它：① `run_workspace_preview` 工具结果（on-request）；② C5 `autofix_round`（auto）。
- pipeline 把它 append 进 replay + yield（与现有事件同路径，前端不识别也无害）。

### F1 · 对话流「运行结果」卡（前端）
- 在 CodingPage 的消息流渲染里加一种卡片：识别 `run_result` 事件（由 pipeline 从工具结果与 C5 autofix 归一，见 B3——前端只认 `run_result` 这一种）→ 渲染状态(运行中/编译成功/报错 N 条/自愈第 k 轮)、dev URL、报错摘要、「查看预览」按钮。
- 复用现有 tool/diff 卡的渲染套路（`useStreamMessages`/消息卡组件）。
- 纯展示状态(状态归一、报错聚合)抽成 pure `.ts` + vitest 单测（对齐 runDebugState 套路）。

### F2 · RunDebugPanel → 对话驱动「预览位」（前端，改造）
- **删**：运行/停止按钮里的 `startServe`/`captureStart`-on-run 逻辑（即 403 根源）。
- **改**：监听一个反应式「当前运行」状态（如 codingStore.activePreview `{dev_url, capture_session, capture_available}`，由 `run_result` 事件写入）→ 预览位 iframe 加载 `dev_url`；控制台/网络面板吃该次抓取数据；CDP 不可用时面板标「运行时抓取不可用」。
- 右栏 tab：「运行/调试」→「预览」；「文件/代码」保留;「查看预览」卡片按钮切到「预览」tab。
- 保留一个「停止」收 dev server（调 stopServe，正常用户鉴权，无 403）。
- C2 的 `/browser/capture/*` HTTP 路由（SP1 Task 5）**本路径不再使用**（agent 进程内调）；作为死代码在本次一并删除（含其测试），避免遗留 ide_access 误用面。

## 6. 数据流（两条）

### 6.1 on-request（用户「跑一下」）
用户消息 → LLM 调 `run_workspace_preview` → 后端起 serve(+CDP) → 工具结果 → pipeline 发 `run_result(source=manual)` → 前端出卡 + 预览位加载 dev_url。

### 6.2 auto（agent 改完一轮）
agent 编辑 → C5 build/serve+抓错 → 有错回灌 fix_hint 重跑 → 每轮发 `run_result(source=autofix, round=k)` → 前端卡片显示「验证中/发现 N 错/修复中/已通过」，预览位随末轮 dev_url 更新。

## 7. 包内降级（诚实边界）
打包 sidecar 排除 playwright（`ruijing-sidecar.spec` excludes，无法冻结）：
- **能用**：起 dev server、实时日志、预览位 iframe + HMR、**build 报错自愈**。
- **降级**：运行时 console/network 抓取、DevTools、**运行时报错自愈**。卡片 + 预览位标「运行时抓取不可用（需 dev 模式）」。`capture_available=false` 贯穿前后端。
- 根治在 SP3（内置可冻结运行时 / 外置 Chromium）。

## 8. 登录跳转 bug 的处置
- 对话驱动下 agent 进程内调 BrowserService/WorkspaceManager，**不经** `/browser/capture/*`；F2 删除前端 `captureStart`-on-run → 该 403 路径无调用方 → 跳登录消失。
- 一并删除 `/browser/capture/*` 路由 + 其 ide_access 测试（死代码）。
- 不动全局拦截器（`request.ts:62` 的 401/403→login 行为对其余正常路径仍正确）。

## 9. 错误处理与边界
- node/npm 缺失：工具返回 status=error + 人话（沿用 C1）；卡片显示「未找到 Node」。
- 端口冲突 / 进程清理：沿用 RunSession kill；切工作区/会话结束停 serve。
- serve↔preview shim：仅对**新建** form-page 工作区生效（dev 模板 public/index.html，C3）；存量工作区能跑能 HMR，apaas 数据调用不走 shim——卡片/文档注明。
- 自愈防死循环：沿用 C5（max 3 轮 / 同错重复即停 / 计 token）。

## 10. 测试策略
- 后端：`run_workspace_preview` 工具单测（mock RunSession/BrowserService，验返回 payload + CDP 降级分支）；`run_result` 归一单测；C5 已测（复用）。
- 前端：运行结果卡的纯状态归一 vitest 单测；预览位驱动（无 unit runner 的 SFC 走 preview 验证）。
- 回归：删 `/browser/capture/*` 后 import + 全量测试不破；startServe/stopServe/deploy 路径不变。

## 11. 复用 / 改动 / 删除 账
- **复用**：C1 RunSession + serve-logs、C2 BrowserService capture、C3 serve↔preview + shim、C5 drive_coding_with_autofix。
- **改造**：C4 RunDebugPanel（手动面板 → 对话驱动预览位）；pipeline（发 run_result）；coding agent（加工具 + 默认开 C5）。
- **删除**：C2 的 `/browser/capture/*` HTTP 路由 + 测试（死代码）；前端 capture endpoints（serveLogsUrl 保留给日志流；captureStart/Console/Network/Devtools/Stop 删）；手动运行按钮。

## 12. 未决（实现期定）
- 「运行结果」卡与现有 tool 卡的视觉对齐细节（实现期按现有卡样式走）。
- on-request 工具是否同时把 CDP 抓取做进去，还是分两个工具（preview / inspect）——倾向合一（一个工具，capture_available 控制深度），实现期确认。
