# AI Coding 治理 + Builder 无缝衔接 — 实施计划 (Phase 1)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 AI Coding 修顺(session 为主的数据模型 + 结构化工具卡 + 去强制 brainstorm 门)并把 Builder→Coding 衔接做到无缝,全在现有 pipeline 上做。

**Architecture:** 仅改主仓 `backend/` + `frontend/`(`mcp-server/` 副本不碰)。会话(`Conversation`)为唯一主单位,1:1 懒拥有 workspace。重 codegen 仍走现有 `harness/coding/pipeline`;接 v2 异步后端是 Phase 2,本计划不含。

**Tech Stack:** FastAPI + SQLAlchemy(async, sqlite/pg)· Vue 3 + Pinia + Element Plus · SSE。

**Spec:** `docs/superpowers/specs/2026-06-01-ai-coding-overhaul-design.md`

---

## 执行顺序与并行约束(给 agent 分工)

改动集中在少数大文件且有依赖,**必须按下面顺序**,同文件任务不可并行:

```
后端组 (B*)   ──先──>   前端组 (F*)
B1 模型/删除语义 ─┐
B2 迁移脚本      ─┤(B1→B2)
B3 去 brainstorm 门 ─┐(B3→B4 同改 pipeline.py)
B4 结构化工具事件   ─┘
                      F1 侧栏=会话 ─┐
                      F2 工具卡+删正则 ─┤(F1→F2→F3 同改 CodingPage.vue,严格串行)
                      F3 handoff 修复  ─┘
```
- **后端组 B1–B4** 与 **前端组 F1–F3** 之间:F2 依赖 B4 的事件结构、F1 依赖 B1 的删除语义 → **先做完后端组,再做前端组**。
- 后端组内:B1→B2(B2 依赖 B1 模型);B3、B4 都改 `pipeline.py` → 串行(B3 后 B4)。
- 前端组内:F1、F2、F3 都改 `CodingPage.vue` → **严格串行 F1→F2→F3**。
- 每个任务自成一个 commit;每个任务用一个 fresh subagent。

---

## Task B1: 确立 会话↔workspace 1:1 + 删除语义

**Files:**
- Modify: `backend/app/routes/coding.py`(`delete_coding_conversation` 已存在,补强 + 确认 1:1)
- Modify: `backend/app/models/`(`Conversation` 模型,确认 `workspace_id` 字段语义为「至多一个」)
- Test: `backend/tests/test_coding_conversation_delete.py`(新建)

- [ ] **Step 1: 读现状**。读 `backend/app/routes/coding.py` 中 `delete_coding_conversation`(我们上轮加的)+ `Conversation` 模型的 `workspace_id`。确认:删会话时会 best-effort 删其 workspace;workspace_id 为单值(非多对一)。

- [ ] **Step 2: 写失败测试**(参照 `backend/tests/` 现有 async + sqlite fixture 风格):

```python
# test: 删除带 workspace 的会话 → 会话没了 + workspace 清理被调用 + 不报错(孤儿目录也安全)
async def test_delete_conversation_removes_owned_workspace(db_session, monkeypatch):
    called = {}
    async def fake_delete_ws(ws_id): called["ws"] = ws_id
    monkeypatch.setattr("app.coding.workspace.WorkspaceManager.delete_workspace", fake_delete_ws)
    conv = await _make_coding_conversation(db_session, workspace_id="form-page-x__1_abc")
    resp = await client.delete(f"/api/coding/conversations/{conv.id}", headers=auth)
    assert resp.status_code == 200
    assert called["ws"] == "form-page-x__1_abc"
    assert await _get_conversation(db_session, conv.id) is None
```

- [ ] **Step 3: 跑测试确认失败**。`cd backend && ./.venv/bin/pytest tests/test_coding_conversation_delete.py -v`。预期:FAIL(测试文件/fixture 未就位)。

