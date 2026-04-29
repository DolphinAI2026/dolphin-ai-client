from datetime import datetime
import pytest
from app.builder_spec.schema import Spec, Phase, Goal, Role, ObjectSpec, FieldSpec, Completeness
from app.builder_spec.tools import (
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


def test_update_role_marks_confirmed_item_unconfirmed():
    spec = _empty_spec()
    spec = dispatch_tool(spec, "add_role", {"code": "r1", "name": "r1", "scope": "ALL"})
    spec = dispatch_tool(spec, "confirm_role", {"code": "r1"})
    spec = dispatch_tool(spec, "update_role", {"code": "r1", "description": "负责全局配置"})
    assert spec.roles[0].description == "负责全局配置"
    assert spec.roles[0].confirmed is False


def test_update_field_marks_confirmed_item_unconfirmed():
    spec = _empty_spec()
    spec.objects.append(ObjectSpec(
        code="t_candidate",
        name="候选人",
        fields=[FieldSpec(code="remark", name="备注", type="单行输入", confirmed=True)],
        confirmed=True,
    ))
    spec = dispatch_tool(spec, "update_field", {
        "object_code": "t_candidate",
        "field_code": "remark",
        "type": "多行文本",
    })
    assert spec.objects[0].fields[0].type == "多行文本"
    assert spec.objects[0].fields[0].confirmed is False


def test_ready_write_reopens_spec_as_draft():
    spec = _empty_spec()
    spec.phase = Phase.READY
    spec = dispatch_tool(spec, "add_object", {
        "code": "t_candidate",
        "name": "候选人",
        "fields": [{"code": "remark", "name": "备注", "type": "多行文本"}],
    })
    assert spec.phase == Phase.DRAFTING


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


def test_gathering_first_turn_allows_spec_extraction_when_confident():
    """The agent may write high-confidence facts before asking follow-up questions."""
    spec = _empty_spec()
    new_spec = dispatch_tool(spec, "set_goal", {
        "title": "预算管理", "summary": "管理预算申请与审批", "business_problem": "预算流转不透明",
    }, enforce_first_turn=True)
    assert new_spec.goal is not None
    assert new_spec.goal.title == "预算管理"


def test_unknown_tool_raises():
    spec = _empty_spec()
    with pytest.raises(ToolError):
        dispatch_tool(spec, "no_such_tool", {})
