"""BrainstormAgent 单元测试。

覆盖：
- 5 个 tool 的成功 / 失败分支
- BrainstormState snapshot/restore
- Confidence 计算 + emit_decision gate
- Agent 构造 / system prompt / initial user message
- max_turns 降级
"""
import asyncio
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

os.environ.setdefault("LLM_API_KEY", "test-key")
os.environ.setdefault("JWT_SECRET_KEY", "test-secret")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from app.agents.brainstorm import (  # noqa: E402
    BrainstormAgent,
    BrainstormState,
    MAX_ASK_USER_TURNS,
    MAX_TURNS,
    build_brainstorm_tools,
    compute_confidence,
    emit_decision,
    make_p1_list,
)
from app.agents.brainstorm.prompts import build_user_prompt  # noqa: E402
from app.agents.publisher import InMemoryEventPublisher  # noqa: E402
from app.agents.trace_writer import InMemoryTraceWriter  # noqa: E402
from app.agents.types import AgentContext  # noqa: E402
from app.spec.schema import SceneType  # noqa: E402


# ══════════════════════════════════════════════════════════════
# 辅助
# ══════════════════════════════════════════════════════════════

def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro) if _no_running_loop() else asyncio.get_event_loop().run_until_complete(coro)


def _no_running_loop() -> bool:
    try:
        asyncio.get_running_loop()
        return False
    except RuntimeError:
        return True


def _ctx(workspace_id=None, input_data=None) -> AgentContext:
    return AgentContext(
        session_id="bs_s1",
        conversation_id=1,
        user_id=1,
        tenant_id=1,
        model="test-model",
        workspace_id=workspace_id,
        input=input_data or {"requirement": "做个评分组件"},
        publisher=InMemoryEventPublisher(),
        trace_writer=InMemoryTraceWriter(),
    )


# ══════════════════════════════════════════════════════════════
# State / P1 清单
# ══════════════════════════════════════════════════════════════

def test_p1_list_by_scene():
    assert len(make_p1_list(SceneType.WEB_COMPONENT_DUAL)) >= 1
    assert len(make_p1_list(SceneType.WEB_PAGE)) >= 1
    assert len(make_p1_list(SceneType.BACKEND_API)) >= 1


def test_p1_make_is_independent_copy():
    a = make_p1_list(SceneType.WEB_COMPONENT_DUAL)
    b = make_p1_list(SceneType.WEB_COMPONENT_DUAL)
    a[0].answered = True
    assert not b[0].answered


def test_state_snapshot_roundtrip():
    s = BrainstormState()
    s.scene_type = SceneType.WEB_COMPONENT_DUAL
    s.scene_confidence = 0.8
    s.p1_questions = make_p1_list(SceneType.WEB_COMPONENT_DUAL)
    s.p1_questions[0].answered = True
    s.p1_questions[0].answer = "单值"
    s.ask_user_count = 2
    snap = s.to_snapshot()
    restored = BrainstormState.from_snapshot(snap)
    assert restored.scene_type == SceneType.WEB_COMPONENT_DUAL
    assert restored.scene_confidence == 0.8
    assert restored.p1_questions[0].answered is True
    assert restored.ask_user_count == 2


def test_state_p1_coverage():
    s = BrainstormState()
    s.p1_questions = make_p1_list(SceneType.WEB_COMPONENT_DUAL)
    assert s.p1_coverage() == 0.0
    s.mark_p1_answered(s.p1_questions[0].key, "x")
    assert 0 < s.p1_coverage() < 1


def test_state_mark_p1_answered_missing_key_returns_false():
    s = BrainstormState()
    s.p1_questions = make_p1_list(SceneType.WEB_COMPONENT_DUAL)
    assert s.mark_p1_answered("nope", "x") is False


# ══════════════════════════════════════════════════════════════
# Confidence
# ══════════════════════════════════════════════════════════════

def test_compute_confidence_empty_state():
    assert compute_confidence(BrainstormState()) == 0.0


def test_compute_confidence_high():
    s = BrainstormState()
    s.scene_confidence = 1.0
    s.p1_questions = make_p1_list(SceneType.WEB_COMPONENT_DUAL)
    for q in s.p1_questions:
        q.answered = True
    c = compute_confidence(s)
    assert c >= 0.99


