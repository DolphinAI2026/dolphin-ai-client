# 智能开发 Agent V2 重构 —— 会话交接文档（2026-04-20）

## 1. 工作目录
```
/Users/mars/Desktop/apaas-build/apaas-builder-ai/.claude/worktrees/competent-chatterjee-6d4c33
```
- 分支：`claude/competent-chatterjee-6d4c33`
- 从 `main` 分叉 48 个 commit，**未合入 main**

## 2. 最终目标
把 aPaaS 智能开发模块从单体 `VibeCodingAgent` + `pipeline.py` 流水线重构为**三 Agent 架构**（BrainstormAgent → Spec → CodingAgent → VerificationAgent），完整方案见 `docs/internal/INTELLIGENT_DEV_AGENT_ARCHITECTURE_V1_2026-04-19.md`。

## 3. 已完成（按阶段）

### P1（在本会话之前已完成）
- BaseAgent 运行时（`backend/app/agents/base.py`）+ 13 hook
- CodingAgent 从 VibeCodingAgent 迁移（字节级 prompt 兼容）
- 7 张 agent 相关 DB 表（`backend/app/models/agent_models.py`）
- `DbEventPublisher` / `DbTraceWriter` 写 DB + SSE 推送

### P2（本会话）
- **Spec 契约**：`backend/app/spec/`（schema / ui_editor_registry / ui_section_registry / validators）
- **BrainstormAgent**：`backend/app/agents/brainstorm/`（agent + 5 tool：detect_scene / ask_user / query_marketplace / read_workspace_context / emit_spec + confidence 算法）
- **Spec 持久化 + Session 管理**：`backend/app/services/spec_service.py` + `brainstorm_session_service.py`
- **Spec CRUD API**：`backend/app/routes/spec.py`（GET / versions / confirm / refine / rollback）
- **Orchestrator**：`backend/app/orchestrator/`（phases / coordinator / driver）

### P3
- **Spec → CodingAgent 桥接**：`backend/app/agents/coding/spec_bridge.py`
- CodingAgent 支持 `spec_brief` 注入 prompt（保持旧路径字节级兼容）
- Driver 高级 API：`drive_brainstorm` / `drive_coding_from_spec`

### A（SSE + 新路由）
- `backend/app/routes/sse.py` — `GET /api/sse/conversation/{id}?last_seen_seq=N`
- `backend/app/routes/coding_v2.py` — `POST /api/coding/v2/message` + `POST /api/coding/v2/spec/{id}/start-coding`
- 老 `/coding` 路径保留不动

### B（VerificationAgent）
- `backend/app/agents/verification/`（4 tool：grep_code / read_file / check_ac / emit_report）
- `drive_coding_with_autofix` 闭环：coding → verify → failed 触发 coding 重跑 ≤ 2 次
- `backend/app/services/verification_report_service.py`

### D（迭代分级）
- `backend/app/agents/iteration/`（SpecPatch + `classify_iteration` 独立轻量 LLM + 启发式 fallback）
- 集成到 `coding_v2.py` iterate 路由按 trivial/minor/major/cross_scene 分派

### C（前端）
- `frontend/src/api/codingV2.ts` / `stores/codingV2.ts` / `utils/sseClient.ts`
- 11 个 Vue 组件（`frontend/src/components/coding-v2/`）：SpecPreview + 三场景 Summary + AskUserCard + VerificationReportPanel + IterationBanner + BrainstormProgress / CodingProgress 等
- `frontend/src/views/coding-v2/CodingPageV2.vue` — phase-driven 布局
- 路由 `/coding-v2/:conversationId?`

## 4. Git 提交（没合入 main）

```
74747d1 后端 MVP 完整链路：Spec 契约 + Brainstorm/Verification Agent + Orchestrator + 迭代分级
c39508d 前端 V2：phase-driven 布局 + SpecPreview + AskUserCard + 验收报告 UI
```

**注意**：P2-D 的所有 Bug 修复（见第 6 节）**还没 commit**，当前这些改动在 working tree 里未提交。

## 5. 测试状态（268+ 个测试**全部绿**）

| 文件 | 测试数 |
|---|---|
| test_spec_schema.py | 33 |
| test_brainstorm_agent.py | 37 |
| test_spec_service.py | 17 |
| test_spec_api.py | 9 |
| test_orchestrator.py | 32 |
| test_coding_agent_stage_2_3.py | 17 |
| test_spec_to_coding_bridge.py | 17 |
| test_e2e_brainstorm_to_coding.py | 4 |
| test_coding_v2_routes.py | 18 |
| test_verification_agent.py | 31 |
| test_verification_driver.py | 8 |
| test_spec_patch.py | 23 |
| test_iteration.py | 22 |
| **test_brainstorm_pause_resume_integration.py** | **5**（新增，真实 pause/resume 链路） |

