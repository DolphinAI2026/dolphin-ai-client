from datetime import datetime
import pytest
from app.spec.schema import Spec, Phase, Goal, Role, ObjectSpec, FieldSpec, Completeness
from app.spec.tools import (
    TOOL_DEFINITIONS, dispatch_tool, ToolError,
)


def _empty_spec():
    return Spec(
        id="spec_t",
        phase=Phase.GATHERING,
        completeness=Completeness(),
        created_at=datetime(2026, 4, 25),
        updated_at=datetime(2026, 4, 25),
        created_by=1,
    )


def test_tool_definitions_count():
    assert len(TOOL_DEFINITIONS) == 22
    names = {t["function"]["name"] for t in TOOL_DEFINITIONS}
    assert "ask_clarifying_question" in names
    assert "set_goal" in names
    assert "transition_phase" in names
    assert "add_role" in names
    assert "confirm_role" in names
    assert "confirm_goal" in names
    assert "dismiss_role" in names


def test_set_goal_writes_unconfirmed():
    spec = _empty_spec()
    new_spec = dispatch_tool(spec, "set_goal", {
        "title": "预算管理", "summary": "季度预测", "business_problem": "对齐财务"
    })
    assert new_spec.goal is not None
    assert new_spec.goal.title == "预算管理"
    assert new_spec.goal.confirmed is False


def test_add_role_appends_unconfirmed():
    spec = _empty_spec()
    new_spec = dispatch_tool(spec, "add_role", {
        "code": "finance_lead", "name": "财务负责人", "scope": "ALL",
    })
    assert len(new_spec.roles) == 1
    assert new_spec.roles[0].code == "finance_lead"
    assert new_spec.roles[0].confirmed is False


def test_confirm_role_flips_flag():
    spec = _empty_spec()
    spec = dispatch_tool(spec, "add_role", {"code": "r1", "name": "r1", "scope": "ALL"})
    spec = dispatch_tool(spec, "confirm_role", {"code": "r1"})
    assert spec.roles[0].confirmed is True


def test_dismiss_role_removes():
    spec = _empty_spec()
    spec = dispatch_tool(spec, "add_role", {"code": "r1", "name": "r1", "scope": "ALL"})
    spec = dispatch_tool(spec, "dismiss_role", {"code": "r1"})
    assert spec.roles == []


def test_ask_clarifying_question_appends_decision():
    spec = _empty_spec()
    new_spec = dispatch_tool(spec, "ask_clarifying_question", {
        "topic": "季度起算月", "options": ["1月起", "财年起"], "blocking": True,
    })
    assert len(new_spec.decisions_pending) == 1
    d = new_spec.decisions_pending[0]
    assert d.topic == "季度起算月"
    assert d.blocking is True
    assert d.id.startswith("d_")


def test_resolve_decision_moves_to_resolved():
    spec = _empty_spec()
    spec = dispatch_tool(spec, "ask_clarifying_question", {
        "topic": "x", "blocking": True,
    })
    decision_id = spec.decisions_pending[0].id
    spec = dispatch_tool(spec, "resolve_decision", {
        "decision_id": decision_id, "resolution": "1 月起",
    })
    assert spec.decisions_pending == []
    assert len(spec.decisions_resolved) == 1
    assert spec.decisions_resolved[0].resolution == "1 月起"


def test_transition_phase_blocked_by_blocking_decision():
    spec = _empty_spec()
    spec = dispatch_tool(spec, "ask_clarifying_question", {
        "topic": "x", "blocking": True,
    })
    with pytest.raises(ToolError) as exc:
        dispatch_tool(spec, "transition_phase", {"target": "drafting", "reason": "ok"})
    assert "blocking decision" in str(exc.value).lower()


def test_transition_phase_allowed_when_no_blocking():
    spec = _empty_spec()
    new_spec = dispatch_tool(spec, "transition_phase", {"target": "drafting", "reason": "ready"})
    assert new_spec.phase == Phase.DRAFTING


def test_gathering_first_turn_blocks_set_goal_when_completeness_zero():
    """Per design spec section 5: gathering phase first turn must call ask_clarifying_question
    at least 3 times before any add_/set_."""
    spec = _empty_spec()
    # confirmed=0, no decisions yet → must ask first
    with pytest.raises(ToolError) as exc:
        dispatch_tool(spec, "set_goal", {
            "title": "x", "summary": "x", "business_problem": "x",
        }, enforce_first_turn=True)
    assert "ask_clarifying_question" in str(exc.value).lower()


def test_unknown_tool_raises():
    spec = _empty_spec()
    with pytest.raises(ToolError):
        dispatch_tool(spec, "no_such_tool", {})