def test_emit_decision_gates():
    assert emit_decision(0.9)[0] == "ok"
    assert emit_decision(0.6)[0] == "warn"
    assert emit_decision(0.4)[0] == "block"
    assert emit_decision(0.1)[0] == "block"


# ══════════════════════════════════════════════════════════════
# Tool: detect_scene
# ══════════════════════════════════════════════════════════════

def test_tool_detect_scene_success():
    state = BrainstormState()
    tools = {t.name: t for t in build_brainstorm_tools(state)}
    r = _run(tools["detect_scene"].execute(
        {"scene_type": "web_component_dual", "confidence": 0.9, "reason": "用户说要评分组件"},
        _ctx(),
    ))
    assert r.success
    assert state.scene_type == SceneType.WEB_COMPONENT_DUAL
    assert state.scene_confidence == 0.9
    assert len(state.p1_questions) >= 1
    assert r.emit_event and r.emit_event["type"] == "brainstorm.scene_detected"


def test_tool_detect_scene_invalid_enum():
    state = BrainstormState()
    tools = {t.name: t for t in build_brainstorm_tools(state)}
    r = _run(tools["detect_scene"].execute(
        {"scene_type": "not_a_real_scene", "confidence": 0.9, "reason": "x"},
        _ctx(),
    ))
    assert not r.success


def test_tool_detect_scene_preserves_answered_on_rerun():
    state = BrainstormState()
    tools = {t.name: t for t in build_brainstorm_tools(state)}
    _run(tools["detect_scene"].execute(
        {"scene_type": "web_component_dual", "confidence": 0.9, "reason": "x"},
        _ctx(),
    ))
    first_key = state.p1_questions[0].key
    state.mark_p1_answered(first_key, "已答")
    _run(tools["detect_scene"].execute(
        {"scene_type": "web_component_dual", "confidence": 0.95, "reason": "x"},
        _ctx(),
    ))
    assert state.p1_questions[0].answered is True
    assert state.p1_questions[0].answer == "已答"


# ══════════════════════════════════════════════════════════════
# Tool: ask_user
# ══════════════════════════════════════════════════════════════

def test_tool_ask_user_pauses_and_emits_event():
    state = BrainstormState()
    tools = {t.name: t for t in build_brainstorm_tools(state)}
    r = _run(tools["ask_user"].execute(
        {
            "question": "值是单值还是范围？",
            "options": [
                {"value": "scalar", "label": "单值"},
                {"value": "range", "label": "范围"},
                {"value": "free", "label": "让我自己决定"},
            ],
            "priority": 1,
            "p1_key": "form_value_shape",
        },
        _ctx(),
    ))
    assert r.success
    assert r.should_pause is True
    assert state.ask_user_count == 1
    assert r.emit_event and r.emit_event["type"] == "brainstorm.ask_user"


def test_tool_ask_user_injected_answer_does_not_pause():
    state = BrainstormState()
    tools = {t.name: t for t in build_brainstorm_tools(state)}
    ctx = _ctx(input_data={
        "requirement": "t",
        "_ask_user_answer": {"answer": "单值", "question_matches": True},
    })
    r = _run(tools["ask_user"].execute(
        {"question": "q", "priority": 1, "p1_key": "form_value_shape"},
        ctx,
    ))
    assert r.success
    assert r.should_pause is False
    assert "单值" in r.content
    # p1 被标记
    # （注意：此 state 的 p1_questions 是空的；mark_p1_answered 会返回 False 但不报错）


def test_tool_ask_user_max_turns_exceeded():
    state = BrainstormState()
    state.ask_user_count = MAX_ASK_USER_TURNS
    tools = {t.name: t for t in build_brainstorm_tools(state)}
    r = _run(tools["ask_user"].execute(
        {"question": "再问一个", "priority": 1},
        _ctx(),
    ))
    assert not r.success
    assert "上限" in r.content


def test_tool_ask_user_empty_question_rejected():
    state = BrainstormState()
    tools = {t.name: t for t in build_brainstorm_tools(state)}
    r = _run(tools["ask_user"].execute(
        {"question": "", "priority": 1},
        _ctx(),
    ))
    assert not r.success


