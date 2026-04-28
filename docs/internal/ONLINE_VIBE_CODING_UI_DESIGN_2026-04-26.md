# 在线通用 Vibe Coding UI 设计

**Date**: 2026-04-26
**Status**: Draft v0.1
**Related**: `docs/internal/ONLINE_VIBE_CODING_ARCHITECTURE_2026-04-26.md`

---

## 0. 设计结论

在线通用 Vibe Coding 的 UI 不应该做成“AI 聊天页 + 一个编辑器 iframe”。它应该是一个工程工作台：

> 左侧是 AI 执行与计划，中间是代码/预览/差异/终端，右侧是运行状态、变更、端口、Git 和风险审批。

整体方向：

- **工作台优先**：首屏就是可操作的开发环境，不做营销式 hero。
- **状态可见**：项目、分支、沙箱、模型、运行状态、Git 状态始终在顶栏可见。
- **AI 可监督**：Agent 的计划、工具调用、测试结果、文件改动都要可追踪。
- **低代码/全代码统一骨架**：低代码显示 SPEC/Deploy/平台发布，全代码显示 Code/Preview/Diff/Terminal/Git。
- **企业级克制视觉**：中性背景、细边框、小圆角、低阴影，少用大色块和装饰。

---

## 1. 信息架构

### 1.0 首页主入口

首页必须把能力拆成三种一级入口，而不是只放一个泛化的 `Code`：

| 入口 | 页面文案 | 目标用户 | 跳转 |
| --- | --- | --- | --- |
| 低代码智能搭建 | 描述业务系统，生成 SPEC、配置与应用 | 业务顾问、实施、产品 | `/chat?mode=requirements` 或 `/work/:appId` |
| Code 模式 · 低代码二开 | 开发 aPaaS 组件、页面、接口、脚本 | 低代码开发者 | `/coding?type=apaas-custom-dev` |
| Vibe Coding · 全代码 | 导入 Git 仓库，在云沙箱中让 AI 改全代码 | 专业开发者 | `/coding/new?type=full-code` 或 `/dev/:workspaceId` |

当前首页如果只有 `CoWork / Code` 两个 tab，会把“低代码二开”和“全代码开发”混在一起。建议改成三张主入口卡：

```text
┌──────────────────────────────────────────────────────────────┐
│ 今天要做什么？                                      搜索 / 设置 │
├──────────────────┬──────────────────┬────────────────────────┤
│ 低代码智能搭建    │ Code 模式          │ Vibe Coding          │
│ 生成应用配置      │ 低代码二开          │ 全代码开发              │
│ [开始搭建]        │ [进入 Code 模式]    │ [导入 Git / 新建项目]   │
└──────────────────┴──────────────────┴────────────────────────┘
```

入口优先级：

1. 如果当前产品主卖点仍是低代码 AI，则“低代码智能搭建”放第一张，并作为默认高亮。
2. “Code 模式 · 低代码二开”放第二张，继承现有 CodingPage。
3. “Vibe Coding · 全代码”放第三张，标记为新能力，但不要做成角落里的次级入口。

### 1.1 顶层导航

```text
GlobalNavRail
├── Workspaces     当前工作区、最近任务
├── Projects       项目 / 应用 / Git 仓库
├── Runs           Agent 执行历史
├── Reviews        待评审变更 / PR / 低代码 proposal
├── Resources      模型、沙箱、Secret、Git 连接
└── Settings       组织、成员、审计、配额
```

顶层导航按用户任务组织，不按后端模块命名。

### 1.2 核心路由建议

| 路由 | 页面 | 说明 |
| --- | --- | --- |
| `/coding` | Workspace Catalog | 最近工作区 + 新建/导入入口 |
| `/coding/new` | Create Workspace | 选择低代码二开、Git 导入、空项目、模板 |
| `/dev/:workspaceId` | Online Workspace | 通用在线 Vibe Coding 主工作台 |
| `/reviews/:changeId` | Review & Ship | 变更审阅、测试结果、PR/发布 |
| `/runs/:runId` | Agent Run Detail | 执行日志、工具调用、审计 |
| `/resources` | Resource Center | Git、模型、Secret、Sandbox profile |

现有 `/work/:appId` 可以作为低代码应用工作台继续保留；当用户进入“自开发/全代码”时，跳到 `/dev/:workspaceId`。

---

