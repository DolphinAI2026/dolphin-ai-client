# 配置助手统一到 AI Builder unified 引擎 — 设计文档

- 日期：2026-06-04
- 状态：设计已确认（大明哥拍板），待 plan
- 方向锚：[[config_assistant_unify_into_unified]]、[[agent_routing_and_redundancy_2026_06_03]]（R1/R3 重复建设根）

## 1. 背景与目标

### 背景
ChatPage 右栏的「配置助手」和 AI Builder 的 unified 引擎是两套重叠的对话 agent：

- **配置助手**：`_config_chat_event_stream` 内联函数（`backend/app/routes/applications/__init__.py:2870`），`MAX_TURNS=25`，72 个工具（含 4 个自开发工具 + `save_config_skill` 自学习），写 `config_chat_sessions`/`config_chat_messages` 两张表，前端 `ConfigAssistantPanel.vue`（默认 420px，可拖 320–880）挂 ChatPage 右栏，改完配置靠 `ConfigAssistantMessages.vue` watch 到 modify 工具 emit `refresh-iframe` 刷预览。system prompt 里有过时的「去 AI Coding 模块」引导（AI Coding 独立入口已删并入 AI Builder）。
- **unified**：`run_agent`（`backend/app/ai_chat/agent.py:589`，`_run_agent_inner` + holder/`asyncio.shield`），`MAX_TURNS=20`，工具 = 8 本地 + MCP（`builder∪coding` 过滤），写 `ai_chat_sessions`/`messages`/`tool_calls`/`artifacts` + `agent_run`/`agent_step` trace（token 已采），前端 `AIChatPage.vue` 三栏 + 抽屉式 trace，已有 `app_dev` dispatch（sessionStorage + `?app_dev=1`）和 embedded 模式。

配置助手缺 codegen 地基（无 `create_dev_workspace`/`write_workspace_files`），且后端是内联函数、无 trace/会话/产出物基建。

### 目标
ChatPage 右栏换成 unified `run_agent` + `AgentConversation` + trace，**锁定当前应用上下文**，一套引擎覆盖 配置 + codegen + 会话历史 + 产出物 + trace + 自学习 skill + 自动刷预览。

### 为什么是配置助手并进 unified，而非反过来
配置助手后端是内联函数、无 trace/会话/产出物地基，往旧壳堆能力是负债；unified 已有完整基建。

### 非目标
- 延迟工具 / ToolSearch 机制（Claude Code 那套按需拉 schema）—— 记为独立后续 track，不在本 spec。它才是彻底消解 `builder/coding/config` 三套白名单分裂的北极星，但属通用 agent 基建改造、与本次正交。
- /ai-chat 全局侧栏收纳 app 级会话（app 级会话只在右栏自己的 session 抽屉按 app 过滤列出）。

## 2. 关键决策（已拍板）

| # | 挑战 | 决策 |
|---|------|------|
| 范围 | spec 野心 | 全端到端一份 spec（6 挑战全包，含数据迁移 + 布局收敛） |
| ② | 工具集 | `builder∪coding∪config` 去重 ~85 全并；0-1/跨应用工具靠 system prompt + 后端注入锁定 app_id 软约束 |
| ③ | 前端布局 | 右栏拖宽不跳转（嵌 `AgentConversation`，maxWidth 880→~1200；开 IDE 走现成全屏抽屉 `WorkspaceIdeDrawer`，那是 overlay 不是路由跳转） |
| ④ | 数据 | 一次性迁到 AIChat 表，旧表留 archive 不删 |
| ① | 应用上下文 | 常驻锁：`ai_chat_sessions.app_id` 列 + system prompt 注入 + 工具 app_id 后端填死（memory 已定方向） |
| ⑤ | refresh-iframe | 接进 unified（前端换检测源，信号链不变） |
| ⑥ | 自学习 skill | 保留 `save_config_skill` + `config_assistant_skills` 表 |

### 工程现实（影响落地写法）
- **无 Alembic / 任何迁移框架**。表靠 `Base.metadata.create_all` 建（只建缺表、不改已有表），加列是 `backend/app/database.py:66` 一长串 try/except 手写 `ALTER TABLE`（兼容 SQLite dev + MySQL prod），数据迁移有先例 `_migrate_legacy_builder_specs`（`database.py:189`，`init_db` 内 boot-time 跑）。本 spec 照这套，不引新框架。
- `AIChatSession` 刻意无 FK 到 `applications`（解耦），`ConfigChatSession.app_id` 是带级联 FK。两边 `app_id` 都是内部 `applications.id`（非 apaas 平台 id），env/平台标识从 application 记录现取。
- 本地 dev DB 是 SQLite，prod 是 MySQL。改后端必重启 preview backend。.venv 是 py3.13。

