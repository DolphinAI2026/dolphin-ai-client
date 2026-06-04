"""读 API：租户隔离 + trace 详情有序 steps。直接调路由函数（不走 HTTP，沿用本仓约定）。"""
from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.deps import AuthContext
from app.models import User
from app.models.agent_observability import AgentRun, AgentStep
from app.routes.agent_observability import list_agent_runs, get_agent_run_detail


def _ctx(user: User, tenant_id: int) -> AuthContext:
    return AuthContext(user=user, tenant_id=tenant_id, tenant_role="member", org_permissions={})


async def _seed_run(db, *, run_id, tenant_id, agent_type="ai_builder", session_id="1"):
    db.add(AgentRun(run_id=run_id, agent_type=agent_type, tenant_id=tenant_id,
                    user_id=1, session_id=session_id, status="success",
                    total_tokens=10, total_prompt_tokens=8, total_completion_tokens=2))
    await db.commit()


@pytest.mark.asyncio
async def test_list_is_tenant_scoped(db_session):
    user = User(username="u1", hashed_password="x")
    db_session.add(user)
    await db_session.flush()
    await _seed_run(db_session, run_id="r_t7", tenant_id=7)
    await _seed_run(db_session, run_id="r_t9", tenant_id=9)

    out = await list_agent_runs(_ctx(user, 7), db_session)
    ids = [r["run_id"] for r in out["runs"]]
    assert ids == ["r_t7"]          # 只看到自己租户的
    assert "r_t9" not in ids


@pytest.mark.asyncio
async def test_detail_cross_tenant_404(db_session):
    user = User(username="u2", hashed_password="x")
    db_session.add(user)
    await db_session.flush()
    await _seed_run(db_session, run_id="r_other", tenant_id=9)

    with pytest.raises(HTTPException) as ei:
        await get_agent_run_detail("r_other", _ctx(user, 7), db_session)
    assert ei.value.status_code == 404


@pytest.mark.asyncio
async def test_detail_returns_ordered_steps(db_session):
    user = User(username="u3", hashed_password="x")
    db_session.add(user)
    await db_session.flush()
    await _seed_run(db_session, run_id="r_ok", tenant_id=7)
    for seq, st in [(2, "tool"), (1, "llm"), (3, "llm")]:
        db_session.add(AgentStep(run_id="r_ok", seq=seq, step_type=st))
    await db_session.commit()

    out = await get_agent_run_detail("r_ok", _ctx(user, 7), db_session)
    assert out["run"]["run_id"] == "r_ok"
    assert [s["seq"] for s in out["steps"]] == [1, 2, 3]   # 按 seq 升序
