"""Typed ActionRun results and one-way legacy protocol projections.

ActionRun is the source of truth.  The helpers in this module only build
compatibility payloads and tolerate failures in diagnostic sinks.
"""
from __future__ import annotations

import inspect
from dataclasses import asdict, dataclass
from typing import Any, Callable, Mapping

from app.system_assistant.telemetry import governance_telemetry, log_governance_event


RESULT_STATUSES = (
    "succeeded", "recovered", "denied", "failed", "partially_failed",
    "recovery_blocked", "outcome_unknown", "aborted",
)
SUCCESS_STATUSES = frozenset({"succeeded", "recovered"})
LEGACY_STATUS = {
    "succeeded": "success", "recovered": "success", "aborted": "aborted",
    "denied": "error", "failed": "error", "partially_failed": "error",
    "recovery_blocked": "error", "outcome_unknown": "error",
}
_STATUS_MESSAGES = {
    "succeeded": "动作执行成功",
    "recovered": "动作恢复成功",
    "denied": "当前会话不能执行该动作",
    "failed": "动作执行失败",
    "partially_failed": "动作部分失败",
    "recovery_blocked": "动作恢复被阻断",
    "outcome_unknown": "动作结果未知",
    "aborted": "动作已中止",
}


@dataclass(frozen=True)
class ResultEnvelope:
    """Stable internal result contract, populated from one ActionRun snapshot."""

    ok: bool
    status: str
    error_code: str | None = None
    message: str = ""
    retriable: bool = False
    correlation_id: str | None = None
    policy_revision: int | None = None
    snapshot_digest: str | None = None
    data: Any = None

    def __post_init__(self) -> None:
        if self.status not in RESULT_STATUSES:
            raise ValueError(f"unsupported result status: {self.status}")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def model_dump(self, **_: Any) -> dict[str, Any]:
        return self.to_dict()

    dict = to_dict


def _value(source: Any, name: str, default: Any = None) -> Any:
    if isinstance(source, Mapping):
        return source.get(name, default)
    return getattr(source, name, default)


def _status(action_run: Any) -> str:
    # result_status is the terminal result column; status is the lifecycle
    # fallback used by light-weight fakes and old rows.
    value = _value(action_run, "result_status") or _value(action_run, "status")
    value = str(value or "outcome_unknown")
    return value if value in RESULT_STATUSES else "outcome_unknown"


def _summary(action_run: Any) -> Mapping[str, Any]:
    summary = _value(action_run, "result_summary", {})
    return summary if isinstance(summary, Mapping) else {}


def _message(action_run: Any, status: str) -> str:
    summary = _summary(action_run)
    for key in ("message", "summary", "result"):
        value = summary.get(key)
        if isinstance(value, str) and value:
            return value
    return _STATUS_MESSAGES[status]


def project_action_run(action_run: Any) -> ResultEnvelope:
    """Create an envelope without mutating the authoritative ActionRun."""
    status = _status(action_run)
    error_code = _value(action_run, "error_code")
    snapshot_digest = _value(action_run, "snapshot_digest") or _summary(action_run).get("digest")
    return ResultEnvelope(
        ok=status in SUCCESS_STATUSES,
        status=status,
        error_code=error_code,
        message=_message(action_run, status),
        retriable=status in {"failed", "partially_failed", "outcome_unknown"},
        correlation_id=_value(action_run, "correlation_id"),
        policy_revision=_value(action_run, "policy_revision"),
        snapshot_digest=snapshot_digest,
        data=dict(_summary(action_run)) or None,
    )


def legacy_result_text(value: Any) -> str:
    """Preserve the old dispatcher contract: callers always receive ``str``."""
    if isinstance(value, str):
        return value
    return str(value)


def _projection_fields(action_run: Any, envelope: ResultEnvelope | None = None) -> dict[str, Any]:
    envelope = envelope or project_action_run(action_run)
    fields: dict[str, Any] = {
        "action_run_id": _value(action_run, "run_id") or _value(action_run, "action_run_id"),
        "correlation_id": envelope.correlation_id,
        "result_status": envelope.status,
        "error_code": envelope.error_code,
        "snapshot_digest": envelope.snapshot_digest,
    }
    return {key: value for key, value in fields.items() if value is not None}


