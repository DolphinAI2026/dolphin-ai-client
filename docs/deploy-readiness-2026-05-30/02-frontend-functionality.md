# 前端功能与用户流程地图

> 生成日期: 2026-05-30 | 只读评审，未修改任何源码
> 数据来源: `frontend/src/views/` + `frontend/src/router/index.ts` + `frontend/src/components/v3/` + `admin-spa/src/` + `docs/audit-2026-05-29-codebase-health.md`

---

## 一、主前台 (frontend) 页面总览

| 路由 | 组件 | 作用 | 备注 |
|------|------|------|------|
| `/login` | `Login.vue` | 用户名/密码登录，aPaaS token 自动 chain | 真功能，入口 |
| `/tenant-select` | `TenantSelect.vue` | 多租户账号选择租户 | 真功能，平台管理员需要 |
| `/` | `Landing.vue` | 工作台首页：AI Composer + 最近应用 + 统计条 | 真功能 |
| `/apps` | `Apps.vue` | 应用列表：卡片/列表视图 + 状态筛选 + 导入 | 真功能 |
| `/ai-chat/:id?` | `AIChatPage.vue` | **AI 对话设计工作台**：多会话 + 文件上传 + 生成进度 CTA + 设计文档面板 | 核心路径 A（设计→生成） |
| `/chat/:id?` | `ChatPage.vue` | **低代码配置工作台**：应用已生成后的 4 panel 配置界面（SectionNav + 设计器 + 配置助手 + apaas 内嵌） | 核心路径 B（配置调整）⚠️ ≠ AIChatPage |
| `/coding` | `CodingPage.vue` | **AI Coding 工作台**：自开发组件对话 + IDE + 文件抽屉 | ai-code 类型应用 |
| `/quick-db` | `QuickDbPage.vue` | DB 快速接入 Wizard（4步：连接→选表→描述→生成） | UI 骨架 + 后端 stub，Step4 生成端点待接 |
| `/db-connections` | `DbConnectionsPage.vue` | 数据库连接管理（增删改查） | 真功能 |
| `/platform-envs` | `PlatformEnvs.vue` | 平台环境 + 模型配置（租户管理员） | 真功能；`requiresTenantAdmin` |
| `/tenant-users` | `TenantUsers.vue` | 成员管理（邀请/删除/权限过滤） | 真功能；`requiresTenantAdmin` |
| `/platform-admin/*` | `PlatformAdminEmbed.vue` | 嵌入 admin-spa 的平台管理后台 | `requiresPlatformAdmin` |
| `/admin/tenants` | `PlatformTenants.vue` | 平台级租户列表（平台管理员） | 真功能 |
| `/admin/mcp` | `McpToolsPage.vue` | MCP 工具列表查看页（开发/调试） | 真功能 |
| `/agents` | `AgentsPage.vue` | Agent 配置（Builder/Coding/Vibe 三 Agent 的模型+提示词+MCP+知识库） | MCP/行业包部分为本地 stub，Agent 配置真接后端 |
| `/specs` | `SpecsPage.vue` | 设计文档（SPEC）列表与详情 | 真接后端 `/api/specs-v2` |
| `/industry` | `IndustryPage.vue` | 行业知识库（本体图 + 4 行业包展示） | 行业包按钮全 stub（ElMessage.info），包数据接后端 |
| `/runtime` | `RuntimePage.vue` | 运行与发布：流水线/平台环境/部署历史 3 tab | 环境/流水线/部署历史真接后端；操作按钮部分 stub（见下节） |
| `/mcp` | `McpHubPage.vue` | MCP Hub：服务清单/连接状态/工具详情 | 服务列表真接后端；"添加/测试"按钮 stub（ElMessage.info） |
| `/workspace-catalog` | `WorkspaceCatalogPage.vue` | 工作区目录（应用相关 vs 通用组件分类） | 真功能（ai-code 类型入口） |
| `/project/:id` | `ProjectOverview.vue` | 项目概览 | 真功能 |
| `/devops` | `BuilderDevOpsPage.vue` | DevOps 面板（公共访问，无需认证） | 真功能 |
| `/proposals/:id` | `ProposalDetailPage.vue` | 提案详情页 | 真功能 |
| `/git/callback/:provider` | `GitOAuthCallback.vue` | Git OAuth 回调页 | 真功能 |
| `/extension-demo` | `ExtensionSectionDemoPage.vue` | ExtensionSection 组件验收 demo（非产品页） | 仅内部验收用 |
| `/section-nav-demo` | `SectionNavDemoPage.vue` | SectionNav 组件 demo（非产品页） | 仅内部验收用 |
| `/datasources` | redirect → `/db-connections` | 老路径兼容 | 重定向 |
| `/settings` | redirect → `/platform-envs` 或 `/tenant-users` | 老路径兼容 | 重定向 |
| `/generate/:id?` | redirect → `/chat?deploy_app_id=:id` | 老部署链接兼容 | 重定向 |

