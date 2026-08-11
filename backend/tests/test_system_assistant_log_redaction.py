from __future__ import annotations

import logging


def test_structured_governance_log_is_allowlisted_and_sensitive_canary_is_absent(caplog):
    from app.system_assistant.telemetry import log_governance_event

    canary = "SENSITIVE-CANARY-token-123"
    with caplog.at_level(logging.INFO, logger="system_assistant"):
        log_governance_event(
            "projection_failed",
            correlation_id="corr-1",
            session_public_id="session-1",
            object_digest="digest-1",
            capability_id="code.workspace.edit",
            policy_revision=4,
            execution_generation=2,
            error_code="projection_unavailable",
            token=canary,
            args={"body": canary},
            file_body=canary,
        )

    message = "\n".join(record.getMessage() for record in caplog.records)
    assert canary not in message
    assert "token" not in message.lower()
    assert "args" not in message.lower()
    assert "file_body" not in message.lower()
    assert "correlation_id" in message