# ══════════════════════════════════════════════════════════════
# Tool: query_marketplace
# ══════════════════════════════════════════════════════════════

def test_tool_query_marketplace_mvp_returns_empty():
    state = BrainstormState()
    tools = {t.name: t for t in build_brainstorm_tools(state)}
    r = _run(tools["query_marketplace"].execute({"keywords": "评分"}, _ctx()))
    assert r.success
    assert r.data.get("results") == []
    assert "评分" in state.marketplace_queries


def test_tool_query_marketplace_dedupe():
    state = BrainstormState()
    tools = {t.name: t for t in build_brainstorm_tools(state)}
    _run(tools["query_marketplace"].execute({"keywords": "评分"}, _ctx()))
    r = _run(tools["query_marketplace"].execute({"keywords": "评分"}, _ctx()))
    assert r.success
    assert r.data.get("repeat") is True


def test_tool_query_marketplace_empty_keywords_rejected():
    state = BrainstormState()
    tools = {t.name: t for t in build_brainstorm_tools(state)}
    r = _run(tools["query_marketplace"].execute({"keywords": ""}, _ctx()))
    assert not r.success


# ══════════════════════════════════════════════════════════════
# Tool: read_workspace_context
# ══════════════════════════════════════════════════════════════

def test_tool_read_workspace_context_without_workspace_id():
    state = BrainstormState()
    tools = {t.name: t for t in build_brainstorm_tools(state)}
    r = _run(tools["read_workspace_context"].execute({}, _ctx(workspace_id=None)))
    assert not r.success
    assert r.error == "no_workspace"


def test_tool_read_workspace_context_summary_only():
    """mock WorkspaceManager → 只返回摘要，不传 paths"""
    from app.coding import workspace as ws_module

    class FakeWs:
        def get_workspace_info(self, wid):
            return {"id": wid, "project_name": "p", "project_type": "form-component-dual", "files": ["a", "b"]}

        def get_workspace_path(self, wid):
            return Path("/tmp/fake")

    orig = ws_module.WorkspaceManager
    ws_module.WorkspaceManager = FakeWs  # type: ignore[assignment]
    try:
        state = BrainstormState()
        tools = {t.name: t for t in build_brainstorm_tools(state)}
        r = _run(tools["read_workspace_context"].execute({}, _ctx(workspace_id="ws1")))
    finally:
        ws_module.WorkspaceManager = orig  # type: ignore[assignment]
    assert r.success
    assert state.workspace_context_read is True
    assert "p" in r.content
    assert "form-component-dual" in r.content


def test_tool_read_workspace_context_path_whitelist():
    from app.coding import workspace as ws_module
    import tempfile

    with tempfile.TemporaryDirectory() as td:
        td_path = Path(td)
        (td_path / "apaas.json").write_text('{"x": 1}')
        (td_path / "secret.txt").write_text("TOPSECRET")  # 非白名单

        class FakeWs:
            def get_workspace_info(self, wid):
                return {"id": wid, "project_name": "p", "project_type": "x", "files": []}

            def get_workspace_path(self, wid):
                return td_path

        orig = ws_module.WorkspaceManager
        ws_module.WorkspaceManager = FakeWs  # type: ignore[assignment]
        try:
            state = BrainstormState()
            tools = {t.name: t for t in build_brainstorm_tools(state)}
            r = _run(tools["read_workspace_context"].execute(
                {"paths": ["apaas.json", "secret.txt"]},
                _ctx(workspace_id="ws1"),
            ))
        finally:
            ws_module.WorkspaceManager = orig  # type: ignore[assignment]
    assert r.success
    # apaas.json 被允许
    assert "apaas.json" in r.content
    # secret.txt 被拒
    assert "path_not_allowed" in str(r.data)


# ══════════════════════════════════════════════════════════════
# Tool: emit_spec — happy path + validation failures
# ══════════════════════════════════════════════════════════════

