# Code 系统助手 Implementation Plan

Design spec: `../product-design/docs/superpowers/specs/2026-07-18-orcamatrix-agentic-developer-workbench-design.md`

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 Code Web/桌面客户端中交付一个以企业 Code 能力基线为中心的系统助手，能够识别和治理任意工程/仓库、环境、能力、知识、Skill、协作治理及验证流程，同时复用现有会话、Runtime 和资产事实源。模板或脚手架只是可选的工程来源，不是系统助手的产品前提。

**Architecture:** `apaas-builder-ai` 负责系统助手入口、会话编排、资产委托适配、Code 工作区和本地/远程 Runtime 选择；`agent-runtime` 负责 Dynamic Plan、节点执行、暂停/恢复/取消、事件时间线和恢复事实；Full Workspace 继续是 Skill、知识库、MCP、模型和共享员工资产的唯一主数据。系统助手通过 `system_assistant` profile 接入现有 Entry Agent/AIChat 会话，不创建第二套浏览器会话存储。

**Tech Stack:** Vue 3 + TypeScript + Pinia + Element Plus + Vite；FastAPI + SQLAlchemy + Pydantic + SSE；Tauri/Rust + Python sidecar；Agent Runtime Go HTTP/SSE；现有 Code workspace、LocalRuntimeClient、Agentic Coding worker 和 Full Workspace API。

## Global Constraints

- 系统助手只在 Code/桌面客户端提供；不修改 `web-console` 入口和页面，不改变 Builder 低代码对话和 Builder API。
- 会话事实源只能是现有 Entry Agent/AIChat 会话主数据；不得新增平行 conversation API、浏览器侧会话主存储或第二套 Plan 状态机。
- Dynamic Plan、节点状态、attempt、暂停/恢复和事件事实由 Agent Runtime 持有；`apaas-builder-ai` 只保存会话/profile、绑定和只读投影引用。
- Full Workspace 是 Skill、知识库、MCP、模型和共享数字员工资产的唯一事实源；Builder 只能创建草稿、发起受控委托、查询对账并展示 `asset_ref`。
- 本地桌面模式只启动本机 Runtime/sidecar，不调用远程注册、远程沙箱创建或线上发布接口；远程模式复用现有 Code Runtime Proxy 和 token heartbeat。
- 系统助手明确支持附件；现有 Builder、Entry Agent 和应用 Code 会话的附件行为保持当前实现，不在本计划中改变或全局收紧。
- 运行中输入框始终可用；暂停的是 Plan 节点或 operation，不锁死会话，不丢弃草稿；所有写操作使用幂等键和版本条件。
- URL 不携带长期 token、租户密钥或运行时凭据；深链打开资产时重新校验租户、权限、版本和来源。
- 低风险动作可自动执行；修改共享资产、扩大权限、环境写入、Git push、发布和不可逆操作必须展示影响并确认。
- 新增代码文件不超过 500 行；每个新模块只承担一个职责，复用现有 UI token、AgentConversation、SessionSidebar 和 Code Runtime API。
- 本轮只完成 Code 系统助手的第一版闭环：基线诊断、草稿/受控变更、Code 工作区执行和验证；生产集群、数据库结构变更、生产 CI/CD 发布保持明确拒绝。

## Product Contract

### 1. 入口与用户路径

Code 客户端增加一个“系统助手”入口，进入后仍是普通对话，而不是固定流程选择器。首屏展示当前企业 Code 基线摘要：

- 工程资产：已有仓库、工作区、可选模板/脚手架、版本、最近验证结果和适用技术栈；技术栈从工程或模板清单识别，不由系统助手写死；
- 环境：本地 Runtime、开发环境、测试环境及可用性；
- 能力：Git、CI/CD、镜像仓库、数据库、消息、监控、MCP 的已接入/缺口；
- 知识与 Skill：已发布、个人草稿、来源不可用或版本过期；
- 治理：当前账号权限、可自动执行范围、需要确认的动作；
- 推荐下一步：只给一个当前最有价值的动作，允许用户直接改问其他事情。

系统助手收到“帮我完善企业 Code 基线”时执行基线诊断，再按诊断结果动态生成节点。推荐路线为：