> **警告**: `/ai-chat`（AIChatPage）和 `/chat`（ChatPage）是完全独立的两条路径，功能不同，路由守卫逻辑也不同（ChatPage 必须绑定应用上下文）。

---

## 二、ChatPage 设计器子面板

ChatPage (`/chat?app_id=N`) 是已生成应用的配置工作台，左侧 SectionNav 切换 5 个顶级 Tab，每个 Tab 下有若干子面板：

| 顶级 Tab | 子面板/子 Tab | 对应组件 | 主要功能 | 状态 |
|----------|-------------|---------|---------|------|
| **设计** (design) | 表单 | `FormDesignerPanel.vue` | 业务视角预览（真字段+真数据）；切"编辑"内嵌 apaas 原生表单编辑器 iframe | 预览真；iframe 编辑可能崩（已知 apaas bug） |
| **设计** (design) | 列表 | `ListDesignerPanel.vue` | 业务视角（el-table + 真数据）；切"编辑"显字段配置 | 预览真；编辑 tab 行操作全 alert（见假功能节） |
| **设计** (design) | SPEC 设计 | `SpecDesignPanel.vue` | 11 章节 SPEC 文档渲染；版本历史下拉 | SPEC 只读展示真；"确认并生成"按钮 disabled（P2） |
| **数据** (data) | 数据模型 | `DataSchemaEditor.vue` | 模型列表 + 字段 CRUD；字段编辑/删除接真 apaas API | 删除字段真接后端；新增/编辑数据行 alert 引导对话 |
| **数据** (data) | 数据模型详情 | `DataModelDetailPanel.vue` | 字段 table 查看；编辑/批量编辑 disabled | 只读真；写操作 disabled（P1） |
| **数据** (data) | 字典 | `DictEditorPanel.vue` | 字典 master-detail（左列表+右选项 table） | 查看真；"添加选项" alert；选项"编辑" disabled |
| **逻辑** (logic) | 流程设计 | `ProcessDesignerPanel.vue` | 业务视角（mock 实例着色）+ 设计模式（x6 canvas + 24 节点库）；真接 section-content/processes | 查看真；"创建/编辑流程"按钮 alert；BPMN 详情 P3（无 API） |
| **权限** (perm) | 角色权限矩阵 | `RoleManagePanel.vue` | 角色×资源 4 状态矩阵；角色列表视图（成员 table） | 矩阵推断值（非真权限）；form 类型改动可真存；其他（model/process/app_setting）P5 跳过 |
| **权限** (perm) | 表单权限 | `FormPermPanel.vue` | 角色×操作权限（查看/编辑/删除/新增/导入+数据范围）只读 | 只读真；写回（Phase B）永久阻塞（已知平台 bug，详 MEMORY） |
| **运行** (log) | 日志 | `LogsPanel.vue` | apaas 运行日志流 | 真功能 |
| **运行** (log) | 运行预览 | `CustomPagePreviewPanel.vue` / `ApaasEmbedIframe.vue` | 内嵌 apaas 原生 iframe | 已知 apaas 渲染 bug（偶发崩回首页） |

