from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.system_assistant.result_envelope import ResultEnvelope, legacy_result_text, project_action_run


STATUSES = (
    "succeeded", "recovered", "denied", "failed", "partially_failed",
    "recovery_blocked", "outcome_unknown", "aborted",
)


@pytest.mark.parametrize("status", STATUSES)
def test_action_run_projects_all_governance_statuses(status: str):
    run = SimpleNamespace(
        run_id="run-1", status=status, result_status=status,
        error_code="E_TEST" if status not in {"succeeded", "recovered"} else None,
        result_summary={"result": "value"}, correlation_id="corr-1",
        policy_revision=7, snapshot_digest="digest-1",
    )
    envelope = project_action_run(run)
    assert isinstance(envelope, ResultEnvelope)
    assert envelope.status == status
    assert envelope.correlation_id == "corr-1"
    assert envelope.policy_revision == 7
    assert envelope.snapshot_digest == "digest-1"
    assert envelope.ok is (status in {"succeeded", "recovered"})


def test_legacy_result_text_preserves_existing_string_contract():
    assert legacy_result_text("old result") == "old result"
    assert legacy_result_text({"ok": False, "message": "denied"}) == "{'ok': False, 'message': 'denied'}"


def test_envelope_serializes_without_optional_none_fields():
    envelope = ResultEnvelope(ok=True, status="succeeded", message="done", retriable=False)
    assert envelope.to_dict() == {
        "ok": True, "status": "succeeded", "message": "done",
        "error_code": None, "retriable": False, "correlation_id": None,
        "policy_revision": None, "snapshot_digest": None, "data": None,
    }


@pytest.mark.asyncio
async def test_execute_tool_keeps_the_public_string_return_type(monkeypatch):
    from app.ai_chat import tools

    async def structured_handler(_args, _session, _db):
        return {"ok": False, "message": "old handler payload"}

    monkeypatch.setitem(tools.TOOL_HANDLERS, "result-envelope-test", structured_handler)
    session = SimpleNamespace(app_id=None)
    result = await tools.execute_tool("result-envelope-test", {}, session, db=None)
    assert result == "{'ok': False, 'message': 'old handler payload'}"
    assert isinstance(result, str)