1. 盘点已有工程/仓库，必要时再选择或完善一个可选模板；
2. 补齐本地/远程开发环境；
3. 接入 Git、CI/CD、镜像、数据库、消息、监控和 MCP 能力；
4. 建立企业知识库和 Skill；
5. 配置数字员工协作、权限、审计和审批边界；
6. 用真实样例应用完成开发、测试、构建和运行验证；
7. 生成企业 Code 基线快照并进入持续维护。

这七项是可插拔节点，不是强制顺序。缺口不存在时节点直接标记 `not_needed`；有依赖时只展开受影响的下游节点。

### 2. 统一协议

```python
class SystemAssistantScope(BaseModel):
    tenant_id: str
    user_id: int
    client: Literal["web", "desktop"]
    runtime_target: Literal["local", "remote"]
    workspace_id: str | None = None
    repository_ref: str | None = None

class SystemAssistantOperation(BaseModel):
    operation_id: str
    idempotency_key: str
    session_id: str
    plan_id: str | None
    plan_version: int | None
    action: str
    target: str
    risk: Literal["low", "medium", "high"]
    status: Literal["requested", "accepted", "running", "succeeded", "failed", "outcome_unknown", "cancelled"]
    runtime_target: Literal["local", "remote"]
    request_digest: str

class AssetRef(BaseModel):
    asset_type: str
    source_system: Literal["full_workspace", "control_plane", "agent_runtime", "local_workspace"]
    tenant_id: str
    asset_id: str
    asset_version: str | None
    resolve_action: str
    return_context: dict[str, str]
```

事件使用同一 SSE envelope：`session_id`、`plan_id`、`plan_version`、`node_id`、`operation_id`、`sequence`、`event_type`、`payload`。必需事件为 `plan.snapshot`、`plan.node.updated`、`operation.started`、`operation.progress`、`approval.required`、`artifact.ready`、`operation.completed`、`operation.failed`、`session.paused`、`session.resumed`、`done`、`error`。

### 3. 风险与恢复

系统助手可执行的动作分为：

| 风险 | 默认行为 | 典型动作 |
| --- | --- | --- |
| low | 自动执行并记录 | 读取基线、扫描仓库、运行测试、生成草稿、读取环境健康 |
| medium | 展示差异后执行 | 修改选定模板或仓库、安装依赖、更新开发配置、拉取并修改代码 |
| high | 明确确认/审批 | Git push、共享 Skill 发布、扩大权限、环境绑定、发布资产 |

所有 operation 支持 `retry`、`cancel`、`reconcile`。取消只停止可取消节点，不删除脏工作区；响应丢失统一进入 `outcome_unknown`，随后用原幂等键查询，不重复创建资产或执行外部写入。

## File Map

### `apaas-builder-ai`

- Modify: `backend/app/models/ai_chat.py` — 为 AIChatSession 增加 `assistant_profile`，保留旧 mode 行为；P1 的 Plan/runtime 字段不在 P0 提前落库。
- Create: `backend/app/models/system_assistant.py` — 仅保存本地的 operation/委托/审计投影，不保存 Full Workspace 资产正文和 Runtime Plan 主状态。
- Modify: `backend/app/database.py` — SQLite/MySQL 兼容的增量列和表创建，启动时校验旧数据默认 `entry_agent`。
- Create: `backend/app/system_assistant/contracts.py` — P0 profile 和基线摘要合同；P1 再扩展 operation/asset_ref。
- Create: `backend/app/system_assistant/baseline_service.py` — P0 只读基线快照、缺口分类和推荐下一步。
- Create: `backend/app/routes/system_assistant.py` — P0 bootstrap 和 profile 会话摘要 API；P1 再扩展 Plan/action/asset 委托。
- Modify: `backend/app/routes/ai_chat.py` — 创建/发送/附件/列表接口增加 `system_assistant` profile 守卫和返回字段，底层仍复用 AIChat run bus。
- Modify: `backend/app/main.py` — 注册系统助手路由。
- Create: `backend/tests/test_system_assistant_contracts.py`、`test_system_assistant_policy.py`、`test_system_assistant_service.py`、`test_system_assistant_routes.py`。
- Modify: `backend/tests/test_ai_chat_routes.py`、`test_code_runtime_routes.py` — 验证旧 Builder/Code 会话不被 profile 变化污染。

