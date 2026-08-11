"""Bounded, local-only telemetry primitives for B0 governance operations."""
from __future__ import annotations

import json
import logging
import re
import threading
from collections import OrderedDict
from collections.abc import Mapping
from itertools import product
from typing import Any


ALLOWED_LOG_KEYS = frozenset({
    "correlation_id",
    "session_public_id",
    "object_digest",
    "capability_id",
    "policy_revision",
    "execution_generation",
    "error_code",
})

_PROJECTION_RESULTS = ("success", "failure", "unavailable", "not_modified")
_SNAPSHOT_RESULTS = ("success", "failure", "stale", "unavailable")
_ACCESS_DECISIONS = ("allow", "deny", "not_enforceable", "other")
_ACCESS_RESULTS = ("match", "mismatch", "failure")
_TICKET_TRANSITIONS = (
    "issued_to_authorized",
    "authorized_to_reserved",
    "authorized_to_expired",
    "issued_to_revoked",
    "other",
)
_TRANSITION_RESULTS = ("success", "conflict", "failure")
_RUN_STATUSES = (
    "prepared", "authorized", "executing", "succeeded", "failed",
    "partially_failed", "recovered", "recovery_blocked", "outcome_unknown", "aborted",
)
_TERMINAL_STATUSES = frozenset(_RUN_STATUSES[3:])
_CAPABILITY_IDS = (
    "code.workspace.edit",
    "code.workspace.read",
    "code.build",
    "code.preview",
    "system_assistant.project_result",
)
_RECOVERY_RESULTS = ("recovered", "blocked", "skipped", "failure")
_LATE_COMPLETION_RESULTS = ("ignored", "recorded", "failure")
_OBSERVABILITY_RESULTS = ("success", "failed")
_SAFE_POLICY_REVISIONS = tuple(str(value) for value in range(10))
_MAX_TERMINAL_RUN_KEYS = 4096
_SENSITIVE_VALUE = re.compile(
    r"(?:token|secret|password|authorization|apikey|api[_-]?key|"
    r"postgres(?:ql)?|mysql|mongodb|redis|amqp)|"
    r"(?:postgres(?:ql)?|mysql|mongodb|redis|amqp)://",
    re.IGNORECASE,
)


def _label(value: Any, allowed: tuple[str, ...], fallback: str = "other") -> str:
    normalized = str(value or "").strip().lower()
    return normalized if normalized in allowed else fallback


def _series(name: str, **labels: str) -> str:
    if not labels:
        return name
    rendered = ",".join(f'{key}="{value}"' for key, value in sorted(labels.items()))
    return f"{name}{{{rendered}}}"


def _safe_log_value(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float)):
        return value
    text = str(value).replace("\n", " ").replace("\r", " ").strip()
    if _SENSITIVE_VALUE.search(text):
        return "redacted"
    return text[:160]


def redact_log_fields(fields: Mapping[str, Any]) -> dict[str, Any]:
    """Return the only governance fields allowed to reach local logs."""
    return {
        key: _safe_log_value(value)
        for key, value in fields.items()
        if key in ALLOWED_LOG_KEYS and value is not None
    }


def log_governance_event(event: str, /, **fields: Any) -> None:
    """Emit a structured, allowlisted local diagnostic without exception details."""
    payload = redact_log_fields(fields)
    logging.getLogger("system_assistant").info(
        "governance_event=%s fields=%s",
        _safe_log_value(event),
        json.dumps(payload, sort_keys=True, separators=(",", ":")),
    )


