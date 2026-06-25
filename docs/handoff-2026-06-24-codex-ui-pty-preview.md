# 交接 — Code 模式 Codex 化 + PTY 终端 + 预览联动 + 端口持久化(2026-06-24)

> 换会话接手必读。本会话很长,核心是把 Code 模式做成 Codex 观感 + 可交互终端 + 预览联动,并修了一串 bug。
> 分支 `dev`。**push 全程被阻塞**(本机无 GitHub 凭证:osxkeychain 空 / 无 gh / 无 token)。

---

## 0. ⚠️ 最关键的两件事(先看)

1. **已提交的 Codex UI 是坏的,修复在工作树未提交。**
   - `d22d74c3`(0.2.27)提交了 Codex 化,但那一版 `frontend/src/styles/codex-tokens.css` 的头部注释里有 `--t-*/--line` → 其中 `*/` **提前闭合了 CSS 注释** → 整个 `.codex-skin { --cx-* }` 定义块没进 CSSOM → 所有 `--cx-*` 颜色为空 → 主题全白、模型下拉炸、面板乱。
   - **修复(改注释去掉 `*/`)+ 后续所有功能都在工作树未提交。** 所以:**从 HEAD 构建 = 坏的白版;工作树 = 好的版本。务必把工作树提交掉。**
   - 这个 `*/`-in-CSS-注释 坑本会话踩了**两次**(先 CodingPage.styles.css 后 codex-tokens.css)。以后写 CSS 注释避开 `--x-*/` 这种 `*/` 相邻。

2. **未提交工作必须提交**(含上面的关键修复 + 下面所有功能)。当前 `tauri.conf.json` = 0.2.32(未提交)。

---

## 1. Git 状态

**已提交(dev,顶 `f00385d4`):**
- `45c5485e` feat(observability): coding+builder 接入 recorder
- `edcd1326` feat(coding): 二次开发调试闭环(预览接真数据 + 运行时报错回流)
- `3c42ec26` chore: 版本→0.2.25
- `5ffa2909` fix(coding): 失败错误可读化(describe_exception)+ run 收尾 shield
- `86c25f45` chore: →0.2.26
- `d22d74c3` feat(coding): **Code 模式 Codex 化(对话流 restyle + 外壳/命令面板 + 四面板)← 含 `*/` bug,坏**
- `f00385d4` chore: →0.2.27

**未提交(working tree,= 0.2.28→0.2.32 的全部内容,是好的版本):**
- M `frontend/src/styles/codex-tokens.css` — **`*/` 注释 bug 修复**(关键)
- M `frontend/src/views/CodingPage.vue` — 恒暗 force-dark + 终端 server-detected 接线 + 预览联动守卫
- M `frontend/src/views/coding/RunDebugPanel.vue` — 停止按源分流(terminal=断开跟踪)+ 终端源不显示「抓取不可用」
- M `frontend/src/views/coding/panels/TerminalPanel.vue` — 多 tab 终端管理器
- ?? `frontend/src/views/coding/panels/TerminalTab.vue` — 单 PTY 终端(xterm+WS+URL 嗅探)
- ?? `frontend/src/views/coding/detectServerUrl.ts` + `.spec.ts` — dev server URL 探测纯函数(7 测)
- M `frontend/vite.config.ts` — `/api` 代理加 `ws: true`(dev 下 WS 用)
- M `frontend/package.json` / `package-lock.json` — 装了 `@xterm/xterm` + `@xterm/addon-fit`
- M `backend/app/routes/coding.py` — **PTY WebSocket 路由** `@router.websocket("/workspace/{ws_id}/pty")`
- M `src-tauri/src/lib.rs` — **端口持久化**(`stable_port` → data_dir/ui_port,免每次重登)
- M `src-tauri/tauri.conf.json` — 0.2.32
- ?? `docs/superpowers/specs/2026-06-24-unify-preview-source-plan.json` — 预览联动主计划

**下一步**:① 把工作树提交(建议拆 2-3 个 commit:Codex-fix+theme / PTY 终端 / 预览联动+端口持久化)② push(需用户凭证或 token)。

---

## 2. 本会话做了什么(按功能)

### 2.1 可观测埋点(已提交 45c5485e)
recorder(`app/observability/recorder.py`)接进 coding(CodingAgent 的 before_run/after_run/on_llm_response/after_tool_call hook)和 builder(SpecAgent.run + 补 usage 采集,gated on tenant_id)。删了从未实例化的死 `error_recorder`。routes/chat.py 把 user_id/conversation_id/app_id 接进 SpecAgent.run。