**ConfigAssistantPanel（配置助手，右侧常驻栏）**:  
- 对话驱动配置修改（自然语言 → 调 MCP 工具 → 真写 apaas）
- 会话历史抽屉（可新建/切换）
- 模型选择 dropdown
- 动态 quick-action chips（按当前 Tab 联动）
- 小屏幕实时预览（MJPEG 视口流）

---

## 三、核心用户流程（端到端）

### Flow 1：从描述需求到生成 apaas 应用（主线）

```
Landing 首页 (/)
  ↓ LandingComposer 输入需求文字 / 上传 .md/.pdf/.docx
AIChatPage (/ai-chat)
  ↓ 发消息 → agent SSE 流 → 生成设计文档 artifact（右侧面板渲染）
  ↓ 应用就绪 CTA 出现（generate_app_from_doc/deploy_application 成功后）
ChatPage (/chat?app_id=N)
  ↓ 4 panel 显示（菜单树 + 设计器面板 + 配置助手 + apaas iframe）
  ↓ 顶栏"发布到生产"→ DeployConfirmModal → 部署到 apaas 平台
  ↓ 顶栏"查看应用"→ 当前页切换内嵌 iframe 打开 apaas 应用
```

**关键步骤对应组件**: Landing → LandingComposer → AIChatPage (AgentConversation + artifact panel) → ChatPage (SectionNav + FormDesignerPanel/DataSchemaEditor/etc + ConfigAssistantPanel + ApaasEmbedIframe) → DeployConfirmModal

---

### Flow 2：已有应用 → 配置助手对话修改

```
Apps (/apps)
  ↓ 点击应用行
ChatPage (/chat?app_id=N)
  ↓ 右侧 ConfigAssistantPanel 输入指令（例："给借书申请表加审批人字段"）
  ↓ agent 调 MCP 工具真写 apaas
  ↓ 左侧设计器面板刷新显示结果
```

---

### Flow 3：上传设计文档快速建应用

```
Landing (/)
  ↓ LandingComposer "上传文件" 按钮 → 选 .md/.pdf/.docx
  ↓ 跳 ChatPage (/chat?from=upload)
ChatPage
  ↓ pendingFile → 触发文档解析 + AI 生成
```

---

### Flow 4：AIChatPage 生成设计文档 → 送给 Builder 建应用

```
AIChatPage (/ai-chat)
  ↓ AI 生成 markdown artifact
  ↓ 点 artifact 卡上"在 Builder 中调整"按钮
ChatPage (/chat?from=aichat)
  ↓ pendingMarkdown → 继续构建
```

---

### Flow 5：应用部署后切自开发

```
ChatPage (/chat?app_id=N)
  ↓ 顶栏"→ 自开发"（应用已部署 apaas_app_id 存在时才显示）
  ↓ sessionStorage 注入 app context（模型/表单/角色）
CodingPage (/coding?embeddedAppId=N)
  ↓ AI Coding agent 对话，带应用结构上下文
  ↓ IDE 抽屉 + 文件抽屉 + 代码生成 + 部署
```

---

### Flow 6：平台环境管理（管理员）

```
PlatformEnvs (/platform-envs)  [requiresTenantAdmin]
  ↓ Tab1: 添加/编辑/删除 aPaaS 平台环境（host/用户名/密码）
  ↓ Tab2: 新增/编辑/删除 LLM 模型配置
  ↓ 测试连接 / 登录刷新 token → 连接状态更新
```

---

### Flow 7：成员管理（管理员）

```
TenantUsers (/tenant-users)  [requiresTenantAdmin]
  ↓ 邀请用户（输入用户名/email/角色）
  ↓ 修改用户权限（平台管理员/租户管理员/开发者/查看者）
  ↓ 删除用户
```

---

### Flow 8：DB 快速接入（Wizard，当前半功能）

