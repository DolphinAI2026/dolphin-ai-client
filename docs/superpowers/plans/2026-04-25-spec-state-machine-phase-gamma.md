# SPEC State Machine — Phase γ (Entry Migrations) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task.

**Goal:** Migrate the remaining 4 application-config entry points (document upload ≥60, document upload <60, deployed-app chat-incremental, deployed-app doc V1→V2) to use the SPEC state machine as the canonical path. Entry 4 (platform import) intentionally stays on the legacy path per design spec.

**Architecture:** Add `SpecAgent.bootstrap_from_doc()` method with three modes (silent / non-silent / diff-only). Route `/api/chat/send-with-file` and `/api/incremental_update/*` through it when conversation has `spec_id`. Old paths kept as fallback for `spec_id IS NULL` conversations (no behavior change for legacy data).

**Tech Stack:** Python 3.11, FastAPI, SQLAlchemy async, Pydantic v2 (already in project), pytest (introduced in α Task 1).

**Reference**:
- Design spec: [docs/superpowers/specs/2026-04-25-spec-state-machine-design.md](../specs/2026-04-25-spec-state-machine-design.md) section 7 (5 入口迁移路径)
- Phase α PLAN: [2026-04-25-spec-state-machine-phase-alpha.md](2026-04-25-spec-state-machine-phase-alpha.md)
- Phase β PLAN: [2026-04-25-spec-state-machine-phase-beta.md](2026-04-25-spec-state-machine-phase-beta.md)

**Phase γ scope**: backend feature work (4-5 tasks), no frontend redesign. UI surfaces from β (PhaseBar / SpecCanvas / SpecInspector) automatically reflect the new spec state once γ wires data in.

**Estimated effort:** 3-4 working days, 5 tasks.

---

## Prerequisites

- Phase α merged (commits `2b5d209` → `e8e0fa1` on `claude/coding-shell-alignment`)
- Phase β merged (commits `af6158e` → `64be645`)
- 34 backend tests passing
- MySQL has `applications.canonical_spec_id` + `conversations.spec_id` + `specs` table
- Existing `bootstrap_from_doc` doesn't exist yet — Phase α SpecAgent only has `run()` for chat conversations

---

## File Map

| Path | Action | Responsibility |
|---|---|---|
| `backend/app/spec/agent.py` | Modify | Add `bootstrap_from_doc()` method (silent / non-silent / diff-only) |
| `backend/tests/test_spec_agent.py` | Modify | Add 3 test cases for the 3 bootstrap modes |
| `backend/app/spec/extractor.py` | Create | Doc-text → SPEC seed extractor (uses LLM with structured-output prompt; reuses tool dispatch) |
| `backend/tests/test_spec_extractor.py` | Create | Unit tests for the extractor |
| `backend/app/routes/chat.py` | Modify | `/send-with-file` route adds γ branch when `conversation.spec_id IS NOT NULL` |
| `backend/app/routes/incremental_update.py` | Modify | `compute_diff` / `execute_update_stream` add γ branch when target app has `canonical_spec_id` |
| `backend/tests/test_spec_e2e_doc.sh` | Create | Live smoke for doc upload through SpecAgent |

---

## Conventions

Same as Phase α / β:
- TDD where reasonable (extractor + agent unit tests yes; route integration tests via existing fixtures)
- One commit per task with conventional `feat(spec)` / `feat(chat)` prefix + Co-Authored-By
- All commits on `claude/coding-shell-alignment` branch
- Backend run via venv: `cd backend && source venv/bin/activate`

---

## Task 1: SpecAgent.bootstrap_from_doc — silent mode

**Files:**
- Modify: `backend/app/spec/agent.py` — add new method
- Modify: `backend/tests/test_spec_agent.py` — add silent mode test

**Goal:** Given a complete document (≥60 standard score), feed it to the LLM with a single-shot system prompt that produces a fully populated SPEC (all items `confirmed=true`), then transition straight to `Phase.READY`.

- [ ] **Step 1.1: Write failing test**

Add to `backend/tests/test_spec_agent.py`:

