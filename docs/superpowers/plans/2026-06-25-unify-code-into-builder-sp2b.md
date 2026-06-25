# SP2b: 把 Code 面板搬进 Builder + 删 Code 标签 — Implementation Plan

> **For agentic workers:** subagent-driven-development. Frontend-heavy → 每个 Task 的"验证"是 `npm run build:nocheck` + 浏览器 preview 实测(非单测)。后端 Task 配 pytest。

**Goal:** AIChatPage 成为唯一统一外壳:右栏挂 Codex 面板(审查/文件/终端/浏览器),内容驱动 + 按 code 会话自动聚焦;放行 SP1 两道闸让 code 会话进统一列表+可发;「我的开发」落到这里;删 Code 标签(CodingPage 留盘,SP3 退役)。

**Architecture(condensed,详见 workflow 输出):** AIChatPage 3 列 grid,右栏(aside-right,283-390)按 `isCodeSession = currentSession.mode==='code' && !!currentSession.workspace_id` 切换:code→新抽的 `CodexPanelHost.vue`,否则原设计产物 aside。数据流 session→workspace_id→面板。CodexPanelHost 从 CodingPage:347-427 抽出,props 驱动,两页复用。RunDebugPanel 解耦 useCodingStore.activePreview→prop+emit。activePreview 各页各自持有(CodingPage 回写 store,AIChatPage 本地 ref)。后端 `_session_to_dict` 补 `workspace_id`;放行时删两处 `mode != "code"`。

**已定决策:** ①「我的开发」用 query param `/ai-chat?workspace_id=X&mode=code`(非 sessionStorage dispatch)。②`run_workspace_command` v1 用普通 ToolCard 渲染(命令流卡片=fast-follow,不在本轮)。③会话列表按 updated_at 交错(不加 Code 徽标)。④保留 `MODE_META.code`(类型+localStorage 回退安全)。⑤code 会话进来内容驱动自动开 files 面板 + 头部留一个面板开关。

## Global Constraints
- 工作目录 `/Users/mars/Vibe Coding/ai-builder`。前端 `cd frontend`。
- 前端构建 `npm run build:nocheck`(vue-tsc 预存错,nocheck 是 gate);后端 `cd backend && .venv/bin/python -m pytest`(.venv py3.13)。改后端必重启 `run.py`。
- **每 Task 只 commit 本 Task 文件**(精确 `git add`)。工作树有大量无关未提交改动(Codex/PTY)——绝不 `git add -A`/`.`;提交前 `git diff --cached --stat` 自查。
- **不破坏现有 Builder(chat/cowork)行为**——每个改 AIChatPage 的 Task 都要 preview 验证 chat 会话照常。
- CodingPage 留盘可继续工作到 Task 9 nav 改完(其后非导航可达,SP3 删)。
- **workspace_id ≠ workspace_dir**:`workspace_dir`=附件临时目录;`workspace_id`(SP2a 新列)=WorkspaceManager slug,FileTree/Terminal/RunDebug 用它。传错静默坏。
- commit message 中文 + 结尾 `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`。

---

### Task 1: RunDebugPanel 解耦 useCodingStore(activePreview→prop+emit),零行为变化
**Files:** `frontend/src/views/coding/RunDebugPanel.vue`, `frontend/src/views/CodingPage.vue`
**Change:** RunDebugPanel.vue:删 useCodingStore import(~43)+实例(~47);加 prop `activePreview: ActivePreview | null`(类型从 `@/stores/coding` 引或重声明)+ emit `update:activePreview`。`~59` `computed(()=>codingStore.activePreview)`→`computed(()=>props.activePreview)`;`~136` `codingStore.activePreview={...}`→`emit('update:activePreview',{...})`;`~169` `=null`→`emit('update:activePreview',null)`。CodingPage.vue 在 RunDebugPanel 挂载处(~394-399)加 `:active-preview="codingStore.activePreview"` + `@update:active-preview="v=>codingStore.activePreview=v"`(保住 store 回写→1231-1235 两 watcher 照常触发)。
**Verify:** `npm run build:nocheck` 过;preview `/coding`:run_result 卡点「查看预览」+ 聊天里 localhost 链接 → RunDebugPanel 仍加载 dev_url,stop() 仍清空(store 经 emit 往返)。
**dependsOn:** none

