# 交接：桌面端「运行/调试」对话驱动闭环（2026-06-18）

> 给换 session 接手的人。冷启读这一份 + 两份 spec/plan + 记忆 [[desktop_debug_loop_sp1_2026_06_18]] 就够上手。

## 0. 一句话现状

低代码交付里「PC 配管理后台 + 移动端做小程序 / 二次开发组件」这类场景，用户想在 **desktop app 内直接调试生成的代码**（不用 download 去 VS Code）。已落地一套 **对话驱动的运行/调试闭环**：在 CodingPage 对话里说「跑一下」→ agent 起 dev server + 抓运行时报错 → 对话出「运行结果」卡 + 右栏「预览」位渲染；改完代码 agent 自动跑+自愈。全绿、已打包、已 push desktop 分支。**还没真机 live 全量验证**（用户在验最新 dmg）。

## 1. 分支 / git 状态（重要，先看）

- **分支模型**：`feat/desktop-login-mvp` = **desktop 线**；`dev` = **web 线**。两条独立产品线。
- 本轮所有工作在 `feat/desktop-login-mvp`，**已 push origin**，顶 `e67e564a`（128 commit）。
- **run/debug 是 desktop 独有能力**（靠桌面 sidecar 本地 spawn dev server / Playwright，web 无运行环境）→ **不要合进 dev/web**。dev 上 `61c3919c "Merge feat… Task 6-10"` 是早先一次性同步，别再往 dev 合 desktop 的活。
- 用户工作树还有 ~49 个**未提交**的 skill/admin 在途改动（`ai_chat/skills.py`、`SkillLibraryPage.vue`、`admin-spa/*`、`src-tauri/icons/*` 等）——**不是这个功能的，别动、别 commit**。
- 本轮 commit 区间：`276d6812`(T1) → `e67e564a`(docs)，加更早的 SP1 那批（搜 commit message 含 `(C1..C5)` / `run_workspace_preview` / `运行结果卡` / `对话驱动预览位` / `预览白屏`）。

## 2. 设计（两份正式文档）

- SP1（底座，14 task，已实现）：`docs/superpowers/specs/2026-06-18-inapp-run-debug-loop-sp1-design.md` + `docs/superpowers/plans/2026-06-18-inapp-run-debug-loop-sp1.md`
- 对话化重做（取代 SP1 的手动 tab 呈现层，6 task，已实现）：`docs/superpowers/specs/2026-06-18-conversational-run-debug-design.md` + `docs/superpowers/plans/2026-06-18-conversational-run-debug.md`

## 3. 架构 / 数据流（对话驱动 run/debug）

```
CodingPage 右栏 chat
  用户「跑一下」 → LLM 调 run_workspace_preview 工具 ─┐
  agent 改完一轮代码 → C5 drive_coding_with_autofix ─┤ (默认开)
                                                     ▼ 进程内调 WorkspaceManager/BrowserService(不走 HTTP)
            后端: start_serve(起 dev server) + launch_capture(CDP 抓 console/network)
                                                     │ 事件
                            run_result(工具 emit_event) / autofix_round(C5) ──SSE──▶
                                   │                          │
                          对话流「运行结果」卡          coding store activePreview ──▶ 右栏「预览」位 iframe
```

关键文件（都在 `feat`）：
- 后端工具：`backend/app/agents/coding/tools.py` 的 `_run_workspace_preview` + `_resolve_serve_command`（在 `WorkspaceManager`，见下）+ `build_coding_tools` 里注册的 `Tool(name="run_workspace_preview", ...)`。图标 `agents/coding/agent.py:TOOL_ICONS`。
- serve 编排：`backend/app/coding/workspace.py` `start_serve`（流式日志 + `_resolve_serve_command`）、`iter_serve_logs`、`_serve_processes`。
- CDP：`backend/app/coding/browser_service.py` `launch_capture/get_console_logs/get_network_requests/open_devtools/close_capture`（Playwright，进程内）。
- 自愈：`backend/app/agents/coding/autofix_driver.py` `drive_coding_with_autofix` + `autofix_signals.py`；pipeline 接线 `backend/app/coding/pipeline.py`（`_autofix_enabled` 默认开、`_autofix_preview_url`）。
- 前端：`frontend/src/views/coding/runResult.ts`（归一器）、`stores/coding.ts` `activePreview`、`useCodingPipeline.ts` 的 `run_result`/`autofix_round` handler、`CodingPage.vue` 运行结果卡（custom slot）、`RunDebugPanel.vue`（对话驱动预览位）。
- 事件契约：见对话化 spec §「run_result 契约」。

## 4. 能用 / 不能用（务必交代清楚）

- **能用**（desktop app 内，需机器有 node）：起 dev server、实时日志、内嵌预览 + HMR、build 报错自愈、不跳登录。
- **包内降级**：PyInstaller spec `ruijing-sidecar.spec` **故意 `excludes=["playwright"]`**（playwright 无法冻结）→ 打包的 .app 里 **CDP 抓取 / DevTools / 运行时报错自愈 全降级**（`capture_available=false`，卡片标「运行时抓取不可用」，不崩）。完整 CDP 要 **dev 模式**跑。根治 = SP3 内置可冻结运行时 / 外置 Chromium。
- **预览只对「有 preview harness 的工程」生效**：`start_serve` 现在 `_resolve_serve_command` —— 工程 `package.json` 有 `preview` 脚本就跑 `npm run preview -- --port N`（preview/main.js 真 mount + preview/index.html 模板），否则回退裸 `vue-cli-service serve src/index.js`。⚠️**仓库 5 个 cli-generated 模板都没有 preview harness**（访客小程序工作区有，是 agent 生成时带的）→ **无 harness 的标准工程本地仍渲染不出**（serve src/index.js 是 UMD 库入口，只 export {install} 不 mount → 白屏）。这是下一步最该补的（见 §6）。

