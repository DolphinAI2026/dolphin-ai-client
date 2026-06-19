# Phase 2 — 统一工作区:代码面板 + workspace 绑定(设计 spec)

> 日期 2026-06-19 · 总览见 `2026-06-18-unified-desktop-workspace-roadmap.md`,Phase 1 见 `2026-06-18-unified-workspace-shell-phase1-design.md`。
> Phase 2 = 把「代码工作流」接进 Phase 1 的统一工作区:路由驱动 workspace 绑定 + 注册代码面板(文件树 / 代码-diff 查看器)+ 对话按 ws_id 操作 workspace。**绞杀式:旧 /coding 保留不动。**

## 1. 已定决策(采集 + 大明哥拍板 2026-06-19)

1. **对话引擎不变 = 单一 useAiChatSession(run_agent)。** run_agent 已挂全套 workspace 代码工具(`read/write/edit/glob/grep/run_workspace_command` + `create_dev_workspace`,deferred 经 search_tools 激活)+ app 上下文 CORE 读工具;app_dev dispatch 已把代码二次开发落到同一引擎、live 验证过。**不需要第二引擎、不需要 ChatPane 按 binding 切 useCodingPipeline。**
2. **绑定 = 路由驱动,不改后端。** `/workspace/<ws_id>` 驱动 `currentBinding = {kind:'workspace', workspaceId}`。代码面板按 ws_id 经 `codingApi.*` 渲染(与会话模型解耦)。**不改 `AIChatSession` schema、不加 workspace_id 列。** 代价(已接受):侧栏「代码会话」徽标不持久化(刷新靠路由恢复);完整持久化往后排。
3. **面板范围(据采集收紧)**:Phase 2 只做 **Files(FileTree)+ 代码/Diff 查看器(CodeViewer)**。**Preview 延后**(RunDebugPanel 读的是 coding pipeline 的 `activePreview` store,由 coding SSE `run_result` 事件写;统一工作区走 AIChat SSE,需另写 tool-result→preview 适配,非本期)。**Terminal = Phase 4。**

## 2. 目标 / 非目标

**目标**
- `/workspace/:id?` 的 `:id` = ws_id,驱动 workspace 绑定(Phase 1 未消费此参数)。
- 注册两个 context 面板(替换 Phase 1 的 `stub-code`):`files`(文件树)、`code-view`(文件/diff 查看器),`availableWhen: binding.kind==='workspace'`。
- 打开 workspace 时:加载文件树 + git 改动,面板可浏览文件、看 diff。
- 对话:把 ws_id 作为上下文喂进 `useAiChatSession` → run_agent,使其代码工具操作该 workspace。
- 资产库入口 `WorkspaceCatalogPage.openWorkspace` → 改指 `/workspace/<ws_id>`(原指 `/coding`)。
- 顺手:清 ChatPane 重复头部按钮(产物/历史/新建已被外壳 ToolMenu/SessionSidebar 接管)。
- `currentBinding` 从写死 `{kind:'none'}` 改为路由/会话驱动。

**非目标(后续)**
- Preview 面板(AIChat 引擎的 run_result→activePreview 适配)= Phase 2.5 / 与 Phase 4 一起。
- 集成终端 = Phase 4。
- 会话↔workspace 后端持久化(AIChatSession.workspace_id)= 暂不做。
- 旧 /coding 退役 = Phase 4。
- 侧栏混列 Coding `Conversation` 与 AIChat 会话 = 不做(两套会话模型不合并)。

## 3. 架构与改动单元

```
frontend/src/views/workspace/
├─ WorkspaceShell.vue          改: watch route.params.id → currentBinding;
│                                  workspace 态加载文件树/改动编排; 把 wsId 喂 ChatPane
├─ panels/
│  ├─ FilesPanel.vue           新: 包 FileTree, 拉 tree+changes, 维护 selected(复刻 CodingPage ~50 行编排)
│  └─ CodeViewPanel.vue        新: 包 CodeViewer, 按 selected 文件展示内容/diff
├─ panels.ts                   改: 删 stub-code, 注册 files + code-view(availableWhen workspace)
├─ workspaceData.ts            新(纯/composable): 按 ws_id 拉 tree/changes 的逻辑(可测)
└─ ChatPane.vue                改: 去重复头部按钮; 接 workspaceId 上下文入参

frontend/src/views/WorkspaceCatalogPage.vue   改: openWorkspace → push('/workspace/<ws_id>')
```

**复用(不重写,采集确认契约)**
- `@/views/coding/FileTree.vue`:props `{ tree, changed:Set, changes?, selected, wsId? }`;emits `select(path)`/`select-line({path,line})`/`accept-all`。**父必须喂 tree+changes**(自身不拉)。
- `@/views/coding/CodeViewer.vue`:props `{ wsId, filePath, change?, focusLine?, dark? }`;自调 `readWorkspaceFile`/`getWorkspaceFileDiff`,内部 diff/full 自管;emits `quote`/`accept-change`。
- `@/api/coding.ts`:`getWorkspace(wsId)` / `listWorkspaceFiles(wsId)` / `getWorkspaceChanges(wsId)` / `getWorkspaceFileDiff(wsId,path)` / `acceptWorkspaceChanges(wsId,path?)` / `searchWorkspaceContent(wsId,q)`。
- `@/views/coding/fileTree.ts`:`buildFileTree(files)` / `compactTree` / `TreeNode`。

