# Phase 1 — 统一桌面工作区:外壳 + 工具面板框架(设计 spec)

> 日期 2026-06-18 · 总览见 `2026-06-18-unified-desktop-workspace-roadmap.md`。
> 本期 = 地基:搭外壳 + 面板注册契约 + 绑定模型,先承载「通用对话」跑通。后续期只往
> registry 注册新面板、不动外壳。**绞杀式:旧三页(AIChatPage/ChatPage/CodingPage)Phase 1 不动。**

## 1. 目标 / 非目标

**目标**
- 新建统一工作区外壳 `WorkspaceShell`(五区:左会话 / 中对话 / 右面板 / 顶工具菜单 / 底输入)。
- 定死「外壳 ↔ 面板」契约 `panelRegistry`,让 P2/P3 只 `register()` 新面板即可插入。
- 定 `binding` 会话绑定模型(none / app / workspace),驱动工具面板可用性。
- 在新壳里把「通用对话」(binding=none)工作流端到端跑通,复用现有对话链路。
- 通用面板:产物/设计文档(复用)、后台任务(简版)、Plan(占位)。
- 新路由 + feature flag,与旧三页**并存**(绞杀第一刀,不退役任何旧页)。

**非目标(后续期)**
- 代码面板(Files/Diff/Preview/Terminal)迁入 = P2。
- 配置面板(表单/数据/流程/权限)迁入 = P3。
- 集成终端、完整后台任务、Plan 模式、RailSidebar 导航收口、旧路由退役 = P4。

## 2. 架构与单元

```
WorkspaceShell.vue  (新, 五区宿主)
├─ 左  SessionList     ← 复用 SessionSidebar.vue (加 binding 徽标)
├─ 中  ChatPane        ← 复用 AgentConversation + UnifiedChatComposer + BuilderModelPicker
├─ 顶  ToolMenu.vue    (新, 从 panelRegistry 渲染全集 + 灰显禁用)
├─ 右  PanelHost.vue   (新, 停靠当前打开的 panel, 管开/关/活动态)
└─ 底  Composer        ← UnifiedChatComposer (已含模型选择/停止/附件/@技能)

panelRegistry.ts        (新, 纯模块: 面板注册表 + 可用性判定)
stores/workspaceSession (新/扩展: 会话 + binding 归一)
```

**每个单元的契约(做什么 / 怎么用 / 依赖谁)**

- **`panelRegistry.ts`**(纯 TS 模块,无 Vue 依赖,可单测)
  - 做什么:登记面板、按当前会话判定可用性。
  - 面板定义:`Panel = { id: string; label: string; icon: string; shortcut?: string; group: 'context'|'common'; availableWhen: (session: WorkspaceSession) => boolean; component: Component | (() => Promise<Component>) }`。
  - API:`registerPanel(p)` / `listPanels(): Panel[]`(稳定顺序)/ `isAvailable(p, session): boolean`。
  - 依赖:`WorkspaceSession` 类型(binding)。**P2/P3 的唯一接入点**——只调 `registerPanel`。

- **`ToolMenu.vue`**(顶部工具菜单,对应截图那个下拉)
  - 做什么:渲染 `listPanels()` **全集**;`isAvailable(p, currentSession)` 为假 → 项禁用灰显(不可点);点击可用项 → 通知 PanelHost 打开该 panel;显示快捷键。
  - 怎么用:`<ToolMenu :session="current" @open="id => panelHost.open(id)" />`。
  - 依赖:panelRegistry、当前会话。

- **`PanelHost.vue`**(右侧停靠容器)
  - 做什么:维护「当前打开的 panel id」+ 渲染其 component(异步 component 用 `defineAsyncComponent` + 加载/失败态);关闭/切换;空态(未开任何 panel)。
  - 错误处理:component 加载失败 → 显降级占位(「面板加载失败,请重试」),**不崩外壳**。
  - 怎么用:`panelHost.open(id)` / `close()`;接收当前 session 传给 panel。
  - 依赖:panelRegistry(取 component)、当前会话(传给 panel)。

- **`WorkspaceShell.vue`**(宿主)
  - 做什么:五区布局 + 串联上述单元 + 当前会话状态;响应路由 `/workspace/:id?`。
  - 依赖:全部上述 + 会话 store。

- **`SessionList`(复用 `SessionSidebar.vue`)**
  - 改动:列表项按 `binding.kind` 加类型徽标(💬/⚙️/⌨️)。SessionSidebar 已支持 `badgeIcon` + `meta`,**只加映射,不改组件结构**。

- **`ChatPane`(复用)**
  - 直接组合 `AgentConversation`(消息流/工具卡/澄清卡/思考计时)+ `UnifiedChatComposer`(输入/停止/附件/@技能)+ `BuilderModelPicker`,与 AIChatPage 现有组合一致。Phase 1 走通用对话(binding=none)的现有 run_agent / SSE 链路。

## 3. 会话 + 绑定模型(数据流)

```ts
type Binding =
  | { kind: 'none' }
  | { kind: 'app'; appId: number }
  | { kind: 'workspace'; workspaceId: string; appId?: number }  // 二开可同时关联 app

interface WorkspaceSession {
  id: string
  title: string
  binding: Binding
  // …复用现有会话字段(时间/分组等)
}
```