- [ ] **Step 4: 实现/补强**。确认 `delete_coding_conversation` 满足:owner 校验 → 有 workspace 则 `delete_workspace`(异常忽略继续)→ 删 messages → 删 conv → commit。已实现的话仅补 owner=自己的断言 + 文档串注释「会话是主单位,workspace 随会话删」。

- [ ] **Step 5: 跑测试确认通过**。预期:PASS。

- [ ] **Step 6: Commit**。`git add -A && git commit -m "refactor(coding): 确立会话为主、1:1 拥有 workspace 的删除语义 + 测试"`

---

## Task B2: 孤儿 workspace 迁移脚本(幂等)

**Files:**
- Create: `backend/app/coding/migrate_orphan_workspaces.py`
- Test: `backend/tests/test_migrate_orphan_workspaces.py`

- [ ] **Step 1: 读现状**。读 `backend/app/coding/workspace.py` 的 `list_accessible_workspaces`(扫盘 + `.workspace.json`)+ `Conversation` 查询,理解 workspace 目录 ↔ 会话的关联键(`workspace_id` 形如 `form-page-x__<conv_marker>`,`.workspace.json` 里有 project_id/user_id/tenant_id)。

- [ ] **Step 2: 写失败测试**:造 2 个 workspace 目录(一个有会话指向、一个孤儿)→ 跑迁移 → 断言:孤儿被补建一个 owner 会话(同 user/tenant)并挂上;有主的不动;**再跑一次结果不变(幂等)**;无数据丢失。

- [ ] **Step 3: 跑测试确认失败**。

- [ ] **Step 4: 实现**。`migrate_orphan_workspaces()`:扫所有 workspace → 对每个无会话指向的,按 `.workspace.json` 的 user/tenant/project_id 补建一个 `Conversation(agent_type='coding', workspace_id=<ws_id>, title=display_name)`;无法定位 owner 的标记归档(workspace status='archived',不删盘)。幂等:已挂的跳过。

- [ ] **Step 5: 跑测试确认通过**(含二次运行幂等)。

- [ ] **Step 6: 接到启动**。在 `backend/app/main.py` lifespan 的 startup recovery 处调用一次(参照现有 `sweep_dead_coding_sessions` 的挂法,异常不致命)。

- [ ] **Step 7: Commit**。`git commit -m "feat(coding): 孤儿 workspace 迁移到 owner 会话(幂等)+ 启动时执行"`

---

## Task B3: 去掉强制两段式 brainstorm 确认门

**Files:**
- Modify: `backend/app/coding/pipeline.py:1604-1641`(brainstorm 门 + `_create_workspace_now`)
- Test: `backend/tests/test_pipeline_no_brainstorm_gate.py`

- [ ] **Step 1: 读现状**。读 `pipeline.py:1458`(detect_scene 调用)+ `1604-1641`(命中 BRAINSTORM_SCENES 时 emit `done waiting_confirmation:True` then return)+ `_create_workspace_now:1529`。理解前端 `useCodingPipeline.ts` 对 `waiting_confirmation` 的消费。

- [ ] **Step 2: 写失败测试**:模拟一条首消息命中 brainstorm 场景 → 断言 pipeline **不**提前 return waiting_confirmation,而是继续到 workspace 懒创建 + codegen(可 mock LLM/codegen,只验流程不在第一步截断)。

- [ ] **Step 3: 跑测试确认失败**。

- [ ] **Step 4: 实现**。移除/改造首消息的强制确认 return:首消息直接进入开发流;若仍要保留 brainstorm 提案,改成 **inline 一条提示消息**(不 return、不阻塞),workspace 在确需 codegen 时由 `_create_workspace_now` 懒创建。保留 `waiting_confirmation` 字段兼容(永远 False)以免前端炸。

- [ ] **Step 5: 跑测试确认通过**。

- [ ] **Step 6: 回归检查**。grep `waiting_confirmation` 在前后端的所有引用,确认去门后无残留依赖导致卡住。

