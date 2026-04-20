"""VerificationAgent 单元测试。

覆盖：
- state：init_state_from_spec / overall_status / snapshot roundtrip
- tools：grep_code / read_file / check_ac / emit_report 正反向
- Agent：构造 / build_initial_user_message / should_terminate / finalize 降级
"""
import asyncio
import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("LLM_API_KEY", "test-key")
os.environ.setdefault("JWT_SECRET_KEY", "test-secret")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from app.agents.publisher import InMemoryEventPublisher  # noqa: E402
from app.agents.trace_writer import InMemoryTraceWriter  # noqa: E402
from app.agents.types import AgentContext  # noqa: E402
from app.agents.verification import (  # noqa: E402
    AcItem,
    ConstraintResult,
    VerificationAgent,
    VerificationState,
    build_verification_tools,
    init_state_from_spec,
)


# ══════════════════════════════════════════════════════════════
# 辅助
# ══════════════════════════════════════════════════════════════

def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def _envelope() -> dict:
    return {
        "schema_version": "1.0",
        "scene_type": "web_component_dual",
        "spec_id": "spec_test",
        "provenance": {"version": 1, "confidence": 0.9, "open_questions": [], "created_by": "agent"},
        "identity": {
            "code_name": "rating-star", "display_name": "评分",
            "description_cn": "x", "widget_code": "FORM_CUSTOM_RATING_STAR",
        },
        "intent": {
            "original_requirement": "做评分",
            "core_purpose": "1-5 星",
            "acceptance_criteria": ["可点击 1-5 星", "主色可配"],
        },
        "spec": {
            "data": {
                "bof_type": "BOF_NUMBER", "component_model_field": ["NUM"],
                "form_value_shape": "scalar", "default_value": 0, "storage_note": "x",
            },
            "config_properties": [],
            "scenes_required": ["edit", "read"],
            "scenes_optional": [],
            "constraints_hard": ["禁止 innerHTML"],
            "constraints_soft": ["主色用 CSS var"],
        },
    }


def _ctx(input_data: dict = None) -> AgentContext:
    return AgentContext(
        session_id="v_s1", conversation_id=1, user_id=1, tenant_id=1, model="m",
        input=input_data or {
            "spec_envelope": _envelope(),
            "workspace_root": "/tmp/ws_dummy",
        },
        publisher=InMemoryEventPublisher(),
        trace_writer=InMemoryTraceWriter(),
    )


# ══════════════════════════════════════════════════════════════
# state
# ══════════════════════════════════════════════════════════════

def test_init_state_from_spec_expands_ac_and_constraints():
    s = init_state_from_spec(_envelope())
    assert s.spec_id == "spec_test"
    assert [a.description for a in s.ac_items] == ["可点击 1-5 星", "主色可配"]
    assert [a.index for a in s.ac_items] == [0, 1]
    assert [(c.text, c.severity) for c in s.constraint_results] == [
        ("禁止 innerHTML", "hard"),
        ("主色用 CSS var", "soft"),
    ]


def test_overall_status_pending_then_passed():
    s = init_state_from_spec(_envelope())
    assert s.overall_status() == "pending"
    for a in s.ac_items:
        a.status = "passed"
    assert s.overall_status() == "passed"


def test_overall_status_failed_beats_partial():
    s = init_state_from_spec(_envelope())
    s.ac_items[0].status = "passed"
    s.ac_items[1].status = "failed"
    assert s.overall_status() == "failed"
    s.ac_items[1].status = "needs_review"
    assert s.overall_status() == "partial"


def test_snapshot_roundtrip_preserves_state():
    s = init_state_from_spec(_envelope())
    s.ac_items[0].status = "passed"
    s.ac_items[0].evidence = "见 edit.vue"
    s.ac_items[0].confidence = 0.9
    s.constraint_results[0].status = "ok"
    s.read_files.add("edit.vue")
    s.grep_queries.append("formValue")
    snap = s.to_snapshot()
    rs = VerificationState.from_snapshot(snap)
    assert rs.ac_items[0].status == "passed"
    assert rs.ac_items[0].confidence == 0.9
    assert rs.ac_items[0].evidence == "见 edit.vue"
    assert rs.constraint_results[0].status == "ok"
    assert "edit.vue" in rs.read_files
    assert "formValue" in rs.grep_queries


# ══════════════════════════════════════════════════════════════
# grep_code tool
# ══════════════════════════════════════════════════════════════

