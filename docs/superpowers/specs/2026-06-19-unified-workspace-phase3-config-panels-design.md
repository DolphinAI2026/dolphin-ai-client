# Phase 3 — 统一工作区:配置面板 + app 绑定(设计 spec)

> 日期 2026-06-19 · 总览见 `2026-06-18-unified-desktop-workspace-roadmap.md`,Phase 1/2 见同目录。
> Phase 3 = 把「应用配置工作流」接进统一工作区:`/workspace?app_id=N` 驱动 app 绑定 → 工具菜单点亮「配置」面板(菜单栏 + 表单/数据/流程/权限设计面板,只读 + 深链)→ 对话经 useAiChatSession 锁定 app(run_agent 自动注入 app 上下文)。旧 /chat 不动(绞杀)。

## 1. 已定决策(采集确认)

1. **app 绑定 = `useAiChatSession({ appId })`,零新机制。** app_id 是 `createSession` 一等参数 + `AIChatSession.app_id` DB 列 + `listSessions` 过滤键;run_agent 据 `session.app_id` 自动注入 app 上下文(`build_app_context_block`)+ 强制把 `env_id`/`apaas_app_id` 注入 apaas 工具(`_inject_locked_app_ctx`)。**app_id = ai-builder 本地 `Application.id`(number),不是 apaas_app_id**(后端反查)。ChatPane(Phase 2 已知有 appId 入参,现写死 `ref(null)`)接通 binding.appId 即可。
2. **路由 = `/workspace?app_id=N`(query)。** 路径 `:id` 已被 Phase 2 占作 ws_id 字符串(`1_8ae94ab4`),app_id 是 number,形状会撞;复用现成 `?app_id=N` 契约(Apps.vue/ChatPage/`resolveInitialAppId` 一致,迁移成本最低)。三态:`/workspace`(none)/`/workspace/<ws_id>`(workspace)/`/workspace?app_id=N`(app)。
3. **配置面板 = 一个组合「配置」面板**(`ConfigWorkspacePanel.vue`):内含 `ApaasMenuSidebar`(选菜单)+ 子 tab(表单/数据/流程/权限)+ 当前选中菜单的设计面板 + `OpenLowcodeBackendButton`(去后台编辑深链)。因为 4 个设计面板需要 (app_id, menu_id, form_id),menu 上下文由 ApaasMenuSidebar 提供——所以不能是 4 个独立 panel(PanelHost 一次显一个、菜单栏要常驻)。availableWhen: `binding.kind==='app'`。
4. **复用(自包含,采集确认零 provide/inject/route/store,只用 `request`)**:`FormDesignerPanel`/`DataSchemaEditor`/`ProcessDesignerPanel`/`FormPermPanel`(`@/components/v3/`)、`ApaasMenuSidebar`(`@/components/`)、`OpenLowcodeBackendButton`(`@/components/v3/`)。
5. **Apps.vue openApp → `/workspace?app_id=N`**(原 `/chat`),`appWorkspaceQuery` 产出的 query 形状可复用。旧 /chat 绞杀保留。

## 2. 目标 / 非目标

**目标**
- `routeToBinding(wsId, appIdRaw)` 三态;WorkspaceShell 同时 watch `route.query.app_id`(KeepAlive→watch);app binding 喂 ChatPane → `useAiChatSession({ appId })` 锁 app。
- 注册「配置」面板(`config`,group context,availableWhen app),组合菜单栏 + 子 tab + 4 设计面板 + 深链按钮。
- 选菜单 → 解析 menu_id/form_id/menu_name → 设计面板渲染;子 tab 切表单/数据/流程/权限;权限 sub 需 form_id(无则禁用)。
- Apps.vue openApp → /workspace?app_id=N。
- `onSelect`(侧栏)补 app 分支;`sessionList` 的 binding 仍 none(会话列表 binding 持久化非本期,见 Phase 2)。

**非目标(后续/Phase 4)**
- AI 改配置后面板自动刷新(refreshNonce 接 SSE 信号)= 延后;Phase 3 用**手动刷新按钮**(bump refreshNonce 绕 180s 缓存)。
- menu 感知的 viewContext(AI 知道你在看哪个表单)= 延后;Phase 3 只 app 级绑定(AI 经 MCP 读 app 菜单/表单)。
- CUSTOM 菜单类型(自定义页)= Phase 3 显提示 + 深链,不嵌 CustomPagePreviewPanel。
- 旧 /chat 退役 + 5-tab 完整迁移 = Phase 4。
- 侧栏混列 ChatPage 配置会话 = 不做。

## 3. 架构与改动单元

```
frontend/src/views/workspace/
├─ workspaceRoute.ts        改: routeToBinding(wsId, appIdRaw) 三态(复用 resolveInitialAppId); parseSidebarSelect 补 app
├─ workspaceRoute.spec.ts   改: app 态测试
├─ panels/ConfigWorkspacePanel.vue   新: ApaasMenuSidebar + 子tab + 4设计面板 + 深链 + 手动刷新; 读 binding.appId
├─ panels/ConfigWorkspacePanel.spec.ts
├─ panels.ts                改: 注册 config 面板(group context, availableWhen app)
├─ panels.spec.ts           改: 断言 config 面板(none/workspace 灰, app 亮)
├─ WorkspaceShell.vue       改: watch route.query.app_id; appId computed → ChatPane; onSelect app 分支
├─ WorkspaceShell.spec.ts   改
├─ ChatPane.vue             改: appId 从 prop(binding) 取(现写死 null)→ useAiChatSession({ appId })
└─ ChatPane.spec.ts         改
frontend/src/views/Apps.vue  改: openApp → push('/workspace', query)
```