## 3. 端状态架构

ChatPage 右栏不再跑 `_config_chat_event_stream`，改成嵌 unified 的 `AgentConversation`，后端走 `run_agent`，session 是带 `app_id` 锁的 app 级 `AIChatSession`。

一套 `run_agent` 同时服务两态：
- **自由态**（`app_id` 为空）：现有 /ai-chat，0-1 创建、通用。
- **应用态**（`app_id` 锁死）：右栏配置 + 二次开发，工具 app_id 被后端填死锁定。

`_config_chat_event_stream`、两个 config-chat 路由、`ConfigAssistantPanel` 引擎层、`config_chat` 两张表（迁完后）全删。

## 4. 详细设计

### 4.1 应用上下文常驻锁（①）

**数据库**（加到 `database.py` 的 ALTER 列表，try/except 幂等）：
```sql
ALTER TABLE ai_chat_sessions ADD COLUMN app_id INTEGER
CREATE INDEX IF NOT EXISTS ix_ai_chat_sessions_app_id ON ai_chat_sessions(app_id)
```
- `app_id` nullable，内部 `applications.id`。空 = 自由态，非空 = 锁定该应用。
- 不加 FK（沿用 ai_chat 解耦风格）。app 删除时的孤儿会话：在删应用路径里顺手清，或接受孤儿（plan 定）。
- 不新增 `mode` 枚举值；app 态由 `app_id IS NOT NULL` 判定（`mode` 仍是 chat/cowork，决定基础 SYSTEM_PROMPT）。
- 对应 model：`AIChatSession` 加 `app_id: Mapped[Optional[int]]`。

**锁的设置**：
- 扩 `POST /api/ai-chat/sessions` 请求体收 `app_id` + `section`（建会话即锁）。
- 右栏开会话时带上当前 app_id；锁定后整个 session 生命周期不变。

**注入 agent（system prompt）**：
- `run_agent`/`_build_initial_messages` 组 system prompt 时，若 session 有 `app_id` → 拼「应用上下文块」：应用名 / 内部 id / apaas 平台标识 / env / SPEC 摘要 / 当前 section 软提示。
- 有 app_id 时基础 prompt 切到 app-context 变体（见 4.5）。

**工具护栏（app_id 填死）**：
- `execute_tool`（`tools.py:1444`）调 apaas 类工具前，若 `session.app_id` 非空，后端强制把锁定 app_id 填进该工具的 app-id 参数（覆盖 LLM 给的值），env 从 application 现取。
- 效果：0-1/跨应用工具即使在工具集里，agent 也跨不出锁定应用。
- **plan 待办**：各工具 app-id 参数名不完全一致（`app_id` / `appId` / `application_id` 等），plan 阶段逐个对一份清单。

### 4.2 工具集 ~85 全并（②）

- `get_all_tool_schemas()`（`tools.py:1384`，现按 `tools_for_agent("builder") | tools_for_agent("coding")` 过滤，`tools.py:1404`）扩成 `builder ∪ coding ∪ config`。全局生效（自由态也拿得到 config 工具，无害）。
- `save_config_skill` 进白名单。
- `MAX_TURNS` 统一到 25（config 多步任务证明 25 必要；现 unified 是 20，`agent.py:582`）。
- token 代价：每轮多 ~10–30k schema token（schema 内联随 `payload["tools"]` 每轮发，`agent.py:403`+`660`+`692`）。接受 —— config 现在就跑 72 个，union ~85 只多一点。

### 4.3 数据模型 + 迁移（④）

**标记列**（加到 ALTER 列表，幂等用）：
```sql
ALTER TABLE config_chat_sessions ADD COLUMN migrated_session_id INTEGER
```