### Task 2: 抽 CodexPanelHost.vue(从 CodingPage 内联 chrome,纯移动零行为变化)
**Files:** `frontend/src/views/coding/CodexPanelHost.vue`(新), `frontend/src/views/CodingPage.vue`
**Change:** 新建 CodexPanelHost.vue,内容=CodingPage.vue:347-427(左缘 resizer + .cph-topbar 段控/动作 + 4 个 v-show 面板)。根 div 加 class `codex-skin`。Props: `wsId, open, activePanel, panelCommands, changes, selectedFile, acceptingChanges, fileTree, changedPaths, selectedDiff, selectedGitChange, viewerFocusLine, activePreview, treePaneWidth, dark?`。Emits: `update:open, update:activePanel, select-file, accept-all, select-tree, select-tree-line, viewer-quote, accept-change, server-detected, update:activePreview, tree-resize-start`。RunDebugPanel 的 `:active-preview`/`@update:active-preview`(Task1)透传。外栏宽度 resizer + codePaneWidth 留 CodingPage(宿主页控);treePaneWidth 传入、tree-resize-start 传出。CommandPalette 留 CodingPage。CodingPage 347-427 替为 `<CodexPanelHost>` 接既有 refs/handlers;previewEpoch + activePreview.dev_url watcher(1231-1235)留 CodingPage。
**Verify:** build:nocheck 过;preview `/coding`:4 tab(审查/文件/终端/浏览器)都渲染、段控切换、resize、⌘K palette、文件选+diff+accept-change 全与抽取前一致。
**dependsOn:** [1]

### Task 3: 后端 _session_to_dict 出 workspace_id;前端 AIChatSession 类型加 workspace_id + 'code' mode
**Files:** `backend/app/routes/ai_chat.py`, `frontend/src/api/aiChat.ts`
**Change:** ai_chat.py:`_session_to_dict`(~113,workspace_dir 后)加 `"workspace_id": getattr(s, "workspace_id", None),`。aiChat.ts:AIChatSession 接口(~21,workspace_dir 后)加 `workspace_id?: string | null`;mode 联合(~17)加 `'code'`;createSession body(~142)mode 联合加 `'code'` + 可选 `workspace_id`。
**Verify:** 后端 `GET /ai-chat/sessions` 与 `/{id}` JSON 含 workspace_id(chat 会话为 null)——加一条 pytest 断言 `_session_to_dict` 暴露 workspace_id(镜像 test_session_app_lock.py 的 `test_session_to_dict_exposes_app_id`)。前端 build:nocheck 过、无新类型错。无 UI 变化。
**dependsOn:** none

### Task 4: 把 CodexPanelHost 挂进 AIChatPage 右栏,内容驱动 + 本地 activePreview + 工作区数据接线
**Files:** `frontend/src/views/AIChatPage.vue`
**Change:** `<script setup>`:加 `codexPanelWsId = computed(()=>currentSession.value?.workspace_id ?? null)` + `isCodeSession = computed(()=>currentSession.value?.mode==='code' && !!codexPanelWsId.value)`(~522);实例化 `useCodexPanels()`(~707,open/active/palette);本地 `activePreview = ref<ActivePreview|null>(null)`;isCodeSession 变 true 时懒加载 `getWorkspaceChanges(wsId)`/`listWorkspaceFiles(wsId)`(同 codingApi)填 changes/fileTree;本地 selectedFile/viewerFocusLine/acceptingChanges + accept handlers;onTerminalServerDetected 写本地 activePreview(复刻 CodingPage 守卫,但用 AIChatPage 自己的 isStreaming,来自 useAiChatSession——**复刻语义别复制变量**)。Template:aside-right(283-390)加 v-if 分支:isCodeSession→`<CodexPanelHost :ws-id=codexPanelWsId v-model:open v-model:activePanel :active-preview ... @update:active-preview="v=>activePreview=v" @server-detected=onTerminalServerDetected ...>`;ELSE 现有产物 aside(保其 v-if)。isCodeSession 时隐藏头部产物 toggle(83-89)、加 code 面板 toggle(v-if=isCodeSession)。loadSession(maybeAttachRunningRun 后 ~1769)mode==='code'&&workspace_id 时自动开 files 面板。`watch(isCodeSession)`→false 时 closeHost()(防切会话残留)。usePanelResize storageKey 用 `'ai-chat:code-pane-width'`。
**Verify:** build:nocheck 过。preview:载入一个 code 会话(Task6 放行后,或临时直接 API 造 code 会话)——CodexPanelHost 挂右栏、files 自动开、产物 aside 隐藏、头部 toggle 收放;切到 chat 会话→产物 aside 回来、host 隐藏无残留。**chat 会话回归:照常。**
**dependsOn:** [2,3]

