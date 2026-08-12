from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.harness.profiles.runagent_event_map import map_runagent_event
from app.system_assistant.result_envelope import (
    apply_agent_step_projection,
    apply_tool_call_projection,
    project_agent_step,
    project_sse_end,
    project_tool_call,
)


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
def test_legacy_projections_are_additive(status, legacy, sse_status, step):
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
    step_payload = project_agent_step(run, result_text="old")
    assert step_payload["status"] == step
    assert step_payload["action_run_id"] == "run-1"


def test_sse_order_and_event_names_remain_unchanged():
    start = map_runagent_event("tool_call_start", {"id": 4, "tool_name": "x", "args": {}})
    end = map_runagent_event("tool_call_end", {"id": 4, "tool_name": "x", "status": "success", "result_text": "old"})
    assert [item["type"] for item in start + end] == ["agent_tool", "agent_result"]


def test_agent_step_projection_failure_does_not_mutate_action_run():
    run = SimpleNamespace(status="succeeded", result_status="succeeded", result_summary={}, correlation_id="corr-1")
    before = run.status
    project_agent_step(run, recorder=lambda _payload: (_ for _ in ()).throw(RuntimeError("down")))
    assert run.status == before


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