## 2. 主工作台布局

### 2.1 桌面布局

```text
┌────┬────────────────────────────────────────────────────────────────────────────┐
│Nav │ Project / Branch / Sandbox / Model / Members / Git / Primary Action       │
├────┼───────────────┬───────────────────────────────────────┬──────────────────┤
│    │ AgentPanel    │ Workbench                             │ Inspector        │
│    │               │                                       │                  │
│    │ Goal          │ [Code] [Preview] [Diff] [Terminal]    │ Run              │
│    │ Plan          │                                       │ Changes          │
│    │ Tool Events   │ VS Code Web / Preview / Diff Viewer   │ Tests            │
│    │ Composer      │                                       │ Ports            │
│    │               │                                       │ Git              │
└────┴───────────────┴───────────────────────────────────────┴──────────────────┘
```

推荐尺寸：

| 区域 | 宽高 |
| --- | --- |
| GlobalNavRail | `56px` 固定 |
| TopBar | `48px` 固定 |
| AgentPanel | `360px`，可在 `320-440px` 之间拖拽 |
| Workbench | `minmax(520px, 1fr)` |
| Inspector | `336px`，可折叠 |
| 分隔线 | `1px` |
| 卡片圆角 | `8px` |
| 面板内边距 | `12px` 或 `16px` |

### 2.2 响应式

| 断点 | 行为 |
| --- | --- |
| `>= 1440px` | 三栏完整显示 |
| `1024-1439px` | Inspector 默认折成右侧抽屉 |
| `768-1023px` | AgentPanel 与 Workbench 使用分段切换 |
| `< 768px` | 只保留任务监督与预览，不主打完整编码 |

移动端不承诺完整 VS Code 编程体验，只做任务查看、审批、停止运行、看预览。

---

## 3. 视觉系统

### 3.1 色彩

| Token | Light | Dark | 用途 |
| --- | --- | --- | --- |
| `bg.base` | `#f7f8fb` | `#090b10` | 页面底色 |
| `bg.panel` | `#ffffff` | `#111318` | 面板 |
| `bg.subtle` | `#f2f4f8` | `#151922` | 次级区域 |
| `line` | `rgba(24,31,45,.09)` | `rgba(148,163,184,.14)` | 分隔线 |
| `text.primary` | `#181f2d` | `rgba(248,250,252,.94)` | 主文本 |
| `text.muted` | `#667085` | `rgba(203,213,225,.64)` | 辅助文本 |
| `accent` | `#4f6ef7` | `#8aa2ff` | 主操作/激活 |
| `success` | `#0f9f8f` | `#34d399` | 测试通过/同步 |
| `warning` | `#b7791f` | `#fbbf24` | 等待确认/风险 |
| `danger` | `#d14a61` | `#f87171` | 失败/阻断 |

不要把页面做成大面积蓝紫渐变。主色只用于激活态、主按钮、焦点和关键状态。

### 3.2 字体与密度

| 场景 | 字号 |
| --- | --- |
| 顶栏项目名 | `14-15px / 600` |
| 面板标题 | `12px / 600`，大写或短中文 |
| 正文/控件 | `13px` |
| 辅助元信息 | `11-12px` |
| 代码/命令 | `12px` mono |

### 3.3 控件规范

- Icon button：`32x32`，圆角 `8px`。
- Primary button：高度 `32px`，圆角 `8px`。
- Secondary button：边框 + 透明底。
- Segmented tabs：高度 `32px`，用于 Code/Preview/Diff/Terminal。
- Status chip：高度 `22-24px`，文字短，不放长句。
- 面板卡片：圆角 `8px`，边框优先于阴影。

实现时优先使用 `lucide` 图标：`Code2`、`Eye`、`FileDiff`、`Terminal`、`GitBranch`、`Play`、`Square`、`CheckCircle2`、`AlertTriangle`、`Lock`、`Cloud`、`Settings`。

---

## 4. 核心页面

### 4.1 Workspace Catalog

目标：让用户快速继续最近工作或新建工作区。

```text
┌────────────────────────────────────────────────────────────┐
│ Workspaces                                  [New Workspace] │
├────────────────────────────────────────────────────────────┤
│ Filters: All / Low-code / Full-code / Running / Needs review│
├──────────────────────┬─────────────────────────────────────┤
│ Recent Workspaces    │ Activity                            │
│ - 供应商门户          │ - PR ready                           │
│ - CRM 客户模块        │ - Sandbox sleeping                   │
│ - billing-api        │ - Tests failed                       │
└──────────────────────┴─────────────────────────────────────┘
```

