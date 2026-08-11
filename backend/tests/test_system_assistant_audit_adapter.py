from __future__ import annotations

import logging

class RaisingAuditPort:
    def __init__(self) -> None:
        self.calls = 0

    def record(self, event):
        self.calls += 1
        raise RuntimeError("local audit unavailable")


class FalseAuditPort:
    def record(self, event):
        return False


def test_best_effort_audit_failure_does_not_escape_and_only_increments_gap():
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
    snapshot = telemetry.snapshot()
    assert snapshot["system_assistant_audit_gap_total"] == 1
    assert snapshot['system_assistant_observability_projection_total{result="failed"}'] == 0


def test_false_audit_delivery_only_increments_gap_and_logs_allowlisted_fields(caplog):
    from app.system_assistant.audit_adapter import BestEffortAuditAdapter
    from app.system_assistant.telemetry import GovernanceTelemetryRegistry

    telemetry = GovernanceTelemetryRegistry()
    with caplog.at_level(logging.INFO, logger="system_assistant"):
        assert BestEffortAuditAdapter(FalseAuditPort(), telemetry=telemetry).record(
            "action_terminal",
            correlation_id="corr-1",
            token="SENSITIVE-CANARY-token-123",
        ) is False

    snapshot = telemetry.snapshot()
    assert snapshot["system_assistant_audit_gap_total"] == 1
    assert snapshot['system_assistant_observability_projection_total{result="failed"}'] == 0
    message = "\n".join(record.getMessage() for record in caplog.records)
    assert "corr-1" in message
    assert "SENSITIVE-CANARY-token-123" not in message


def test_local_fake_records_allowlisted_event_without_calling_remote_control_plane():
    from app.system_assistant.audit_adapter import InMemoryAuditPort

    port = InMemoryAuditPort()
    assert port.record({"event": "access_compare", "result": "allow"}) is True
    assert port.events == [{"event": "access_compare", "result": "allow"}]