- Create: `frontend/src/api/systemAssistant.ts` — typed API、SSE 消费、attach/reconcile。
- Create: `frontend/src/stores/systemAssistant.ts` — 会话/Plan/operation/附件状态；浏览器状态只作为缓存。
- Create: `frontend/src/views/SystemAssistantPage.vue` — Code 侧系统助手主页面。
- Create: `frontend/src/views/system-assistant/SystemAssistantBaseline.vue`、`SystemAssistantPlan.vue`、`SystemAssistantOperationCard.vue`、`SystemAssistantAssetCard.vue`、`systemAssistantModels.ts`。
- Modify: `frontend/src/router/index.ts` — 在 Code 路由下增加 `system-assistant`，不改 Builder 和 web-console 路由。
- Modify: `frontend/src/views/CodeConversationPage.vue`、`frontend/src/views/Apps.vue` — 增加系统助手入口/返回 Code 工作区的显式深链。
- Reuse: `frontend/src/components/common/AgentConversation.vue`、`SessionSidebar.vue`、`AgentRunTraceDrawer.vue` 和 Code composer 样式，不复制一套消息渲染器。
- Create: `frontend/src/views/SystemAssistantPage.spec.ts`、`frontend/src/stores/systemAssistant.spec.ts`、`frontend/src/api/systemAssistant.spec.ts`。

- P2 才修改桌面 Runtime 配置；P0 不改变现有桌面 sidecar 生命周期。

### `agent-runtime`（P1/P2）

- P1 才修改 Agent Runtime；P0 不新增 Go 侧 Plan/operation 协议，避免与现有 Runtime 状态产生第二事实源。
- Modify: `internal/http/asset_handlers.go`、`digital_employee_handlers.go`、`capability_mcp_handlers.go` — 资产引用、能力检查和委托结果投影。
- Create: `internal/systemassistant/baseline.go`、`planner.go`、`operation_store.go` — 动态基线节点、幂等 operation 和状态 reducer；唯一在线 owner 仍是 Runtime Workflow Store。
- Create: `internal/http/system_assistant_handlers.go` 及对应 `_test.go` — Runtime 端 API 与 SSE。

### `app-seed` / `agentic-coding`

- `app-seed/` 不是系统助手的核心依赖，仅作为一个可选模板来源适配仓库；P0 不修改它。
- `agentic-coding/` 只保留 worker 执行合同、Skill 使用策略和不可变 execution receipt；不在其中新增 Plan Store、系统助手会话或资产主数据。

## Implementation Staging

本次先交付一个可运行、可验证的 P0 闭环，再扩展 Runtime/资产治理能力。P0 不新增第二套 Plan Store、资产主数据或桌面 Runtime 生命周期；它复用现有 AIChat run bus、工作区工具和 Code Shell，只新增系统助手 profile、入口、通用基线摘要和会话恢复。P1/P2 的 Runtime Dynamic Plan、Full Workspace 委托和桌面单 Runtime 由后续任务推进，不能在 P0 中提前假设接口已经存在。

### P0 本次执行范围

- `assistant_profile=system_assistant` 独立于现有 `mode=chat|cowork|code`；旧会话缺省为 `entry_agent`。
- 系统助手复用 AIChat 会话、SSE、附件、停止和历史恢复链路。
- 系统助手 profile 使用通用工程诊断/工作区/Skill/知识读取能力，不绑定任何语言或框架，不进入 Builder 应用创建分支。
- Code Shell 增加系统助手入口和独立页面；页面复用 `AgentConversation`、会话列表和现有 composer，不复制消息渲染器。
- 增加只读基线摘要 API，来源不可用时显示 `unavailable`，不把不可用当成空数据。
- 用真实本地 AIChat 会话验证创建、历史恢复、附件、工具调用、最终回复和 Code 入口；不做 mock-only 验收。

### P1/P2 后续范围

- P1：Agent Runtime 唯一 Dynamic Plan、节点暂停/恢复/取消/重试/对账和事件投影。
- P1：Full Workspace Skill/知识/MCP/模型委托、版本化 `asset_ref` 和审计。
- P2：桌面端单 Runtime、本地/远程 target 恢复、跨租户/用户 workspace 隔离和发布门禁。

## Implementation Tasks

### Task 1: Add an isolated assistant profile and migration boundary (P0)

