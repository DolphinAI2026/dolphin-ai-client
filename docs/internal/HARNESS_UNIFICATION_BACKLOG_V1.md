# Harness 统一改造任务拆解 v1

> 关联设计文档：
> `docs/internal/HARNESS_UNIFICATION_PLAN_V1.md`

## 1. 目标

把当前四块能力：

1. 智能搭建
2. 辅助搭建
3. 智能开发
4. 需求分析

统一收口到一个平台级 Harness Core 上，并以四个 profile 运行：

- `builder_profile`
- `platform_profile`
- `coding_profile`
- `requirements_profile`

本任务拆解面向：

- 立项评审
- Epic 拆分
- Jira / 飞书项目 / GitHub Issues 建单
- 12 周实施排期


## 2. 拆解原则

- 不一次性重写三块业务。
- 先统一后端运行时，再统一前端协议。
- 先迁移智能开发，再迁移智能搭建，最后推进辅助搭建脱离纯 iframe。
- 保留现有页面入口，优先做兼容层，不让业务链路中断。
- 高风险动作必须逐步补审批，而不是先默认放开。


## 3. Epic 总览

| Epic | 名称 | 优先级 | 主要产出 |
|------|------|------|------|
| E0 | 方案定稿与迁移基线 | P0 | 范围确认、迁移边界、回滚策略 |
| E1 | Harness Core 基础设施 | P0 | contracts / manager / store / events / migrations |
| E2 | 统一事件协议与兼容层 | P0 | 内部事件模型 + SSE 兼容输出 |
| E3 | Coding Mode 迁移 | P0 | 智能开发接入 harness |
| E3.5 | 模型适配统一 | P0 | 统一 LLM adapter，消除 Anthropic/OpenAI 格式冲突 |
| E4 | Builder Mode 迁移 | P0 | 智能搭建接入 harness |
| E4.5 | Requirements Mode 迁移 | P1 | 需求分析接入 harness |
| E5 | Platform Mode Phase 1 | P1 | 辅助搭建只读能力与状态理解 |
| E6 | 审批与策略中心 | P1 | shell / publish / 平台写操作审批 |
| E7 | 前端统一 runtime 协议 | P1 | ChatPage / CodingPage 接统一 adapter |
| E8 | 可观测性、artifact 与评估 | P2 | 日志、diff、截图、回放、质量指标 |


## 4. Epic 明细

## E0. 方案定稿与迁移基线

### 目标

确认迁移边界、顺序、兼容策略和回滚策略，避免后续实现中反复改方向。

### 建议负责人角色

- 技术负责人
- 后端主程
- 前端主程

### Issues

#### H-001 统一改造范围确认

内容：

- 明确三块业务最终都接入 Harness Core
- 明确第一阶段不替换前端入口
- 明确辅助搭建短期保留 iframe fallback

验收标准：

- 形成书面结论
- 设计文档和 backlog 文档评审通过

#### H-002 迁移边界与回滚策略

内容：

- 明确哪些 API 保持兼容
- 明确 Phase 1 可回退点
- 明确老逻辑保留周期

验收标准：

- 产出迁移边界表
- 产出回滚预案


## E1. Harness Core 基础设施

### 目标

建立统一运行时底座，不承载具体业务逻辑，但为三种 mode 提供统一结构。

### 建议负责人角色

- 后端主程
- 架构 owner

### 依赖

- 无，最优先

### Issues

#### H-101 创建 Harness 模块骨架

目标文件：

- `backend/app/harness/contracts.py`
- `backend/app/harness/manager.py`
- `backend/app/harness/session_store.py`
- `backend/app/harness/events.py`
- `backend/app/harness/context.py`
- `backend/app/harness/policy.py`
- `backend/app/harness/approvals.py`
- `backend/app/harness/artifacts.py`

任务：

- 定义目录结构
- 初始化模块导出
- 约定 profile 注册方式

验收标准：

- 模块可被后端正常 import
- 有最小 smoke test 或启动校验

