# Code 系统助手 P0 技术方案

**文档 ID**：`ARCH-20260809-002-code-system-assistant-p0`
**版本**：`1.0`
**状态**：P0 实现中
**适用工程**：`apaas-builder-ai`

## P0 增量边界与事实源

系统助手是 Code Web 与桌面客户端中的系统级对话入口，用于盘点、建设和维护企业 Code 能力。它不是某一种脚手架生成器，也不绑定 React、Spring Boot 或其他固定技术栈。

系统助手所在宿主继续使用 `apaas-builder-ai` 既有 Vue 3、TypeScript、FastAPI、SQLAlchemy 与 Tauri 技术基线。被系统助手诊断或修改的目标工程，其语言、框架、构建方式、测试方式和目录结构必须从真实仓库、工作区或模板清单识别，不能从宿主技术栈推断。

P0 只增加以下职责：

- `assistant_profile=system_assistant` 会话入口；
- Code 导航、应用页入口和系统助手会话页面；
- 当前组织范围内的只读 Code 基线摘要；
- 对现有 AIChat 消息、SSE、附件、停止、产物和运行恢复链路的复用；
- 对工作区工具、组织边界和可见资产来源的收紧。

P0 不新增 Runtime Plan、operation store、资产主数据、桌面 Runtime 生命周期或发布协议。Full Workspace 仍是共享 Skill、知识、MCP、模型和数字员工资产的权威来源；本地 Builder 数据只能作为明确标记的缓存或 preset 展示。

## AIChat 会话、组织与运行恢复合同

`assistant_profile` 与 `mode` 正交：系统助手使用 `mode=code`，但不把 `system_assistant` 写入旧 mode 字段。旧会话缺省为 `entry_agent`，Builder、Entry Agent 和应用 Code 会话行为保持不变。

系统助手复用现有 AIChat 会话表、消息表、工具调用、附件、产物和 run bus，不创建第二套会话 API、Pinia Store、SSE reducer 或浏览器侧主存储。

会话隔离同时满足：

- 本地租户与用户隔离；
- Control Plane 组织隔离；
- `assistant_profile=system_assistant` 过滤；
- 详情、列表和恢复使用相同边界。

页面加载历史会话后调用现有 `run-status`，检测到运行中任务时使用 `attach` 恢复事件流。切换会话只终止当前浏览器的 SSE 连接，不自动取消后台任务；用户显式停止时继续使用现有 `abort`。

P0 不宣称提供分布式并发锁、节点级暂停或幂等外部 operation。上述能力属于 Runtime 后续阶段。

## 工具与工作区安全边界

系统助手默认不继承宿主全部本地工具。工程读取、修改、构建和测试必须通过绑定 `workspace_id` 的 workspace 工具执行，工具根目录由现有工作区服务校验。

会话临时目录只用于附件、产物和受限的临时计算。P0 不自动暴露无工作区边界的 `write_file`、`edit_file`、`run_command` 和 `start_serve`。

系统助手可以读取基线、扫描工程、运行聚焦测试和形成草稿。Git push、共享 Skill 发布、权限扩大、环境写入、部署和生产操作仍需要后续受控协议与明确确认，P0 不通过提示词伪造这些能力。

## 只读基线来源与失败语义

`GET /api/system-assistant/bootstrap` 返回当前组织的只读基线快照、一个推荐动作、可用动作列表和逐来源状态。它不创建 Runtime Plan。

P0 节点包括工程与工作区、环境、能力、知识、Skill、治理和模板来源。状态区分 `ready`、`partial`、`missing`、`stale`、`unavailable` 与 `not_needed`。

来源语义如下：

- 本地工作区只返回当前用户可见记录；
- 环境拓扑只对租户管理员或平台管理员读取，普通成员收到权限受限状态；
- 本地 Knowledge 标记为 `builder_local_cache`；
- 本地 Skill 只展示 `local_platform_preset`，不把无法证明归属的 user Skill 投影为个人资产；
- Full Workspace、远程能力与模板目录不可用时必须显示 `unavailable` 或 `partial`，不能伪装为空数据；
- 任一关键来源为 `partial` 或 `unavailable` 时，不得返回“无需操作”。

各来源自行降级，快照投影、策略和契约中的编程错误进入标准 5xx，不能被路由 catch-all 伪装为 200。

## Code Web 与桌面入口复用

系统助手页面位于静态路由 `/code/system-assistant`，路由顺序必须在 `/code/:id` 之前，避免被解释为应用 ID。

Code 导航和 Code 应用页提供同一个入口。进入系统助手页面时，全局 Rail 只查询 `mode=code + assistant_profile=system_assistant` 的 AIChat 会话；普通 Code 应用页面继续读取 Code Runtime 会话历史，两类历史不混合。

主区继续复用 `AgentConversation`、`UnifiedChatComposer`、`BuilderModelPicker`、`AgentRunTraceDrawer` 和现有产物查看组件。首屏展示真实 bootstrap 基线和一个推荐动作；有消息后基线收缩为状态条，不增加固定流程菜单、右侧 Plan 面板或占位卡片。

模型列表使用 Code 用途配置。输入框在任务运行中仍可编辑草稿，发送按钮按现有能力提供停止；P0 不伪造队列发送或节点级暂停。

桌面端复用同一 Vue 页面和后端 profile。P0 不修改 sidecar、Tauri Runtime target 或桌面单 Runtime 生命周期。

## P1/P2 延迟范围、回滚与验证

P1 再接入 Agent Runtime 唯一 Dynamic Plan、节点暂停/恢复/取消/重试、幂等 operation、Full Workspace 资产委托和版本化 `asset_ref`。P2 再处理桌面单 Runtime、本地/远程 target 恢复与跨会话目录租约。

P0 回滚按原位增量处理：移除静态路由和入口、停止创建 `system_assistant` profile 会话、保留旧会话字段的向后兼容读取。无需回滚 Builder、Code Runtime、桌面 sidecar 或数据库主业务结构。

P0 验证必须覆盖：

1. profile 默认迁移、创建、列表、详情与旧 mode 回归；
2. 本地用户、租户与 Control Plane 组织隔离；
3. bootstrap 权限和来源失败语义；
4. 系统助手工具白名单与工作区边界；
5. 前端 Code 入口、真实会话创建、附件、工具过程、最终回复和产物；
6. 刷新后 `run-status/attach` 恢复；
7. Code Web 构建和真实浏览器主路径。

文本或 CSS 类检查不能替代真实浏览器会话验证。P0 验收不包含 Git push、共享资产发布、生产部署或 Runtime 节点级暂停。