**boot-time 幂等迁移** `_migrate_config_chat_to_ai_chat(conn)`，在 `init_db` 的 `create_all` + ALTER 之后调（仿 `_migrate_legacy_builder_specs`）：
1. 并发护栏：MySQL `SELECT GET_LOCK('migrate_config_chat', 0)`，抢到才跑（多 pod 启动防双跑）；SQLite 无此函数 → try/except 直接跑（dev 单进程）。
2. 选 `config_chat_sessions WHERE migrated_session_id IS NULL`，逐条：
   - 建 `ai_chat_sessions`：`app_id`=旧 `app_id`，`tenant_id`/`user_id`/`title`/`created_at`/`updated_at` 照搬，`status='active'`（迁过来可续），`mode='chat'`。
   - `config_chat_messages` → `ai_chat_messages`：`role`/`content`/`created_at` 照搬；`change_plan_json` + `actions_summary_json` 塞进 `extra_meta`。
   - `tool_trace_json`（list of `{tool_name, args, ok, summary, duration_ms, image_data_url?}`）尽量还原成 `ai_chat_tool_calls` 行：`tool_name`/`args_json`/`result_text`(summary)/`status`(ok→success/error)/`duration_ms`；`provider_call_id` 旧数据没有 → 留空。
   - 回写 `config_chat_sessions.migrated_session_id` = 新 session id。
3. 释放 lock。
- **续旧会话上下文不精确**：`provider_call_id` 缺失使跨轮 LLM 上下文重建（`_build_initial_messages` 对齐 `assistant.tool_calls` 与 `role:tool`）略不精确，但 config agent 每轮读实时应用态，可接受。
- 旧表 `config_chat_sessions`/`config_chat_messages` 保留作 archive 不删（可回滚）。

### 4.4 前端右栏改造（③）

**抽 composable `useAiChatSession`**（本半截核心 refactor）：
- unified 的流式编排（SSE→响应式 `AgentMessage[]`、工具拼装、typing 计时、排队、停止）现内联在 `AIChatPage.vue`（transport 走 `api/aiChat.ts` 的 `aiChatApi`）。
- 抽成 composable（transport 仍用 `aiChatApi`），`AIChatPage` 和新右栏面板共用，不复制几百行。

**新面板**（就地改造 `ConfigAssistantPanel.vue`）：
- `usePanelResize`（保留拖宽，maxWidth 880→~1200 给 diff）
- `useAiChatSession`（锁 `app_id`）
- `AgentConversation`（`components/common/AgentConversation.vue`，纯展示，吃 `AgentMessage[]`，emit `open-trace`/`open-artifact`/`answer-ask`/`feedback`）
- 复用 unified 输入器 / 模型选择
- trace 抽屉（per-message「查看本次 trace」+ 会话级「Agent 活动」）
- app 级 session 抽屉（列按 `app_id` 过滤的 `AIChatSession`）

**ChatPage 侧几乎不动**：仍 `@refresh-iframe="refreshPlatformAndSidebar"`（`ChatPage.vue:387`，+ `designerRefreshKey++` at `ChatPage.vue:2600`），把子组件从 `ConfigAssistantPanel` 换成新面板。

### 4.5 refresh-iframe 接进 unified（⑤）

- 信号链不变，只换检测源。现在 `ConfigAssistantMessages.vue:47` watch config 消息里 modify 工具（正则 `^(update_|create_|add_|delete_|disable_|set_)` + `ok=true`，`useConfigChat.ts:15`）→ emit。
- 新面板换成 watch `AgentConversation` 喂的 `tool_calls` 数据形状，同一套正则 + 成功判定，满足 emit `refresh-iframe`（沿用 200ms debounce + `Set<id>` 去重）。
- ChatPage 的 `refreshPlatformAndSidebar` + `designerRefreshKey++` 一字不改。
- 可选硬化（记 backlog）：后端在 modify 工具成功后发显式 `config_changed` SSE event，前端不靠正则猜。

### 4.6 自学习 skill + config 特性移植（⑥ + 收尾）