- [ ] **Step 7: Commit**。`git commit -m "refactor(coding): 去掉强制两段式 brainstorm 确认门,首消息直接开发"`

---

## Task B4: 结构化工具事件(供前端工具卡 + 历史 replay)

**Files:**
- Modify: `backend/app/coding/pipeline.py`(工具调用 emit 结构化事件)
- Modify: 会话消息持久化处(`stream_messages` 落库)
- Test: `backend/tests/test_pipeline_structured_tool_events.py`

- [ ] **Step 1: 读现状**。读 `pipeline.py` 里工具调用 emit SSE 的地方(现状把 `🔧`/`✅`/`❌` 拼进文本)+ `useCodingPipeline.ts:163` 的 12 类事件 dispatch + `stream_messages` 落库逻辑。

- [ ] **Step 2: 定事件契约**(写进测试):每个工具调用 emit `{type:'tool', tool_name, action:'read|write|run', target, status:'running|ok|error', summary, output?}`,而非 emoji 文本。历史持久化保存该结构。

- [ ] **Step 3: 写失败测试**:跑一段 mock codegen(含 read/write/run)→ 断言 emit 的事件是结构化 tool 事件(有 tool_name/status),且落库的 `stream_messages` 可按结构还原。

- [ ] **Step 4: 跑测试确认失败**。

- [ ] **Step 5: 实现**。工具调用处改 emit 结构化 `tool` 事件 + 结构化落库。保留一条人话 `summary` 字段(给卡片标题用)。

- [ ] **Step 6: 跑测试确认通过**。

- [ ] **Step 7: Commit**。`git commit -m "feat(coding): 工具调用改 emit 结构化事件并结构化持久化"`

---

## Task F1: AI Coding 侧栏只列会话(消灭双轨)

**Files:**
- Modify: `frontend/src/views/CodingPage.vue:854-895`(`sidebarCodingItems` + `sidebarWorkspaceFallbackItems`)、`:964`(`onSidebarCodingSelect`)、`:1008-1052`(`onSidebarCodingDelete`)
- Verify: 手动 + 浏览器

- [ ] **Step 1: 读现状**。读 `CodingPage.vue:854-895`(双轨合并去重 `conv:`/`ws:`)、select(`:964`)、delete(`:1008`)。

- [ ] **Step 2: 改 sidebar 数据源**。`sidebarCodingItems` 只由会话列表生成(去掉 `sidebarWorkspaceFallbackItems` 这条孤儿 workspace 来源);item id 统一 `conv:<id>`,去掉 `ws:` 分支。

- [ ] **Step 3: 改 select**。`onSidebarCodingSelect` 只处理会话:有 `workspace_id` 走 `openWorkspaceById`,无则 `loadCodingConversationOnly`(去掉 ws-only 分支)。

- [ ] **Step 4: 改 delete**。统一调 `codingApi.deleteConversation(id)`(我们已加),去掉 ws-only 删除分支。

- [ ] **Step 5: 编译校验**。`cd frontend && node -e '...@vue/compiler-sfc parse CodingPage.vue...'`(参照本会话用过的 SFC 校验)预期模板 OK;`npx vue-tsc --noEmit -p tsconfig.app.json 2>&1 | grep CodingPage` 预期无新错。

- [ ] **Step 6: 手动验**。刷新 → AI Coding 侧栏只剩会话项、无游离 workspace;选择/删除正常。

- [ ] **Step 7: Commit**。`git commit -m "refactor(coding): 侧栏只列会话,消灭 conv/ws 双轨"`

---

## Task F2: 结构化工具卡渲染 + 删除 emoji 正则反解

**Files:**
- Modify: `frontend/src/views/coding/useCodingPipeline.ts`(消费 B4 的结构化 tool 事件)
- Modify: `frontend/src/components/common/AgentConversation.vue`(渲染工具卡,复用 Builder 风格)
- Modify: `frontend/src/views/CodingPage.vue:1327`(删 `parseAssistantHistory`)、`:1268-1326`(历史改结构化 replay)