**Files:**
- Create: `apaas-builder-ai/backend/app/system_assistant/contracts.py`
- Modify: `apaas-builder-ai/backend/app/models/ai_chat.py`
- Modify: `apaas-builder-ai/backend/app/database.py`
- Test: `apaas-builder-ai/backend/tests/test_system_assistant_contracts.py`

**Interfaces:**
- `assistant_profile` 与 `mode` 分离；P0 只冻结 profile、附件和会话恢复字段，不冻结 P1 的跨 Runtime operation 合同。
- 旧 `AIChatSession.mode in {chat,cowork,code}` 的读取结果不变；缺省 `assistant_profile` 为 `entry_agent`。

- [ ] Step 1: 写 Python schema/route 测试，覆盖合法 profile、未知 profile、旧会话默认值和现有附件行为不回归。
- [ ] Step 2: 实现 `assistant_profile` 增量列和 API 字段；禁止使用 `mode=system_assistant` 污染旧模式。
- [ ] Step 3: 在 profile 解析中加入 `system_assistant`，复用现有工具注册表和 run bus。
- [ ] Step 4: 运行 `pytest -q tests/test_system_assistant_contracts.py tests/test_ai_chat_routes.py`。
- [ ] Step 5: Commit `feat(system-assistant): add isolated conversation profile`。

### Task 2: Add the `system_assistant` profile to the existing conversation chain (P0)

**Files:**
- Modify: `apaas-builder-ai/backend/app/routes/ai_chat.py`
- Modify: `apaas-builder-ai/backend/app/ai_chat/agent.py`
- Test: `apaas-builder-ai/backend/tests/test_system_assistant_profile.py`
- Test: `apaas-builder-ai/backend/tests/test_ai_chat_routes.py`

**Interfaces:**
- `POST /api/ai-chat/sessions` 接受 `assistant_profile=system_assistant`，仍按原规则使用 `mode=chat|cowork|code`。
- `POST /api/ai-chat/sessions/{id}/send`、`/attach`、`/run-status`、`/attach`、`/abort` 继续复用同一 run bus。
- `resolve_profile(session) -> AgentProfile` 将系统助手工具集限制为系统资产、Code workspace、Runtime 和验证工具。

- [ ] Step 1: 写测试，验证 system assistant 可创建/列表/恢复，Builder/Entry Agent/Code 的现有附件行为保持不变。
- [ ] Step 2: 实现 profile 解析和系统助手 system prompt，明确先基线诊断、再执行受控动作，不进入应用创建 `create_new` 分支。
- [ ] Step 3: 保持现有工具调用事件字段和 run bus 不变；仅确认 system assistant 事件沿用现有会话标识和恢复链路，P1 再扩展 Plan/operation 字段。
- [ ] Step 4: 复用现有 abort、run-status 和 attach 行为；P1 再实现节点级暂停/恢复和可恢复 snapshot，页面关闭不取消后台 run。
- [ ] Step 5: 运行 `pytest -q tests/test_system_assistant_profile.py tests/test_ai_chat_routes.py`。
- [ ] Step 6: Commit `feat(system-assistant): reuse ai-chat conversation profile`。

### Task 3: Implement baseline diagnosis and the adaptive enterprise Code route (P0)

**Files:**
- Create: `apaas-builder-ai/backend/app/system_assistant/baseline_service.py`
- Create: `apaas-builder-ai/backend/app/system_assistant/policy.py`
- Test: `apaas-builder-ai/backend/tests/test_system_assistant_baseline.py`

**Interfaces:**
- `GET /api/system-assistant/bootstrap` 返回 `baseline_snapshot`、`recommended_action`、`available_actions` 和 `source_status`。
- P0 只返回推荐路线草稿，不创建 Runtime Dynamic Plan；P1 才把它提交到 Agent Runtime。

- [ ] Step 1: 用通用 fixture 构造“只有已有仓库/有可选模板/已有仓库但验证过期/已有完整基线”四种输入并写期望节点；fixture 不绑定具体语言或框架。
- [ ] Step 2: 实现只读基线扫描，区分 `ready`、`partial`、`missing`、`stale`、`unavailable`，不把不可用当成空数据。
- [ ] Step 3: 实现只读推荐动作，缺口不存在时输出 `not_needed`，不生成固定角色流水线。
- [ ] Step 4: 保留推荐路线为轻量草稿；节点依赖、Plan snapshot 和动态 reducer 延后到 P1，不在 P0 虚构 Runtime 接口。
- [ ] Step 5: 运行后端定向测试，并校验 snapshot JSON 与通用 fixture 一致。
- [ ] Step 6: Commit `feat(system-assistant): add adaptive code baseline snapshot`。