- **skill**：`save_config_skill` 进白名单（4.2 已含）。把 config stream「开场加载 tenant+app skills 注入 prompt」（`applications/__init__.py:3025`–`3048`/`3177`）搬进 `run_agent` 组 app-context prompt 时执行（有 `app_id` 才加载）。`config_assistant_skills` 表（`config_assistant_skill.py:21`）不动（已按 `app_id` 隔离）。
- **change_plan / requires_confirmation / actions_summary**：unified 已有确认门 + `ask_clarifying_question` 可点卡片。把 config 的「改动计划→确认」映射到这套，别背平行机制；视觉保留「改动计划，确认?」卡片；`actions_summary`（人话变更摘要）作收尾文字呈现。
- **section hint**：ChatPage 的 `currentSection` 随发消息体带 `section`，拼成 prompt 一行软提示（「用户当前在 X 设计器」），不硬过滤（同现状，`_CONFIG_CHAT_SECTION_HINTS` at `applications/__init__.py:2477`）。
- **SPEC 上下文**：有 `app_id` 时复用 config 那段 `canonical_spec → config_preview → requirement_doc`（各 ≤12000 字，`applications/__init__.py:2951`）注入 prompt。
- **过时引导删除**：「去 AI Coding 模块」（`applications/__init__.py:3120`–`3124`/`2505`–`2506`）随旧 prompt 一起删，新 app-context prompt 写「codegen/自开发你现在就能干」（工具已在 union）。memory 里那个短期独立 bug 被本 spec 吸收，不单独修。

## 5. 切换 / 删码（cutover 后）

- **后端删**：`_config_chat_event_stream` + `POST /applications/{app_id}/config-chat`（`__init__.py:2574`）+ `/config-chat-stream`（`:3432`）+ `ConfigChatReq`（`:2525`）+ `_CONFIG_CHAT_SECTION_HINTS`/`_build_section_hint`/`_CONFIG_CHAT_TOOL_WHITELIST` 那套。
- **前端删**：`ConfigAssistantPanel` 引擎层 + 子组件（Header/Messages/Input/SessionDrawer）+ `useConfigChat.ts` + `api/configChat.ts`。
- **DB**：`config_chat_*` 两表迁完保留 archive。
- 顺序：先上新链路 + 迁移 + live 验证通过，再删旧码（避免删早了回不去）。

## 6. 测试策略

**后端**：
- 迁移幂等性（跑两次不产生重复 ai_chat 行）
- `tool_trace_json` → `ai_chat_tool_calls` 还原正确
- app_id 注入护栏（LLM 给别的 app_id 被后端覆盖成锁定值）
- app-context prompt 组装（skill / SPEC / section / 应用上下文块都进，无 app_id 时不进）
- 工具集 union ~85（`save_config_skill` 在内、0-1 工具仍在但被护栏锁）
- 测试基建：recorder/run_agent 风格 —— StaticPool 共享内存库 + monkeypatch `AsyncSessionLocal`（迁移测试同理需共享 conn）

**前端**：
- 新面板锁 app 发消息端到端
- `refresh-iframe` 触发（modify 工具成功 → 预览刷）
- session 抽屉按 `app_id` 过滤
- 拖宽（到 ~1200）
- trace 抽屉（两入口）

**live（真 gpt-5.5）**：
- 在某 app（产品租户 57，有模型 + 通用 B2B CRM）跑真实配置改动（如某字段改必填）→ 预览自动刷 + trace 有 run + token 采到 + skill 能存能复用
- 二次开发：在锁定 app 上跑一个 codegen（write_artifact）验证 union 工具 + app_id 注入

## 7. 风险与缓解

| 风险 | 缓解 |
|------|------|
| 迁移并发双跑（多 pod） | MySQL `GET_LOCK` 兜；幂等标记列 |
| `tool_trace` 还原不全 | 只影响旧会话续聊的 LLM 上下文重建；config agent 每轮读实时应用态，可接受 |
| union ~85 在 gpt-5.5 注意力够不够 | config 现 72 已生产验证，风险低；真不行再启延迟工具 track |
| 右栏拖宽挤窄预览 | 用户选「拖宽不跳转」方案的固有取舍，接受 |
| app_id 注入逐工具对参数名 | plan 阶段出清单逐个核 |
| 删旧码删早回不去 | 先验证新链路通过再删 |

## 8. plan 阶段待办（开放项）

- 各 apaas 工具的 app-id 参数名清单（4.1 护栏注入用）
- `useAiChatSession` 从 `AIChatPage.vue` 抽取的边界（哪些状态/方法进 composable，哪些留页面）
- change_plan → unified 确认门的具体映射（复用哪个事件/卡片组件）
- 任务依赖排序（多 agent 并行的安全切分）：后端 schema → 工具 union + 注入 + prompt → 迁移；前端 composable 抽取 → 新面板 → refresh-iframe；最后 cutover + 删码