def _valid_component_spec_args() -> dict:
    return {
        "scene_type": "web_component_dual",
        "identity": {
            "code_name": "rating-star",
            "display_name": "评分",
            "description_cn": "星级评分组件",
            "widget_code": "FORM_CUSTOM_RATING_STAR",
        },
        "intent": {
            "original_requirement": "做个评分组件",
            "core_purpose": "1-5 星点击打分",
            "acceptance_criteria": ["用户可点击 1~5 星完成评分"],
        },
        "spec": {
            "data": {
                "bof_type": "BOF_NUMBER",
                "component_model_field": ["NUM"],
                "form_value_shape": "scalar",
                "default_value": 0,
                "storage_note": "整数 1~5",
            },
            "config_properties": [],
            "scenes_required": ["edit", "read"],
            "scenes_optional": [],
        },
        "open_questions": [],
    }


def _fill_state_for_emit() -> BrainstormState:
    s = BrainstormState()
    s.scene_type = SceneType.WEB_COMPONENT_DUAL
    s.scene_confidence = 0.95
    s.p1_questions = make_p1_list(SceneType.WEB_COMPONENT_DUAL)
    for q in s.p1_questions:
        q.answered = True
        q.answer = "x"
    return s


def test_tool_emit_spec_happy_path():
    state = _fill_state_for_emit()
    tools = {t.name: t for t in build_brainstorm_tools(state)}
    r = _run(tools["emit_spec"].execute(_valid_component_spec_args(), _ctx()))
    assert r.success, r.content
    assert state.emitted is True
    assert state.emitted_spec_id is not None
    # emit_event 由 driver 层在 spec commit 后发出，tool 本身不再携带（避免竞态 404）
    assert r.emit_event is None
    assert r.data.get("confidence") >= 0.9


def test_tool_emit_spec_blocks_on_low_confidence():
    state = BrainstormState()  # 空 state → p1_coverage=0, scene_confidence=0
    tools = {t.name: t for t in build_brainstorm_tools(state)}
    r = _run(tools["emit_spec"].execute(_valid_component_spec_args(), _ctx()))
    assert not r.success
    assert r.error == "confidence_too_low"


def test_tool_emit_spec_pydantic_failure():
    state = _fill_state_for_emit()
    tools = {t.name: t for t in build_brainstorm_tools(state)}
    bad = _valid_component_spec_args()
    bad["identity"]["widget_code"] = "invalid_lower"  # 违反正则
    r = _run(tools["emit_spec"].execute(bad, _ctx()))
    assert not r.success
    assert r.error == "pydantic_validation_failed"
    assert not state.emitted


def test_tool_emit_spec_business_rule_failure():
    state = _fill_state_for_emit()
    tools = {t.name: t for t in build_brainstorm_tools(state)}
    bad = _valid_component_spec_args()
    bad["identity"]["widget_code"] = None  # 组件必填
    r = _run(tools["emit_spec"].execute(bad, _ctx()))
    assert not r.success
    assert r.error == "business_validation_failed"
    assert not state.emitted


def test_tool_emit_spec_double_emit_rejected():
    state = _fill_state_for_emit()
    tools = {t.name: t for t in build_brainstorm_tools(state)}
    r1 = _run(tools["emit_spec"].execute(_valid_component_spec_args(), _ctx()))
    assert r1.success
    r2 = _run(tools["emit_spec"].execute(_valid_component_spec_args(), _ctx()))
    assert not r2.success
    assert r2.error == "already_emitted"


# ══════════════════════════════════════════════════════════════
# Agent 构造 / lifecycle
# ══════════════════════════════════════════════════════════════

def test_agent_build_initial_message_no_workspace():
    a = BrainstormAgent(_ctx(input_data={"requirement": "做评分组件"}))
    msg = a.build_initial_user_message()
    assert "## 用户需求" in msg
    assert "做评分组件" in msg
    assert "detect_scene" in msg


def test_agent_system_prompt_contains_rules():
    a = BrainstormAgent(_ctx())
    sp = a.get_system_prompt()
    assert "反问原则" in sp
    assert "detect_scene" in sp
    assert "emit_spec" in sp


def test_agent_system_prompt_override():
    a = BrainstormAgent(_ctx(input_data={"requirement": "t", "system_prompt": "自定义"}))
    assert a.get_system_prompt() == "自定义"