### Task 4: Add controlled asset and capability operations (P1, deferred)

**Files:**
- Create: `apaas-builder-ai/backend/app/system_assistant/asset_gateway.py`
- Create: `apaas-builder-ai/backend/app/system_assistant/service.py`
- Create: `apaas-builder-ai/backend/app/routes/system_assistant.py`
- Modify: `apaas-builder-ai/backend/app/main.py`
- Modify: `agent-runtime/internal/http/asset_handlers.go`
- Modify: `agent-runtime/internal/http/capability_mcp_handlers.go`
- Test: `apaas-builder-ai/backend/tests/test_system_assistant_asset_gateway.py`
- Test: `apaas-builder-ai/backend/tests/test_system_assistant_routes.py`
- Test: `agent-runtime/internal/http/system_assistant_handlers_test.go`

**Interfaces:**
- `GET /api/system-assistant/assets/{asset_type}`：只读 Full Workspace/Control Plane 投影。
- `POST /api/system-assistant/sessions/{session_id}/actions`：body `{action,target,payload,plan_version,idempotency_key}`。
- `POST /api/system-assistant/operations/{operation_id}/reconcile`：查询外部结果，不重复写。
- `GET /api/system-assistant/assets/resolve?asset_type=&asset_id=&version=`：返回可访问、无权限、已删除、版本不可见、来源不可用或引用失效。
- 资产委托必须携带 `operation_id`、Full Workspace request id、draft digest、tenant id、visibility、publish level、approval ref。

- [ ] Step 1: 为本地只读、远程只读、外部写成功、响应丢失、权限拒绝和版本冲突分别写 route tests。
- [ ] Step 2: 实现 `AssetGateway`，Skill/知识/MCP/模型读取走已有 API；本地 Skill 仅作为 local preset 或个人草稿，不成为共享主数据。
- [ ] Step 3: 实现 action policy：扫描/测试/草稿自动执行；修改环境、Git push、共享发布需要 confirmation token。
- [ ] Step 4: 实现幂等 operation store，`same key + same digest` 返回原结果，`same key + different payload` 返回 `IDEMPOTENCY_CONFLICT`。
- [ ] Step 5: 实现 Full Workspace delegate/reconcile 适配；超时进入 `outcome_unknown`，不在 Builder 本地补写资产。
- [ ] Step 6: 运行后端和 Runtime handler 测试，确认错误码和审计引用可追踪。
- [ ] Step 7: Commit `feat(system-assistant): add governed asset operations`。

### Task 5: Reuse the existing Code workspace chain (P0); runtime expansion is deferred

**Files:**
- P0 only reuses existing workspace tools; `app-seed/` and `agentic-coding/` remain unchanged.
- RuntimeGateway, template manifests, worker receipts and new workspace adapters are P1/P2 work and are not part of this implementation pass.

**Interfaces:**
- P0 不新增 RuntimeGateway、WorkspaceGateway 或模板协议；系统助手只复用现有 Code 会话上下文和工具注册表。
- Runtime target、WorkspaceGateway 和 Template manifest 约束保留为 P1/P2 设计输入，不能在本轮实现中假设接口已经存在。

- [ ] Step 1: 验证 system assistant 会话仍能复用现有 Code workspace 上下文和工具白名单，不新增 workspace 或 Runtime 协议。
- [ ] Step 2: 记录 P1/P2 的 Runtime target、模板 manifest、worker receipt 和 writer lease 缺口，作为后续实现输入。

### Task 6: Build the Code system assistant UI (P0)