## 6. 本会话发现并修复的重大 Bug（严重警告）

**用户发现后端 MVP 在真实环境里根本不可用**。所谓 268 个测试绿其实**未覆盖核心交互路径**（反问 + pause/resume）。接手的会话**必须**认识到这点。

| # | Bug | 根因 | 修复文件 |
|---|---|---|---|
| 1 | SSE 404/403 无法订阅 | EventSource 不支持自定义 header，auth dependency 只读 header | `routes/sse.py` 新增 `_sse_auth` dependency 支持 `?token=` query |
| 2 | 事件类型双重前缀 `brainstorm.brainstorm.ask_user` | `_publish()` 无脑拼接 `{agent_type}.{action}`，但 tool emit_event.type 已含完整前缀 | `agents/base.py` `_publish`：action 已含点号则直接用 |
| 3 | **Agent 每次从头重跑**（反问循环无限死循环） | BaseAgent.run() 开头**硬编码** `_messages = [...]` 覆盖 `from_snapshot` 恢复的状态 | `agents/base.py` run(): 检测 `is_resume = bool(self._messages)`，resume 场景跳过重建 |
| 4 | **用户答案从未被注入 agent messages** | 架构文档 § 5.5 第 5 步"把答案作为 tool_result 追加"从未实装 | `services/brainstorm_session_service.py` 新增 `_inject_user_answer_as_tool_result` + `resume_session(user_answer=...)` |
| 5 | **Snapshot 永远是 None**（本会话核弹级 bug） | BaseAgent.run() 的 pause 分支 `await _wait_for_resume_or_cancel()` 永远阻塞 → drive_brainstorm 拿不到 PAUSED → `suspend_session()` 从不被调用 | `agents/base.py` pause 分支改为立即 `break` 退出循环 |
| 6 | run 结尾把 PAUSED 改成 COMPLETED | finalize 覆盖 status | `agents/base.py` run 结尾 PAUSED 跳过 finalize |
| 7 | **DB 变更不持久化** | `suspend_session` 只 flush，后台 task 退出 context 时事务回滚 | `routes/coding_v2.py` 每个 `_run_*_task` 结尾 `await task_db.commit()` + 异常 rollback |
| 8 | **MySQL 连接丢失**（最后一个，现在可能还在验证） | `database.py` engine 没开 `pool_pre_ping`，池里死连接被再次使用就 `Lost connection during query` | `database.py` 加 `pool_pre_ping=True` + `pool_recycle=1800` |

## 7. 方法论错误（已被用户批评）

用户明确指出：
> "这种就是发现问题然后打补丁"

**本会话犯过的错**：
- 在前端加 `normalizeEventType()` 折叠 `brainstorm.brainstorm.X` 兼容后端 bug —— **用户要求撤掉**（防御式编程只该防不可控的输入，不该防自己代码的输出）
- 用 268 个单测但**脚本化 mock 的 `_call_llm`** 绕过了真实 tool 执行 + pause/resume 链路 —— 把"测试覆盖率"当"功能可用"

**用户的批评是对的**：必须看根因不打补丁，必须真实链路测试。

**为了补救**，本会话新增了 `tests/test_brainstorm_pause_resume_integration.py`（5 个测试）：
- 用 `ScriptedLLMClient` 返回真实 OpenAI-format tool_call response
- Agent 的 `_call_llm` 走默认实现，真实调 LLM client
- 真实的 `_handle_tool_calls` 执行真实工具体
- 走完整 pause → suspend_session → DB snapshot → resume_session → inject tool_result → continue

## 7.5 未实现的 Phase（严重告警 —— 不是 bug 是功能缺失）

架构文档 § 2.2 定义的 phase 状态机包含：
```
UNDERSTAND → CONFIRM → SCAFFOLD → GENERATE → VERIFY → DONE
```

**但 `SCAFFOLD` 阶段根本没有实现**：
- Orchestrator 有 `Phase.SCAFFOLD` 枚举 + `on_scaffold_done()` 状态转移函数
- `coding_v2.py` 的 confirm flow 会把 phase 推进到 SCAFFOLD（当 `need_scaffold=True`，即 conversation 没 workspace_id 时）
- **但没有任何代码真的去创建 workspace / 安装依赖 / 拷贝 scaffold 模板**
- 前端 `CodingPageV2.vue` 有 `<div class="scaffold-panel">` UI 展示"📦 正在创建工作区..."，但后端无 worker 在做这件事 → UI 永远转圈

首轮用户（`workspace_id=null`）走完 CONFIRM → SCAFFOLD 后就**卡死**。真实 E2E 无法从 CONFIRM 继续到 GENERATE。

