from __future__ import annotations


class RaisingAuditPort:
    def __init__(self) -> None:
        self.calls = 0

    def record(self, event):
        self.calls += 1
        raise RuntimeError("local audit unavailable")


def test_best_effort_audit_failure_does_not_escape_and_increments_gap():
    from app.system_assistant.audit_adapter import BestEffortAuditAdapter
    from app.system_assistant.telemetry import GovernanceTelemetryRegistry

    telemetry = GovernanceTelemetryRegistry()
    adapter = BestEffortAuditAdapter(RaisingAuditPort(), telemetry=telemetry)

    assert adapter.record(
        "action_terminal",
        correlation_id="corr-1",
        session_public_id="session-1",
        object_digest="digest-1",
        capability_id="code.workspace.edit",
        policy_revision=3,
        execution_generation=2,
        error_code=None,
    ) is False
    assert telemetry.snapshot()["system_assistant_audit_gap_total"] == 1


def test_local_fake_records_allowlisted_event_without_calling_remote_control_plane():
    from app.system_assistant.audit_adapter import InMemoryAuditPort

    port = InMemoryAuditPort()
    assert port.record({"event": "access_compare", "result": "allow"}) is True
    assert port.events == [{"event": "access_compare", "result": "allow"}]
