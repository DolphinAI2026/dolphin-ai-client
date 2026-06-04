"""Agent 可观测两张表建表 + 默认值。"""
from __future__ import annotations

import pytest

from app.models.agent_observability import AgentRun, AgentStep


@pytest.mark.asyncio
async def test_agent_run_defaults(db_session):
    run = AgentRun(
        run_id="run_abc",
        agent_type="ai_builder",
        tenant_id=7,
        user_id=3,
        session_id="42",
        model="gpt-5.5",
    )
    db_session.add(run)
    await db_session.commit()
    await db_session.refresh(run)

    assert run.id is not None
    assert run.status == "running"
    assert run.total_prompt_tokens == 0
    assert run.total_completion_tokens == 0
    assert run.total_tokens == 0
    assert run.turn_count == 0
    assert run.started_at is not None
    assert run.created_at is not None
    assert run.ended_at is None


@pytest.mark.asyncio
async def test_agent_step_persists(db_session):
    step = AgentStep(
        run_id="run_abc",
        seq=1,
        step_type="llm",
        prompt_tokens=120,
        completion_tokens=34,
    )
    db_session.add(step)
    await db_session.commit()
    await db_session.refresh(step)

    assert step.id is not None
    assert step.run_id == "run_abc"
    assert step.seq == 1
    assert step.step_type == "llm"
    assert step.prompt_tokens == 120
    assert step.ts is not None
    assert step.tool_name is None
    assert step.args_json is None