```
Landing (/) → Landing 第4张卡入口 或 QuickDb (/quick-db)
  Step1: 填数据库连接（MySQL/PG/SQLServer 等）→ 测试连接
  Step2: 表多选（智能跳过框架表）
  Step3: 填业务描述 + 选模板风格
  Step4: 生成（进度条）→ 完成后跳应用页
  ⚠️ Step4 后端 stub，真实生成端点未接
```

---

## 四、Admin-SPA 平台管理后台

Admin-SPA 独立打包，基路径 `/mcp-server/admin/`，平台管理员登录后操作：

| 路由 | 视图 | 功能 | 状态 |
|------|------|------|------|
| `/status` | `SystemStatus.vue` | 平台概览（MCP 服务状态/工具数/快捷链接） | 真功能 |
| `/mcp` | `McpServices.vue` | MCP 服务清单（5个入口：Builder/Coding/Vibe/Design/Main）；显示协议/URL/工具数；复制地址 | 真功能，只读展示 |
| `/tester` | `McpTester.vue` | MCP 测试台：选服务→获取工具列表→单工具调用测试 | 真功能（调试用） |
| `/tenants` | `PlatformTenants.vue` | aPaaS 租户列表：从平台同步租户（select 管理员 + 刷新） | 真功能 |
| `/envs` | `PlatformEnvs.vue` | **占位页（下线）**，任务迁到 ai-builder `PlatformEnvs.vue` | 仅显 PlaceholderView，Phase 4.2 待做 |
| `/llm-configs` | `LlmConfigs.vue` | 大模型配置 CRUD（供应商/模型/API Key/默认模型） | 真功能 |
| `/users` | `PlatformUsers.vue` | 平台用户管理 | 真功能 |
| `/workspaces` | `SandboxMonitor.vue` | 工作区监控（启动/停止/销毁 coding workspace） | 真功能 |
| `/logs` | `CallLogs.vue` | MCP 调用日志（多条件过滤：服务/状态/时间/关键词） | 真功能 |
| `/datasources` | `PlatformDatasources.vue` | 数据源管理（从 ai-builder 工作台搬来） | 真功能 |
| `/design-preview/:draftId` | `DesignPreview.vue` | 设计稿预览 | 真功能 |

---

## 五、假功能清单（未接真后端，点了无效）

> 来源: `docs/audit-2026-05-29-codebase-health.md §B` + 本次代码核查