class GovernanceTelemetryRegistry:
    """In-process counter registry; it has no exporter or lifecycle of its own."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._counters: dict[str, float] = {}
        self._terminal_runs: OrderedDict[str, None] = OrderedDict()
        self._initialize()

    def _initialize(self) -> None:
        for result in _PROJECTION_RESULTS:
            self._counters[_series("system_assistant_projection_load_total", result=result)] = 0.0
        for result, revision in product(_SNAPSHOT_RESULTS, _SAFE_POLICY_REVISIONS + ("other",)):
            self._counters[_series("system_assistant_snapshot_total", result=result, policy_revision=revision)] = 0.0
        for legacy, current, result in product(_ACCESS_DECISIONS, _ACCESS_DECISIONS, _ACCESS_RESULTS):
            self._counters[_series(
                "system_assistant_access_compare_total", legacy=legacy, new=current, result=result
            )] = 0.0
        for transition, result in product(_TICKET_TRANSITIONS, _TRANSITION_RESULTS):
            self._counters[_series(
                "system_assistant_ticket_transition_total", transition=transition, result=result
            )] = 0.0
        for status, capability_id in product(_RUN_STATUSES, _CAPABILITY_IDS + ("other",)):
            self._counters[_series(
                "system_assistant_run_transition_total", status=status, capability_id=capability_id
            )] = 0.0
        for result in _RECOVERY_RESULTS:
            self._counters[_series("system_assistant_recovery_total", result=result)] = 0.0
        for result in _LATE_COMPLETION_RESULTS:
            self._counters[_series("system_assistant_late_completion_total", result=result)] = 0.0
        for result in _OBSERVABILITY_RESULTS:
            self._counters[_series(
                "system_assistant_observability_projection_total", result=result
            )] = 0.0
        self._counters["system_assistant_audit_gap_total"] = 0.0

    def _increment(self, name: str, **labels: str) -> None:
        key = _series(name, **labels)
        with self._lock:
            self._counters[key] += 1

    def record_projection(self, result: str) -> None:
        normalized = "not_modified" if str(result) == "304" else _label(result, _PROJECTION_RESULTS, "failure")
        self._increment("system_assistant_projection_load_total", result=normalized)

    def record_snapshot(self, result: str, policy_revision: Any) -> None:
        revision = _label(policy_revision, _SAFE_POLICY_REVISIONS)
        self._increment(
            "system_assistant_snapshot_total",
            result=_label(result, _SNAPSHOT_RESULTS, "failure"),
            policy_revision=revision,
        )

    def record_access_compare(self, legacy: str, current: str, result: str) -> None:
        self._increment(
            "system_assistant_access_compare_total",
            legacy=_label(legacy, _ACCESS_DECISIONS),
            new=_label(current, _ACCESS_DECISIONS),
            result=_label(result, _ACCESS_RESULTS, "failure"),
        )

    def record_ticket_transition(self, transition: str, result: str) -> None:
        self._increment(
            "system_assistant_ticket_transition_total",
            transition=_label(transition, _TICKET_TRANSITIONS),
            result=_label(result, _TRANSITION_RESULTS, "failure"),
        )

    def record_run_transition(
        self,
        status: str,
        capability_id: str,
        *,
        run_id: str | None = None,
        cas_won: bool = True,
    ) -> None:
        normalized_status = _label(status, _RUN_STATUSES, "failed")
        if normalized_status in _TERMINAL_STATUSES:
            if not cas_won:
                return
            if run_id:
                with self._lock:
                    if run_id in self._terminal_runs:
                        return
                    self._terminal_runs[run_id] = None
                    if len(self._terminal_runs) > _MAX_TERMINAL_RUN_KEYS:
                        self._terminal_runs.popitem(last=False)
        self._increment(
            "system_assistant_run_transition_total",
            status=normalized_status,
            capability_id=_label(capability_id, _CAPABILITY_IDS),
        )

    def record_recovery(self, result: str) -> None:
        self._increment("system_assistant_recovery_total", result=_label(result, _RECOVERY_RESULTS, "failure"))

    def record_late_completion(self, result: str) -> None:
        self._increment(
            "system_assistant_late_completion_total",
            result=_label(result, _LATE_COMPLETION_RESULTS, "failure"),
        )

    def record_observability_projection(self, result: str) -> None:
        self._increment(
            "system_assistant_observability_projection_total",
            result=_label(result, _OBSERVABILITY_RESULTS, "failed"),
        )

    def record_audit_gap(self) -> None:
        self._increment("system_assistant_audit_gap_total")

    def snapshot(self) -> dict[str, float]:
        with self._lock:
            return dict(self._counters)

    def render(self) -> str:
        lines = [
            "# TYPE system_assistant_projection_load_total counter",
            "# TYPE system_assistant_snapshot_total counter",
            "# TYPE system_assistant_access_compare_total counter",
            "# TYPE system_assistant_ticket_transition_total counter",
            "# TYPE system_assistant_run_transition_total counter",
            "# TYPE system_assistant_recovery_total counter",
            "# TYPE system_assistant_late_completion_total counter",
            "# TYPE system_assistant_observability_projection_total counter",
            "# TYPE system_assistant_audit_gap_total counter",
        ]
        lines.extend(f"{name} {value:g}" for name, value in sorted(self.snapshot().items()))
        return "\n".join(lines) + "\n"


governance_telemetry = GovernanceTelemetryRegistry()
