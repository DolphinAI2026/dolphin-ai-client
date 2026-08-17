"""B0 local audit port. It is diagnostic only, never a Control Plane audit sink."""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Protocol

from app.system_assistant.telemetry import (
    GovernanceTelemetryRegistry,
    governance_telemetry,
    log_governance_event,
    redact_log_fields,
)


class AuditPort(Protocol):
    def record(self, event: Mapping[str, Any]) -> bool | None: ...


class InMemoryAuditPort:
    """Small local fake for tests and diagnostics; data is process-local only."""

    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []

    def record(self, event: Mapping[str, Any]) -> bool:
        self.events.append(dict(event))
        return True


class BestEffortAuditAdapter:
    """Write to a local port without affecting an ActionRun or its transaction."""

    def __init__(
        self,
        port: AuditPort,
        *,
        telemetry: GovernanceTelemetryRegistry = governance_telemetry,
    ) -> None:
        self._port = port
        self._telemetry = telemetry

    def record(self, event: str, /, **fields: Any) -> bool:
        payload = {"event": str(event), **redact_log_fields(fields)}
        try:
            delivered = self._port.record(payload)
        except Exception:
            self._record_delivery_gap(fields)
            return False
        if delivered is False:
            self._record_delivery_gap(fields)
            return False
        return True

    def _record_delivery_gap(self, fields: Mapping[str, Any]) -> None:
        self._telemetry.record_audit_gap()
        log_governance_event(
            "local_audit_failed",
            **{**fields, "error_code": "AUDIT_DELIVERY_FAILED"},
        )

    record_event = record