def test_grep_code_finds_matches_in_temp_workspace():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "src").mkdir()
        (root / "src" / "edit.vue").write_text(
            "<template>\n<div>rating</div>\n<input v-model=\"formValue\" />\n</template>\n"
        )
        (root / "node_modules").mkdir()
        (root / "node_modules" / "ignored.vue").write_text("formValue-skip-me")

        state = VerificationState()
        tools = {t.name: t for t in build_verification_tools(state, root)}
        r = _run(tools["grep_code"].execute({"query": "formValue"}, _ctx()))
        assert r.success, r.content
        matches = r.data["matches"]
        # node_modules 被跳过
        files = {m["file"] for m in matches}
        assert "src/edit.vue" in files
        assert all("node_modules" not in m["file"] for m in matches)
        # query 被记录
        assert "formValue" in state.grep_queries


def test_grep_code_no_match_returns_ok_empty():
    with tempfile.TemporaryDirectory() as td:
        state = VerificationState()
        tools = {t.name: t for t in build_verification_tools(state, Path(td))}
        r = _run(tools["grep_code"].execute({"query": "nosuchstring"}, _ctx()))
        assert r.success
        assert r.data["matches"] == []


def test_grep_code_rejects_empty_query():
    with tempfile.TemporaryDirectory() as td:
        state = VerificationState()
        tools = {t.name: t for t in build_verification_tools(state, Path(td))}
        r = _run(tools["grep_code"].execute({"query": "  "}, _ctx()))
        assert not r.success


def test_grep_code_regex_mode():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "a.js").write_text("function foo() {}\nfunction bar() {}\n")
        state = VerificationState()
        tools = {t.name: t for t in build_verification_tools(state, root)}
        r = _run(tools["grep_code"].execute(
            {"query": r"function\s+\w+", "regex": True}, _ctx(),
        ))
        assert r.success
        assert len(r.data["matches"]) == 2


def test_grep_code_glob_filter():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "src").mkdir()
        (root / "src" / "a.vue").write_text("marker in vue")
        (root / "src" / "b.js").write_text("marker in js")
        state = VerificationState()
        tools = {t.name: t for t in build_verification_tools(state, root)}
        r = _run(tools["grep_code"].execute(
            {"query": "marker", "glob": "*.vue"}, _ctx(),
        ))
        assert r.success
        files = {m["file"] for m in r.data["matches"]}
        assert "src/a.vue" in files
        assert "src/b.js" not in files


# ══════════════════════════════════════════════════════════════
# read_file tool
# ══════════════════════════════════════════════════════════════

def test_read_file_returns_content():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "a.vue").write_text("hello world")
        state = VerificationState()
        tools = {t.name: t for t in build_verification_tools(state, root)}
        r = _run(tools["read_file"].execute({"path": "a.vue"}, _ctx()))
        assert r.success
        assert "hello world" in r.content
        assert "a.vue" in state.read_files


def test_read_file_not_found():
    with tempfile.TemporaryDirectory() as td:
        state = VerificationState()
        tools = {t.name: t for t in build_verification_tools(state, Path(td))}
        r = _run(tools["read_file"].execute({"path": "missing.vue"}, _ctx()))
        assert not r.success
        assert r.error == "not_found"


def test_read_file_traversal_rejected():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td) / "ws"
        root.mkdir()
        outside = Path(td) / "secret.txt"
        outside.write_text("TOPSECRET")
        state = VerificationState()
        tools = {t.name: t for t in build_verification_tools(state, root)}
        r = _run(tools["read_file"].execute({"path": "../secret.txt"}, _ctx()))
        assert not r.success
        assert r.error == "path_traversal"


def test_read_file_line_range():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        content = "\n".join(f"line {i}" for i in range(1, 11))
        (root / "x.txt").write_text(content)
        state = VerificationState()
        tools = {t.name: t for t in build_verification_tools(state, root)}
        r = _run(tools["read_file"].execute(
            {"path": "x.txt", "start_line": 3, "end_line": 5}, _ctx(),
        ))
        assert r.success
        assert "line 3" in r.content
        assert "line 5" in r.content
        assert "line 7" not in r.content


def test_read_file_dir_returns_listing():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "sub").mkdir()
        (root / "sub" / "a.txt").write_text("x")
        (root / "sub" / "b.txt").write_text("y")
        state = VerificationState()
        tools = {t.name: t for t in build_verification_tools(state, root)}
        r = _run(tools["read_file"].execute({"path": "sub"}, _ctx()))
        assert r.success
        assert r.data.get("is_dir") is True
        assert "a.txt" in r.content
        assert "b.txt" in r.content