#### H-102 定义 contracts 与核心类型

任务：

- 定义 `HarnessThread`
- 定义 `HarnessTurn`
- 定义 `HarnessItem`
- 定义 `HarnessArtifact`
- 定义 `HarnessApproval`
- 定义 `HarnessMode`
- 定义 `HarnessProfile`

验收标准：

- 三个 profile 均可复用这些类型
- 不再在 route 层随意拼装 event dict

#### H-103 建 Harness 数据表与 migration

目标表：

- `harness_threads`
- `harness_turns`
- `harness_items`
- `harness_artifacts`
- `harness_approvals`

任务：

- 编写 migration
- 建索引
- 设计和 `conversations/messages` 的关系

验收标准：

- 本地迁移成功
- 不破坏现有旧表

#### H-104 实现 HarnessManager 与运行时入口

任务：

- create/load thread
- start turn
- event publish
- replay support
- in-memory runtime registry + DB state

验收标准：

- 能从一个最小 demo profile 跑通 thread -> turn -> events


## E2. 统一事件协议与兼容层

### 目标

把现在 builder/coding 各自的 SSE 事件风格统一起来，同时不打断现有前端。

### 建议负责人角色

- 后端主程
- 前端协作

### 依赖

- E1

### Issues

#### H-201 定义内部事件协议

事件建议：

- `thread.started`
- `turn.started`
- `item.started`
- `item.delta`
- `item.completed`
- `approval.requested`
- `approval.resolved`
- `turn.completed`
- `turn.failed`
- `thread.completed`

任务：

- 定义统一 envelope
- 定义 item kinds
- 明确 payload 字段

验收标准：

- profile 不再直接返回前端自定义事件名

#### H-202 实现 SSE 兼容适配器

任务：

- 把内部事件映射成现有 CodingPage 可识别的事件
- 把内部事件映射成现有 ChatPage builder 可识别的事件

兼容目标：

- `agent_tool`
- `agent_thinking_delta`
- `agent_done`
- `done`
- builder 现有 `progress/done/error`

验收标准：

- 前端页面无需大改即可消费

#### H-203 补 replay / reconnect 机制

任务：

- `after_seq` 支持
- 断线重连补发
- turn 已完成时可回放完整过程

验收标准：

- CodingPage 刷新后可以恢复最近 turn 进度或历史


## E3. Coding Mode 迁移

### 目标

先把最接近 harness 的智能开发迁移到统一底座上。

### 建议负责人角色

- 后端主程
- IDE / workspace 负责人

### 依赖

- E1
- E2

### Issues

#### H-301 抽离 `coding_profile`

来源：

- `backend/app/coding/vibe_agent.py`
- `backend/app/routes/coding.py`

任务：

- 把当前 agent loop 挪到 `backend/app/harness/profiles/coding.py`
- route 层只负责 transport
- 把工作区上下文构建收口到 harness context

验收标准：

- Coding Mode 可通过 HarnessManager 启动
- 旧接口仍能正常工作

#### H-302 抽离模型适配层

来源：

- `backend/app/routes/coding.py` 中模型路由
- `_codex_responses_proxy()`

任务：

- 新建 model adapter 抽象
- Codex `/responses` 迁入 adapter
- MiniMax/Qwen/GPT/Claude 统一接口

验收标准：

- route 层不再直接处理 `/chat/completions` 和 `/responses` 差异

#### H-303 抽离 coding tools

来源：

- `backend/app/coding/tools.py`

任务：

- 拆为 registry
- 拆为 executor
- 拆为 policy 检查
- 按 profile 决定暴露工具集

验收标准：

- tools 不再直接绑死在 `VibeCodingAgent`

#### H-304 接入 workspace / preview / debug artifact

任务：

- 工作区创建结果入 artifact
- preview URL 入 artifact
- debug 截图 / 日志入 artifact
- publish 构建结果入 artifact

验收标准：

- 一个 coding turn 的重要产物都可追踪