## 4. 数据流 / 绑定

- **路由消费(KeepAlive singleton ⇒ 必须 watch,不能只 onMounted)**:`WorkspaceShell` `watch(() => route.params.id, ...)`:
  - 有 `id`(= ws_id 字符串)→ `currentBinding = {kind:'workspace', workspaceId:id}`;`workspaceData.load(id)`(getWorkspace + 文件树 + 改动);`currentSessionId` 走该 workspace 的会话(Phase 2:新建一个绑该 ws 上下文的 AIChat 会话,或复用路由所选)。
  - 无 `id` → `{kind:'none'}`(Phase 1 通用对话,不变)。
- **面板渲染**:`buildToolMenuItems(currentBinding)` 已有;workspace 绑定下 `files`/`code-view` 点亮。`PanelHost` 把 `wsId` + 文件树数据 + selected 透传给面板。selected 文件状态在 WorkspaceShell(或 workspaceData composable)持有,FilesPanel `@select` 更新,CodeViewPanel 读。
- **对话操作 workspace**:`ChatPane` 接 `workspaceId` prop → 透传给 `useAiChatSession` 的 `viewContext`(或新 opt),建会话/发消息时把「当前在 workspace <ws_id> 做二次开发」注入 run_agent 上下文,使其 `edit_workspace_files` 等工具带 ws_id。(run_agent 既有 `_inject_locked_workspace_project_id` 锁定机制,Phase 2 复用/对齐,不新发明引擎。)
- **id 解析**:Phase 1 `onSelect` 用 `Number(rawId(id))`(假设数字 id);workspace 会话 id 是字符串 ws_id。Phase 2 修 `WorkspaceShell` 的 id 解析:按 `bindingKindFromId` 分流(`chat:` → Number;`workspace:` → 字符串 ws_id),不再无脑 Number。

## 5. 路由 / 入口

- `/workspace`(无 id)= 通用对话(Phase 1)。`/workspace/<ws_id>` = 代码 workspace。
- `WorkspaceCatalogPage.openWorkspace(ws)`:`push('/workspace/' + encodeURIComponent(ws.id))`(原 `push('/coding',{query:{workspace_id:ws.id}})`)。`openLocalFolder` 同理用返回的 `ws_id`。
- 地址栏同步沿用 Coding 的二分法:切会话(不重挂)用 `history.replaceState`;换 workspace 上下文用 `router`。
- 旧 `/coding` 路由 + CodingPage **保留不动**(绞杀;退役 = Phase 4)。RailSidebar「自开发资产库」仍在。

## 6. 错误处理 / 边界

- `getWorkspace(wsId)` 失败(无权限/不存在)→ 面板/壳显错误态,不崩;回落通用对话。
- 文件树/改动拉取失败 → 面板内错误态,对话不受影响。
- ws_id 含特殊字符 → 路由 encode/decode。
- workspace 无改动 → FileTree changes 段空(已有行为)。
- 面板 `availableWhen` 对未知 binding → 禁用(Phase 1 已保证)。

## 7. 测试(沿用仓库约定:纯模块单测 + 组件 ?raw 断言,vitest node 无 DOM)

- `workspaceData`(纯/可注入):按 ws_id 组织 tree/changes 加载 + selected 状态的纯逻辑单测(mock codingApi)。
- `panels.spec` 扩:断言注册了 `files`/`code-view`、`availableWhen workspace`、不再有 `stub-code`。
- `WorkspaceShell.spec`(?raw):断言 watch route.params.id、workspace binding 推导、wsId 透传面板/ChatPane。
- `FilesPanel.spec`/`CodeViewPanel.spec`(?raw):断言复用 FileTree/CodeViewer + 传 wsId + 编排拉取调用。
- id 解析纯函数单测:`chat:123`→123(number)、`workspace:1_8ae94ab4`→`1_8ae94ab4`(string)。
- 绞杀守卫:`/coding` 路由 + CodingPage 不被破坏。
- 门禁:`vitest` 绿 + `build:nocheck` + `build:desktop`。

## 8. 验收

- `/workspace/<ws_id>` 打开 → 工具菜单「文件/代码」点亮;Files 面板出文件树 + git 改动;点文件 → CodeView 出内容,改动文件出红绿 diff。
- 对话能对该 workspace 做二次开发(run_agent 代码工具带 ws_id;至少 live 验证一次)。
- 资产库点 workspace → 进 `/workspace/<ws_id>`(不再进 /coding)。
- `/workspace`(无 id)通用对话不受影响;旧 /coding 不受影响。
- ChatPane 重复按钮已清。

## 9. 开放点(实现时定,不阻塞)

- workspace 会话:Phase 2 进 `/workspace/<ws_id>` 时是「新建一个绑该 ws 上下文的 AIChat 会话」还是「该 ws 复用一个会话」?倾向:进入即新建/复用一个该 ws 的通用会话(路由不带会话 id),对话上下文带 ws_id;不引 Coding 的 getWorkspaceConversation(那是另一套模型)。
- ws_id 喂 run_agent 的确切通道(viewContext 文本注入 vs 新 createSession 参数);倾向 viewContext 文本(零后端改动,符合"不改后端"决策)。
- FileTree 改动刷新时机:Phase 2 先做手动/进入时拉;跟随对话流自动刷新(对话改了文件后)可对齐 CodingPage 的 watch,但需 AIChat SSE 信号,作为 Phase 2 内增强或延后。