# ══════════════════════════════════════════════════════════════
# check_ac tool
# ══════════════════════════════════════════════════════════════

def test_check_ac_marks_passed():
    state = init_state_from_spec(_envelope())
    with tempfile.TemporaryDirectory() as td:
        tools = {t.name: t for t in build_verification_tools(state, Path(td))}
        r = _run(tools["check_ac"].execute({
            "ac_index": 0,
            "status": "passed",
            "evidence": "edit.vue 第 32 行绑定了 click",
            "confidence": 0.95,
        }, _ctx()))
    assert r.success
    assert state.ac_items[0].status == "passed"
    assert state.ac_items[0].evidence.startswith("edit.vue")
    assert state.ac_items[0].confidence == 0.95


def test_check_ac_low_confidence_downgrades_passed_to_needs_review():
    state = init_state_from_spec(_envelope())
    with tempfile.TemporaryDirectory() as td:
        tools = {t.name: t for t in build_verification_tools(state, Path(td))}
        r = _run(tools["check_ac"].execute({
            "ac_index": 0,
            "status": "passed",
            "evidence": "不是很确定",
            "confidence": 0.3,
        }, _ctx()))
    assert r.success
    assert state.ac_items[0].status == "needs_review"
    assert "降级" in r.content


def test_check_ac_invalid_index():
    state = init_state_from_spec(_envelope())
    with tempfile.TemporaryDirectory() as td:
        tools = {t.name: t for t in build_verification_tools(state, Path(td))}
        r = _run(tools["check_ac"].execute({
            "ac_index": 99, "status": "passed", "evidence": "x", "confidence": 0.9,
        }, _ctx()))
    assert not r.success
    assert r.error == "ac_not_found"


def test_check_ac_empty_evidence_rejected():
    state = init_state_from_spec(_envelope())
    with tempfile.TemporaryDirectory() as td:
        tools = {t.name: t for t in build_verification_tools(state, Path(td))}
        r = _run(tools["check_ac"].execute({
            "ac_index": 0, "status": "failed", "evidence": "", "confidence": 0.9,
        }, _ctx()))
    assert not r.success


def test_check_ac_emits_event():
    state = init_state_from_spec(_envelope())
    with tempfile.TemporaryDirectory() as td:
        tools = {t.name: t for t in build_verification_tools(state, Path(td))}
        r = _run(tools["check_ac"].execute({
            "ac_index": 0, "status": "failed", "evidence": "缺 scenes_required",
            "confidence": 0.9,
        }, _ctx()))
    assert r.emit_event["type"] == "verification.ac_checked"
    assert r.emit_event["data"]["status"] == "failed"


# ══════════════════════════════════════════════════════════════
# emit_report tool
# ══════════════════════════════════════════════════════════════

def _mark_all_ac(state: VerificationState, status: str = "passed"):
    for a in state.ac_items:
        a.status = status  # type: ignore[assignment]
        a.evidence = "ok"
        a.confidence = 0.9


def test_emit_report_requires_all_ac_checked():
    state = init_state_from_spec(_envelope())
    with tempfile.TemporaryDirectory() as td:
        tools = {t.name: t for t in build_verification_tools(state, Path(td))}
        r = _run(tools["emit_report"].execute({"summary": "ok"}, _ctx()))
    assert not r.success
    assert r.error == "pending_ac"


def test_emit_report_happy_path():
    state = init_state_from_spec(_envelope())
    _mark_all_ac(state, "passed")
    with tempfile.TemporaryDirectory() as td:
        tools = {t.name: t for t in build_verification_tools(state, Path(td))}
        r = _run(tools["emit_report"].execute({"summary": "整体通过"}, _ctx()))
    assert r.success
    assert state.report_emitted is True
    assert state.emitted_report_id is not None
    assert r.data["overall_status"] == "passed"
    # 未标注的 constraint 默认为 ok
    assert all(c.status == "ok" for c in state.constraint_results)


def test_emit_report_double_emit_rejected():
    state = init_state_from_spec(_envelope())
    _mark_all_ac(state)
    with tempfile.TemporaryDirectory() as td:
        tools = {t.name: t for t in build_verification_tools(state, Path(td))}
        _run(tools["emit_report"].execute({"summary": "s"}, _ctx()))
        r2 = _run(tools["emit_report"].execute({"summary": "s"}, _ctx()))
    assert not r2.success
    assert r2.error == "already_emitted"