**接手会话需要实现**：
- 新增 `backend/app/orchestrator/scaffold.py` 或类似模块
- 从 Spec `scene_type` → project_type → 调现有的 `app.coding.workspace.WorkspaceManager.create_workspace()`
- 写 `agent_messages` 进度事件（`scaffold.started` / `scaffold.done` / `scaffold.failed`）
- 把新 `workspace_id` 写回 `conversations.workspace_id`
- 完成后调 `orchestrator.on_scaffold_done()` 推进到 GENERATE，继续调 `_run_coding_task`

**workaround**：先在既有 workspace 里测试（`need_scaffold=False` 路径 SCAFFOLD 被跳过，直接到 GENERATE）。

同样未完全实现的：
- **VERIFY phase 自动触发**：`drive_coding_with_autofix` 函数存在，但没在 `_run_coding_task` 里被调用。coding 跑完直接 DONE，不走 verify。
- **`start-coding` 触发后，从 `scene_type` 决定 workspace 模板的映射**（spec_bridge 有 `scene_to_project_type`，但没被 scaffold 流程使用）

## 8. 当前状态（待用户验证）

**刚做完 Bug #8（`pool_pre_ping`）的修复**，让用户刷新浏览器重新测。**还没确认修复是否生效**。

前端已经开着，后端跑在：
- 后端：`uvicorn app.main:app --reload` 端口 8000（task id `b60wm7cmi`，在 `worktrees/.../backend` 目录）
- 前端：`npm run dev` 端口 5173（task id `bp5h1r6rn`）
- code-server：端口 8080（task id `bt7kpizue`）

## 9. 用户语言偏好

**默认中文回复**（用户在 `/Users/mars/.claude/projects/-Users-mars-Desktop-apaas-build-apaas-builder-ai/memory/user_language.md` 里设了）。Commit message 也只允许中文。

## 10. 下一个会话应该做什么

**优先级 1**：等用户测试 Bug #8 的修复。如果还有问题：
- **看日志 / DB，不猜**。用户已经对"打补丁"很不耐烦
- 用 `/private/tmp/claude-501/.../tasks/b60wm7cmi.output` 看后端日志
- 用小脚本查 DB：`events` / `brainstorm_sessions.agent_snapshot` 里的实际状态

**优先级 2**：把所有 Bug 修复 commit 掉（现在未提交）：
- `agents/base.py`（run() resume + pause 退出）
- `services/brainstorm_session_service.py`（tool_result 注入）
- `routes/coding_v2.py`（task commit）
- `routes/sse.py`（_sse_auth）
- `database.py`（pool_pre_ping）
- 新增集成测试 `tests/test_brainstorm_pause_resume_integration.py`

**优先级 3**：**实现缺失的功能（见 § 7.5）**：
- **SCAFFOLD phase 的实际执行**（创建 workspace / 装依赖）—— 完全没实现
- **VERIFY phase 在 coding 完成后自动触发** —— driver 层有 `drive_coding_with_autofix` 但没接入 `_run_coding_task`
- scene_type → project_type → scaffold 模板的真实挂接

**优先级 4**：可能还存在的问题：
- LLM 返回不带 tool_calls 时 agent 会 `LLM_NO_TOOL_CALL → break → COMPLETED`，但 state.emitted=False → degraded。应该发 `brainstorm.failed` 或 `brainstorm.stuck` 事件让前端知道，而不是前端一直转圈（目前用户看到的"卡住"现象之一）
- CodingAgent 在真实 MySQL + MiniMax 环境还没跑通过，**真实 E2E 从未成功过**

## 11. 架构关键点（避免下个会话绕弯）

- 前端 `CodingPage.vue` 3182 行是老代码，**不要动**。新代码走 `/coding-v2` 路径
- `/coding/pipeline`（老 API）+ `pipeline.py` 继续工作，不要删
- `_run_brainstorm_task` / `_resume_brainstorm_task` / `_run_coding_task` 是 `asyncio.create_task()` 起的**后台任务**，独立 DB session，**必须显式 commit**
- `DbEventPublisher` 自己 commit event 行，但其他 DB 变更（BrainstormSession / Spec）**不自己 commit**
- `BrainstormAgent` 的 `to_snapshot()` 包含 `_messages / _turn / state`；`from_snapshot` 恢复它们；`run()` 看到 `_messages` 非空就是 resume 场景

## 12. 用户风格

- **直接、严格、不给面子**：说"一步一个坑"、"你之前做的功能都是不可用的"时是真的在指出问题
- **希望看根因不看补丁**
- **中文沟通**
- **希望系统级架构**不是玩具

---

**给接手会话的建议**：先把 Bug #8 的修复结果和用户确认清楚，再决定下一步。**不要自作主张继续推进功能**。
