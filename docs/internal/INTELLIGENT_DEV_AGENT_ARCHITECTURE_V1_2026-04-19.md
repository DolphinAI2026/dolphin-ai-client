# 智能开发模块 Agent 架构重设计 V1

**版本**：V1  
**日期**：2026-04-19  
**状态**：待评审  
**涉及模块**：智能开发（`backend/app/coding/` + `frontend/src/views/coding/`）  
**不涉及**：智能搭建（requirements / chat / config_assembler / ai_doc_parser）保持零改动

---

## 摘要

本次重设计将智能开发模块从**单一 CodingAgent + 大 prompt** 的架构，升级为**三 Agent 线性流水线 + 结构化 Spec 契约**的架构。核心变化：

| 维度 | 现状 | 新架构 |
|---|---|---|
| Agent 数量 | 1（VibeCodingAgent）| 3（BrainstormAgent / CodingAgent / VerificationAgent） |
| 需求到代码的中间契约 | Markdown 方案（用正则反解）| 结构化 Spec JSON（Pydantic 校验） |
| 需求澄清 | 一次性 LLM 调用，固定 prompt | BrainstormAgent 反问 + 置信度驱动 |
| 代码质量验收 | 仅平台合约校验 | VerificationAgent 按用户验收点（AC）逐条校验 + 自动修复闭环 |
| Agent 运行时 | 一套 loop 在 VibeCodingAgent 内部 | 抽象 BaseAgent，统一 loop / tool / 事件 / trace |
| LLM 调用 | 两套并存（LLMClient + VibeCodingAgent 内嵌 httpx） | 扩展 LLMClient 支持 tools（兼容所有现有调用） |

**MVP 预计工期**：10 周（1 后端 + 1 前端）/ 7-8 周（2 后端 + 1 前端）

---

## 目录