def project_tool_call(action_run: Any) -> dict[str, Any]:
    """Build the additive AIChatToolCall/SSE-compatible result payload."""
    envelope = project_action_run(action_run)
    return {"status": LEGACY_STATUS[envelope.status], **_projection_fields(action_run, envelope)}


def apply_tool_call_projection(tool_call: Any, action_run: Any) -> Any:
    """Copy only nullable compatibility fields onto an existing ToolCall row."""
    for key, value in _projection_fields(action_run).items():
        if hasattr(tool_call, key):
            setattr(tool_call, key, value)
    tool_call.status = LEGACY_STATUS[_status(action_run)]
    return tool_call


def project_action_run_to_tool_call(action_run: Any, tool_call: Any | None = None) -> Any:
    if tool_call is None:
        return project_tool_call(action_run)
    return apply_tool_call_projection(tool_call, action_run)


def project_sse_end(
    action_run: Any,
    *,
    tool_call_id: Any = None,
    tool_name: str | None = None,
    result_text: Any = "",
    duration_ms: int | None = None,
) -> dict[str, Any]:
    """Build the existing ``tool_call_end`` event with optional governance fields."""
    envelope = project_action_run(action_run)
    data: dict[str, Any] = {
        "id": tool_call_id,
        "tool_name": tool_name,
        "status": LEGACY_STATUS[envelope.status],
        "result_text": legacy_result_text(result_text),
    }
    if duration_ms is not None:
        data["duration_ms"] = duration_ms
    data.update(_projection_fields(action_run, envelope))
    data["policy_revision"] = envelope.policy_revision
    data = {key: value for key, value in data.items() if value is not None}
    return {"event": "tool_call_end", "data": data}


def project_sse_start(
    action_run: Any,
    *,
    tool_call_id: Any = None,
    tool_name: str | None = None,
    args: Any = None,
) -> dict[str, Any]:
    """Build the unchanged ``tool_call_start`` event plus nullable identifiers."""
    data = {"id": tool_call_id, "tool_name": tool_name, "args": args}
    data.update(_projection_fields(action_run))
    return {
        "event": "tool_call_start",
        "data": {key: value for key, value in data.items() if value is not None},
    }


def _agent_step_payload(
    action_run: Any,
    *,
    result_text: Any = "",
) -> dict[str, Any]:
    """Build an AgentStep compatibility payload without touching a recorder."""
    envelope = project_action_run(action_run)
    return {
        "status": LEGACY_STATUS[envelope.status],
        "result_text": legacy_result_text(result_text),
        **_projection_fields(action_run, envelope),
    }


async def project_agent_step(
    action_run: Any,
    *,
    result_text: Any = "",
    recorder: Callable[[dict[str, Any]], Any] | None = None,
) -> dict[str, Any]:
    """Build an AgentStep projection and await an async recorder if provided."""
    envelope = project_action_run(action_run)
    payload = _agent_step_payload(action_run, result_text=result_text)
    if recorder is not None:
        try:
            recorded = recorder(payload)
            if inspect.isawaitable(recorded):
                await recorded
            governance_telemetry.record_observability_projection("success")
        except Exception:
            governance_telemetry.record_observability_projection("failed")
            log_governance_event(
                "observability_projection_failed",
                correlation_id=envelope.correlation_id,
                error_code="RECORDER_STEP_FAILED",
            )
    return payload


def apply_agent_step_projection(agent_step: Any, action_run: Any, *, result_text: Any = "") -> Any:
    payload = _agent_step_payload(action_run, result_text=result_text)
    for key, value in payload.items():
        if hasattr(agent_step, key):
            setattr(agent_step, key, value)
    return agent_step


async def project_action_run_to_agent_step(
    action_run: Any, agent_step: Any | None = None, *, result_text: Any = ""
) -> Any:
    if agent_step is None:
        return await project_agent_step(action_run, result_text=result_text)
    return apply_agent_step_projection(agent_step, action_run, result_text=result_text)


# Explicit aliases keep the adapter discoverable to existing callers.
to_result_envelope = project_action_run
action_run_to_envelope = project_action_run
to_legacy_result_text = legacy_result_text
action_run_to_tool_call = project_tool_call
action_run_to_sse = project_sse_end
action_run_to_agent_step = project_agent_step
build_result_envelope = project_action_run
project_action_run_to_sse = project_sse_end