#### H-305 `coding.py` 兼容改造

任务：

- `auto-pipeline` 内部转为 HarnessManager 调用
- 保留现有请求参数
- 保留现有 `done/step/error` 外观

验收标准：

- 前端 `CodingPage` 不需要大改即可继续运行


## E3.5. 模型适配统一

### 目标

统一所有模块的 LLM 调用格式，消除 Anthropic 原生 vs OpenAI 兼容的冲突。

### 依赖

- E1

### Issues

#### H-351 定义统一 model adapter 接口

任务：

- 定义 base class，包含 `chat_completion`、`chat_completion_stream`、`tool_call` 方法
- 统一入参和出参格式

验收标准：

- 各 profile 可复用同一 adapter 接口

#### H-352 实现 OpenAI 兼容 adapter

任务：

- 适配 jieko.ai、dashscope 等 OpenAI 兼容格式的模型服务

验收标准：

- OpenAI 兼容模型可通过统一 adapter 调用

#### H-353 实现 Anthropic 原生 adapter

任务：

- 适配 MiniMax anthropic proxy 等原生 Anthropic 格式的模型服务

验收标准：

- Anthropic 原生模型可通过统一 adapter 调用

#### H-354 迁移 LLMClient 到统一 adapter

任务：

- 把现有 `LLMClient` 的调用切换到统一 adapter

验收标准：

- 智能搭建的模型调用走统一 adapter

#### H-355 迁移 VibeCodingAgent 到统一 adapter

任务：

- 把现有 `VibeCodingAgent` 的模型调用切换到统一 adapter

验收标准：

- 智能开发的模型调用走统一 adapter

#### H-356 消除 ANTHROPIC_*/VIBE_AGENT_* 环境变量分裂

任务：

- 统一模型配置的环境变量命名
- 消除 `ANTHROPIC_*` 和 `VIBE_AGENT_*` 两套配置的冗余

验收标准：

- 环境变量配置清晰统一，不再有格式冲突


## E4. Builder Mode 迁移

### 目标

把智能搭建从“分阶段 route + service 直连”迁到统一 harness。

### 建议负责人角色

- 后端主程
- 平台业务 owner

### 依赖

- E1
- E2

### Issues

#### H-401 抽离 `builder_profile`

来源：

- `backend/app/routes/chat.py`
- `backend/app/config_assembler.py`

任务：

- 用 profile 包装骨架生成、字典生成、模型生成
- 统一 event 产出
- 统一上下文注入

验收标准：

- Builder Mode 能作为独立 profile 跑起来

#### H-402 builder 阶段事件统一

当前阶段：

- skeleton
- dicts
- models
- complete

任务：

- 映射为 harness item lifecycle
- 保留前端右侧预览的实时刷新能力

验收标准：

- ChatPage 不再依赖 builder 专属事件方言

#### H-403 接入 change plan 与增量执行

来源：

- `backend/app/incremental_executor.py`

任务：

- 增量执行过程纳入 turn/items
- 每个 stage 输出 item / artifact
- 关键 API 调用结果可审计

验收标准：

- 增量更新链路能在 harness 下回放

#### H-404 Builder route 兼容改造

来源：

- `/chat/generate-config`

任务：

- route 只做 transport
- 调用 HarnessManager + `builder_profile`

验收标准：

- 旧页面不需要改变入口 URL


## E4.5. Requirements Mode 迁移

### 目标

把需求分析会话接入 Harness Core。

### 依赖

- E1
- E2

### Issues

#### H-451 创建 `requirements_profile`

任务：

- 新增 profile 骨架
- 绑定需求分析相关上下文

验收标准：

- 能创建 requirements mode thread/turn

#### H-452 迁移需求分析会话到 harness thread/turn 模型

任务：

- 把现有需求分析对话流程迁移到 harness 统一会话模型

验收标准：

- 需求分析会话走 harness 统一 thread/turn 管理

#### H-453 需求分析生成文档接入 artifact 体系