- **归一**:后端已有 `Conversation.coding_app_id` / workspace 关联等字段;前端加一个 adapter 把现有
  会话来源映射成 `WorkspaceSession.binding`(Phase 1 只需 none/app/workspace 三态的归一,不改后端表)。
- **新建会话**:默认 `binding: {kind:'none'}`(通用对话)。
- **绑定升级两条路**(Phase 1 先打通「none → 显式」与「框架就绪」,意图路由复用现有 dispatch 机制):
  - **意图路由(主)**:agent 识别「做个订单应用」/「改这段代码」→ 后端建 app / 起 workspace → 回填
    binding → 前端 panel 自动点亮。Phase 1 复用现有 `ai_builder_pending_app_dev` 等 dispatch 契约接线,
    不新发明。
  - **显式入口(辅)**:从应用库/资产库点进来,直接带 binding 开会话。
- **绑定变化** → ToolMenu 重算 `isAvailable` → 对应面板项点亮/置灰(纯响应式,无需手动刷新)。

## 4. 路由 / 绞杀共存

- 新路由 `/workspace`(+ `/workspace/:id` 会话)。**feature flag 控制是否暴露入口**(默认对内开,稳定后切默认)。
- 旧 `/`、`/ai-chat(/:id)`、`/chat`、`/coding` **全部保留、不动**。Phase 1 不退役任何旧页。
- 端态(P4):`/workspace` 成唯一工作区,旧路由 redirect。

## 5. 通用面板(Phase 1 内容)

| 面板 | group | availableWhen | Phase 1 实现 |
|------|-------|--------------|-------------|
| 产物 / 设计文档 | common | 总是 | **复用** AIChatPage 现有产物面板组件 |
| 后台任务 | common | 总是 | **简版**:列当前/近期 agent runs(复用 agent observability 的 `agent_run` 读 API);完整队列/调度 = P4 |
| Plan | common | 总是 | **占位**:菜单项存在,面板显「Plan 模式 P4」说明;真流程 = P4 |
| (stub)代码面板 | context | binding.kind==='workspace' | **仅测试用 stub**:验证 registry 驱动的点亮/置灰,P2 替成真 Files/Diff/… |

## 6. 错误处理 / 边界

- panel component 异步加载失败 → PanelHost 降级占位,外壳不崩。
- `availableWhen` 遇未知/缺字段 binding → 默认 `false`(禁用),不抛。
- binding=none 时 context 组(代码/配置)面板项全灰、不可点。
- 后台任务读 API 失败 → 面板内显空态/错误条,不影响对话。
- flag 关时 `/workspace` 不暴露入口(但路由可直达,便于内测)。

## 7. 测试

- **panelRegistry(纯函数)**:`isAvailable` 在 none/app/workspace 三种 binding 下,各 panel 的
  enabled/disabled 正确;`listPanels` 顺序稳定。
- **ToolMenu(组件)**:渲染全集;禁用态正确;点可用项 emit open、点禁用项无反应;快捷键展示。
- **PanelHost(组件)**:open/switch/close;异步组件加载失败 → 降级占位。
- **WorkspaceShell(组件)**:binding=none 渲染通用面板;注入 stub workspace-panel,把会话 binding
  从 none 切到 workspace 后,该项从灰变亮(**证明 registry 驱动、契约可插**)。
- **通用对话 E2E**:新壳里发消息 → 流式 → 出产物 → 会话进列表 → 可切换(沿用现有 AIChatPage 链路)。
- **绞杀守卫**:旧三页路由仍正常渲染(不被本期破坏)。

## 8. 复用映射(具体文件)

| 现有文件 | Phase 1 怎么用 |
|---------|---------------|
| `frontend/src/components/common/SessionSidebar.vue` | 复用为 SessionList,加 binding 徽标映射 |
| `frontend/src/components/common/AgentConversation.vue` | 复用为 ChatPane 消息流 |
| `frontend/src/components/common/UnifiedChatComposer.vue` | 复用为底部输入 |
| `frontend/src/components/common/BuilderModelPicker.vue` | 复用为模型选择 |
| `frontend/src/views/AIChatPage.vue`(产物面板部分) | 抽出/复用为「产物」面板 |
| `frontend/src/components/WorkbenchShell.vue` | 参考其 context-provider 模式;WorkspaceShell 可借鉴或并存 |
| `frontend/src/router/index.ts` | 加 `/workspace` 路由(flag) |
| agent observability `agent_run` 读 API | 后台任务简版数据源 |

## 9. 验收标准

- `/workspace` 通用对话可用:发消息 / 流式 / 出产物 / 会话列表 / 切换会话。
- ToolMenu 全集灰显正确:none 会话下 stub 代码面板灰、通用面板亮;切到 workspace binding 后 stub 亮。
- 旧三页(`/ai-chat`、`/chat`、`/coding`)不受影响。
- 前端 `build:nocheck`(vite)绿 + `vitest` 绿(含新单测),**不新增 vue-tsc 报错**(全量 vue-tsc 预存坏,非 gate)。

## 10. 开放点(实现时定,不阻塞 spec)

- WorkspaceShell 是新建还是从 WorkbenchShell 演进(倾向新建,避免动现役壳)。
- 产物面板从 AIChatPage 抽离的粒度(整组件抽 vs 复制薄封装)。
- 后台任务简版到底接 `agent_run` 读 API 还是先 mock(倾向接真 API,数据已在)。
