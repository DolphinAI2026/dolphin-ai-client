# 统一智能体引擎 — Phase 1':退役 coding 流水线,Code 改由 run_agent 驱动

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development 或 superpowers:executing-plans 逐任务实施。步骤用 `- [ ]`。

**Goal:** 让 Code 模式的二次开发改由已好用的 `run_agent` 驱动,退役烂的 coding 流水线;保留整套 Codex 工作区 UI(文件树/diff/终端/预览)。用户即刻在 Code 与 Builder 两侧都获得好 agent。

**Architecture:** 单一改动点 = `CodingProfile.run_turn`(harness/profiles/coding.py)。它当前是唯一调用 `run_coding_entry` 的地方。改成驱动 `run_agent`(ai_chat/agent.py),把 run_agent 的 SSE 事件**映射**回 Code UI 认的 `coding.*` 事件,并把 Code 会话既有的 `ws_id`/`app_id` 绑给 run_agent。工作区/面板/路由壳/run-survival 全部不动。

**Tech Stack:** Python 3.13, pytest;`run_agent`(ai_chat)、`HarnessManager`/EventBus、`WorkspaceManager`、`tool_registry`。

## Global Constraints

- **不碰** `routes/coding.py` 的工作区/面板端点(files/file/changes/file-diff/pty/serve)与 `routes/harness.py` 的路由壳(/pipeline /attach /stop /run-status)。
- **不碰** `WorkspaceManager`、`git_changes`。
- run_agent 写盘必须命中 Code 会话**既有 ws_id**(同 ws_id=同文件),不得新建另一个工作区。
- 退役前先迁移 `pipeline.py` 里被外部 import 的共享 helper(至少 `get_conversation_history`,被 `read_query.py:825` 用)。
- cutover 期间用 **feature flag** 让新旧路径可切换 A/B,验证通过再删旧码。
- 前端零改动即可工作(panels 自重读磁盘);`coding.*` 内联卡片(红绿 diff / preview 卡)是增强项,缺失不阻塞。
- TDD;每 Task 独立可测、独立提交、只 add 本 Task 文件。venv:`backend/.venv/bin/python`。

## 关键设计决策(cutover 前确认)

**会话模型**:run_agent 围绕 `AIChatSession`+`AIChatMessage` 写;Code 走 coding `Conversation`+`Message`。两种 cutover 路线:
- **(i) 轻适配(推荐起步)**:run_turn 内把 coding 会话上下文(history + 既有 ws_id + app_id)组装成 run_agent 需要的输入,run_agent 的消息持久化沿用其 ai_chat 落库;Code 侧只消费映射后的 SSE,会话列表后续统一。
- **(ii) 泛化 run_agent**:把 run_agent 的 session 依赖抽象成接口,兼容 coding Conversation。改动更大,留到 Phase 2 收编时一并做。

本计划按 (i) 起步、flag 兜底;(ii) 归入 Phase 2。

---

### Task 1: run_agent→coding UI 事件映射(纯函数,加法)

把 run_agent 的 ai-chat 事件翻成 Code UI(useCodingPipeline)认的 `coding.*` 事件。纯函数,先独立 TDD,后被新 run_turn 复用。

**Files:**
- Create: `backend/app/harness/profiles/runagent_event_map.py`
- Test: `backend/tests/test_runagent_event_map.py`

**Interfaces:**
- Produces: `map_runagent_event(event: str, data: dict) -> list[dict]`。输入 = run_agent 的 `(event, data)`(data 已解析为 dict);输出 = 0~N 条 `{"type": <coding事件>, ...}`,直接喂给现有 EventBus/SSE。
- 工具名映射 `TOOL_NAME_TO_CODING`:`write_workspace_files→write_file`、`edit_workspace_files→edit_file`、`read_workspace_file→read_file`、`glob_workspace→glob_files`、`grep_workspace→grep_search`、`run_workspace_command→run_command`。

映射规则(基于 spike 的两套事件清单):
- `assistant_delta {text}` → `[{"type":"agent_thinking_delta","text":text}]`
- `assistant_message {content,...}` → `[{"type":"content","content":content}]`
- `tool_call_start {id,tool_name,args}` → `[{"type":"agent_tool","action":TOOL_NAME_TO_CODING.get(tool_name,tool_name),"id":id,"args":args,"status":"running"}]`
- `tool_call_end {id,tool_name,status,result_text}` → `[{"type":"agent_result","id":id,"action":TOOL_NAME_TO_CODING.get(tool_name,tool_name),"status":status,"result":result_text}]`
- `ask_user {tool_call_id,question,options}` → `[{"type":"clarify","question":question,"options":options}]`
- `done {ok,...}` → `[{"type":"agent_done"},{"type":"done","ok":ok}]`(workspace_id 由 run_turn 补,见 Task 3)
- `error {error}` → `[{"type":"error","error":error}]`
- `thinking/run_started/tool_call_delta/assistant_thinking_lock/artifact_created` → `[]`(Code UI 无对应卡;artifact 由面板自重读覆盖)