卡片应显示：

- 项目名、类型、repo/应用编码。
- 最近 agent 任务。
- 沙箱状态。
- 分支/Git 状态。
- 预览端口数量。
- 待评审数量。

主操作只有一个：`New Workspace`。

### 4.2 Create Workspace

四个入口：

| 入口 | 说明 | 主字段 |
| --- | --- | --- |
| 低代码智能搭建 | 从业务需求生成应用 | 租户、应用名、模板 |
| 低代码二次开发 | aPaaS 自开发组件/页面/接口 | 应用、开发类型、环境 |
| 导入 Git 仓库 | 全代码项目 | Git provider、repo、branch |
| 空项目/模板 | 新建全代码项目 | 技术栈、包管理器、运行命令 |

表单采用两列：左侧选择来源，右侧显示对应字段。高级项折叠在底部。

### 4.3 Online Workspace

这是最核心页面。

顶栏展示：

```text
ProjectName / branch       Sandbox: Running       Model: GPT-5.3 Codex
members                    Git: synced            [Stop] [Commit] [Open PR]
```

左侧 AgentPanel：

- Goal：当前用户需求。
- Plan：可勾选步骤，显示当前进行项。
- Events：工具调用流，默认折叠命令输出。
- Composer：输入任务、上传附件、选择模式。

中间 Workbench：

| Tab | 内容 |
| --- | --- |
| Code | VS Code Web iframe |
| Preview | port proxy 预览，支持多端口切换 |
| Diff | 文件 diff、按文件分组 |
| Terminal | sandbox terminal，只对有权限用户开放 |
| Logs | build/test/deploy 日志 |

右侧 Inspector：

- Run：当前 agent turn、耗时、模型、token/成本。
- Changes：文件变更、增删改统计。
- Tests：最近测试命令和结果。
- Ports：已暴露端口与预览链接。
- Git：branch、commit、PR 状态。
- Risk：等待确认的高风险命令或发布动作。

### 4.4 Review & Ship

当 agent 完成任务后，页面自动进入审阅状态：

```text
┌────────────────────┬────────────────────────────────────┬─────────────────┐
│ Summary            │ Diff Viewer                        │ Ship Checklist  │
│ Goal               │ file tree + unified diff           │ Tests           │
│ Plan done          │                                    │ Preview         │
│ Risk notes         │                                    │ Commit          │
└────────────────────┴────────────────────────────────────┴─────────────────┘
```

主操作按场景变化：

- 全代码：`Commit`、`Open PR`、`Deploy preview`。
- 低代码二开：`Build`、`Upload to platform`、`Publish`。
- 低代码 SPEC：`Promote`、`Approve`、`Apply`。

---

## 5. 状态与交互

### 5.1 Agent 状态

| 状态 | UI 表达 | 可操作 |
| --- | --- | --- |
| Idle | Composer 可输入 | Start |
| Planning | Plan 区域流式生成 | Stop |
| Editing | Tool Events + changed files 递增 | Stop / View Diff |
| Running tests | Tests 卡片置顶 | Stop |
| Waiting approval | Risk 卡片高亮 | Approve / Deny |
| Completed | Review & Ship 入口高亮 | Commit / PR / Publish |
| Failed | Error summary + retry | Retry / Open logs |

### 5.2 高风险确认

确认弹窗不使用浏览器原生 `confirm`，用平台内 modal。

弹窗信息：

- 将执行的命令或动作。
- 风险级别。
- 影响范围。
- Agent 为什么需要它。
- `Deny`、`Approve once`、`Always allow in this workspace`。

`rm -rf`、`curl | sh`、`npm publish`、`deploy`、低代码不可逆 apply 都必须走确认。

### 5.3 沙箱休眠

当 workspace sleeping：

- 顶栏状态显示 `Sleeping`。
- Workbench 显示最近 snapshot 信息。
- 主操作是 `Resume`。
- AgentPanel 保留历史对话，但输入框 disabled，避免用户误以为任务已经执行。

### 5.4 测试失败

Tests 卡片置顶显示：

- 命令。
- 失败数量。
- 最近错误摘要。
- `Ask AI to fix`。
- `Open logs`。