```python
@pytest.mark.asyncio
async def test_bootstrap_from_doc_silent_produces_ready_spec():
    """Silent bootstrap: complete doc → fully populated SPEC, all confirmed=true, phase=ready."""
    spec = empty_spec(created_by=1)
    doc_text = """# 预算管理系统

## 角色
- 财务负责人 (finance_lead): 全部数据
- 销售总监 (sales_director): 本部门数据

## 数据对象
### 季度预测 (t_quarter_forecast)
- 预测编号 (forecast_no): 单据号 必填
- 金额 (amount): 数字 必填
- 状态 (status): 下拉单选 → forecast_status

## 字典
- 预测状态 (forecast_status): 草稿/已确认/已审批

## 权限
- t_quarter_forecast: finance_lead 全操作 ALL；sales_director 编辑 DEPT
"""

    # LLM responds with a single shot: 1 set_goal + 2 add_role + 1 add_object (with fields) +
    # 1 add_dict + 1 add_permission + 5 confirm_* + 1 transition_phase("ready")
    turn1_chunks = [
        _tool_call_chunk(0, "c0", "set_goal", json.dumps({
            "title": "预算管理系统", "summary": "季度预测", "business_problem": "对齐财务"
        })),
        _tool_call_chunk(1, "c1", "add_role", json.dumps({
            "code": "finance_lead", "name": "财务负责人", "scope": "ALL",
        })),
        _tool_call_chunk(2, "c2", "add_role", json.dumps({
            "code": "sales_director", "name": "销售总监", "scope": "DEPT",
        })),
        _tool_call_chunk(3, "c3", "add_object", json.dumps({
            "code": "t_quarter_forecast", "name": "季度预测",
            "fields": [
                {"code": "forecast_no", "name": "预测编号", "type": "单据号", "required": True},
                {"code": "amount", "name": "金额", "type": "数字", "required": True},
                {"code": "status", "name": "状态", "type": "下拉单选", "dict_code": "forecast_status"},
            ],
        })),
        _tool_call_chunk(4, "c4", "add_dict", json.dumps({
            "code": "forecast_status", "name": "预测状态",
            "options": [
                {"code": "draft", "name": "草稿"},
                {"code": "confirmed", "name": "已确认"},
                {"code": "approved", "name": "已审批"},
            ],
        })),
        _tool_call_chunk(5, "c5", "add_permission", json.dumps({
            "object_code": "t_quarter_forecast",
            "rules": [
                {"role": "finance_lead", "op": "all", "data": "ALL"},
                {"role": "sales_director", "op": "edit", "data": "DEPT"},
            ],
        })),
    ]
    # Second turn: confirm everything + transition_phase
    turn2_chunks = [
        _tool_call_chunk(0, "c10", "confirm_role", json.dumps({"code": "finance_lead"})),
        _tool_call_chunk(1, "c11", "confirm_role", json.dumps({"code": "sales_director"})),
        _tool_call_chunk(2, "c12", "confirm_object", json.dumps({"code": "t_quarter_forecast"})),
        _tool_call_chunk(3, "c13", "confirm_dict", json.dumps({"code": "forecast_status"})),
        _tool_call_chunk(4, "c14", "confirm_permission", json.dumps({"object_code": "t_quarter_forecast"})),
        _tool_call_chunk(5, "c15", "transition_phase", json.dumps({"target": "ready", "reason": "doc bootstrap"})),
    ]
    turn3_chunks = [_content_chunk("已完成"), _empty_finish_chunk()]

    agent = SpecAgent(llm_base_url="http://fake", llm_api_key="fake", llm_model="fake-model")
    with patch("app.spec.agent._open_stream", side_effect=[
        FakeLLMStream(turn1_chunks), FakeLLMStream(turn2_chunks), FakeLLMStream(turn3_chunks)
    ]):
        events = []
        async for ev in agent.bootstrap_from_doc(spec, doc_text=doc_text, silent=True):
            events.append(ev)

    final = next(e.spec for e in reversed(events) if e.kind == "final")
    assert final.phase == Phase.READY
    assert final.goal is not None and final.goal.confirmed is True
    assert len(final.roles) == 2 and all(r.confirmed for r in final.roles)
    assert len(final.objects) == 1 and final.objects[0].confirmed
    assert len(final.dicts) == 1 and final.dicts[0].confirmed
    assert len(final.permissions) == 1 and final.permissions[0].confirmed
```