| # | 位置 | 按钮/操作 | 实际行为 | 备注 |
|---|------|-----------|---------|------|
| 1 | `ListDesignerPanel.vue:505` | 列表行"查看详情" | `alert()` 弹窗（P1 接入提示） | 未接真 |
| 2 | `ListDesignerPanel.vue:513` | 列表行"编辑数据行" | `alert()` 弹窗（引导去应用运行页） | 未接真 |
| 3 | `ListDesignerPanel.vue:517` | 列表"添加列" | `alert()` 弹窗（引导用配置助手） | 未接真 |
| 4 | `ListDesignerPanel.vue:521` | 列表"批量编辑" | `alert()` 弹窗 | 未接真 |
| 5 | `ListDesignerPanel.vue:525/529` | 列表"编辑列"/"删除列" | `alert()` 弹窗 | 未接真 |
| 6 | `ListDesignerPanel.vue:312` | 列表预览数据 | 默认显 mock fallback 数据（5行假数据） | 真实数据 API 可能返空时降级 |
| 7 | `DataModelDetailPanel.vue:67` | 数据模型"新增字段" | `disabled`，永久不可点 | 未接真（P1） |
| 8 | `DataModelDetailPanel.vue:66` | 数据模型"批量编辑" | `disabled`，永久不可点 | 未接真（P1） |
| 9 | `DataModelDetailPanel.vue:41` | 数据模型"编辑模型名" | `alert()` 弹窗 | 未接真（P1） |
| 10 | `DictEditorPanel.vue:63,174` | 字典"+ 添加选项" | `alert()` 弹窗（引导用配置助手） | 未接真（P2） |
| 11 | `DictEditorPanel.vue:103` | 字典选项"编辑 (⋯)" | `disabled` | 未接真（P2） |
| 12 | `ProcessDesignerPanel.vue:655` | 流程"用对话创建流程"（空态 CTA 内部 alert 路径） | `alert()` 弹窗引导 | 跳转配置助手功能 OK，alert 本身是过渡 |
| 13 | `ProcessDesignerPanel.vue:1264` | 流程节点"AI 提问" | `alert()` 弹窗（P2 转给 ConfigAssistant） | 未接真（P2） |
| 14 | `ProcessDesignerPanel.vue` 保存按钮 | 保存流程 | `alert()` 弹窗（走配置助手对话） | 未接真；apaas 无 query process detail API（P3） |
| 15 | `RoleManagePanel.vue:751` | 权限矩阵"新增角色" | `alert()` 弹窗（引导配置助手） | 未接真 |
| 16 | `RoleManagePanel.vue:755` | 角色列表"添加成员" | `alert()` 弹窗（引导配置助手） | 未接真 |
| 17 | `RoleManagePanel.vue:572` | 权限矩阵 model/process/app_setting 类型改动 | 本地 state 假更新 + alert 提示 P5 跳过 | form 类型改动可真存；其他类型永久假（P5） |
| 18 | `RoleManagePanel.vue:261` | 权限矩阵显示内容 | 推断值（基于角色名），非真 apaas 权限 | 视觉上像真权限矩阵，但数据是假的 |
| 19 | `DataSchemaEditor.vue:1370` | 数据 Tab "新增数据"行 | `alert()` 弹窗（引导配置助手） | 未接真 |
| 20 | `SpecDesignPanel.vue` | SPEC"确认并生成"按钮 | `disabled` | P2 待接 |
| 21 | `FormPermPanel.vue` | 表单权限"编辑/写回" | 整个写入路径阻塞，界面仅只读 | 平台破坏性写入 bug（已知根因，详 MEMORY `form_perms_on_designer_2026_05_29.md`） |
| 22 | `ChatPage.vue` 顶部"生产"环境切换 | 切到生产环境 | 真功能（如有 prod env 配置），但无 prod env 时 disabled | 条件性可用 |
| 23 | `QuickDbPage.vue` Step4 生成 | DB 接入 Wizard 最终生成 | UI 骨架，后端 endpoint 未接 | 整个 QuickDb flow 当前半功能 |
| 24 | `RuntimePage.vue` 流水线操作按钮 | 触发流水线/回滚 | `ElMessage.info` stub | 数据真接后端，操作按钮 P2 stub |
| 25 | `McpHubPage.vue` "添加"/"测试"服务按钮 | 添加/测试 MCP 服务 | `ElMessage.info` stub | P3 |
| 26 | `IndustryPage.vue` 行业包操作按钮 | 安装/使用行业包 | `ElMessage.info` stub | P2 |
| 27 | `AgentsPage.vue` MCP server 条目（8个） | 显示 MCP 绑定 | 本地 stub 数据（非真配置） | Session 4/5 backend 才接真 |

---

## 六、测试建议：可做端到端测试的核心流程

以下流程可在 staging 环境执行冒烟测试：