不要在主聊天流里堆满完整日志，完整日志进 Logs tab。

---

## 6. 低代码与全代码的差异化显示

同一个 Online Workspace shell，根据 adapter 切换内容。

| 区域 | 低代码 SPEC | 低代码二开 | 全代码 |
| --- | --- | --- | --- |
| Workbench tabs | SPEC / Deploy / Diff / Logs | Code / Preview / Build / Logs | Code / Preview / Diff / Terminal / Logs |
| Inspector | Draft / Proposal / Apply risk | Build / Upload / Platform env | Tests / Ports / Git / PR |
| Primary action | Promote / Apply | Build / Publish | Commit / Open PR |
| 风险门 | 不可逆平台操作 | 发布到平台 | 高风险命令 / deploy |

这样可以保留现有 Phase F 的低代码工作台心智，同时承接全代码项目。

---

## 7. 组件拆分

```text
frontend/src/views/
├── OnlineWorkspaceShell.vue
├── WorkspaceCatalogPage.vue
└── CreateWorkspacePage.vue

frontend/src/components/online-workspace/
├── WorkspaceTopBar.vue
├── GlobalNavRail.vue
├── AgentPanel.vue
├── AgentPlanList.vue
├── AgentEventStream.vue
├── AgentComposer.vue
├── WorkbenchPanel.vue
├── WorkbenchTabs.vue
├── CodeFrame.vue
├── PreviewFrame.vue
├── DiffViewer.vue
├── TerminalPane.vue
├── RunInspector.vue
├── ChangeSummaryCard.vue
├── TestStatusCard.vue
├── PortListCard.vue
├── GitStatusCard.vue
├── RiskApprovalCard.vue
└── SandboxSleepOverlay.vue
```

可复用现有：

| 现有模块 | 新职责 |
| --- | --- |
| `WorkspaceShell.vue` | 低代码应用 shell 的基础参考 |
| `ChatPanel.vue` | 提炼为 `AgentPanel` |
| `PreviewPanel.vue` | 扩成 `WorkbenchPanel` |
| `ActivityPanel.vue` | 扩成 `RunInspector` |
| `useIdeManager.ts` | 管理 Code iframe |
| `useCodingPipeline.ts` | 接入 Agent run SSE |
| `builder.css` | 继续使用当前 neutral token，补充 online workspace token |

---

## 8. 静态原型

本设计配套了一个可直接打开的静态 HTML 原型：

`docs/internal/online-vibe-coding-ui-prototype.html`

原型覆盖：

- Global nav。
- AgentPanel。
- Workbench tabs。
- Preview / Code / Diff 密度。
- Run inspector。
- Sandbox / Git / Tests 状态。
- Review & Ship 操作区。

---

## 9. 实施顺序

### UI-1：工作台 shell

- 新建 `OnlineWorkspaceShell.vue`。
- 搭好三栏布局、顶栏、折叠 inspector。
- 不接真实数据，先使用 mock。

### UI-2：Workspace Catalog + Create Workspace

- 新建工作区列表。
- 新建/导入向导。
- 对接 full-code project/workspace API mock。

### UI-3：AgentPanel 与事件流

- 将现有 SSE stream message 映射到标准 run event。
- Plan、tool、command、file diff 分类型渲染。

### UI-4：Workbench tabs

- 接入 code-server iframe。
- 接入 preview port proxy。
- 接入 diff viewer。
- Terminal 先只做 UI 占位，等 sandbox 权限策略完成再开放。

### UI-5：Review & Ship

- 汇总 changed files、tests、preview、Git。
- 支持 commit / open PR。
- 低代码 adapter 显示 upload/publish。

---

## 10. 验收标准

- 用户进入 `/dev/:workspaceId` 后 3 秒内能看懂：项目、分支、沙箱状态、AI 正在做什么、下一步能点什么。
- 页面没有大段说明文字，不靠 banner 教用户怎么用。
- 低代码二开和全代码开发共用同一套视觉系统。
- Agent 的每个重要行为都能追踪到 plan、tool event、diff 或 log。
- 高风险动作有明确确认，不隐藏在聊天文本里。
- 桌面端三栏不拥挤，`<1440px` 时右侧 Inspector 可折叠。
- 所有卡片和按钮圆角统一，视觉不依赖大面积渐变或装饰。
