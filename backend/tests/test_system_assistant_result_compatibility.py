from __future__ import annotations

from types import SimpleNamespace
import asyncio
import json

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

import app.ai_chat.agent as agent_mod
import app.database as database
from app.harness.profiles.runagent_event_map import map_runagent_event
from app.database import Base
from app.models import AIChatSession, AIChatToolCall
from app.models.agent_observability import AgentStep
from app.models.system_assistant_governance import ActionRun, ActionTicket
from app.observability import recorder
from app.system_assistant.result_envelope import (
    apply_agent_step_projection,
    apply_tool_call_projection,
    project_agent_step,
    project_sse_end,
    project_tool_call,
)


@pytest_asyncio.fixture
async def live_projection_db(monkeypatch):
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False}, poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    monkeypatch.setattr(database, "AsyncSessionLocal", Session)
    monkeypatch.setattr(recorder, "AsyncSessionLocal", Session)
    async with Session() as db:
        yield db
    await engine.dispose()


def _async_value(value):
    async def _value(*_args, **_kwargs):
        return value
    return _value


def _stub_live_llm(monkeypatch):
    responses = iter([
        {
            "type": "done",
            "message": {"content": "", "tool_calls": [{
                "id": "call-1", "type": "function",
                "function": {"name": "project_result", "arguments": "{}"},
            }]},
            "usage": {"prompt_tokens": 1, "completion_tokens": 1},
        },
        {
            "type": "done", "message": {"content": "done", "tool_calls": None},
            "usage": {"prompt_tokens": 1, "completion_tokens": 1},
        },
    ])

    async def stream(*_args, **_kwargs):
        yield next(responses)

    monkeypatch.setattr(agent_mod, "_call_llm_stream", stream)


@pytest.mark.asyncio
async def test_live_tool_loop_dispatches_governance_request_and_projects_result(
    live_projection_db, monkeypatch,
):
    session = AIChatSession(
        tenant_id=7,
        control_plane_tenant_id="cp-7",
        user_id=3,
        title="live projection",
        assistant_profile="system_assistant",
    )
    live_projection_db.add(session)
    await live_projection_db.commit()
    await live_projection_db.refresh(session)
    monkeypatch.setattr(agent_mod, "_resolve_llm_config", _async_value(SimpleNamespace(model="test")))
    monkeypatch.setattr(
        agent_mod, "_build_initial_messages",
        _async_value([{"role": "system", "content": "x"}, {"role": "user", "content": "hi"}]),
    )
    monkeypatch.setattr(agent_mod, "get_all_tool_schemas", _async_value([]))
    _stub_live_llm(monkeypatch)

    session._governance_action_request = agent_mod.GovernanceActionRequest(
        tool_name="project_result",
        capability_id="system_assistant.project_result",
        action_kind="project_result",
        object_ref="workspace:1",
        object_revision="v1",
        policy_revision=9,
        snapshot_digest="snapshot-1",
        correlation_id="corr-1",
    )
    calls = []

    async def execute_handler(_tool_name, _args, _session, _db):
        calls.append(_tool_name)
        return "legacy result"

    monkeypatch.setattr(agent_mod, "execute_tool", execute_handler)
    events = []
    async for event in agent_mod.run_agent(
        live_projection_db, session, "请执行项目结果操作", asyncio.Event(),
    ):
        events.append((event["event"], json.loads(event["data"])))

    assert [name for name, _data in events if name == "error"] == []
    tool_call = (await live_projection_db.execute(select(AIChatToolCall))).scalar_one()
    action_run = (await live_projection_db.execute(select(ActionRun))).scalar_one()
    ticket = (await live_projection_db.execute(select(ActionTicket))).scalar_one()
    assert calls == ["project_result"], (
        events, action_run.status, action_run.result_status, action_run.error_code,
        ticket.status, ticket.state_version,
    )
    assert action_run.ticket_id == ticket.ticket_id
    assert action_run.tool_call_id == tool_call.id
    assert (action_run.status, action_run.result_status) == ("succeeded", "succeeded")
    assert (ticket.status, ticket.state_version) == ("consumed", 3)
    assert (tool_call.status, tool_call.action_run_id, tool_call.correlation_id) == (
        "success", action_run.run_id, "corr-1",
    )
    assert (tool_call.result_status, tool_call.snapshot_digest) == ("succeeded", "snapshot-1")
    tool_end = [data for name, data in events if name == "tool_call_end"]
    assert tool_end == [
        {
            "id": tool_call.id, "tool_name": "project_result", "status": "success",
            "result_text": "legacy result", "duration_ms": tool_end[0]["duration_ms"],
            "action_run_id": action_run.run_id, "correlation_id": "corr-1",
            "result_status": "succeeded", "policy_revision": 9,
            "snapshot_digest": "snapshot-1",
        }
    ]
    tool_step = (await live_projection_db.execute(
        select(AgentStep).where(AgentStep.step_type == "tool")
    )).scalar_one()
    assert (tool_step.status, tool_step.action_run_id, tool_step.correlation_id) == (
        "success", action_run.run_id, "corr-1",
    )
    assert (tool_step.result_status, tool_step.snapshot_digest) == ("succeeded", "snapshot-1")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status", "legacy", "sse_status", "step"),
    [
        ("succeeded", "success", "success", "success"),
        ("recovered", "success", "success", "success"),
        ("denied", "error", "error", "error"),
        ("failed", "error", "error", "error"),
        ("partially_failed", "error", "error", "error"),
        ("recovery_blocked", "error", "error", "error"),
        ("outcome_unknown", "error", "error", "error"),
        ("aborted", "aborted", "aborted", "aborted"),
    ],
)
async def test_legacy_projections_are_additive(status, legacy, sse_status, step):
    run = SimpleNamespace(
        run_id="run-1", status=status, result_status=status,
        error_code="E" if status not in {"succeeded", "recovered"} else None,
        result_summary={}, correlation_id="corr-1", policy_revision=3,
        snapshot_digest="digest-1",
    )
    envelope = project_tool_call(run)
    assert envelope["status"] == legacy
    assert envelope["action_run_id"] == "run-1"
    assert envelope["result_status"] == status
    sse = project_sse_end(run, tool_call_id=4, tool_name="project_result", result_text="old")
    assert sse["event"] == "tool_call_end"
    assert sse["data"]["status"] == sse_status
    assert sse["data"]["result_status"] == status
    step_payload = await project_agent_step(run, result_text="old")
    assert step_payload["status"] == step
    assert step_payload["action_run_id"] == "run-1"