def test_emit_report_constraint_updates_applied():
    state = init_state_from_spec(_envelope())
    _mark_all_ac(state)
    with tempfile.TemporaryDirectory() as td:
        tools = {t.name: t for t in build_verification_tools(state, Path(td))}
        r = _run(tools["emit_report"].execute({
            "summary": "ok",
            "constraint_updates": [
                {"index": 0, "status": "violated", "evidence": "发现 innerHTML 在 edit.vue:20"},
            ],
        }, _ctx()))
    assert r.success
    assert state.constraint_results[0].status == "violated"
    # 硬约束违反时，overall 应降级到 failed
    assert r.data["overall_status"] == "failed"


def test_emit_report_ac_failed_sets_overall_failed():
    state = init_state_from_spec(_envelope())
    state.ac_items[0].status = "passed"
    state.ac_items[0].evidence = "ok"
    state.ac_items[0].confidence = 0.9
    state.ac_items[1].status = "failed"
    state.ac_items[1].evidence = "缺主色变量"
    state.ac_items[1].confidence = 0.9
    with tempfile.TemporaryDirectory() as td:
        tools = {t.name: t for t in build_verification_tools(state, Path(td))}
        r = _run(tools["emit_report"].execute({"summary": "有失败"}, _ctx()))
    assert r.success
    assert r.data["overall_status"] == "failed"
    assert r.data["failed_count"] == 1
    assert r.data["passed_count"] == 1


# ══════════════════════════════════════════════════════════════
# Agent 构造 / finalize
# ══════════════════════════════════════════════════════════════

def test_agent_construction_without_spec_raises():
    try:
        VerificationAgent(_ctx(input_data={"workspace_root": "/tmp"}))
    except ValueError as e:
        assert "spec_envelope" in str(e)
        return
    raise AssertionError("expected ValueError")


def test_agent_build_initial_message_contains_spec_and_acs():
    a = VerificationAgent(_ctx())
    msg = a.build_initial_user_message()
    assert "## 目标 Spec" in msg
    assert "rating-star" in msg
    assert "FORM_CUSTOM_RATING_STAR" in msg
    assert "可点击 1-5 星" in msg
    assert "主色可配" in msg
    assert "禁止 innerHTML" in msg
    assert "## 下一步" in msg


def test_agent_build_initial_message_without_pending_tells_emit():
    # 手动 mark 所有 AC passed，再 build message
    a = VerificationAgent(_ctx())
    for ac in a.state.ac_items:
        ac.status = "passed"
    msg = a.build_initial_user_message()
    assert "直接调 `emit_report`" in msg


def test_agent_should_terminate_after_emit():
    a = VerificationAgent(_ctx())
    assert a.should_terminate() == (False, "")
    a.state.report_emitted = True
    a.state.emitted_report_id = "vr_xxx"
    terminate, reason = a.should_terminate()
    assert terminate
    assert "vr_xxx" in reason


def test_agent_finalize_degraded_marks_pending_as_needs_review():
    a = VerificationAgent(_ctx())
    # 不 emit report，直接 finalize
    result = _run(a.finalize())
    assert result["emitted"] is False
    assert all(
        item["status"] in ("needs_review",) for item in result["items"]
    )
    assert result["overall_status"] == "partial"


def test_agent_finalize_with_emitted_report_returns_metadata():
    a = VerificationAgent(_ctx())
    for ac in a.state.ac_items:
        ac.status = "passed"
        ac.evidence = "ok"
        ac.confidence = 0.9
    a.state.report_emitted = True
    a.state.emitted_report_id = "vr_done"
    result = _run(a.finalize())
    assert result["emitted"] is True
    assert result["report_id"] == "vr_done"
    assert result["overall_status"] == "passed"
    assert result["passed_count"] == 2
    assert result["total_ac"] == 2


def test_agent_snapshot_custom_state_roundtrip():
    a = VerificationAgent(_ctx())
    a.state.ac_items[0].status = "passed"
    a.state.read_files.add("edit.vue")
    a.state.grep_queries.append("formValue")

    snap = a.to_snapshot()
    a2 = VerificationAgent.from_snapshot(_ctx(), snap)
    assert a2.state.ac_items[0].status == "passed"
    assert "edit.vue" in a2.state.read_files
    assert "formValue" in a2.state.grep_queries
    # Tool 重新绑到恢复后的 state
    tool_names = [t.name for t in a2.get_tools()]
    assert tool_names == ["grep_code", "read_file", "check_ac", "emit_report"]


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