- [ ] **Step 1: 读现状**。读 Builder 侧工具卡渲染(`AIChatPage.vue:561-648` summarizeToolResult / chip)+ `AgentConversation.vue` 现有渲染 + `useCodingPipeline.ts` 事件 dispatch + `CodingPage.vue` 历史加载。

- [ ] **Step 2: 消费结构化事件**。`useCodingPipeline.ts` 把 B4 的 `tool` 事件映射成 stream message 的结构化卡片项(action/status/target/summary/output)。

- [ ] **Step 3: 渲染工具卡**。`AgentConversation.vue` 增加工具卡渲染分支(「正在读 X / 已写 Y(+N 行)/ 跑了 Z」+ 状态点 + output 折叠),与 Builder 视觉一致。

- [ ] **Step 4: 删正则反解**。删 `CodingPage.vue:parseAssistantHistory`(`:1327`);历史加载改为按结构化 `stream_messages` replay;无结构化数据的旧会话降级为纯文本展示(不报错)。

- [ ] **Step 5: 编译校验**(同 F1 Step 5,覆盖三文件)。

- [ ] **Step 6: 手动验**。新会话开发时工具卡实时可见(看得出 read/write/run + 状态);旧会话历史能 replay 不报错。

- [ ] **Step 7: Commit**。`git commit -m "feat(coding): 结构化工具卡渲染,删除 emoji 正则反解历史"`

---

## Task F3: Builder→Coding handoff 修复(字段对齐 + 上下文 + 回跳)

**Files:**
- Modify: `frontend/src/views/ChatPage.vue:2319-2355`(生产端 payload)、`:2295`(buildCodingRouteQuery)
- Modify: `frontend/src/views/CodingPage.vue:1147-1181`(消费端 `maybeConsumeAiBuilderDispatch`)
- Modify: `backend/app/routes/coding.py`(会话记录来源 `app_id`,如需)

- [ ] **Step 1: 读现状**。生产端写 `{message, app_id, app_name}`(`ChatPage.vue:2350`)+ route query 带 `project_id`;消费端按 `{message, projectId, sceneCategory}` 读(`CodingPage.vue:1155`)→ 字段对不上(spec §4.3)。

- [ ] **Step 2: 对齐字段**。消费端 payload 类型改为 `{ message?, app_id?, app_name? }`;`project_id` 从 `route.query.project_id` 取;`coding_last_project_id` 用它来设;`message` 注入逻辑保留。

- [ ] **Step 3: 带上下文 + 归属**。新建 Coding 会话时把 `app_id`/`app_name` 存进会话(后端 `coding.py` 接受可选 `app_id`),并把应用上下文作为种子;UI 顶部显示「为应用《X》自开发」+「← 回 Builder 配置」链(跳回 `/chat?app_id=X`)。

- [ ] **Step 4: 编译校验**(覆盖 ChatPage + CodingPage)。

- [ ] **Step 5: 端到端验**。在 Builder(`/chat?app_id=N`)点进 Coding → 会话带应用上下文、`project_id` 正确、能点「← 回 Builder」跳回。

- [ ] **Step 6: Commit**。`git commit -m "fix(coding): 修 Builder→Coding handoff 字段不一致,带应用上下文+回跳链"`

---

## 验收(Phase 1 完成判据)
1. AI Coding 侧栏只列会话、无游离 workspace;删会话连带清 workspace。
2. 开发时工具卡实时可见(看得出 read/write/run + 状态);历史 replay 不靠正则、不报错。
3. 首条消息直接开发,无强制二段确认。
4. 从 Builder 一键进 Coding:带应用上下文 + 能回跳;字段不再丢。
5. 迁移脚本幂等、无数据丢失。
6. 全程不碰 `mcp-server/`;`vue-tsc`/SFC 校验无新错。