def test_agent_should_terminate_after_emit():
    a = BrainstormAgent(_ctx())
    assert a.should_terminate() == (False, "")
    a.state.emitted = True
    a.state.emitted_spec_id = "spec_xxx"
    terminate, reason = a.should_terminate()
    assert terminate
    assert "spec_xxx" in reason


def test_agent_finalize_degraded_path():
    a = BrainstormAgent(_ctx())
    result = _run(a.finalize())
    assert result["status"] == "degraded"
    assert result["degraded"] is True
    assert result["spec_id"] is None


def test_agent_snapshot_custom_state_roundtrip():
    a = BrainstormAgent(_ctx())
    a.state.scene_type = SceneType.WEB_PAGE
    a.state.scene_confidence = 0.7
    a.state.p1_questions = make_p1_list(SceneType.WEB_PAGE)
    a.state.ask_user_count = 2

    snap = a.to_snapshot()
    ctx2 = _ctx()
    a2 = BrainstormAgent.from_snapshot(ctx2, snap)
    assert a2.state.scene_type == SceneType.WEB_PAGE
    assert a2.state.scene_confidence == 0.7
    assert a2.state.ask_user_count == 2
    # 恢复后的 tools 应绑到新 state
    tool_names = [t.name for t in a2.get_tools()]
    assert tool_names == [
        "detect_scene", "ask_user", "query_marketplace",
        "read_workspace_context", "emit_spec",
    ]


async def _on_max_turns_hook(a: BrainstormAgent):
    # 模拟：有 P1 未答 → on_max_turns_exceeded 应填 open_questions
    await a.on_max_turns_exceeded()


def test_agent_on_max_turns_exceeded_fills_open_questions():
    a = BrainstormAgent(_ctx())
    a.state.scene_type = SceneType.WEB_COMPONENT_DUAL
    a.state.p1_questions = make_p1_list(SceneType.WEB_COMPONENT_DUAL)
    # 不标 answered
    _run(_on_max_turns_hook(a))
    # 每个 P1 都应转成 open_question
    assert len(a.state.open_questions) == len(a.state.p1_questions)
    assert all("max_turns" in oq.assumed_answer for oq in a.state.open_questions)


def test_agent_on_max_turns_exceeded_skipped_when_emitted():
    a = BrainstormAgent(_ctx())
    a.state.emitted = True
    a.state.p1_questions = make_p1_list(SceneType.WEB_COMPONENT_DUAL)
    _run(_on_max_turns_hook(a))
    assert len(a.state.open_questions) == 0


def test_agent_initial_scene_hint_from_input():
    a = BrainstormAgent(_ctx(input_data={
        "requirement": "x", "scene_hint": "web_component_dual",
    }))
    msg = a.build_initial_user_message()
    assert "web_component_dual" in msg or "双端组件" in msg


# ══════════════════════════════════════════════════════════════
# build_user_prompt 独立测试
# ══════════════════════════════════════════════════════════════

def test_build_user_prompt_with_attachments():
    p = build_user_prompt(
        requirement="做个页面",
        scene_hint=SceneType.WEB_PAGE,
        attachments=["https://img.example.com/mock.png"],
    )
    assert "附件" in p
    assert "mock.png" in p


def test_build_user_prompt_with_workspace_info():
    p = build_user_prompt(
        requirement="改评分",
        scene_hint=SceneType.WEB_COMPONENT_DUAL,
        workspace_info={"project_name": "rating-star", "project_type": "form-component-dual", "files": ["a"]},
    )
    assert "rating-star" in p
    assert "迭代" in p
    assert "read_workspace_context" in p


if __name__ == "__main__":
    import inspect, traceback as _tb
    current = sys.modules[__name__]
    tests = [
        (n, f) for n, f in inspect.getmembers(current, inspect.isfunction)
        if n.startswith("test_")
    ]
    passed = failed = 0
    for name, func in tests:
        try:
            func()
            print(f"✓ {name}")
            passed += 1
        except Exception as e:
            print(f"✗ {name}: {type(e).__name__}: {e}")
            _tb.print_exc()
            failed += 1
    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)