**Files:**
- Create: `apaas-builder-ai/frontend/src/api/systemAssistant.ts`
- Create: `apaas-builder-ai/frontend/src/stores/systemAssistant.ts`
- Create: `apaas-builder-ai/frontend/src/views/SystemAssistantPage.vue`
- Create: `apaas-builder-ai/frontend/src/views/system-assistant/SystemAssistantBaseline.vue`
- Create: `apaas-builder-ai/frontend/src/views/system-assistant/SystemAssistantPlan.vue`
- Create: `apaas-builder-ai/frontend/src/views/system-assistant/SystemAssistantOperationCard.vue`
- Create: `apaas-builder-ai/frontend/src/views/system-assistant/SystemAssistantAssetCard.vue`
- Modify: `apaas-builder-ai/frontend/src/router/index.ts`
- Modify: `apaas-builder-ai/frontend/src/views/CodeConversationPage.vue`
- Modify: `apaas-builder-ai/frontend/src/views/Apps.vue`
- Reuse: `apaas-builder-ai/frontend/src/components/common/AgentConversation.vue`, `SessionSidebar.vue`, `AgentRunTraceDrawer.vue`
- Test: `apaas-builder-ai/frontend/src/views/SystemAssistantPage.spec.ts`
- Test: `apaas-builder-ai/frontend/src/stores/systemAssistant.spec.ts`

**Interfaces:**
- `systemAssistantApi.listSessions/createSession/getSession/send/attach/abort/reconcile` 全部使用已有 AIChat session id。
- Store 的 P0 核心方法：`loadBootstrap()`、`openSession(id)`、`send(message, attachmentIds)`、`abort()`、`attach()`；节点级暂停/恢复、重试和对账方法属于 P1，不在 P0 页面展示。
- 页面布局：左侧会话、中心普通对话、对话中可展开执行过程、右侧只在有内容时显示 Plan/资产/证据；没有内容时不占位。

- [ ] Step 1: 先写 store/API 测试，覆盖 SSE 事件 reducer、断线 attach、重复消息、运行中继续输入和失序事件。
- [ ] Step 2: 实现系统助手 API 类型和事件解析，复用 `aiChat.ts` 的 SSE 消费器，不复制解析逻辑。
- [ ] Step 3: 实现首屏基线摘要和一个“推荐下一步”入口；不展示固定角色或复杂菜单。
- [ ] Step 4: 实现对话消息、执行链、Plan 节点、资产结果和阻断/确认卡片；所有卡片支持展开/收起和返回原会话。
- [ ] Step 5: 复用现有停止、run-status 和 attach UI，保证输入框在运行中仍可编辑；节点级暂停/恢复/重试和 `outcome_unknown` 对账 UI 延后到 P1。
- [ ] Step 6: 通过 Code 路由增加系统助手入口和返回 Code 工作区深链；不触碰 Builder/低代码页面。
- [ ] Step 7: 运行 `cd frontend && npm run test -- --run` 及 `npm run build`。
- [ ] Step 8: Commit `feat(system-assistant): add code client workbench`。

### Task 7: Make desktop local/remote execution explicit and recoverable (P2, deferred)

**Files:**
- Modify: `apaas-builder-ai/src-tauri/src/desktop_config.rs`
- Modify: `apaas-builder-ai/src-tauri/src/desktop_backend.rs`
- Modify: `apaas-builder-ai/backend/desktop_sidecar.py`
- Modify: `apaas-builder-ai/frontend/src/views/CodeConversationPage.vue`
- Test: `apaas-builder-ai/src-tauri/tests/system_assistant_config.rs`
- Test: `apaas-builder-ai/backend/tests/test_desktop_sidecar_system_assistant.py`
- Test: `apaas-builder-ai/frontend/src/views/system-assistant/SystemAssistantDesktop.spec.ts`

**Interfaces:**
- 桌面配置新增 `system_assistant_runtime_target: "local" | "remote" | "auto"`，旧 schema 自动迁移为 `auto`。
- local target 启动一个全局 Runtime；工作区目录为 `<root>/.appdata/system-assistant/<tenant>/<user>/<session>`，租户/用户只隔离目录，不创建多个 Runtime。
- remote target 只使用现有远程 Code Runtime binding；token 通过现有安全存储和 heartbeat 管理，不进入 URL。

- [ ] Step 1: 写 schema migration 测试，覆盖旧配置、非法 target、路径穿越和 root/data 目录重叠。
- [ ] Step 2: 在 sidecar 中注入系统助手运行目标和数据根，不注册远程沙箱；保留桌面 token 加密和敏感日志脱敏。
- [ ] Step 3: 在 Tauri backend 中实现单 Runtime 生命周期和按 session 的 workspace lease。
- [ ] Step 4: 前端在 local/remote 切换后重新绑定当前 session，输入框保持可用；绑定失败显示可恢复诊断而不是假 iframe。
- [ ] Step 5: 运行 Rust、Python 和前端定向测试，检查桌面启动、重启、恢复和跨 session 目录隔离。
- [ ] Step 6: Commit `feat(system-assistant): support desktop local runtime`。