### 2.2 二次开发调试闭环(已提交 edcd1326)
- **agent 驱动预览接真数据**:`_run_workspace_preview`(agents/coding/tools.py)之前不传 apaas_api_base/proxy_target → 永远 mock(用户「接真实 API」失败根因)。抽共享 resolver `app/coding/preview_data.py`(路由 manage_serve 与 agent 共用),agent 路径用 `_with_db` + relogin 兜底解析 tenantCode/appCode,proxy_target 用 `settings.port`。
- **运行时报错回流(模式 B)**:预览 harness 注入 JS 采 window 报错/console.error/fetch 失败 → postMessage → RunDebugPanel → 后端环形缓冲 → 新工具 `get_runtime_errors` 按需读(不自动改)。

### 2.3 「unknown error」修复(已提交 5ffa2909)
- 根因:codegen 首个 LLM 调用超时,异常 `str(e)` 为空 → adapter 回退「unknown error」。`agents/coding/adapter.py:55`。
- 修:`describe_exception()`(agents/base.py,空则退回异常类型名)用在 base.py 两处失败出口 + read_query.py。
- coding `after_run` 的 `recorder.end_run` 加 `asyncio.shield`(否则取消时 run 卡 running + error 写不进库)。

### 2.4 Code 模式 Codex 化(部分提交 d22d74c3=坏 + 工作树=修复)
- **Phase 0** `frontend/src/styles/codex-tokens.css`:唯一 `--cx-*` 定义(.codex-skin 作用域,取自 `frontend/dist/aichat-mockup.html` 设计稿)+ main.ts import。
- **Phase 1** 对话流 restyle:`.coding-body codex-skin` + CodingPage.styles.css 桥接(旧 --t-*/--line→--cx-*)+ 13 段 :deep() 覆盖共享组件。**0 改数据逻辑**。
- **恒暗修复(工作树)**:全局默认 light,token 桥接盖不住组件里写死的 `html:not([data-theme=dark])` 浅色规则 → Code 模式挂载强制 `data-theme=dark`、卸载还原(不持久化,不走 setTheme,embed 模式不强制);CodeViewer/RunDebugPanel 传 `:dark="true"`。CodingPage.vue 的 `applyCodexDark()`。
- **Phase 2** 外壳+命令面板:`useCodexPanels.ts`(状态机 + ⌘K/⌘P/⌘T/⌃⇧G 匹配纯函数,11 测)+ `CommandPalette.vue` + `CodexPanelHost`(在 CodingPage 内,段控顶栏替换旧 ws-pane-tabs)。状态机:`codePaneOpen` 别名 `panelOpen`(1:1 等价,守住懒加载/切会话守卫),`wsPaneTab`→`activePanel`(4 值)。
- **Phase 3** 四面板:审查(ReviewPanel,wsGitChanges 文件清单+摘要)/ 终端(见 2.5)/ 浏览器(RunDebugPanel + 地址栏)/ 文件(FileTree+CodeViewer 复用)。
- 设计稿:`docs/superpowers/specs/codex-clone/`(6 份)+ master plan。

### 2.5 PTY 交互式终端(工作树未提交)
- **后端** `routes/coding.py` 的 `@router.websocket("/workspace/{ws_id}/pty")`:pty.openpty + zsh,WS 双向(二进制=键入,文本=resize JSON),token 走 query 鉴权。**Ctrl+C 修复**:`preexec_fn` 做 `setsid()` + `ioctl(slave, TIOCSCTTY)`(否则 SIGINT 投不到前台进程组,^C 只回显不杀进程)。退出 killpg 整组。
- **前端** `TerminalTab.vue`(xterm + WS + server URL 嗅探)+ `TerminalPanel.vue`(多 tab:终端1/终端2/＋,各自独立 shell,× 关闭)。
- xterm 已装;vite 代理加 `ws:true`。冻结桌面包已含 websockets(ruijing-sidecar.spec 第 38-39 行)。