## 5. 踩坑速查（这轮真踩过的）

1. **预览白屏根因**：`start_serve` 跑 `vue-cli-service serve src/index.js`，但 `src/index.js` 是 UMD 组件库入口（不 mount）→ 空白。修法=用工程 `preview` 脚本（harness）。
2. **登录跳转 bug**（已修）：手动 capture 路由用 `ide_access` 鉴权，前端发普通用户 JWT → 403 → 全局拦截器 `request.ts:62` 清 token 跳 `/login`。对话驱动后 agent 进程内调、删了 HTTP capture 路由 → 根除。
3. **run_workspace_preview 是 build_coding_tools 直接工具，不是 MCP 工具 → 别进 tool_registry.yaml**（进了会触发 mcp_server 启动期 drift WARNING）。新加 coding agent 工具按 `Tool(name,description,parameters_schema,execute)` append 进 `build_coding_tools`。
4. **改后端必重启 sidecar/backend**（`backend/run.py` reload=False）；pytest 是 fresh app 不受影响。
5. **dev-mode CDP 需 `playwright install`**：本机 playwright 装的 chromium 版本对不上当前 playwright（要 r1223、缓存里是 1208）→ dev 模式验 CDP/截图前先 `cd backend && .venv/bin/playwright install chromium`。
6. **测试约定**：后端 pytest（`asyncio_mode=auto`，每测自建 StaticPool 内存库，无共享 db fixture）；前端 vitest 只覆盖纯 `.ts`（SFC 不在内，走 build:nocheck + preview 验证）。

## 6. 下一步选项（接手从这里挑）

按"离用户原始痛点近 / 价值"排：

1. **预览 harness 通用化**（建议优先）：让所有二次开发工程生成时都带 preview harness（`preview/main.js` 挂载组件 + `preview/index.html` + `package.json` 加 `preview` 脚本 + `vue.config.js` isPreview 分支）。否则只有访客小程序那种"碰巧有 harness"的能预览。改 `backend/templates/cli-generated/*` + 生成链路。参照访客工作区现成的 harness 抄。
2. **SP2 小程序工程化**：用户的原始痛点是访客**小程序**。现在小程序是 AI 对话 `write_artifact` 产物（不是磁盘真实工程）。要做成真实可运行 uni-app 工程（vendored 模板 + 把生成导成工程）→ `npm run dev:h5` 本地全 devtools 调。见 SP1 spec §SP2。
3. **SP3 客户机运行时打包**：内置 portable Node + 离线依赖（含私有 @x-apaas）+ Chromium 随包 + 微信工具检测降级 → 让 run/debug + CDP 在交付给客户的 .app 里也能用（现在包内 CDP 降级）。
4. **真机 live 全量验证**：装最新 dmg，对话「跑一下」端到端验证（预览渲染 / 自愈 / 控制台抓取在 dev 模式）；用户在验，有反馈接着修。

## 7. 怎么 build / test / verify

- 后端测试：`cd backend && .venv/bin/python -m pytest -q`（当前 1128 passed）。
- 前端测试：`cd frontend && npx vitest run`（93 passed）；构建 `npm run build:nocheck`（vue-tsc 有 ~388 预存错，只 build:nocheck 过）。
- 打包 dmg：`bash scripts/build-desktop.sh`（前端 build:desktop → PyInstaller sidecar → tauri bundle；末尾更新器签名报错 `TAURI_SIGNING_PRIVATE_KEY` 可忽略，.app/.dmg 在那之前已出，在 `src-tauri/target/release/bundle/`）。
- 冒烟：起 sidecar `"…/睿鲸 Builder.app/Contents/MacOS/ruijing-sidecar" --port P --data-dir /tmp/x`，curl `/api/health`、`/api/coding/workspace/x/serve-logs`(期望 401 已注册)。
- 验预览渲染（dev，需 playwright install）：在真实工作区跑 `_resolve_serve_command` 给的命令，Playwright headless 加载 dev_url，看 body 有内容（注意 Vue2 `el:'#app'` mount 后 #app 被替换，别用 #app.innerHTML 判空，用 body 文本）。

## 8. 未决 / 待办

- ①预览 harness 只对访客小程序那种工程有 → 标准工程白屏（§6.1 待补）。
- ②C5 默认开 = 每轮 agent 编辑后自动 build 一次（包内只 build 自愈、无运行时）；嫌勤设 `CODING_AUTOFIX_ENABLED=0`。
- ③运行结果卡的 replay：live 走 SSE handler；纯文本重建 replay 不含该卡（不崩，可接受）。
- ④运行/调试预览位在非 code-first 布局下偏窄。
- ⑤docs/记忆已提交+push 到 feat；用户 49 个未提交在途活仍在本地。