| # | 流程名称 | 入口 | 预期结果 | 优先级 |
|---|---------|------|---------|--------|
| T1 | 登录 + 租户选择 | `/login` | 成功登录跳 Landing | P0 |
| T2 | 首页加载统计 + 最近应用 | `/` | stats 非 0，最近 5 条应用可点 | P0 |
| T3 | AIChatPage 新建会话 → 描述需求 → 等 agent 回复 | `/ai-chat` | agent SSE 流式输出，工具卡出现 | P0 |
| T4 | AIChatPage 上传 .md 文件 → 生成设计文档 artifact | `/ai-chat` | artifact 右侧面板显示渲染后内容 | P0 |
| T5 | AIChatPage 生成应用 → CTA 卡出现 → 点"打开应用" | `/ai-chat` | 跳 ChatPage，app_id 正确 | P0 |
| T6 | ChatPage 表单设计器预览（已部署应用） | `/chat?app_id=N` → 设计→表单 | 字段列表加载，业务视角 grid 显示 | P1 |
| T7 | ChatPage 表单设计器切"编辑"（内嵌 apaas iframe） | 同上 → 点"编辑" | apaas 原生编辑器加载（可能崩，已知 bug） | P1 |
| T8 | ChatPage 数据模型列表加载 + 字段查看 | 数据 Tab → 点模型 | `DataModelDetailPanel` 显字段 | P1 |
| T9 | ChatPage 流程设计器加载（有流程的应用） | 逻辑 Tab → 流程 | x6 canvas 渲染节点，业务视角 mock 实例 | P1 |
| T10 | ChatPage 角色权限矩阵显示 | 权限 Tab | 矩阵渲染（注意：内容为推断值，非真权限） | P1 |
| T11 | ChatPage 配置助手发送指令 → agent 调工具 | 右侧 ConfigAssistantPanel | agent 回复，工具调用可见 | P0 |
| T12 | ChatPage 顶部"发布到生产"→ 部署弹窗 → 部署进度 | ChatPage 有应用 | DeployConfirmModal 弹出，进度条展示 | P0 |
| T13 | ChatPage 顶部"查看应用"→ apaas iframe 加载 | 部署后 | iframe 内嵌 apaas 应用（已知偶发崩回首页） | P1 |
| T14 | ChatPage →"→ 自开发"→ CodingPage 带上下文 | 已部署应用 | CodingPage 接收 sessionStorage app context | P1 |
| T15 | Apps 列表导入应用（ImportAppDialog） | `/apps` → 导入 | 弹窗可填信息，提交后应用出现在列表 | P1 |
| T16 | PlatformEnvs 添加环境 + 测试连接 | `/platform-envs` | 连接状态更新为 connected | P1 |
| T17 | PlatformEnvs 新增 LLM 模型 | `/platform-envs` → 模型配置 Tab | 模型出现在 AIChatPage 模型选择下拉 | P1 |
| T18 | TenantUsers 邀请用户 | `/tenant-users` | 用户出现在列表，角色正确 | P1 |
| T19 | Admin-SPA MCP 服务清单展示 | `/mcp-server/admin/mcp` | 5个服务条目在线 | P1 |
| T20 | Admin-SPA MCP 测试台调工具 | `/mcp-server/admin/tester` | 获取工具列表成功，单工具调用返回 | P1 |
| T21 | Admin-SPA LLM 模型 CRUD | `/mcp-server/admin/llm-configs` | 新增/编辑/删除成功 | P1 |
| T22 | 流程 - 有流程设计器加载 + 节点着色 | 逻辑 Tab，选有流程应用 | 业务视角绿/蓝/灰节点着色 | P2 |
| T23 | AIChatPage 切换 LLM 模型 | `/ai-chat` 底部 select | 下一条消息使用选中模型（后端确认） | P2 |
| T24 | ChatPage SPEC 设计 Tab 加载 + 历史版本 | 设计 Tab → SPEC 设计 | 11 章节渲染，版本下拉列出历史 | P2 |

---

## 七、附：已知非功能约束（影响测试）

1. **apaas iframe 偶发崩回首页**（已知根因：apaas 渲染引擎 undefined.type/engineContext bug，闭源无法修复）。T7/T13 测试用例预期可能失败，已有 stub 缓解（缺组件 404 降级空 200）。
2. **表单权限写入永久阻塞**（FormPermPanel 只读，写回破坏 advancedPermissionGroups，详见 MEMORY）。T 中不测表单权限写入。
3. **QuickDb Flow 后端 stub**（T8 中途止步 Step3，Step4 生成不可测）。
4. **权限矩阵内容为推断假数据**（T10 请勿依赖矩阵内容做业务验证）。
