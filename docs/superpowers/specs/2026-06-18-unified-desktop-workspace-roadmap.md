# 统一桌面工作区 — 四期路线 + 架构决策(总览)

> 日期 2026-06-18 · 方向:ai-builder 桌面端 UX 全面对齐 Claude Code desktop。
> 本文是**总览**,固化已定架构决策 + 四期拆分。**Phase 1 有独立详细 spec**
> (`2026-06-18-unified-workspace-shell-phase1-design.md`);Phase 2-4 是方向草案,
> 各自开工时再细化 spec(强依赖 Phase 1 落地后定型的 registry/binding,现在写细必返工)。

## 背景

桌面端 UX 审计(2026-06-18)结论:**零件大半已有,最大差距是形态**。
- 已有且成熟:`SessionSidebar`(会话分组/重命名/删除)、`AgentConversation` + `ToolCard`、
  `UnifiedChatComposer` + `BuilderModelPicker`、`FileTree`、`DiffView`、`RunDebugPanel`、
  AIChatPage 产物面板、桌面集成(登录/更新/打开文件夹/技能库/onboarding)。
- 差距:三套独立页面各管一摊(`AIChatPage` 融合对话 / `ChatPage` 5-tab 配置工作室 /
  `CodingPage` 代码区),布局与心智不统一;而 Claude Code 是**一个统一工作区 + 右上角工具
  面板**(Preview/Diff/Terminal/Files/后台任务/Plan)。
- 完全缺:集成终端、后台任务面板、Plan 模式(只在 ChatPage 有)、权限模式、行级 diff。

## 已定架构决策(brainstorm 2026-06-18,大明哥拍板)

1. **端态形态**:一个统一工作区,三套工作流全融(对话 / 应用配置 / 代码)。不是共享外壳套三页,是真融。
2. **结构 = A 单一会话流**:左栏单一会话列表,每条带类型徽标(💬对话 / ⚙️应用 / ⌨️代码),
   中心永远是对话,右侧工具面板按会话适配。最像 Claude Code。
3. **绑定驱动工具面板**:会话有 `binding`(none / app / workspace)。可用哪些面板由绑定决定——
   绑代码工作区→Files/Diff/Terminal/Preview;绑 aPaaS 应用→表单/数据/流程/权限(只读+深链);
   都没绑→产物/设计文档。「后台任务 / Plan」三类永远有。(把「工作对象优先」B 方案的应用心智
   吃进 A,无需多一层。)
4. **菜单 = 全集灰显**:顶部工具菜单永远显示全集,当前会话用不上的**禁用灰显**(像 Claude Code
   稳定的肌肉记忆,也让用户看到「这会话还能升级出哪些能力」)。
5. **落地 = 渐进绞杀(strangler)**:先搭统一外壳框架,把现有成熟组件原样当面板挂进去,旧页面
   逐步下线。每期可独立 ship、可回退、用户随时能用。不大爆炸重写、不长期双轨。

## 四期路线

| 期 | 目标 | 关键产出 | 依赖 |
|----|------|---------|------|
| **P1 ⭐** | 统一外壳 + 工具面板框架(地基) | `WorkspaceShell` / `PanelHost` / `ToolMenu` / `panelRegistry` / `binding` 模型 / 统一会话列表 / 通用对话跑通 / 通用面板(产物·后台任务简版·Plan 占位) | — |
| **P2** | 对话+代码工作流迁上壳 | 注册代码面板(Files/Diff/Preview/Terminal-占位);会话绑 workspace;`/coding` 迁入并退旧入口 | P1 registry + binding |
| **P3** | 应用配置工作流迁上壳 | 注册配置面板(表单/数据/流程/权限,只读+深链);会话绑 app;`/chat` 5-tab 迁入并退旧布局 | P1 registry + binding |
| **P4** | 补 Claude Code 缺口 + 导航收口 | 集成终端、完整后台任务面板、Plan 模式统一;RailSidebar 功能页(应用库/资产库/技能/日志/平台配置)收进顶部菜单/命令面板;旧路由 redirect,`/workspace` 成唯一工作区 | P2 + P3 |

**地基价值**:P1 把「外壳 + 面板注册契约」定死后,P2/P3 基本只是 `panelRegistry.register()` 加新
面板 + 写 `availableWhen` 谓词,**不动外壳**。这是选渐进绞杀的核心收益。

## 不在范围(整个方向之外)

- 不拆仓库(已在 [桌面壳层收口](../../) 2026-06-18 定:桌面 ~250 行壳 vs 共享核心 ~7700 行,
  像 Claude Code 一核心多薄壳,一条线)。本方向是**桌面端前端 UX 重构**,后端/壳不动。
- 不重写已成熟的对话/工具卡/文件树/diff 等组件——绞杀式复用。

## 风险与原则

- **每期独立可验证可回退**:旧三页在对应期迁完前一直可用,新壳走 flag/新路由灰度。
- **YAGNI**:P2-4 不预先写死细节;P1 的 registry 契约要留足扩展点但不过度抽象。
- 前端工程门禁:`build:nocheck`(vite)绿 + vitest 绿;`npm run build`(vue-tsc)预存坏不作 gate。