- [ ] **Step 1: 写失败测试**

```python
# backend/tests/test_runagent_event_map.py
from app.harness.profiles.runagent_event_map import map_runagent_event


def test_write_tool_maps_to_coding_write_file_chip():
    out = map_runagent_event("tool_call_start",
        {"id": 7, "tool_name": "write_workspace_files", "args": {"files": []}})
    assert out == [{"type": "agent_tool", "action": "write_file", "id": 7,
                    "args": {"files": []}, "status": "running"}]


def test_tool_end_maps_to_agent_result_with_name_translation():
    out = map_runagent_event("tool_call_end",
        {"id": 7, "tool_name": "edit_workspace_files", "status": "success", "result_text": "ok"})
    assert out == [{"type": "agent_result", "id": 7, "action": "edit_file",
                    "status": "success", "result": "ok"}]


def test_assistant_delta_and_message():
    assert map_runagent_event("assistant_delta", {"text": "hi"}) == \
        [{"type": "agent_thinking_delta", "text": "hi"}]
    assert map_runagent_event("assistant_message", {"content": "done"}) == \
        [{"type": "content", "content": "done"}]


def test_ask_user_maps_to_clarify():
    out = map_runagent_event("ask_user", {"tool_call_id": 3, "question": "哪个端?", "options": ["A", "B"]})
    assert out == [{"type": "clarify", "question": "哪个端?", "options": ["A", "B"]}]


def test_done_and_error():
    assert map_runagent_event("done", {"ok": True}) == \
        [{"type": "agent_done"}, {"type": "done", "ok": True}]
    assert map_runagent_event("error", {"error": "boom"}) == [{"type": "error", "error": "boom"}]


def test_noise_events_drop_to_empty():
    for ev in ("thinking", "run_started", "tool_call_delta", "assistant_thinking_lock", "artifact_created"):
        assert map_runagent_event(ev, {}) == []
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && .venv/bin/python -m pytest tests/test_runagent_event_map.py -q`
Expected: FAIL（module 不存在)

- [ ] **Step 3: 写实现**