def test_sse_order_and_event_names_remain_unchanged():
    start = map_runagent_event("tool_call_start", {"id": 4, "tool_name": "x", "args": {}})
    end = map_runagent_event("tool_call_end", {"id": 4, "tool_name": "x", "status": "success", "result_text": "old"})
    assert [item["type"] for item in start + end] == ["agent_tool", "agent_result"]


@pytest.mark.asyncio
async def test_agent_step_projection_failure_does_not_mutate_action_run():
    run = SimpleNamespace(status="succeeded", result_status="succeeded", result_summary={}, correlation_id="corr-1")
    before = run.status
    await project_agent_step(run, recorder=lambda _payload: (_ for _ in ()).throw(RuntimeError("down")))
    assert run.status == before


@pytest.mark.asyncio
async def test_agent_step_projection_awaits_async_recorder_and_keeps_failure_best_effort():
    run = SimpleNamespace(
        status="recovered", result_status="recovered", result_summary={},
        correlation_id="corr-1", run_id="run-1",
    )
    observed = []

    async def async_recorder(payload):
        observed.append(payload)

    payload = await project_agent_step(run, result_text="old", recorder=async_recorder)
    assert observed == [payload]

    async def failed_recorder(_payload):
        raise RuntimeError("recorder down")

    await project_agent_step(run, recorder=failed_recorder)
    assert run.status == "recovered"


@pytest.mark.asyncio
async def test_live_tool_loop_without_action_run_keeps_legacy_sse_payload(
    live_projection_db, monkeypatch,
):
    session = AIChatSession(tenant_id=7, user_id=3, title="legacy projection")
    live_projection_db.add(session)
    await live_projection_db.commit()
    await live_projection_db.refresh(session)
    monkeypatch.setattr(agent_mod, "_resolve_llm_config", _async_value(SimpleNamespace(model="test")))
    monkeypatch.setattr(
        agent_mod, "_build_initial_messages",
        _async_value([{"role": "system", "content": "x"}, {"role": "user", "content": "hi"}]),
    )
    monkeypatch.setattr(agent_mod, "get_all_tool_schemas", _async_value([]))
    monkeypatch.setattr(agent_mod, "execute_tool", _async_value("legacy result"))
    _stub_live_llm(monkeypatch)

    events = []
    async for event in agent_mod.run_agent(live_projection_db, session, "hi", asyncio.Event()):
        events.append((event["event"], json.loads(event["data"])))

    tool_end = [data for name, data in events if name == "tool_call_end"]
    assert len(tool_end) == 1
    assert set(tool_end[0]) == {"id", "tool_name", "status", "result_text", "duration_ms"}
    tool_call = (await live_projection_db.execute(select(AIChatToolCall))).scalar_one()
    assert tool_call.action_run_id is None


def test_nullable_model_fields_receive_one_way_action_run_projection():
    from app.models.agent_observability import AgentStep
    from app.models.ai_chat import AIChatToolCall

    run = SimpleNamespace(
        run_id="run-1", status="recovered", result_status="recovered",
        result_summary={}, error_code=None, correlation_id="corr-1",
        policy_revision=3, snapshot_digest="digest-1",
    )
    tool_call = AIChatToolCall(session_id=1, tool_name="x")
    step = AgentStep(run_id="agent-1", seq=1, step_type="tool")

    apply_tool_call_projection(tool_call, run)
    apply_agent_step_projection(step, run, result_text="old")

    assert (tool_call.status, tool_call.action_run_id, tool_call.result_status) == (
        "success", "run-1", "recovered",
    )
    assert (step.status, step.action_run_id, step.correlation_id, step.snapshot_digest) == (
        "success", "run-1", "corr-1", "digest-1",
    )
    assert run.status == "recovered"
