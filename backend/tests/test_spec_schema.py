from datetime import datetime
import pytest
from pydantic import ValidationError

from app.spec.schema import (
    Phase, Goal, Role, FieldSpec, ObjectSpec, DictSpec, DictOption,
    PermissionRule, PermissionSpec, Decision, Spec, derive_completeness,
)


def _now():
    return datetime(2026, 4, 25, 10, 0, 0)


def test_phase_enum_values():
    assert Phase.GATHERING.value == "gathering"
    assert Phase.DRAFTING.value == "drafting"
    assert Phase.GENERATING.value == "generating"
    assert Phase.READY.value == "ready"


def test_role_scope_validation():
    Role(code="finance_lead", name="财务负责人", scope="ALL")
    with pytest.raises(ValidationError):
        Role(code="x", name="x", scope="INVALID")


def test_permission_rule_op_validation():
    PermissionRule(role="all", op="all", data="ALL")
    with pytest.raises(ValidationError):
        PermissionRule(role="all", op="invalid_op", data="ALL")


def test_completeness_empty_spec():
    spec = Spec(
        id="spec_1", phase=Phase.GATHERING,
        completeness=derive_completeness_empty(),
        created_at=_now(), updated_at=_now(), created_by=1,
    )
    c = derive_completeness(spec)
    assert c.confirmed == 0
    assert c.total == 0
    assert c.pending_decisions == 0
    assert c.blocking_decisions == 0


def test_completeness_with_confirmed_items():
    spec = Spec(
        id="spec_2", phase=Phase.GATHERING,
        goal=Goal(title="预算", summary="x", business_problem="y", confirmed=True),
        roles=[
            Role(code="r1", name="r1", scope="ALL", confirmed=True),
            Role(code="r2", name="r2", scope="SELF", confirmed=False),
        ],
        objects=[
            ObjectSpec(code="t_a", name="a", confirmed=True, fields=[
                FieldSpec(code="f1", name="f1", type="单行输入", confirmed=True),
                FieldSpec(code="f2", name="f2", type="数字", confirmed=False),
            ]),
        ],
        dicts=[DictSpec(code="d1", name="d1", options=[DictOption(code="a", name="A")], confirmed=False)],
        permissions=[],
        decisions_pending=[
            Decision(id="d1", topic="t", raised_in_phase=Phase.GATHERING,
                     blocking=True, created_at=_now()),
            Decision(id="d2", topic="t2", raised_in_phase=Phase.GATHERING,
                     blocking=False, created_at=_now()),
        ],
        completeness=derive_completeness_empty(),
        created_at=_now(), updated_at=_now(), created_by=1,
    )
    c = derive_completeness(spec)
    # goal(1) + role(2) + object(1) + field(2) + dict(1) = 7 total items
    assert c.total == 7
    # goal=true + r1=true + t_a=true + f1=true = 4 confirmed
    assert c.confirmed == 4
    assert c.by_section["roles"] == (1, 2)
    assert c.by_section["objects"] == (1, 1)
    assert c.by_section["fields"] == (1, 2)
    assert c.by_section["dicts"] == (0, 1)
    assert c.pending_decisions == 2
    assert c.blocking_decisions == 1


def derive_completeness_empty():
    """Helper: completeness placeholder used when constructing fresh Spec for tests."""
    from app.spec.schema import Completeness
    return Completeness(confirmed=0, total=0, by_section={},
                        pending_decisions=0, blocking_decisions=0)
