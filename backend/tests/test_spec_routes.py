import pytest
from datetime import datetime
from sqlalchemy import select

from app.spec.persistence import empty_spec, save_spec
from app.spec.schema import Phase, Role


@pytest.mark.asyncio
async def test_get_spec_returns_payload(db_session, monkeypatch):
    spec = empty_spec(created_by=1)
    spec.roles.append(Role(code="r1", name="r1", scope="ALL", confirmed=False))
    await save_spec(db_session, spec, tenant_id=1)

    # Direct DB read instead of HTTP — keeps test self-contained
    from app.models.spec import Spec as SpecORM
    row = (await db_session.execute(select(SpecORM).where(SpecORM.id == spec.id))).scalar_one()
    assert row.payload["roles"][0]["code"] == "r1"
    assert row.phase == "gathering"


@pytest.mark.asyncio
async def test_phase_transition_blocked_by_pending_blocking_decision(db_session):
    from app.spec.tools import dispatch_tool
    spec = empty_spec(created_by=1)
    spec = dispatch_tool(spec, "ask_clarifying_question", {"topic": "x", "blocking": True})
    await save_spec(db_session, spec, tenant_id=1)

    # Simulate route logic
    from app.spec.tools import dispatch_tool, ToolError
    with pytest.raises(ToolError):
        dispatch_tool(spec, "transition_phase", {"target": "drafting", "reason": "ok"})


@pytest.mark.asyncio
async def test_confirm_role_via_dispatch(db_session):
    from app.spec.tools import dispatch_tool
    spec = empty_spec(created_by=1)
    spec = dispatch_tool(spec, "ask_clarifying_question", {"topic": "x"})
    spec = dispatch_tool(spec, "ask_clarifying_question", {"topic": "y"})
    spec = dispatch_tool(spec, "ask_clarifying_question", {"topic": "z"})
    spec = dispatch_tool(spec, "add_role", {"code": "r1", "name": "r1", "scope": "ALL"})
    spec = dispatch_tool(spec, "confirm_role", {"code": "r1"})
    assert spec.roles[0].confirmed is True
    assert spec.completeness.confirmed == 1