```python
# backend/app/harness/profiles/runagent_event_map.py
"""run_agent(ai-chat) 事件 → Code UI(useCodingPipeline)认的 coding.* 事件。

Phase 1':Code 改由 run_agent 驱动,但前端仍消费 coding.* 事件词汇,
这里做一层翻译,保证前端零改动。见
docs/superpowers/plans/2026-06-24-unified-agent-engine-phase1-retire-coding-pipeline.md
"""
from __future__ import annotations

TOOL_NAME_TO_CODING = {
    "write_workspace_files": "write_file",
    "edit_workspace_files": "edit_file",
    "read_workspace_file": "read_file",
    "glob_workspace": "glob_files",
    "grep_workspace": "grep_search",
    "run_workspace_command": "run_command",
}

_NOISE = {"thinking", "run_started", "tool_call_delta",
          "assistant_thinking_lock", "artifact_created"}


def map_runagent_event(event: str, data: dict) -> list[dict]:
    """把单个 run_agent 事件翻成 0~N 条 Code UI 事件。"""
    if event in _NOISE:
        return []
    if event == "assistant_delta":
        return [{"type": "agent_thinking_delta", "text": data.get("text", "")}]
    if event == "assistant_message":
        return [{"type": "content", "content": data.get("content", "")}]
    if event == "tool_call_start":
        name = data.get("tool_name", "")
        return [{
            "type": "agent_tool",
            "action": TOOL_NAME_TO_CODING.get(name, name),
            "id": data.get("id"),
            "args": data.get("args"),
            "status": "running",
        }]
    if event == "tool_call_end":
        name = data.get("tool_name", "")
        return [{
            "type": "agent_result",
            "id": data.get("id"),
            "action": TOOL_NAME_TO_CODING.get(name, name),
            "status": data.get("status"),
            "result": data.get("result_text"),
        }]
    if event == "ask_user":
        return [{
            "type": "clarify",
            "question": data.get("question"),
            "options": data.get("options"),
        }]
    if event == "done":
        return [{"type": "agent_done"}, {"type": "done", "ok": data.get("ok", True)}]
    if event == "error":
        return [{"type": "error", "error": data.get("error", "")}]
    return []
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd backend && .venv/bin/python -m pytest tests/test_runagent_event_map.py -q`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add backend/app/harness/profiles/runagent_event_map.py backend/tests/test_runagent_event_map.py
git commit -m "feat(harness): run_agent→coding UI 事件映射(Phase 1' cutover 地基)"
```

---

### Task 2: 迁出 pipeline.py 的共享 helper

`read_query.py:825` 从 `pipeline.py` import `get_conversation_history`。退役 pipeline 前,把这类纯 helper 搬到中立模块,避免删 agent 时连带删掉被复用的 helper。

**Files:**
- Create: `backend/app/coding/conversation_history.py`(放 `get_conversation_history` + 相关纯 helper)
- Modify: `backend/app/coding/pipeline.py`(改为从新模块 re-export,保持旧 import 不破)
- Modify: `backend/app/coding/read_query.py`(import 改指向新模块)
- Test: `backend/tests/test_conversation_history_move.py`

**Interfaces:**
- Produces: `app.coding.conversation_history.get_conversation_history(db, conversation_id) -> list[dict]`(签名与现状一致)。
- `pipeline.py` 顶部 `from app.coding.conversation_history import get_conversation_history`(re-export,旧调用方不破)。

- [ ] **Step 1:** 先 `grep -rn "from app.coding.pipeline import" backend` 列全所有从 pipeline 导出的符号,确认要迁的 helper 清单(至少 get_conversation_history;若 read_query 还用了别的也一并迁)。
- [ ] **Step 2:** 写测试:`from app.coding.conversation_history import get_conversation_history` 可用;且 `from app.coding.pipeline import get_conversation_history` 仍可用(re-export 不破)。
- [ ] **Step 3:** 跑测试确认失败(新模块不存在)。
- [ ] **Step 4:** 建新模块、移动函数体、pipeline.py 改 re-export、read_query.py 改 import。
- [ ] **Step 5:** 跑 `pytest -k "read_query or conversation_history or coding_intent"` 确认绿;提交。

---

### Task 3: run_turn cutover(风险最高,flag 兜底)

把 `CodingProfile.run_turn` 改成:绑既有 ws_id/app_id → 驱动 run_agent → 经 Task 1 映射喂 EventBus,`done` 事件补回 `workspace_id`。用 env/flag `CODING_USE_RUNAGENT` 控新旧,默认旧(验证后翻默认)。

**Files:**
- Modify: `backend/app/harness/profiles/coding.py`(run_turn 增 run_agent 分支)
- Test: `backend/tests/test_coding_profile_runagent_cutover.py`

**Interfaces:**
- Consumes: `run_agent`(或其内层)、`map_runagent_event`(Task 1)、既有 EventBus 推送 API。
- 绑定:run_turn 必须把 Code 会话既有 `ws_id` 传进 run_agent 的工作区上下文(令 `write_workspace_files` 命中既有工作区),`app_id` 注入(令读 MCP 锁定应用)。

- [ ] **Step 1:** 写测试:flag 开时 run_turn 调用 run_agent(mock)、不调 run_coding_entry;run_agent 产 `tool_call_start(write_workspace_files)` → EventBus 收到 `agent_tool action=write_file`;`done` 带 `workspace_id`。
- [ ] **Step 2:** 跑测试确认失败。
- [ ] **Step 3:** 实现 run_agent 分支(组装 session 上下文走决策 (i);映射;补 workspace_id)。
- [ ] **Step 4:** 跑测试绿 + 全套 harness/coding 回归不退化。
- [ ] **Step 5:** 提交(flag 默认关)。

---

### Task 4: 带回 autofix / 脚手架 / 契约(Phase 1' 收益项)

run_agent 路径补上 coding 的确定性价值:① 新建工作区走 `create_dev_workspace`(脚手架);② run 后跑 autofix 自愈环(build→抓错→回灌修);③ finalize 跑 workspace 契约校验。各自独立 Task,可在 Task 3 cutover 验证通过后并行做(三件互不依赖)。

- [ ] 4a 脚手架:Code 首轮无 ws 时,run_turn 先建脚手架工作区再交 run_agent。
- [ ] 4b autofix:把 `drive_coding_with_autofix` 包到 run_agent 路径外层(out-loop),复用现有 signals。
- [ ] 4c 契约:finalize 调 workspace 契约校验,产物不合格 emit 失败。

---

### Task 5: 验证 + 翻默认 + 退役旧码

- [ ] 真机/web 验证:Builder 链路不退化;Code 链路改由 run_agent 驱动,面板(树/diff/终端/预览)照常,写代码可用。
- [ ] flag 默认翻成 run_agent。
- [ ] 删 `run_coding_entry`/`run_coding_pipeline`/CodingGenerator + 闸门(classify_*intent / detect_scene 门 / brainstorm 状态机)+ read_query 旧循环(确认 helper 已迁)。
- [ ] 回归全绿;提交。

---

## Self-Review

- **Spec coverage**:覆盖 spec §8 Phase 1+2 的「Code 退役 + 走 run_agent + 带回确定性价值」,但按 brainstorm 重排为价值优先(先用 run_agent 解痛,BaseAgent 收编归 Phase 2')。
- **Placeholder 扫描**:Task 1 完整代码;Task 2/3/4/5 为 cutover/退役类,步骤具体到文件与验证命令,cutover 细节(session 组装)依赖「关键设计决策」(i),已写明,非含糊 TODO。
- **风险**:Task 3 是 load-bearing cutover → flag 兜底 + A/B + 回归;Task 5 删码前必须确认 helper 已迁(Task 2)。
- **类型一致**:`map_runagent_event(event,data)->list[dict]` 全程一致;工具名映射表单一来源。