任务：

- 需求分析生成的需求文档、PRD 等接入 harness artifact

验收标准：

- 需求文档可作为 artifact 统一追踪和查看

#### H-454 需求分析与 builder_profile 衔接

任务：

- 需求确认后自动进入搭建流程
- 实现 requirements -> builder 的 profile 切换

验收标准：

- 需求分析完成后可无缝衔接智能搭建


## E5. Platform Mode Phase 1

### 目标

让辅助搭建从“纯 iframe”升级为“有真实 runtime 的平台操作模式”，先做只读与理解。

### 建议负责人角色

- 后端主程
- 平台集成负责人

### 依赖

- E1
- E2

### Issues

#### H-501 创建 `platform_profile`

任务：

- 新增 profile 骨架
- 绑定 application / project / platform env context

验收标准：

- 能创建 platform mode thread/turn

#### H-502 平台只读工具集

建议工具：

- 查询应用基础信息
- 查询菜单
- 查询模型
- 查询字段
- 查询表单
- 查询流程
- 查询权限

验收标准：

- AI 可以回答“当前平台里有什么”

#### H-503 平台状态摘要与建议

任务：

- 把平台只读结果转成结构化摘要
- 生成下一步建议
- 在 ChatPage 展示操作建议

验收标准：

- 辅助搭建不再只是“打开后台页面”

#### H-504 iframe fallback 整合

任务：

- 保留当前 iframe
- 将其定义为 fallback / 接管界面
- UI 上明确“AI 已理解当前状态，可继续自动辅助”

验收标准：

- 辅助搭建形成“双轨模式”：AI runtime + iframe fallback


## E6. 审批与策略中心

### 目标

给所有高风险动作提供统一审批与策略控制。

### 建议负责人角色

- 后端主程
- 安全/平台 owner

### 依赖

- E1

### Issues

#### H-601 定义审批类型

建议类型：

- shell
- publish
- browser
- platform_write
- destructive_action

验收标准：

- 各 profile 使用同一审批模型

#### H-602 实现审批持久化与恢复

任务：

- request -> pending
- approve -> resume
- deny -> fail/skip

验收标准：

- turn 可以在审批后恢复执行

#### H-603 coding 风险动作接审批

优先动作：

- `run_command`
- publish
- debug browser

验收标准：

- 智能开发里的高风险操作不再全自动裸跑

#### H-604 platform 风险动作接审批

优先动作：

- 平台创建
- 平台更新
- 平台删除
- 大批量修改

验收标准：

- 辅助搭建具备企业可控性


## E7. 前端统一 runtime 协议

### 目标

把 ChatPage 和 CodingPage 对运行时事件的解析统一起来。

### 建议负责人角色

- 前端主程
- 后端协作

### 依赖

- E2
- E3
- E4

### Issues

#### H-701 新增 `frontend/src/api/harness.ts`

任务：

- create thread
- start turn
- subscribe events
- fetch artifacts
- submit approval

验收标准：

- 前端具备直接调用 harness 的能力

#### H-702 新增 `harnessEventAdapter.ts`

任务：

- 统一解析内部事件
- 输出页面可消费的标准 UI 事件

验收标准：

- ChatPage / CodingPage 中的 if-else 事件分支显著减少

#### H-703 ChatPage builder/platform 接 adapter

任务：

- 智能搭建接 adapter
- 辅助搭建接 adapter

验收标准：

- ChatPage 能共用同一事件消费模式

#### H-704 CodingPage 接 adapter

任务：

- 智能开发接 adapter
- 保持现有交互体验

验收标准：

- CodingPage 不再直接耦合后端 event dialect


## E8. 可观测性、artifact 与评估

### 目标

把三种 mode 的结果、过程和质量纳入统一追踪。

### 建议负责人角色

- 后端主程
- 测试 / 质量 owner

### 依赖

- E3
- E4
- E5

### Issues

#### H-801 artifact 统一展示

类型建议：