### Task 5: AIChatPage 加 #tool-renderer slot,write/edit_workspace_files 挂 FileCard(diff BLOCKER)
**Files:** `frontend/src/views/AIChatPage.vue`
**Change:** ⚠️**先核实工具 arg 形状**:读 run_agent 这两个工具的 schema(`write_workspace_files`/`edit_workspace_files` 在 `backend/app/coding/tools.py` TOOL_DEFINITIONS),确认 args 是 `content`/`file_path`/`old_string`/`new_string` 单文件,还是 `files[]` 数组——**按真实 schema 接,若是数组则 slot 内遍历每文件渲一个 FileCard**。`<AgentConversation>` 上提供 `#tool-renderer="{ tool }"` slot(slot 在 AgentConversation.vue:122 已存在,传 `:tool`)。`tool.name==='write_workspace_files'`→`<FileCard action="write" :fileContent="…" :filePath="…">`;`'edit_workspace_files'`→`<FileCard action="edit" :oldContent="args.old_string" :fileContent="args.new_string" :filePath="…">`(FileCard.vue:71-80 双值时已做 LCS 红绿)。import FileCard from `@/components/FileCard.vue`。其它工具回落默认 ToolCard(slot 返回空)。
**Verify:** preview:code 会话发构建请求 → write 渲 FileCard(绿)、edit 渲红绿 LCS diff(带 +/- 计数),不是裸 JSON ToolCard。非 code 工具(write_artifact 等)照旧。
**dependsOn:** [4]

### Task 6: 后端放行:删两处 SP1 `mode != "code"` 闸(列表 + per-session 含 run-survival)
**Files:** `backend/app/routes/ai_chat.py`
**Change:** 删 `_load_session_or_404`(~435)与 `list_sessions`(~458)的 `AIChatSession.mode != "code",` 谓词(两处 `# SP1:` 注释行)。一删同时放开 GET/PATCH/send/upload/artifacts + abort(810)/run-status(820)/attach(836)——全复用 AiChatRunBus/ai_chat_run_registry,无 code 专属逻辑。**已排在 Task4+5 之后**,放行时外壳已能渲染。
**Verify:** `GET /ai-chat/sessions` 现含 code 会话;`POST /ai-chat/sessions/{code_id}/send` 流 tool_call 事件(SP2a 分派);run-status/attach 对在跑 code 会话工作;chat/cowork 不受影响。后端全量测试 vs 基线绿(注:SP1 的 test_ai_chat_mode_scoping.py 里"排除 code"那两测会因放行而失效——**改这两测为新契约**:list 现含 code、load 现允许 code;保留 user/tenant 作用域回归测)。
**dependsOn:** [5]

### Task 7: polish — toolArgsBrief + summarizeToolResult 补编码工具 case
**Files:** `frontend/src/composables/useAiChatSession.ts`
**Change:** toolArgsBrief(~299-303)加 write/edit_workspace_files→file_path/path、run_workspace_command→command。summarizeToolResult(通用回落前 ~400)write→`✅ {path}`、edit→`✅ {path} (N 行)`、run_workspace_command→从 result JSON `✅ exit 0`/`❌ exit N`。非阻塞 cosmetic。
**Verify:** preview code 会话:args-brief 列显文件/命令(非空白)、结果 chip 显 path/exit。其它工具无回归。
**dependsOn:** [6]