### Task 8: Add governance, audit and observability (P1, deferred)

**Files:**
- Create: `apaas-builder-ai/backend/app/system_assistant/audit.py`
- Create: `apaas-builder-ai/backend/app/system_assistant/observability.py`
- Modify: `apaas-builder-ai/backend/app/models/system_assistant.py`
- Modify: `agent-runtime/internal/http/workflow_governance_handlers.go`
- Modify: `agent-runtime/internal/http/observability_issue_handlers.go`
- Test: `apaas-builder-ai/backend/tests/test_system_assistant_audit.py`
- Test: `agent-runtime/internal/http/system_assistant_observability_test.go`

**Interfaces:**
- 审计记录至少包含 `tenant_id`、`user_id`、`session_id`、`plan_id/version`、`operation_id`、`action`、`risk`、`approval_ref`、`runtime_target`、`request_digest`、`result_digest` 和时间。
- 监控摘要从已有 trace/timeline 聚合 `time_to_first_progress`、`time_to_first_output`、`tool_time`、`worker_time`、`wait_time`；缺失显示 `unavailable`，不估算。
- 失败分类固定为 `AUTH_UNAVAILABLE`、`RUNTIME_UNAVAILABLE`、`ASSET_PERMISSION_DENIED`、`ASSET_OUTCOME_UNKNOWN`、`PLAN_VERSION_CONFLICT`、`WORKSPACE_DIRTY`、`CAPACITY_EXHAUSTED`。

- [ ] Step 1: 为敏感字段脱敏、风险确认、审计完整性和事件 reducer 写测试。
- [ ] Step 2: 实现只追加审计投影，禁止把凭据、token、Secret 内容和完整附件正文写入日志。
- [ ] Step 3: 将现有 Runtime/AIChat trace 关联到 session/plan/operation，不新增中央性能状态机。
- [ ] Step 4: 在失败卡片显示可恢复动作和 trace id；容量耗尽映射为 503/可识别错误，不泛化为 401。
- [ ] Step 5: 运行定向测试并检查旧 AIChat/Code 事件兼容。
- [ ] Step 6: Commit `feat(system-assistant): add governance and diagnostics`。

### Task 9: Verify real Code workflows without mock-only acceptance (P0 reduced set)

**Files:**
- Create: `apaas-builder-ai/backend/tests/system_assistant_acceptance_cases.py`
- Create: `apaas-builder-ai/frontend/tests/system-assistant-real.spec.ts`
- Create: `agent-runtime/tests/e2e/system-assistant-code.sh`
- Create: `apaas-builder-ai/docs/acceptance/system-assistant-code.md`

**Interfaces:**
- 每个验收场景绑定 `target_revision/build`、tenant/user、runtime target、session id、plan version、operation ids 和证据路径。
- 浏览器场景使用真实 Code 客户端和真实 SSE；允许 stub 外部 Full Workspace 读 API，但不 stub 会话、Plan、Runtime 或工作区执行。

- [ ] Step 1: 场景 A：系统助手诊断空基线，生成推荐路线，刷新后恢复同一 session/plan。
- [ ] Step 2: 场景 B：从已有工程或用户选择的模板进入工作区，运行一次真实工具调用，展示文件/结果和下一步建议；不在测试中写死框架名称。
- [ ] Step 3: 场景 C：从 Git 拉取已有工程，修改一个文件，暂停节点，刷新后恢复并继续。
- [ ] Step 4: 场景 D：系统助手附件可上传并进入同一会话上下文；Builder/Entry Agent/应用 Code 会话的既有附件行为保持不回归，不在本轮改变全局附件策略。
- [ ] Step 5: 场景 E-G 归入 P1/P2，待对应 Runtime/资产契约落地后再执行。
- [ ] Step 6: 执行真实浏览器和 AIChat 会话验证；截图只作为证据，不把文本/class 断言当成 E2E 通过。
- [ ] Step 7: 记录失败回流到具体任务，不为了通过测试改变产品范围。

### Task 10: Controlled rollout, documentation and closeout