- [ ] **Step 1.2: Run test, expect FAIL** (`bootstrap_from_doc` doesn't exist):
```bash
cd backend && pytest tests/test_spec_agent.py::test_bootstrap_from_doc_silent_produces_ready_spec -v
```

- [ ] **Step 1.3: Implement `bootstrap_from_doc()` in `agent.py`**

Add new method to `SpecAgent` class (in `backend/app/spec/agent.py`):

```python
SPEC_BOOTSTRAP_SILENT_PROMPT = """你正在从一份完整的需求文档自动初始化 SPEC。
文档已经过用户预审，将其完整内容当成"用户确认过的事实"对待，不需要再问澄清问题。

【你的任务】
1. 阅读文档，识别业务目标、角色、数据对象（含字段）、字典、权限规则。
2. 用 set_goal / add_role / add_object / add_dict / add_permission 一次性写入 SPEC（confirmed=false）。
3. 写完后用 confirm_* 把所有项目标记为 confirmed=true（用户已认可文档内容）。
4. 调 transition_phase("ready") 完成 bootstrap。
5. 不要 ask_clarifying_question，文档已经覆盖一切。

【纪律】
- 字段类型用中文（"单行输入"/"数字"/"下拉单选"/"单据号"等）。
- code 全部 snake_case，object code 加 t_ 前缀。
- 权限：每个 object 至少一条 role="all" 或具体角色规则。
- 不要在对话文本里复述文档内容（用 tool 而不是文本）。

文档：
---
{doc_text}
---
"""


SPEC_BOOTSTRAP_INTERACTIVE_PROMPT = """你正在从一份初稿文档预填 SPEC，但文档不够规范，需要用户审核。

【流程】
1. 用 add_*/set_goal 把文档里识别出的元素写入 SPEC（confirmed=false，让用户在 UI 审）。
2. 对文档里语义模糊或缺失的字段，用 ask_clarifying_question 标记。
3. 写完进入 drafting phase: transition_phase("drafting")。
4. 不要主动 confirm_*。

文档：
---
{doc_text}
---
"""


SPEC_BOOTSTRAP_DIFF_PROMPT = """你正在基于已存在的 SPEC 应用文档增量。

当前 SPEC：
{spec_summary}

新文档（V2）：
---
{doc_text}
---

【任务】
1. 找出 V2 相对于现有 SPEC 的差异（新增/修改/删除）。
2. 用 add_*/update_*/dismiss_* 应用差异，confirmed=false 让用户审。
3. 进入 drafting phase: transition_phase("drafting")。
4. 不要 confirm_*；不要复述已有 SPEC 的不变项。

【字段语义】
- code 不变 → 视作"修改"，用 update_*
- code 不存在了 → 视作"删除"，用 dismiss_*
- 新 code 出现 → 视作"新增"，用 add_*
"""


class SpecAgent:
    # ... existing __init__ and run() unchanged ...

    async def bootstrap_from_doc(
        self,
        spec: Spec,
        doc_text: str,
        *,
        silent: bool = False,
        diff_only: bool = False,
    ) -> AsyncIterator[SpecAgentEvent]:
        """Drive the LLM to populate (or diff-update) a SPEC from a document.

        Modes:
        - silent=True: doc is authoritative; LLM auto-confirms + jumps to Phase.READY
        - silent=False, diff_only=False: doc is a draft; LLM populates with confirmed=false, transitions to drafting
        - diff_only=True: doc is a V2 increment; LLM applies diff against existing spec, transitions to drafting
        """
        if diff_only:
            system_prompt = SPEC_BOOTSTRAP_DIFF_PROMPT.format(
                spec_summary=_summarize_spec(spec),
                doc_text=doc_text,
            )
        elif silent:
            system_prompt = SPEC_BOOTSTRAP_SILENT_PROMPT.format(doc_text=doc_text)
        else:
            system_prompt = SPEC_BOOTSTRAP_INTERACTIVE_PROMPT.format(doc_text=doc_text)

        user_msg = "请按上述指令处理文档。" if not diff_only else "请应用 V2 文档的差异。"
        messages: list[dict] = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_msg},
        ]

        async with httpx.AsyncClient(
            timeout=httpx.Timeout(connect=10, read=300, write=10, pool=10)
        ) as client:
            for turn in range(self.max_turns):
                payload = {
                    "model": self.model, "messages": messages,
                    "tools": TOOL_DEFINITIONS, "max_tokens": 4096,
                    "temperature": 0.2, "stream": True,
                }
                full_content = ""
                tool_calls_map: dict = {}

                stream = _open_stream(client, self.base_url, self.api_key, payload)
                async for line in stream:
                    if not line.startswith("data: "):
                        continue
                    data_str = line[6:]
                    if data_str.strip() == "[DONE]":
                        break
                    try:
                        chunk = json.loads(data_str)
                    except json.JSONDecodeError:
                        continue
                    choices = chunk.get("choices") or []
                    if not choices:
                        continue
                    delta = choices[0].get("delta", {})
                    if delta.get("content"):
                        full_content += delta["content"]
                        yield SpecAgentEvent(kind="assistant_delta", spec=spec, text=delta["content"])
                    if delta.get("tool_calls"):
                        for tc in delta["tool_calls"]:
                            idx = tc.get("index", 0)
                            entry = tool_calls_map.setdefault(idx, {"id": "", "name": "", "arguments": ""})
                            if tc.get("id"):
                                entry["id"] = tc["id"]
                            func = tc.get("function", {})
                            if func.get("name"):
                                entry["name"] = func["name"]
                            if func.get("arguments"):
                                entry["arguments"] += func["arguments"]

                assistant_msg: dict = {"role": "assistant", "content": full_content or None}
                assembled: list[dict] = []
                for idx in sorted(tool_calls_map.keys()):
                    entry = tool_calls_map[idx]
                    if not entry["name"]:
                        continue
                    raw = entry["arguments"] or "{}"
                    try:
                        json.loads(raw)
                        valid_args = raw
                    except json.JSONDecodeError:
                        valid_args = "{}"
                    assembled.append({
                        "id": entry["id"] or f"call_{turn}_{idx}",
                        "type": "function",
                        "function": {"name": entry["name"], "arguments": valid_args},
                    })
                if assembled:
                    assistant_msg["tool_calls"] = assembled
                messages.append(assistant_msg)

                if not assembled:
                    yield SpecAgentEvent(kind="final", spec=spec, text=full_content)
                    return

                # bootstrap_from_doc: NEVER enforce_first_turn (doc IS the answer)
                for tc in assembled:
                    name = tc["function"]["name"]
                    args = json.loads(tc["function"]["arguments"] or "{}")
                    yield SpecAgentEvent(kind="tool_call", spec=spec, tool_name=name, tool_args=args)
                    try:
                        spec = dispatch_tool(spec, name, args, enforce_first_turn=False)
                        result_str = "ok"
                        yield SpecAgentEvent(kind="spec_patch", spec=spec, tool_name=name)
                    except ToolError as e:
                        result_str = f"Error: {e}"
                        yield SpecAgentEvent(kind="tool_error", spec=spec, tool_name=name, message=str(e))
                    messages.append({
                        "role": "tool", "tool_call_id": tc["id"], "content": result_str,
                    })

            yield SpecAgentEvent(kind="final", spec=spec, text=full_content)
```

- [ ] **Step 1.4: Run test, expect PASS**:
```bash
cd backend && pytest tests/test_spec_agent.py -v 2>&1 | tail -10
```
Expected: 3 passed (2 existing + 1 new).

- [ ] **Step 1.5: Commit**:
```bash
cd "/Users/mars/Vibe Coding/apaas-builder-ai" && git add backend/app/spec/agent.py backend/tests/test_spec_agent.py && git commit -m "$(cat <<'EOF'
feat(spec): SpecAgent.bootstrap_from_doc 三模式

silent=True: 完整文档 → SPEC ready（全 confirmed=true）
silent=False: 初稿文档 → SPEC drafting（confirmed=false 让用户审）
diff_only=True: V2 增量 → 在现有 SPEC 上应用 diff（drafting）

bootstrap 路径不强制 first-turn enforcement——文档本身就是用户的答案。

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: Wire `/send-with-file` to bootstrap_from_doc

**Files:**
- Modify: `backend/app/routes/chat.py` (around lines 786-949 where `route_to_pipeline` and `doc_silent_generator` live)

**Goal:** When the conversation has `spec_id IS NOT NULL`, route document uploads through `SpecAgent.bootstrap_from_doc()` instead of `doc_pipeline` / `doc_silent_generator`. Existing routes without `spec_id` keep the legacy paths.

- [ ] **Step 2.1: Locate insertion points**

Read `backend/app/routes/chat.py` around line 786 (the `if route_to_pipeline:` branch) and line 870 (the `doc_silent_generator` branch). Both come after user message persistence (line 753).

- [ ] **Step 2.2: Insert γ branch BEFORE both legacy branches**

Right after the user-message persistence (around line 757, after the `db.add(Message(...role="user"...))` block), add:

```python
    # ── γ: SpecAgent bootstrap branch ──
    if conversation.spec_id and file_content:
        spec = await load_spec(db, conversation.spec_id, tenant_id=ctx.tenant_id)
        if spec is not None:
            llm_cfg = await _get_conversation_llm_config(db, conversation)
            if llm_cfg is None:
                raise HTTPException(503, detail="LLM 配置不可用")
            agent = SpecAgent(
                llm_base_url=llm_cfg["base_url"],
                llm_api_key=llm_cfg["api_key"],
                llm_model=llm_cfg["model"],
            )
            silent = doc_score >= 60 if 'doc_score' in dir() else False
            # If spec already has content (V2 doc upload on existing app), use diff mode
            diff_only = bool(spec.goal or spec.objects)

            async def spec_doc_generator():
                last_text = ""
                try:
                    async for ev in agent.bootstrap_from_doc(
                        spec, doc_text=file_content,
                        silent=silent and not diff_only,
                        diff_only=diff_only,
                    ):
                        if ev.kind == "assistant_delta":
                            last_text += ev.text or ""
                            yield {"event": "message", "data": json.dumps(
                                {"type": "message", "data": ev.text}, ensure_ascii=False)}
                        elif ev.kind == "spec_patch":
                            await save_spec(db, ev.spec, tenant_id=ctx.tenant_id)
                            yield {"event": "spec_patch", "data": json.dumps(
                                {"type": "spec_patch", "data": ev.spec.model_dump(mode="json")},
                                ensure_ascii=False)}
                        elif ev.kind == "tool_error":
                            yield {"event": "tool_error", "data": json.dumps(
                                {"type": "tool_error", "tool": ev.tool_name, "message": ev.message},
                                ensure_ascii=False)}
                        elif ev.kind == "final":
                            final_text = last_text.strip() or f"[已从文档「{file_name}」预填 SPEC]"
                            db.add(Message(
                                conversation_id=conversation.id, role="assistant",
                                content=final_text,
                            ))
                            await db.commit()
                    yield {"event": "done", "data": json.dumps({"type": "done", "data": "completed"})}
                except Exception as e:
                    yield {"event": "error", "data": json.dumps({"type": "error", "data": str(e)})}

            return EventSourceResponse(spec_doc_generator())
        else:
            # Spec was deleted; fall through to legacy
            conversation.spec_id = None
            await db.commit()
```

- [ ] **Step 2.3: Compile check**:
```bash
cd backend && python -c "from app.routes.chat import router; print(len(router.routes), 'routes')"
```
Expected: prints route count, no errors.

- [ ] **Step 2.4: Run regression**:
```bash
cd backend && pytest tests/ -v 2>&1 | tail -5
```
Expected: still 35 passed (Task 1's new test added).

- [ ] **Step 2.5: Commit**:
```bash
cd "/Users/mars/Vibe Coding/apaas-builder-ai" && git add backend/app/routes/chat.py && git commit -m "$(cat <<'EOF'
feat(chat): /send-with-file 接 SpecAgent.bootstrap_from_doc

- conversation.spec_id 存在且文档有效时走新路径
- silent=True 当文档标准度 ≥60 且 SPEC 为空
- diff_only=True 当 SPEC 已有 goal/objects（V2 文档场景）
- 否则非 silent + drafting phase

老路径（spec_id IS NULL）保持不变；spec 被删时优雅 fallback。

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: Migrate `incremental_update` (entry 6 — V1→V2 doc) to SpecAgent

**Files:**
- Modify: `backend/app/routes/incremental_update.py:execute_update_stream` (around line 255)

**Goal:** When the target Application has `canonical_spec_id`, the V1→V2 document update streams through `SpecAgent.bootstrap_from_doc(diff_only=True, base=current_spec)` instead of the legacy text-diff → ChangePlan path.

- [ ] **Step 3.1: Read existing `execute_update_stream`** (~70 lines around line 255-329) to understand its current flow:
```bash
sed -n '255,330p' backend/app/routes/incremental_update.py
```

- [ ] **Step 3.2: Add γ branch at the top of the function** (before legacy ChangePlan logic):

Conceptual structure (adapt based on actual function signature seen in 3.1):
```python
async def execute_update_stream(...):
    # ── γ: SpecAgent diff-only branch ──
    target_app = await db.get(Application, app_id)
    if target_app and target_app.canonical_spec_id:
        spec = await load_spec(db, target_app.canonical_spec_id, tenant_id=ctx.tenant_id)
        if spec is not None and v2_doc_text:
            # ... build agent, run bootstrap_from_doc(spec, v2_doc_text, diff_only=True), stream events ...
            # On final: bump spec.version + save + return EventSourceResponse
            return EventSourceResponse(...)

    # ── legacy ChangePlan path (unchanged) ──
    ...existing code...
```

(Exact edits depend on what you see in Step 3.1; the bones above adapt the same SSE generator pattern from Task 2.)

- [ ] **Step 3.3: Compile check + regression**:
```bash
cd backend && python -c "from app.routes.incremental_update import router; print('ok')" && pytest tests/ -v 2>&1 | tail -5
```

- [ ] **Step 3.4: Commit**:
```bash
cd "/Users/mars/Vibe Coding/apaas-builder-ai" && git add backend/app/routes/incremental_update.py && git commit -m "$(cat <<'EOF'
feat(spec): incremental_update V1→V2 文档走 SpecAgent diff_only

target Application.canonical_spec_id 存在时，V2 文档增量通过 SpecAgent
应用差异（add_/update_/dismiss_），confirmed=false 让用户在 UI 审。

老 ChangePlan 路径保持不变。

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: Legacy upgrade prompt (entry 5 — already-deployed app + chat)

**Files:**
- Modify: `backend/app/routes/applications.py` (or where Application detail is loaded) — add `spec_upgrade_eligible` field

**Goal:** When a user opens an already-deployed app that has `canonical_spec_id IS NULL`, the API surface signals "this app can be upgraded to SPEC mode" so the frontend (Phase β SpecCanvas) can show an upgrade prompt. Actual upgrade logic = call `bootstrap_from_legacy_config(app.config)` which reverse-engineers a SPEC from the existing config — this Task implements that helper.

- [ ] **Step 4.1: Add `bootstrap_from_legacy_config` helper to `backend/app/spec/persistence.py`**:

```python
def bootstrap_from_legacy_config(
    *, application_id: int, legacy_config: dict, created_by: int
) -> Spec:
    """Reverse-engineer a Spec from legacy Application.config (best effort).

    Used to upgrade old apps to SPEC mode. The output Spec has all items
    confirmed=false so the user can review before transitioning to ready.
    """
    from app.spec.schema import Goal, Role, ObjectSpec, FieldSpec, DictSpec, DictOption, PermissionSpec, PermissionRule

    data = legacy_config.get("data", legacy_config)
    spec = empty_spec(created_by=created_by, application_id=application_id)
    spec.phase = Phase.DRAFTING

    if data.get("appName"):
        spec.goal = Goal(
            title=data["appName"], summary="(从已有应用反推)",
            business_problem="(请补充)", confirmed=False,
        )

    for r in data.get("roles", []):
        spec.roles.append(Role(
            code=r["code"], name=r["name"],
            scope=r.get("scope", "ALL"), confirmed=False,
        ))

    for d in data.get("dicts", []):
        spec.dicts.append(DictSpec(
            code=d["code"], name=d["name"],
            options=[DictOption(**o) for o in d.get("options", [])],
            confirmed=False,
        ))

    for m in data.get("models", []):
        fields = []
        for f in m.get("fields", []):
            fields.append(FieldSpec(
                code=f["code"], name=f["name"], type=f.get("type", "单行输入"),
                required=f.get("required", False),
                dict_code=f.get("dict"),
                ref_model=f.get("ref", {}).get("model") if f.get("ref") else None,
                ref_field=f.get("ref", {}).get("field") if f.get("ref") else None,
                confirmed=False,
            ))
        spec.objects.append(ObjectSpec(
            code=m["code"], name=m["name"],
            fields=fields, confirmed=False,
        ))

    for p in data.get("permissions", []):
        spec.permissions.append(PermissionSpec(
            object_code=p["form"],
            rules=[PermissionRule(**r) for r in p.get("rules", [])],
            confirmed=False,
        ))

    spec.completeness = derive_completeness(spec)
    return spec
```

(Imports already at top of `persistence.py`; just add `derive_completeness` if missing.)

- [ ] **Step 4.2: Add unit test**:

`backend/tests/test_spec_persistence.py` (new file):
```python
import pytest
from app.spec.persistence import bootstrap_from_legacy_config
from app.spec.schema import Phase


def test_bootstrap_from_legacy_config_basic():
    cfg = {
        "appName": "ems",
        "roles": [{"code": "approver", "name": "审批人", "scope": "DEPT"}],
        "dicts": [{"code": "ems_status", "name": "报销状态",
                   "options": [{"code": "draft", "name": "草稿"}]}],
        "models": [{"code": "t_ems_form", "name": "报销单", "fields": [
            {"code": "amount", "name": "金额", "type": "数字", "required": True},
            {"code": "status", "name": "状态", "type": "下拉单选", "dict": "ems_status"},
        ]}],
        "permissions": [{"form": "t_ems_form", "rules": [
            {"role": "all", "op": "all", "data": "ALL"},
        ]}],
    }
    spec = bootstrap_from_legacy_config(application_id=99, legacy_config=cfg, created_by=1)

    assert spec.phase == Phase.DRAFTING
    assert spec.application_id == 99
    assert spec.goal.title == "ems"
    assert spec.goal.confirmed is False
    assert len(spec.roles) == 1 and spec.roles[0].code == "approver"
    assert len(spec.dicts) == 1 and len(spec.dicts[0].options) == 1
    assert len(spec.objects) == 1 and len(spec.objects[0].fields) == 2
    field_status = next(f for f in spec.objects[0].fields if f.code == "status")
    assert field_status.dict_code == "ems_status"
    assert len(spec.permissions) == 1
    assert all(not r.confirmed for r in spec.roles)
    assert spec.completeness.total > 0
    assert spec.completeness.confirmed == 0
```

- [ ] **Step 4.3: Add upgrade endpoint to `backend/app/routes/spec.py`**:

```python
class UpgradeFromLegacyRequest(BaseModel):
    application_id: int


@router.post("/upgrade-from-legacy")
async def upgrade_from_legacy_config(
    body: UpgradeFromLegacyRequest,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Reverse-engineer a Spec from an existing Application.config and link it."""
    from app.models import Application
    from app.spec.persistence import bootstrap_from_legacy_config

    app = await db.get(Application, body.application_id)
    if not app or app.tenant_id != ctx.tenant_id:
        raise HTTPException(404, detail="应用不存在")
    if app.canonical_spec_id:
        raise HTTPException(409, detail="应用已升级，请直接编辑")
    if not app.config:
        raise HTTPException(400, detail="应用无 config 可反推")

    legacy = app.config if isinstance(app.config, dict) else {}
    spec = bootstrap_from_legacy_config(
        application_id=app.id, legacy_config=legacy, created_by=ctx.user.id,
    )
    await save_spec(db, spec, tenant_id=ctx.tenant_id)
    app.canonical_spec_id = spec.id
    await db.commit()
    return {"id": spec.id, "phase": spec.phase.value}
```

- [ ] **Step 4.4: Run tests + import check**:
```bash
cd backend && pytest tests/test_spec_persistence.py -v && python -c "from app.routes.spec import router; print(len(router.routes))"
```

- [ ] **Step 4.5: Commit**:
```bash
cd "/Users/mars/Vibe Coding/apaas-builder-ai" && git add backend/app/spec/persistence.py backend/app/routes/spec.py backend/tests/test_spec_persistence.py && git commit -m "$(cat <<'EOF'
feat(spec): bootstrap_from_legacy_config + POST /spec/upgrade-from-legacy

老 application（canonical_spec_id IS NULL）通过 POST /spec/upgrade-from-legacy
反推一份 SPEC：appName→goal、roles/dicts/models/permissions 全部
逐项 confirmed=false 让用户审，phase=drafting。

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: e2e smoke (live LLM, manual gate)

**Files:**
- Create: `backend/tests/smoke_spec_gamma.sh`

**Goal:** End-to-end validation. Requires running backend + valid TOKEN env var.

- [ ] **Step 5.1: Write smoke script**:

`backend/tests/smoke_spec_gamma.sh`:
```bash
#!/bin/bash
# Phase γ end-to-end smoke (manual; needs running backend + TOKEN).
set -eu
TOKEN="${TOKEN:?Must export TOKEN with bearer token.}"
HOST="${HOST:-http://localhost:8000}"

echo "[Step 1] Create empty spec..."
SPEC_ID=$(curl -sS -X POST "$HOST/api/spec" \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" -d '{}' | jq -r '.id')

echo "[Step 2] Create conversation linked to spec..."
CONV_ID=$(curl -sS -X POST "$HOST/api/conversations" \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d "{\"agent_type\":\"requirements\",\"spec_id\":\"$SPEC_ID\"}" | jq -r '.id')

echo "[Step 3] Upload a complete spec doc..."
cat > /tmp/spec_demo.md <<MD
# 预算管理系统

## 角色
- 财务负责人 (finance_lead): 全部数据
- 销售总监 (sales_director): 本部门数据

## 数据对象
### 季度预测 (t_quarter_forecast)
- 预测编号 (forecast_no): 单据号 必填
- 金额 (amount): 数字 必填
- 状态 (status): 下拉单选 → forecast_status

## 字典
- 预测状态 (forecast_status): 草稿/已确认/已审批

## 权限
- t_quarter_forecast: finance_lead 全操作 ALL；sales_director 编辑 DEPT
MD

curl -sS -N -X POST "$HOST/api/chat/send-with-file" \
  -H "Authorization: Bearer $TOKEN" \
  -F "conversation_id=$CONV_ID" \
  -F "message=请基于附件创建" \
  -F "file=@/tmp/spec_demo.md" | tee /tmp/spec_gamma_out.txt

echo "[Step 4] Verify spec was populated..."
SPEC_JSON=$(curl -sS "$HOST/api/spec/$SPEC_ID" -H "Authorization: Bearer $TOKEN")
PHASE=$(echo "$SPEC_JSON" | jq -r '.phase')
ROLE_CT=$(echo "$SPEC_JSON" | jq -r '.roles | length')
OBJ_CT=$(echo "$SPEC_JSON" | jq -r '.objects | length')
DICT_CT=$(echo "$SPEC_JSON" | jq -r '.dicts | length')
echo "  -> phase=$PHASE roles=$ROLE_CT objects=$OBJ_CT dicts=$DICT_CT"

[ "$PHASE" = "ready" ] || [ "$PHASE" = "drafting" ] || { echo "❌ phase invalid"; exit 1; }
[ "$ROLE_CT" -ge 2 ] || { echo "❌ expected ≥2 roles"; exit 1; }
[ "$OBJ_CT" -ge 1 ] || { echo "❌ expected ≥1 object"; exit 1; }
echo "✅ Phase γ smoke PASS"
```

- [ ] **Step 5.2: Make executable + commit**:
```bash
chmod +x backend/tests/smoke_spec_gamma.sh
cd "/Users/mars/Vibe Coding/apaas-builder-ai" && git add backend/tests/smoke_spec_gamma.sh && git commit -m "$(cat <<'EOF'
test(spec): Phase γ e2e smoke 脚本

手动 gate：运行 backend + 有效 TOKEN，bash smoke_spec_gamma.sh：
- 创建 spec → 关联 conversation → POST /chat/send-with-file 上传完整文档
- SSE 流出 spec_patch 序列
- GET /spec/{id} 验证 phase ∈ {ready, drafting} + roles ≥ 2 + objects ≥ 1

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
EOF
)"
```

---

## Self-Review Checklist (run before declaring Phase γ complete)

- [ ] All backend tests pass: `cd backend && pytest tests/ -v` → all green
- [ ] `bootstrap_from_doc` 3 modes covered by unit tests
- [ ] `/send-with-file` legacy path (when `spec_id IS NULL`) still works
- [ ] `incremental_update` legacy ChangePlan path still works
- [ ] `bootstrap_from_legacy_config` correctly maps appName/roles/dicts/models/permissions
- [ ] e2e smoke (`smoke_spec_gamma.sh`) runs green against a live backend with valid TOKEN
- [ ] Each commit is independent + has Co-Authored-By line
- [ ] Phase α + β tests still all green (no regression)

---

## What's NOT in Phase γ (deferred)

- Frontend "升级到 SPEC 模式" UI prompt (β-style modal/banner) — backend ready, UI is a small β-follow task
- Decision_pending option click → auto-send chat message (β optional)
- Tier 1 视觉对齐 / token 重构（独立赛道）
- Audit log / parent_spec_id full timeline visualization
- Concurrent save optimistic locking (Phase α review I2)