### Task 8: nav 接线 — rail 会话统一路由 /ai-chat;砍 code-mode /coding 分支
**Files:** `frontend/src/composables/railSessions.ts`, `frontend/src/components/v2/RailSidebar.vue`
**Change:** railSessions.ts:删 mode==='code' 分支——railSessionTarget(48-53)恒返 `{path:`/ai-chat/${id}`}`;isRailSessionActive(61)查 `/ai-chat/:id`;railSessionFallback(69)返 `'/'`。RailSidebar.vue:删 currentMode==='code' 分支(54-58,61-72)恒用 aiChatApi sessions(normalizeAiSessions);删 codingApi.getConversations() 调用 + codingSessions ref + **不再用的 codingApi import**(防死码 lint)。openSession(115)code 会话现走 /ai-chat/:id。
**Verify:** build:nocheck 过。preview:rail 列表 code+chat 同列;点 code 会话开 /ai-chat(非 /coding)且 CodexPanelHost 挂上;无 console 错 / 无 unused-import lint 失败。
**dependsOn:** [6]

### Task 9: 删 Code mode-switcher 入口 + 4 个 /coding 调用方改 /ai-chat?workspace_id&mode=code + onMounted 消费
**Files:** `frontend/src/stores/mode.ts`, `frontend/src/views/WorkspaceCatalogPage.vue`, `frontend/src/components/v3/AppDevWorkspacePanel.vue`, `frontend/src/views/Apps.vue`, `frontend/src/composables/projectVM.ts`, `frontend/src/views/AIChatPage.vue`
**Change:** mode.ts:48 MODE_ORDER→`['builder']`(去 Code 段+⌘2)。loadMode 加 `if(v==='code')return 'builder'` 回退(localStorage 旧值)。mode.ts:38 MODE_META.code.home→`'/ai-chat'`、nav 'c-new' path→`'/ai-chat'`(防御;「我的开发」c-catalog 留 /workspace-catalog)。4 处 `router.push({path:'/coding',query:{workspace_id}})`→`{path:'/ai-chat',query:{workspace_id:String(id),mode:'code'}}`(WorkspaceCatalogPage.vue:572&587、AppDevWorkspacePanel.vue:192、Apps.vue:661、projectVM.ts:68)。AIChatPage onMounted:消费 `route.query.workspace_id`+`mode==='code'`→**建或载一个绑该 workspace 的 code-mode 会话(createSession 必须带 workspace_id=该值 + mode='code')**。/coding 路由(router/index.ts:132)+ App.vue stable-key 留着(无害)。
**Verify:** build:nocheck 过。preview:rail 无 Code 段;⌘2 no-op 不崩;「我的开发」开工作区落 /ai-chat 且该工作区 Codex 面板在(非 /coding);localStorage mode='code' 老用户进 builder 非缺 tab;直接 /coding 仍渲 CodingPage(退役非导航)。
**dependsOn:** [8]

## 关键 Risks(执行时盯)
- workspace_id vs workspace_dir 传错→tree/terminal/file API 静默坏(Task3 出对字段)。
- Task5 FileCard arg-key:实际工具可能是 `files[]` 数组——**先读 schema 再接**(最高不确定点)。
- Task6 放行后非 send 端点(upload/patch/artifacts)对 code 会话无 mode 约束——确认无害再 go-live。
- onTerminalServerDetected 的 isStreaming 必须用 useAiChatSession 的(非 coding 的),否则终端探测的 preview 会顶掉在跑 agent 的 preview。
- Task6 会让 SP1 的 test_ai_chat_mode_scoping「排除 code」两测失效——同 Task 改成新契约,别留红。
- 老 code 会话 workspace_id=NULL(SP2a 只给新会话写)→isCodeSession=false 面板不显,优雅降级(可接受)。