**Files:**
- Create: `apaas-builder-ai/docs/solutions/l1/architecture/code-system-assistant.md`
- Create: `apaas-builder-ai/docs/solutions/l2/system-assistant/operation-contract.md`
- Create: `apaas-builder-ai/docs/solutions/l2/system-assistant/asset-ownership.md`
- Create: `apaas-builder-ai/docs/acceptance/system-assistant-release-checklist.md`
- Modify: `apaas-builder-ai/backend/app/config.py`
- Create: `apaas-builder-ai/frontend/src/config/systemAssistantFlags.ts`

- [ ] Step 1: 增加 `SYSTEM_ASSISTANT_ENABLED`、`SYSTEM_ASSISTANT_LOCAL_RUNTIME_ENABLED` 和 `SYSTEM_ASSISTANT_EXTERNAL_WRITE_ENABLED` 配置，默认只读基线能力开启，外部写委托关闭。
- [ ] Step 2: 写迁移、回滚和兼容说明，明确旧 Builder/Code 会话继续走原路径。
- [ ] Step 3: 运行数据库 doctor、后端定向测试、前端构建、Rust 测试和真实 Code 验收。
- [ ] Step 4: 生成 `verification-entry-contract/v1`，实际打开 Code Web 和桌面入口，核对首屏、认证、主路径和 revision。
- [ ] Step 5: 只在所有门槛通过后在独立 worktree 提交；默认不自动合并、不发布，等待用户查看结果。
- [ ] Step 6: Commit `docs(system-assistant): document code assistant rollout`。

## Error and Recovery Contract

| 场景 | HTTP/事件 | 用户动作 |
| --- | --- | --- |
| 本地 Runtime 未启动 | `503 RUNTIME_UNAVAILABLE` + `runtime.recover` | 重启本地 Runtime或切换远程 |
| 远程 token 失效 | `401 RUNTIME_AUTH_EXPIRED` | 自动刷新；失败后保留会话并允许重试 |
| 容量耗尽 | `503 CAPACITY_EXHAUSTED` | 等待/切换本地 Runtime，不显示泛化鉴权错误 |
| Plan 版本过期 | `409 PLAN_VERSION_CONFLICT` | 重新加载最新 Plan，展示差异后重试 |
| 外部委托响应丢失 | `200 outcome_unknown` 事件 | 用原 operation id 对账，不重复创建 |
| 工作区有未提交变更 | `409 WORKSPACE_DIRTY` | 查看 diff、保留、提交或放弃；不自动删除 |
| 权限不足 | `403 ASSET_PERMISSION_DENIED` | 返回原会话，说明缺少的资源权限 |

## P0 Definition of Done

1. Code Web 和桌面端都能创建/恢复 `system_assistant` 会话，Builder 低代码对话行为无回归。
2. 用户输入企业 Code 基线目标或指定已有工程后，系统先给出现状、缺口和一个推荐动作，再按缺口动态推进，不强制固定流程。
3. P0 不绑定 React、Spring Boot 或其他固定技术栈；基线摘要明确标记技术栈来源或不可用。
4. 系统助手附件可上传并进入同一会话上下文；现有 Builder/Entry Agent/Code 附件行为无回归。
5. 真实 Code AIChat 会话、历史恢复、工具调用、最终回复和浏览器入口可验证；mock 不替代会话或 SSE 验证。

## Deferred Definition of Done (P1/P2)

1. 任意合规工程可被系统助手打开、修改、测试、构建、验证并生成 receipt。
2. 本地单 Runtime、远程 Runtime 恢复、Full Workspace 资产委托、动态 Plan、节点级暂停/恢复/对账和审计完整落地。
3. 不出现假嵌入页、远程注册误触发、长期 token URL、泛化 401/503；发布和生产动作继续受治理门禁约束。

## Non-goals for this delivery

- 不把系统助手放进 `web-console`，不修改其入口、右侧面板或应用对话。
- 不重写 Builder 低代码会话、Builder API、应用创建确认或现有 aPaaS 流程。
- 不在系统助手中直接执行生产集群、生产数据库迁移、生产 CI/CD 发布或绕过 Control Plane 审批。
- 不建设独立 Skill/知识/MCP/模型主数据，不恢复已退役的本地共享 Skill 写接口。
- 不新增第二套 Plan/Workflow/Task 状态机；平台旧 Task 只作为只读上下文。