- [1. 背景与动机](#1-背景与动机)
- [2. 目标架构总览](#2-目标架构总览)
- [3. Spec 契约设计（Phase E）](#3-spec-契约设计phase-e)
- [4. 数据库与 SSE 事件设计（Phase C）](#4-数据库与-sse-事件设计phase-c)
- [5. BaseAgent Runtime 设计（Phase D）](#5-baseagent-runtime-设计phase-d)
- [6. BrainstormAgent 反问策略（Phase B）](#6-brainstormagent-反问策略phase-b)
- [7. 前端 Spec 预览设计（Phase A）](#7-前端-spec-预览设计phase-a)
- [8. 实施 Roadmap](#8-实施-roadmap)
- [9. 风险与应对](#9-风险与应对)
- [10. 向后兼容性保证](#10-向后兼容性保证)
- [11. 技术债登记](#11-技术债登记)
- [12. 评审关注点](#12-评审关注点)

---

## 1. 背景与动机

### 1.1 现状痛点

当前智能开发模块（`backend/app/coding/`）的核心问题：

1. **Brainstorm 单轮 LLM 调用质量不稳定**
   - 系统 prompt 长达 700+ 行，塞满所有约束规则
   - LLM 经常漏读规则，典型表现：BOF 类型错配（日期范围用 `BOF_DATE`）、字段命名冲突、`customComponentConfig` 默认值漏项
   - 用户遇到模糊需求时，LLM 只能瞎猜，反复修方案

2. **Brainstorm 与 Coding 之间的契约不可靠**
   - Brainstorm 输出 markdown，Coding 用正则（`_parse_brainstorm_metadata`）从 markdown 反解结构化信息
   - 契约变更脆弱，无法做字段级校验
   - 无法向前端展示"方案里有哪些决策点"

3. **没有验收环节**
   - 代码生成完后，只做平台合约校验（如路径前缀、禁用组件等）
   - 用户真正关心的"功能是否实现"无法自动检查
   - 典型场景：用户说"要半星"，生成的代码没支持半星，但合约校验通过

4. **Agent 能力复用困难**
   - VibeCodingAgent 自己实现了 loop / tool / 事件 / trace
   - Brainstorm 想用 tool（如反问、查组件市场）就要抄一套 ~200 行 httpx
   - 无法横向扩展新 agent

5. **LLM 层分裂**
   - `app.llm_client.LLMClient`（~458 行）不支持 tool calling
   - `VibeCodingAgent` 内嵌 httpx 支持 tool calling
   - 职责重叠、能力互补

### 1.2 架构目标

1. **需求到代码链路清晰化**：Brainstorm 产出结构化 Spec → Coding 消费 Spec → Verify 按 Spec 验收
2. **人机协作合理化**：Agent 主动反问而非瞎猜，用户能看到 agent 做的默认假设
3. **质量可度量**：每条验收点能被独立检查，统计系统级"一次通过率"
4. **可扩展**：增加新 agent / 新工具成本低
5. **零侵入智能搭建**：现有 13 个使用 `LLMClient` 的模块一行代码不改

---

## 2. 目标架构总览

### 2.1 架构图

```
┌─────────────────────────────────────────────────────────┐
│              Pipeline Orchestrator                      │
│  （纯编排，phase 状态机，路由用户消息）                   │
└─────────────────────────────────────────────────────────┘
          │
          ▼
   ┌──────────────────┐       ┌──────────────────┐
   │ BrainstormAgent  │──emit→│   Spec (JSON)    │
   │  tools:          │       │   (契约)         │
   │  - detect_scene  │       └──────┬───────────┘
   │  - ask_user      │              │
   │  - query_market  │              │ consume
   │  - read_ws_ctx   │              ▼
   │  - emit_spec     │       ┌──────────────────┐
   └──────────────────┘       │   CodingAgent    │
                              │  tools:          │
                              │  - read/write/   │
                              │    edit/command  │
                              └──────┬───────────┘
                                     │
                                     ▼
                              ┌──────────────────┐
                              │ VerificationAgent│
                              │  tools:          │
                              │  - grep_code     │
                              │  - check_ac      │
                              │  - emit_report   │
                              └──────┬───────────┘
                                     │
                 ┌───────────────────┴────────┐
                 ↓                            ↓
            [全通过→Done]            [部分失败→Coding 重试，≤2 次]
```

### 2.2 Phase 状态机

```
UNDERSTAND  →  CONFIRM  →  SCAFFOLD  →  GENERATE  →  VERIFY  →  DONE
   (reason)    (confirm)  (create ws)   (code)      (check)    (ide)
     ↑                                                             │
     └──────────── ITERATE ←────────────────────────────────────────┘
```

### 2.3 各组件职责

| 组件 | 职责 | 技术栈 |
|---|---|---|
| **Orchestrator** | Phase 状态机 / 用户消息路由 / agent 生命周期管理 | 纯 Python 编排，无 LLM |
| **BrainstormAgent** | 需求理解 / 反问 / Spec 产出 | LLM + 5 个 tool |
| **CodingAgent** | 消费 Spec 产出代码（从现有 VibeCodingAgent 改造）| LLM + 7+ 个 tool |
| **VerificationAgent** | 按 AC 逐条验收代码 / 产出 Report | LLM + grep / file tool |
| **BaseAgent Runtime** | 通用 loop / tool / 事件 / trace / 中断 / suspend | 抽象基类 |
| **UnifiedLLMClient** | 扩展现有 LLMClient 支持 tools | httpx + Anthropic/OpenAI 双协议 |
| **Spec Registry** | Pydantic schema + 预置清单 + validators | 纯数据 |
| **Event Publisher** | SSE 事件发布 + seq 管理 + 断线重连 | asyncio + PostgreSQL |

### 2.4 不共享 Conversation 的决策

**三个 agent 不共享对话历史**，通过 **Spec** 连接：

| 维度 | 共享（否决） | 不共享（采用） |
|---|---|---|
| 数据模型 | 一张 messages 表 + agent_type 字段 | 三张独立 session 表 + specs 表连接 |
| Coding 可见 context | brainstorm 全部反问 | 只有 Spec JSON |
| Context 膨胀 | 严重 | 可控 |
| 可评估 | 无法独立评估各 agent 质量 | 可独立评估 |
| 可替换 | brainstorm 难替换 | brainstorm 可换成人工方案/模板 |

---

## 3. Spec 契约设计（Phase E）

### 3.1 设计原则

1. **版本化**：`schema_version` 必填，支持演进（1.0 → 1.1 → 2.0）
2. **场景分形**：顶层字段统一，`spec` 字段按 `scene_type` 分化（ComponentSpec / PageSpec / BackendApiSpec）
3. **可验证**：Pydantic v2 模型，后端强校验
4. **可追溯**：`provenance` 记录 `created_by`（agent/user/mixed）、`confidence`、`open_questions`

### 3.2 顶层结构

```python
BaseSpecEnvelope {
    schema_version: "1.0"           # schema 结构版本
    spec_id: str                    # ULID
    scene_type: SceneType           # 判别字段（discriminator）
    provenance: Provenance          # 来源、版本、置信度、默认假设
    identity: Identity              # 规范化标识（code_name / widget_code）
    intent: Intent                  # 用户意图（原始需求 + 验收点）
    spec: ComponentSpec | PageSpec | BackendApiSpec  # 场景特定
    metadata: Metadata              # 扩展字段（attachments / extra）
    references: list[SpecReference] # Spec 间关联（depends_on / related）
}
```

### 3.3 Scene 覆盖范围（1.0）

**正式支持**：
- `web_component_dual` - 双端组件（所有组件统一走此场景）
- `web_page` - PC 页面
- `mobile_page` - 移动端页面
- `backend_api` - 后端接口
- `backend_feign` - 外部调用
- `backend_scheduled` - 定时任务

**预留**（未来加）：
- `web_list_view` / `web_layout` / `web_login` / `web_plugin`

### 3.4 关键子结构

**Provenance**：
```python
provenance = {
    brainstorm_session_id: str,
    created_at: datetime,
    created_by: "agent" | "user" | "mixed",
    model: Optional[str],
    version: int,           # Spec 实例版本号（v1, v2...）
    parent_version: Optional[int],
    confidence: float,      # 0-1
    open_questions: list[OpenQuestion],   # agent 做的默认假设
}
```

**Intent**：
```python
intent = {
    original_requirement: str,  # 用户原话
    core_purpose: str,          # agent 总结一句话
    acceptance_criteria: list[str],   # 验收点（1.0 字符串数组）
}
```

**Identity**：
```python
identity = {
    code_name: str,         # kebab-case（文件名用）
    display_name: str,      # 中文显示名
    description_cn: str,
    widget_code: Optional[str],  # 仅组件场景：FORM_CUSTOM_*
}
```

### 3.5 UI Editor / UI Section 的开放扩展机制

两者都采用**开放字符串 + 预置清单 + `is_custom_*` 标记**：

- `ConfigProperty.ui_editor: str`（正则 `^form-custom-[a-z][a-z0-9-]*-editor$`）
- `UISection.type: str`（开放命名空间）
- 预置清单独立文件（`ui_editor_registry.py` / `ui_section_registry.py`）
- BrainstormAgent Prompt 中提供推荐清单
- CodingAgent 看到 `is_custom_*=true` 时自动生成对应组件

**好处**：新增 editor / section type 不改 Spec schema，只改推荐清单。

### 3.6 Constraints 分级

`constraints_hard` + `constraints_soft`：
- hard 违反 → VerificationAgent 标记 failed，必须修
- soft 违反 → warning 但 pass

**不细分 category**（MVP）：全部走 LLM 语义检查。未来若需要专业工具（semgrep / eslint / axe-core），升级到 Spec 1.1 加 `category` 字段。

### 3.7 Spec 1.0 完整文件清单

```
backend/app/spec/
├── schema.py                # Pydantic 模型（~400 行）
├── ui_editor_registry.py    # 预置 UI Editor 清单 + prompt 片段
├── ui_section_registry.py   # 预置 UI Section 清单 + prompt 片段
└── validators.py            # 业务规则校验（schema 之外）
```

---

## 4. 数据库与 SSE 事件设计（Phase C）

### 4.1 数据库策略

- 新建表，不改现有 `messages` 表
- 不迁移历史数据（MVP 阶段）
- 独立 `agent_traces` 表（不内嵌到 sessions 的 JSON 字段）
- Spec 存储：JSONB + 关键字段抽列做索引

### 4.2 新表清单

| 表 | 职责 | 核心字段 |
|---|---|---|
| `conversations` | UI 层"一条对话"（保留原表，加字段） | current_phase / active_brainstorm_session_id / active_coding_session_id |
| `agent_messages` | 用户可见消息流 | source（user/brainstorm/coding/verification/system）、content_type、extra |
| `brainstorm_sessions` | Brainstorm 会话状态 | status / final_spec_id / scene_type / trigger_type |
| `specs` | Spec 版本链 | scene_type / code_name / widget_code / version / parent_version / confidence / content(JSONB) |
| `coding_sessions` | Coding 执行记录 | spec_id / workspace_id / trigger_type / turns_used / files_written |
| `verification_reports` | AC 验收报告 | overall_status / passed_count / failed_count / items(JSONB) |
| `agent_traces` | Agent 内部调试 trace | session_type / session_id / seq / event_type / payload / tokens_input / tokens_output |
| `conversation_events` | SSE 事件缓存（支持断线重连） | conversation_id / seq / event_type / agent / payload |

### 4.3 SSE 事件协议

**统一 envelope**：
```python
Event {
    type: str                    # "brainstorm.ask_user" 等，点分命名空间
    agent: str                   # orchestrator/brainstorm/coding/verification/system
    session_id: Optional[str]
    conversation_id: int
    seq: int                     # conversation 内单调递增，支持断线重连
    timestamp: datetime
    data: dict
}
```

**命名空间**：
- `orchestrator.*` - phase 状态变化
- `brainstorm.*` - 反问 / Spec 产出
- `coding.*` - tool call / file write / progress
- `verification.*` - AC 校验进度
- `system.*` - 保活 / 模型切换

### 4.4 断线重连机制

1. 前端维护 `lastSeenSeq`（localStorage 持久化）
2. SSE URL 带 `?last_seen_seq=N`
3. 后端查 `conversation_events where seq > N` 补发历史，然后接实时流
4. 客户端检测 seq 跳跃，触发主动重连

### 4.5 API 清单

| Method | Path | 作用 |
|---|---|---|
| `POST` | `/api/coding/pipeline` | 发送消息（启动或继续流水线） |
| `GET` | `/api/sse/conversation/{id}?last_seen_seq=` | 订阅 SSE 流 |
| `POST` | `/api/spec/{spec_id}/confirm` | 确认 Spec（触发下一阶段） |
| `POST` | `/api/spec/{spec_id}/refine` | 基于当前 draft 让 AI 再优化 |
| `POST` | `/api/spec/{spec_id}/rollback` | 回滚到历史版本 |
| `POST` | `/api/conversation/{id}/cancel` | 取消当前 phase |
| `GET` | `/api/spec/{spec_id}` | 获取完整 Spec |
| `GET` | `/api/spec/{spec_id}/versions` | 获取版本历史 |

---

## 5. BaseAgent Runtime 设计（Phase D）

### 5.1 抽象目标

把 `VibeCodingAgent` 里**通用能力**抽出来，让三个 agent 共享：

| 能力 | 说明 |
|---|---|
| LLM 调用层 | 统一 request/response、重试、超时、token 统计 |
| Tool 系统 | Tool 注册、参数校验、执行、结果反馈 |
| Loop 控制 | max_turns、终止判定 |
| 事件发布 | 对接 `conversation_events` + SSE 推送 |
| Trace 持久化 | 对接 `agent_traces` 表 |
| 状态机 | IDLE → RUNNING → {PAUSED, COMPLETED, FAILED, ABORTED} |
| 中断/取消 | cancel / pause / resume |
| Session suspend/resume | agent 状态序列化，断线后恢复 |
| 错误恢复 | LLM 429 / timeout / tool 异常 / max_turns 耗尽降级 |

### 5.2 子类职责

| 决策点 | BrainstormAgent | CodingAgent | VerificationAgent |
|---|---|---|---|
| `get_system_prompt()` | 反问式设计师 | 代码工程师（现有）| 验收专家 |
| `get_tools()` | 5 个反问/探索工具 | 7+ 个文件/命令工具 | 4 个检查工具 |
| `get_max_turns()` | 15 | 30（现有） | 10 |
| `should_terminate()` | Spec 已 emit | agent done / max_turns | 所有 AC 检查完 |
| `finalize()` | 返回 Spec | 返回 files_written | 返回 VerificationReport |

### 5.3 Hook 清单（13 个）

**必要 hook**：
- `before_run()` / `after_run()` - 生命周期
- `on_each_turn(turn)` - 循环检测 / nudge
- `before_tool_call(tool, args)` / `after_tool_call(tool, result)`
- `on_llm_response(response)`
- `on_max_turns_exceeded()` - 降级策略
- `finalize()` - 产出最终物

**有用 hook**：
- `on_message_appended(msg)`
- `on_context_overflow(msgs)` - 上下文压缩策略
- `on_stream_delta(delta)` - 流式 token
- `on_product_validation_failed(errors)` - 产物不合 schema 时
- `on_retry(attempt, error)`

### 5.4 LLM 层重构策略（重要决策）

**选定方案：增量改 `app.llm_client.LLMClient`**（非新建 `llm/` 模块）

**理由**（查验全仓使用情况）：
- 13 个模块使用 LLMClient（6 智能开发 + 5 智能搭建 + 2 其他）
- 所有调用**零用 tools 参数**
- 新增 `tools=None` 默认参数对所有现有调用 100% 兼容

**改动**：
```python
# LLMClient.chat_completion() / chat_completion_stream()
# 新增参数（默认 None，不传时行为完全不变）
tools: Optional[list[dict]] = None
tool_choice: Optional[str] = None
```

**实现**：
- OpenAI path：直接传 tools 参数
- Anthropic path：把 OpenAI tools 格式转成 Anthropic 格式

**工作量**：3.5 天。智能搭建 4 个模块零改动。

### 5.5 ask_user 工具的 suspend/resume 机制

`ask_user` 是 BrainstormAgent 特有的"阻塞等待用户回答"工具。方案：

1. Tool 执行时，发出 `brainstorm.ask_user` 事件 + 写 `agent_messages`
2. BaseAgent `pause()` + 序列化状态到 `brainstorm_sessions.agent_snapshot`
3. HTTP 连接断开，agent 对象释放
4. 用户回答 → 查 `active_brainstorm_session_id` → 加载 snapshot → 恢复 agent
5. 把用户答案作为上一轮 tool result 追加到 messages
6. 继续 `agent.run()`

**好处**：用户可以关页面离开几小时，回来能继续。

### 5.6 模块组织

```
backend/app/agents/
├── base.py              # BaseAgent, Tool, AgentContext, ToolResult
├── publisher.py         # EventPublisher
├── trace_writer.py      # TraceWriter
├── brainstorm/
│   ├── agent.py
│   ├── prompts.py
│   ├── tools/
│   │   ├── detect_scene.py / ask_user.py / query_marketplace.py
│   │   ├── read_workspace_context.py / emit_spec.py
│   │   └── classify_iteration.py
│   ├── state.py
│   ├── confidence.py
│   └── config.py
├── coding/
│   ├── agent.py         # 原 VibeCodingAgent
│   ├── prompts.py
│   ├── tools.py
│   └── loop_detector.py
├── verification/
│   ├── agent.py
│   ├── prompts.py
│   └── tools.py
└── orchestrator.py      # Phase 状态机
```

---

## 6. BrainstormAgent 反问策略（Phase B）

### 6.1 九条反问原则

1. 一次只问一个问题
2. 有选项不用开放题
3. 有合理默认值直接用，不问
4. 按优先级问
5. 不确认显而易见的事
6. 不问技术细节（LLM 自决）
7. 允许"随便/都行"（LLM 自决 + 记 open_question）
8. 最多 5 轮反问
9. 问题要能触发决策（能改变 Spec 字段）

### 6.2 三档优先级

| 优先级 | 含义 | 策略 |
|---|---|---|
| **P1 关键决策** | 影响 Spec 整体结构 | 必问（单值/范围、BOF 类型、是否跨端） |
| **P2 重要细节** | 影响配置项 / AC | 有默认值跳过，无则问 |
| **P3 锦上添花** | 优化体验 / 边界 | 不问，agent 自决 + 记 open_question |

### 6.3 场景特定 P1 清单

**组件（web_component_dual）**：
- 数据是单值、范围还是数组？
- 存储类型是字符串、数字还是日期？
- 是否需要列表展示（list 模式）？

**页面（web_page）**：
- 主要形式是表单、表格、图表还是详情？
- 数据从接口取还是静态？接口清楚吗？
- 是否需要分页 / 搜索 / 筛选？

**接口（backend_api）**：
- 一共几个接口？每个做什么？
- 是否读写 MpaaS 表？
- 是否需要特殊鉴权？

### 6.4 停止条件（Emit 判定）

满足任一即 emit：
- 所有 P1 问题都有答案 AND confidence ≥ 0.75
- 用户主动说"开始吧/直接生成"
- 反问轮数达 5 轮（降级 emit）
- `max_turns` 耗尽（BaseAgent 触发降级）

### 6.5 Confidence 算法（MVP 简单版）

```python
confidence = 0.4 * scene_confidence + 0.6 * p1_coverage
```

**阈值**：
- `≥ 0.75`：允许 emit
- `< 0.5`：emit 但前端警告 "方案置信度较低"
- `< 0.3`：禁止 emit，继续反问或降级

**不用复杂 5 维度**的理由：
- 维度越多越容易被 LLM "game"（打高分混过关）
- 简单版更抗 game、更易调
- 需要时再升级

### 6.6 迭代场景分级

用户在 DONE 后再次对话（Phase 7 ITERATE）时，**独立 LLM 调用**分级（Haiku 级别）：

| 级别 | 含义 | 处理 |
|---|---|---|
| `trivial` | 明确小改（"默认值改 10"）| 直接产 SpecPatch → Phase 4 Coding |
| `minor` | 模糊小改（"弄漂亮点"）| 反问 1 轮 → SpecPatch → Phase 4 |
| `major` | 重大改动（新增配置项） | 走完整 Phase 1 反问流程 |
| `cross_scene` | 跨场景（组件→页面）| 警告用户建议新建工作区 |

**独立 LLM 调用（非主 agent 工具）**的理由：
- 轻量模型足够，成本低
- trivial 场景（~60-70%）走快通道，省 2 倍时间 + 3 倍成本
- 错误更显性（主 agent 看不到判断依据）

### 6.7 Session Timeout

- **Suspend**：30 分钟无活动 → 卸载内存，session 状态 `suspended`（用户回来时自动 resume，无感）
- **Abort**：7 天持续 suspended → 状态 `aborted`，不能 resume（用户需重新开始）

### 6.8 ask_user Schema

```python
ask_user(
    question: str,
    options: list[Option] = [],    # 强烈推荐，每个带 "让我自己决定" 兜底
    priority: int = 2,              # 1/2/3
    allow_free_text: bool = True,
    context: Optional[str] = None,  # 可选上下文说明
)
```

---

## 7. 前端 Spec 预览设计（Phase A）

### 7.1 关键决策：不做编辑器，只做预览

**选定方案**：Spec 只读 markdown 展示 + 通过对话改

**否决方案**：表单化 Spec 编辑器（SpecEditor + 三套场景表单）

**理由**：
- 用户画像：业务用户看不懂 Spec 字段（BOF 类型、form_value_shape 等），技术用户更希望用自然语言而非填表单
- 开发成本：只读 4-5 天，可编辑 2.5-3 周，ROI 不划算
- 架构早期 schema 会变（1.0→1.1），表单跟改成本高
- 无痛升级：后端 API 保留 `/api/spec/{id}/edit`，未来需要时前端加组件即可

### 7.2 布局：融入现有 CodingPage

不做新页面，现有三栏布局基础上：
- 左栏：工作区列表（保留）
- 中栏：消息流 + 反问气泡（新增交互）
- 右栏：**按 phase 切换主内容区**（新增 phase-driven 布局）

### 7.3 Phase → 主内容区组件映射

| Phase | 主内容区 |
|---|---|
| `understand` | BrainstormProgressPanel（思考过程折叠） |
| `confirm` ⭐ | **SpecPreview**（markdown 渲染的 Spec 摘要） |
| `scaffold` | ScaffoldProgress |
| `generate` | CodingStream（现有改造） |
| `verify` | VerificationReport（AC 逐条状态） |
| `done` | WebIdeFrame（现有 IDE iframe） |

### 7.4 Spec Preview 核心元素

```
┌───────────────────────────────────────────────┐
│ 📋 方案预览 · 星级评分组件    v1  置信度 0.85    │
├───────────────────────────────────────────────┤
│ [markdown 渲染：基本信息 / 数据存储 / 配置项 / │
│  场景 / 验收点 / 约束]                          │
│                                               │
│ ⚠️ 默认假设（2 条，可重新反问）                 │
│ [👁️ 查看完整 JSON]                              │
├───────────────────────────────────────────────┤
│ 💬 不满意？在下方对话说                         │
│ [❌ 取消]         [✅ 确认生成代码]               │
└───────────────────────────────────────────────┘
```

### 7.5 反问气泡（中栏消息流）

```
╔═══════════════════════════════════╗
║ 🤖 数据是单值还是范围？           ║
║ [单值] [范围] [都要] [让我自己决定] ║
║ ℹ️ 这会影响存储类型               ║
╚═══════════════════════════════════╝
```

**视觉规则**：
- 左边框颜色按 priority：P1 红、P2 黄、P3 灰
- 每个反问必带 "让我自己决定" 选项（兜底，触发 agent 自决 + open_question）
- 自由输入始终可用

### 7.6 前端技术栈

| 层 | 选型 | 理由 |
|---|---|---|
| Vue | 3 组合式 API | 与现有一致 |
| 状态 | Pinia（新 `useSpecStore`）| Spec 多处共享 |
| 渲染 | 手写 Vue 组件（不用通用 JSON schema form） | UX 可控、scene 差异大 |
| SSE | EventSource + 断线重连（按 C 阶段方案）| 自动重连带 last_seen_seq |

### 7.7 组件清单

```
frontend/src/views/coding/
├── CodingPage.vue                   # 改造为 phase-driven
├── phases/
│   ├── BrainstormProgressPanel.vue
│   ├── SpecPreview.vue               # ⭐ 核心
│   ├── VerificationReport.vue
│   └── ...
├── spec-preview/
│   ├── SpecMarkdownRenderer.vue
│   ├── ComponentSpecSummary.vue
│   ├── PageSpecSummary.vue
│   ├── BackendApiSpecSummary.vue
│   ├── ConfidenceIndicator.vue
│   ├── OpenQuestionsPanel.vue
│   └── SpecJsonViewer.vue
├── conversation/
│   ├── MessageList.vue
│   ├── AskUserCard.vue
│   └── ...
└── stores/
    ├── useSpecStore.ts
    └── usePipelinePhaseStore.ts
```

---

## 8. 实施 Roadmap

### 8.1 里程碑

```
Week 1      ━━━━ P1.0 LLM 层扩展（加 tools）
Week 2-3    ━━━━━━━━ P1.1 BaseAgent + CodingAgent 迁移
Week 3      ━━ P1.2 数据库迁移（新建 7 张表）
Week 4-5    ━━━━━━━━ P2.1-2.3 Spec schema + BrainstormAgent
Week 5-6    ━━━━━━━━ P2.4 SSE 事件系统 + 断线重连
Week 6-7    ━━━━━━━━ P3 Coding 消费 Spec + Orchestrator
Week 7-8    ━━━━━━━━ P4.1 VerificationAgent
Week 8-9    ━━━━━━━━ P4.2 前端 phase-driven + SpecPreview
Week 9-10   ━━━━━━━━ P4.3 迭代分级 + SpecPatch + 集成联调
────────────────── 🎯 MVP 完成（10 周）
Week 11+    持续：P5 工具生态 / Model Router / 评估框架
```

### 8.2 详细任务

| Phase | 任务 | 工期 |
|---|---|---|
| **P1.0** | LLMClient 加 tools 参数（OpenAI + Anthropic 双路） | 3.5 天 |
| **P1.1** | 新建 `backend/app/agents/base.py`（BaseAgent + Tool + Context） | 3 天 |
| **P1.1** | VibeCodingAgent → CodingAgent 重构 | 4 天 |
| **P1.1** | 单测 + E2E 回归 | 2 天 |
| **P1.2** | 数据库 migration（7 张表） | 2 天 |
| **P1.2** | TraceWriter / EventPublisher 实现 | 1.5 天 |
| **P2.1** | Spec schema 代码化（schema.py + registries + validators） | 2 天 |
| **P2.2** | BrainstormAgent 实现（5 个 tool） | 5 天 |
| **P2.2** | Session suspend/resume | 2 天 |
| **P2.3** | Spec CRUD API | 2 天 |
| **P2.4** | SSE 事件系统 + 断线重连 + seq | 3 天 |
| **P2.4** | Confidence 算法（简单版） | 0.5 天 |
| **P3.1** | CodingAgent 改造消费 Spec | 3 天 |
| **P3.1** | 删除 CodingAgent 内部 scene 识别 | 1 天 |
| **P3.2** | Orchestrator phase 状态机 | 3 天 |
| **P3.3** | E2E 测试：Brainstorm→Coding 全链路 | 2 天 |
| **P4.1** | VerificationAgent 实现 | 5 天 |
| **P4.1** | 自动修复循环（≤ 2 次） | 2 天 |
| **P4.2** | CodingPage 改造为 phase-driven | 1 天 |
| **P4.2** | SpecPreview + 三场景 Summary | 3 天 |
| **P4.2** | AskUserCard 反问气泡 | 1.5 天 |
| **P4.2** | Confidence / OpenQuestions / Report UI | 1 天 |
| **P4.3** | 迭代分级 + SpecPatch | 3 天 |
| **P4.3** | SSE 断线重连前端集成 | 0.5 天 |
| **P4.3** | E2E 联调 + 样式打磨 | 2 天 |

### 8.3 并行机会

- `P2.1 (Spec schema)` 和 `P1.2 (DB)` 可并行
- `P2.3 (API)` 和 `P2.4 (SSE)` 可并行
- `P4.1 (Verify 后端)` 和 `P4.2 (前端)` 可并行

### 8.4 人力模型

- **最少人力**：1 后端 + 1 前端 → 10 周
- **推荐人力**：2 后端 + 1 前端 → 7-8 周

---

## 9. 风险与应对

| 风险 | 严重度 | 应对 |
|---|---|---|
| LLMClient 加 tools 导致智能搭建回归 | 🔴 | 单测 + 现有 E2E 必须全绿才合并（P1.0 死卡 gate） |
| BrainstormAgent 反问质量差影响体验 | 🟡 | P2 后期用 10+ 真实需求压测，不合格调 prompt |
| Spec schema 跑起来发现字段不够 | 🟡 | `metadata.extra` 口袋兜底；1.1 版本规划升级路径 |
| Session suspend/resume 并发问题 | 🟡 | MVP 单实例内存 counter；未来多实例加 Redis |
| VerificationAgent LLM 误判 AC 通过/失败 | 🟡 | confidence 分数；低 confidence 标黄人工审核 |
| 前端 Spec 预览信息密度过高，用户看不懂 | 🟡 | A/B 测试两种摘要密度，收集反馈 |
| `ask_user` 阻塞等回复导致 session 超时 | 🟢 | 已设计 suspend/resume，30 min 自动挂起 |

---

## 10. 向后兼容性保证

### 10.1 智能搭建（零改动）

`app.llm_client.LLMClient` 扩展 `tools` 参数默认 `None`。13 个使用方中：
- **智能搭建 5 模块**（requirements / chat / llm_configs / config_assembler / ai_doc_parser）：现有调用一行代码不改
- **其他 2 模块**（context_compact / module_standardizer）：同上

**承诺**：P1.0 合并前，智能搭建的全部 E2E 测试必须全绿。

### 10.2 现有工作区（`.workspace.json`）

- 新增的 agent 会写 `brainstorm_sessions / specs` 等表，**不触碰** `.workspace.json`
- 老工作区（无 Spec 关联）直接打开正常使用
- 新工作区带 `spec_id` 关联到 specs 表，可追溯

### 10.3 DB 迁移策略

- 只建新表，不改/不删老表
- `messages` 表继续存在（虽然新路径走 `agent_messages`，但老数据不迁移）
- 建议 6-12 个月后评估是否归档老 `messages` 表

### 10.4 API 兼容

- 现有 `/api/coding/auto-pipeline` / `/api/coding/pipeline`（harness）保持 URL，入参已在之前的迭代中移除 `project_type`
- 新增 `/api/spec/*` 和 `/api/sse/conversation/*` 是新 endpoint，不影响现有
- 前端逐步迁移，MVP 期间可能新旧 UI 共存

---

## 11. 技术债登记

明确标记不做的事，未来有需要时回来补：

| # | 内容 | 触发条件 |
|---|---|---|
| TD-1 | `acceptance_criteria` 升级到结构化对象（Spec 1.1） | VerificationAgent 需要按 AC id 精准校验时 |
| TD-2 | `constraints` 加 `category` 字段（Spec 1.1） | 需引入 semgrep / eslint / axe-core 等专业工具时 |
| TD-3 | Model Router（按 task 路由不同模型） | 单一模型成本或质量不够用时 |
| TD-4 | Tool Registry 全局化 | 跨 agent 共用工具多起来时 |
| TD-5 | 多实例部署（Redis pub/sub + 分布式 seq） | 单实例扛不住并发时 |
| TD-6 | 表单化 Spec 编辑器（方案 A） | MVP 数据显示用户需要字段级编辑时 |
| TD-7 | 其他 scene 类型补齐（list_view / layout / login / plugin） | 业务需要时 |
| TD-8 | 旧 `messages` 表归档/删除 | MVP 稳定运行 6-12 个月后 |

---

## 12. 评审关注点

请评审重点确认以下决策是否成立：

### 12.1 必须确认的决策（影响架构）

1. **三 Agent 线性流水线 + Spec 契约**：这是本次重构的核心架构，是否认可？
2. **不共享 conversation**（三个 agent 各自 session，通过 Spec 连接）：是否接受"context 精简 vs 用户视角割裂"的权衡？
3. **LLM 层增量改 LLMClient**（非新建 llm/ 模块）：是否接受"向后兼容优先"的思路？
4. **MVP 不做表单化 Spec 编辑器**：是否接受只做只读预览 + 对话改？
5. **Scene 识别合并进 BrainstormAgent**（不做独立 pipeline 步骤）：是否合理？

### 12.2 需要评估的参数

6. **max_ask_rounds = 5**：是否合理？需要按业务调整吗？
7. **confidence 阈值**（0.75 emit / 0.5 警告 / 0.3 禁止）：是否合理？
8. **session_suspend / abort 时长**（30 min / 7 天）：是否合理？
9. **VerificationAgent 自动修复次数上限 = 2**：是否合理？
10. **CodingAgent max_turns = 30**（现有值）：保持还是调整？

### 12.3 资源 / 工期

11. **10 周 MVP 工期**（1 后端 + 1 前端）或 **7-8 周**（2 后端 + 1 前端）：资源投入是否可接受？
12. **智能搭建零改动承诺**：评审团认可这个 gate 吗？

---

## 附录

### A. 术语表

- **Spec**：Brainstorm 产出的结构化规格，Coding 消费的契约
- **AC**：Acceptance Criteria，用户验收点
- **BaseAgent**：所有 agent 共享的抽象基类
- **Phase**：流水线阶段（understand / confirm / scaffold / generate / verify / done / iterate）
- **Provenance**：Spec 的来源信息（谁产出、confidence、默认假设）
- **SpecPatch**：迭代时产生的 Spec 增量变更

### B. 相关历史文档

- `docs/internal/CODING_REFACTOR_BACKLOG_2026-04-16.md`
- `docs/internal/DUAL_COMPONENT_STRUCTURED_RENDERING_PLAN_2026-04-17.md`
- `docs/internal/HARNESS_INTERNAL_REVIEW_DOC_V1.md`

### C. 主要代码文件影响面

**新增**：
- `backend/app/agents/` 目录（base.py + 三个 agent 子目录）
- `backend/app/spec/` 目录（schema.py + registries + validators）
- `backend/app/models/` 新增 7 个 model 文件
- `frontend/src/views/coding/phases/` + `spec-preview/` + `conversation/` 三个子目录

**修改**：
- `backend/app/llm_client.py`（加 tools 参数，100% 兼容）
- `backend/app/coding/vibe_agent.py`（重构为继承 BaseAgent）
- `backend/app/routes/coding.py`（API 层对接新 agent）
- `backend/app/coding/pipeline.py`（改造为 Orchestrator）
- `frontend/src/views/coding/CodingPage.vue`（phase-driven 布局）

**零改动**（承诺）：
- `backend/app/routes/requirements.py`
- `backend/app/routes/chat.py`
- `backend/app/config_assembler.py`
- `backend/app/ai_doc_parser.py`
- `backend/app/routes/llm_configs.py`

---

**文档结束**
