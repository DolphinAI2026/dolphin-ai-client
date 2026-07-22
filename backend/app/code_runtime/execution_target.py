"""Code runtime execution target definitions."""

from __future__ import annotations

from enum import StrEnum

from sqlalchemy import String
from sqlalchemy.types import TypeDecorator


class ExecutionTarget(StrEnum):
    CONTROL_PLANE = "control_plane"
    LOCAL_FIXTURE = "local_fixture"
    DESKTOP_AGENT_RUNTIME = "desktop_agent_runtime"


def resolve_execution_target(value: ExecutionTarget | str | None) -> ExecutionTarget:
    """Return the persisted target, treating legacy empty values as control plane."""
    if value is None or not str(value).strip():
        return ExecutionTarget.CONTROL_PLANE
    return ExecutionTarget(str(value))


class ExecutionTargetType(TypeDecorator[str]):
    """Persist only supported execution targets and normalize legacy empty rows."""

    impl = String(32)
    cache_ok = True

    def process_bind_param(self, value: ExecutionTarget | str | None, _dialect) -> str:
        try:
            return resolve_execution_target(value).value
        except ValueError as exc:
            raise ValueError(f"unsupported execution target: {value!r}") from exc

    def process_result_value(self, value: ExecutionTarget | str | None, _dialect) -> str:
        return resolve_execution_target(value).value


def is_local_runtime_target(value: ExecutionTarget | str | None) -> bool:
    return resolve_execution_target(value) in {
        ExecutionTarget.LOCAL_FIXTURE,
        ExecutionTarget.DESKTOP_AGENT_RUNTIME,
    }


def is_desktop_agent_runtime_target(value: ExecutionTarget | str | None) -> bool:
    return resolve_execution_target(value) is ExecutionTarget.DESKTOP_AGENT_RUNTIME