**复用契约(采集逐字确认)**
- `ApaasMenuSidebar`:props `{ appId: number|string|null; selectedMenuId?: string|null }`;emits `menu-selected(menu)`/`menus-loaded(menus, firstFormMenu)`。`menu` 含 `menu_id`/`menu_name`/`form_id`/`menu_type`。自拉 `/applications/{appId}/apaas-menus`。
- `FormDesignerPanel`/`DataSchemaEditor`:props `{ appId:number; menuId?; menuName?; formId?; refreshNonce? }`(无 emit)。
- `ProcessDesignerPanel`:props `{ appId; menuId?; menuName?; formId?; hideLowcodeBtn?; assistantOpen? }`(传 `hide-lowcode-btn=true` 让深链按钮归 host)。
- `FormPermPanel`:props `{ appId; formId:string(必填); menuName? }`(无 form_id 不挂)。
- `OpenLowcodeBackendButton`:props `{ appId:number; menuType?; menuId?; formId?:string|null; title? }`。
- `resolveInitialAppId(raw): number|null`(`@/views/chatPageRouteState`)= app_id 统一解析(取数组首项/Number/>0)。

## 4. 数据流 / 绑定

- **路由消费(KeepAlive→watch 双源)**:WorkspaceShell `watch([() => route.params.id, () => route.query.app_id], () => { currentBinding.value = routeToBinding(<params.id>, <query.app_id>) }, { immediate:true })`。
  - params.id → workspace;否则 query.app_id → app;否则 none。
- **app binding → ChatPane**:WorkspaceShell `appId` computed = `binding.kind==='app' ? binding.appId : null`,传 ChatPane `:app-id`;ChatPane 把它喂 `useAiChatSession({ appId })`(替换现写死 `ref(null)`)。建会话自动带 app_id、listSessions 按 app 过滤、run_agent 注入 app 上下文。**切 app(binding 变)→ newSession()**(对齐 AppAssistantPanel `watch(applicationId)`)。
- **ConfigWorkspacePanel 内部**:`appId = binding.appId`;`ApaasMenuSidebar @menu-selected` → 本地 `selectedMenu{id,name,formId,type}`;子 tab(form/data/process/perm)切当前设计面板,传 (appId, menuId, formId, menuName, refreshNonce);深链按钮传 (appId, menuType='MODEL', menuId, formId);手动刷新 bump refreshNonce。CUSTOM menu → 提示 + 深链。
- **id 解析**:`onSelect`(WorkspaceShell)用 `parseSidebarSelect`:app → `router.push({path:'/workspace', query:{app_id: rawId}})`(app rawId 是 number 字符串)。

## 5. 路由 / 入口

- `/workspace?app_id=N`(app)/ `/workspace/<ws_id>`(workspace)/ `/workspace`(none) 并存。
- `Apps.vue.openApp(app)`:`router.push({ path:'/workspace', query: appWorkspaceQuery(app) })`(原 `/chat`)。query 形状(app_id [+tab/workspace])复用;/workspace 至少消费 app_id,tab/workspace=update 暂忽略(Phase 4 再说)。
- 旧 `/chat` 路由 + ChatPage **保留不动**(绞杀;退役=Phase 4)。

## 6. 错误处理 / 边界

- app 未部署 aPaaS(无 apaas_app_id)→ 深链按钮 alert(组件已兜底);设计面板拉数据按各自空态。
- 无选中菜单 → 设计面板空态;perm sub 无 form_id → 禁用该 tab。
- CUSTOM menu_type → 不挂 4 设计面板,显提示「自定义页请去低代码后台」+ 深链。
- app_id 无效/Application 不存在 → run_agent app 上下文静默降级(后端已处理);前端面板空态。
- KeepAlive:切 app_id query 必经 watch 生效。

## 7. 测试(纯模块单测 + 组件 ?raw,vitest node 无 DOM)

- `routeToBinding`/`parseSidebarSelect`:app 态三态分流 + app id 解析(number)单测。
- `panels.spec`:config 面板注册、none/workspace 灰、app 亮。
- `WorkspaceShell.spec`(?raw):watch route.query.app_id、appId computed→ChatPane、onSelect app 分支。
- `ConfigWorkspacePanel.spec`(?raw):复用 ApaasMenuSidebar + 4 设计面板 + OpenLowcodeBackendButton;menu-selected 串 menu 上下文;子 tab 切换;perm 需 formId。
- `ChatPane.spec`:appId 从 prop 取(不再写死 null)。
- 绞杀守卫:/chat 路由 + ChatPage 不动;Apps 改指 /workspace。
- 门禁:vitest + build:nocheck + build:desktop。

## 8. 验收

- 资产库点应用 → `/workspace?app_id=N`;工具菜单「配置」亮;面板出菜单栏,选菜单 → 表单/数据/流程/权限设计面板渲染;切子 tab;点「低代码后台」深链开 aPaaS 编辑器。
- 对话锁定该 app(run_agent 注入 app 上下文;至少 live 验证一次:问「这个应用有哪些表单」走 MCP 读真实 app)。
- `/workspace`(none)/`/workspace/<ws_id>`(code,Phase 2)不受影响;旧 /chat 不受影响。

## 9. 开放点(实现时定)

- 「配置」面板宽度:菜单栏 + 设计面板比代码面板更需空间;WorkspaceShell 的 .ws-panel 宽度 Phase 3 可按面板类型放宽(或固定更宽),实现时定。
- ProcessDesignerPanel 重(@antv/x6 Graph),PanelHost 切面板 mount/unmount 开销;沿用其 `:key` 强制 remount + onBeforeUnmount disposeGraph。
- 子 tab 默认选「表单」;menus-loaded 默认选第一个含 form_id 的菜单(对齐 ChatPage onApaasMenusLoaded)。