### 2.6 预览联动 B(v1,工作树未提交)
单一真相源 = `codingStore.activePreview`,终端探测 + agent start_serve 都喂它,浏览器面板永远反映:
- 终端输出嗅探 dev server URL(`detectServerUrl.ts`,覆盖 vite/vue-cli,剥 ANSI,跨帧缓冲,末次命中)→ TerminalTab emit `server-detected` → TerminalPanel 转发 → CodingPage `onTerminalServerDetected` 写 activePreview(source:'terminal')。
- **守卫**:终端源不抢焦点(activePreview.dev_url watch 跳过 terminal);agent 流式中不被终端顶占(`isStreaming && source==='agent'` 时 return);autofix「修好没」仍只读后端 `is_serve_running(ws_id)`,绝不读 activePreview。
- 停止按源:terminal=「断开跟踪」(只清 UI,不杀 PTY 进程);agent/panel=「停止」(调 stopServe)。
- **v1 未做(deferred,见主计划 json)**:Map<wsId>(现单 activePreview)、后端两套 start_serve 端口收口、死端口存活轮询、启动预览复用终端 server。

### 2.7 端口持久化(工作树未提交)
`src-tauri/src/lib.rs` `stable_port(data_dir)`:复用 data_dir/ui_port 上次端口(空闲就用),被占才另选并存。根因:之前 `pick_free_port` 每次随机 → WebView origin(含端口)变 → localStorage 的登录 token 跟着 origin 丢 → 每次重装/重启要重登。修后 origin 稳定,token 留得住(装 0.2.32 后还要登最后一次,之后免登)。

---

## 3. 验证状态
- 后端全量(committed 部分):1342 passed。
- 前端 coding 单测:84 passed(含 useCodexPanels 11、detectServerUrl 7);build:nocheck 绿。
- **Codex UI + PTY + 预览联动:真机(preview)逐项验过** —— 恒暗主题、模型下拉、命令面板 ⌘K、四面板、PTY 执行命令+Ctrl+C(`sleep 30`→^C→立即中断)、多 tab 独立 shell、终端 server→浏览器面板自动反映(echo URL→地址栏+iframe 变)。截图均通过。
- **端口持久化:仅 cargo 编译通过,免登行为需真机重启验证**(没法在 headless 验)。
- DMG 已出到 0.2.32(在 `~/Downloads/`)。

---

## 4. 待办 / 已知问题
1. **提交 + 推送工作树**(最优先;含关键 `*/` 修复)。push 需用户 GitHub 凭证。
2. **SSE 解析失败 banner**「部分 SSE 事件解析失败,结果可能不完整」(`useCodingPipeline.ts:392-406`):非致命(文件真写了,刷新即完整),预存非本会话引入。拆帧(utils/sse.ts)+ 后端出帧(harness.py json.dumps)都看着对,疑似超大事件(写 umd.js 大包)边角。**未根治**——需先加诊断日志打出失败 payload 头部再对症修(用户未拍板要不要做)。
3. 预览联动 v1 的 4 个 deferred 项(见 2.6)。
4. 运行时报错→agent 是模式 B(呈现,非自动改)。

---

## 5. 环境 / 踩坑速查
- **后端 reload=False**:改后端必重启 `cd backend && .venv/bin/python run.py`(background)。.venv 是 py3.13。
- **本地 dev DB = SQLite `/tmp/fb_demo.db`**(不是 config 里的 MySQL)。admin: id=1, tenant_id=63, apaas_tenant_id=854768733351051265。33 个工作区。
- **DMG**:`./scripts/build-desktop.sh` → `src-tauri/target/release/bundle/dmg/`。`TAURI_SIGNING_PRIVATE_KEY` 报错无害(updater 签名;DMG 在那之前已生成)。前端 `build:desktop`(VITE_BASE_URL=/)**不跑 vue-tsc**(预存类型错不挡)。
- **SendUserFile 工具会话中途被禁用** → 改 `cp 到 ~/Downloads/ + open -R` 交付 DMG。
- **真机调试 preview**:`.claude/launch.json`(frontend,autoPort:false,port:5173)。先 kill 残留 :5173 node。鉴权用铸 token 注入:`create_access_token(user, tenant_id)` → localStorage('token') → 直达 /coding。导航 `打开` 工作区偶发跳根,重试即可。WS URL=`ws://host/api/coding/workspace/{ws}/pty?token=`。
- **桌面端口动态**:lib.rs `pick_free_port`(已加 `stable_port` 持久化)。WebView 加载 `http://127.0.0.1:{port}/`,sidecar 经 `--port` 拿到。
- **`*/`-in-CSS-注释坑**:注释里 `--x-*/` 会提前闭合注释,build:nocheck 不报「规则丢失」,只能真机视觉核对发现。**UI 改动必须真机截图核对再打包**(本会话教训:0.2.27 没核对直接出包=白版)。
