# Agent 可观测模块 — 设计

> 日期: 2026-06-04
> 状态: 待用户确认 spec
> 范围: agent observability —— trace 下钻 + dashboard 聚合 + 统一数据底座，权限分级（平台管理员看全平台 / 租户看自己），分期实现。

## 背景

4 条 LLM agent 链路的活动记录散在 7-8 张表，各记各的，没有聚合的可观测层：

- ai-builder（`AIChatPage` `/ai-chat`）→ `AIChatToolCall`（工具调用全文 + 耗时 + 状态）
- 配置助手（`config-chat-stream`）→ `ConfigChatMessage.tool_trace`（JSON）
- coding pipeline → `AgentTrace`
- MCP 网关 → `MCPCallLog` / `ApiCallLog`
- 部署 → `DeployRecord` / `DeploymentHistory`

前端没有 agent 可观测页（`/devops` 是标了 MVP/mock 的 DevOps 壳）。结论：**有原料、缺一个把它们聚到一起能看的可观测层**。

## 目标

一个统一的 agent 可观测模块：

1. **Trace 下钻** —— 看单次 agent run 的完整执行链路（每轮 LLM、每个工具、耗时、token、错误）。
2. **Dashboard 聚合** —— 看整体健康（调用量 / 失败率 / 耗时 / token 用量 / 错误）。
3. **权限分级** —— 平台管理员看全平台跨租户，租户用户看自己。

## 数据底座（统一表 + 埋点；token 必采）

### 表 1：`agent_run` —— 一次运行（= 一条用户消息触发的完整工具循环）
`id` / `run_id`(uuid, index) / `agent_type`(enum: `ai_builder` / `config` / `coding` / `builder`) / `tenant_id`(index) / `user_id` / `session_id` / `app_id`(nullable) / `status`(running / success / error) / `started_at` / `ended_at` / `duration_ms` / **`total_prompt_tokens` / `total_completion_tokens` / `total_tokens`** / `turn_count` / `error_message`

### 表 2：`agent_step` —— run 内每一步
`id` / `run_id`(FK, index) / `seq` / `step_type`(llm / tool / error / artifact) / `tool_name`(nullable) / `args_json`(JSON, nullable) / `result_text`(BigText, nullable) / `status` / `duration_ms` / **`prompt_tokens` / `completion_tokens`**（llm step 用） / `ts`

### 写入门面 `app/observability/recorder.py`
- `start_run(agent_type, tenant_id, user_id, session_id, ...) -> run_id`
- `record_step(run_id, step_type, ...)` —— llm step 从 LLM response 的 `usage` 取 tokens
- `end_run(run_id, status, error?)` —— 汇总 duration + 累加 tokens
- 容错：recorder 任何异常都不能影响主 agent 流程（observability 是旁路，try/except 吞掉自身错误）。

### 埋点位置（4 条链路）
- ai-builder `ai_chat/agent.py::run_agent`：run 起止 + 每轮 LLM（记 usage）+ 每个工具
- 配置助手 `applications/__init__.py::_config_chat_event_stream`：tool_call / tool_result 处 + LLM 轮
- coding pipeline `coding/pipeline.py`：接入现有 `AgentTrace` 的写入点
- Builder `builder_spec/agent.py::SpecAgent`：工具调用处
- 现有 `AIChatToolCall` 等**保留**，埋点处双写（不破坏现有对话内 ToolCard 展示）。

## Trace 下钻视图

一个 run 的执行时间线：每轮 LLM 思考（+ token）、每个工具（入参 / 结果 / 耗时 / 状态）、错误节点。等于放大版的 ToolCard 流，专看"这一次怎么跑的"。
- 入口：对话里「查看本次 trace」+ 平台管理 run 列表点进去。

## Dashboard 聚合

- 卡片：总调用量 / 失败率 / 平均耗时 / **token 用量** / 错误数。
- 图表：调用量 & token 按时间趋势、错误 Top N、最活跃 agent·租户、工具调用排行。
- 筛选：时间范围、`agent_type`、租户。

## 权限分级

- 租户用户：ai-builder 内「我的 agent 活动」，查询强制 `where tenant_id = 当前租户`（普通用户可进一步限 `user_id`）。
- 平台管理员：「平台管理」后台「Agent 可观测」，跨租户全量。守卫 `requiresPlatformAdmin`。

## 分期

- **Phase 1**：数据底座（2 表 + `recorder` + token 采集）+ **ai-builder 一条链路埋点跑通** + Trace 视图（租户看自己）。
- **Phase 2**：其余 3 条链路埋点 + Dashboard 聚合 + 平台管理全局页 + token 用量趋势（可选成本估算）。

## 不在本次范围 / 开放问题

- 老数据迁移：不迁，从上线起记（查历史仍用现有分散表）。
- 成本估算（token → ¥）：Phase 2 可选，需各模型单价表。
- 实时告警（失败率/耗时超阈值通知）：不在范围。
- trace 数据留存 / 采样：先全量留，数据量大后 Phase 2 再定清理策略。