- code diff
- config diff
- screenshot
- preview URL
- build package
- API call log
- execution log

验收标准：

- 一个 thread 的关键产物能统一查看

#### H-802 可观测性埋点

建议指标：

- turn 时长
- token 消耗
- 工具调用次数
- 审批等待时长
- 失败率
- 回滚率

验收标准：

- 有最小 dashboard 或日志统计出口

#### H-803 评估基线

builder 评估：

- 配置完整率
- 执行成功率

platform 评估：

- 状态理解准确率
- 操作建议命中率

coding 评估：

- 首轮可运行率
- 预览成功率

验收标准：

- 至少有一版人工可读的 weekly report


## 5. 推荐实施顺序

### 第一阶段

- E0
- E1
- E2

目标：

- 把底座搭出来

### 第二阶段

- E3

目标：

- 智能开发先接入 harness

### 第二阶段补充

- E3.5

目标：

- 模型适配统一

### 第三阶段

- E4

目标：

- 智能搭建接入 harness

### 第三阶段补充

- E4.5

目标：

- 需求分析迁移

### 第四阶段

- E5
- E6

目标：

- 辅助搭建不再只是 iframe
- 高风险动作具备审批

### 第五阶段

- E7
- E8

目标：

- 前端协议统一
- 过程与结果可观测


## 6. 并行建议

可并行推进的工作：

- 后端做 E1 时，前端可以先做 E7 的 adapter 设计稿
- E3 和 E4 可以部分并行，但建议先让 coding 跑通一个 profile 模板
- E5 平台只读能力可以和 E6 审批模型设计并行
- E8 埋点方案可以从 E3 开始提前打底

不建议并行推进的工作：

- 不建议同时大改 `ChatPage` 和 `CodingPage` 的页面结构
- 不建议在 E1 未稳定前就直接做平台写操作自动化
- 不建议先替换掉 iframe 再补 platform tools


## 7. 12 周排期映射

| 周次 | 主要目标 | 对应 Epic |
|------|------|------|
| Week 1 | 方案确认、表结构、Harness 骨架 | E0, E1 |
| Week 2 | 事件协议、SSE 兼容层 | E2 |
| Week 3 | 前端 adapter 预埋 + Coding Profile 开始 | E3, E7 |
| Week 4 | Coding Profile 完成 | E3 |
| Week 5 | 模型适配统一 | E3.5 |
| Week 6 | Builder Profile 基础迁移 | E4 |
| Week 7 | 增量执行接 harness，Builder artifact | E4, E8 |
| Week 8 | Requirements Profile 迁移 | E4.5 |
| Week 9 | Platform Profile 只读能力 | E5 |
| Week 10 | 审批与策略中心 | E6 |
| Week 11 | 前端协议统一 | E7 |
| Week 12 | 可观测性、artifact、统一验收 | E8 |


## 8. 建议建单方式

建议在任务系统中采用两层：

- Epic
- Issue

Issue 命名建议：

- `H-101 Harness contracts and manager skeleton`
- `H-201 Unified internal event protocol`
- `H-301 Migrate coding auto-pipeline into coding_profile`
- `H-401 Wrap phased config generation into builder_profile`
- `H-501 Add platform read-only tools`

标签建议：

- `harness`
- `builder-mode`
- `platform-mode`
- `coding-mode`
- `runtime`
- `frontend-adapter`
- `approval`
- `artifact`


## 9. 本轮最先落的 5 个 Issue

如果只能先做最关键的 5 个，建议顺序如下：

1. H-101 创建 Harness 模块骨架
2. H-103 建 Harness 数据表与 migration
3. H-201 定义内部事件协议
4. H-301 抽离 `coding_profile`
5. H-305 `coding.py` 兼容改造

原因：

- 这 5 个完成后，统一 harness 就不再停留在文档层，而是进入真正可运行阶段。

注意：H-351（模型适配统一）建议与 H-301 并行推进，因为当前模型路由冲突已经是最痛的实际问题。

