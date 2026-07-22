"""Code runtime execution target definitions."""

from __future__ import annotations

from enum import StrEnum


class ExecutionTarget(StrEnum):
    CONTROL_PLANE = "control_plane"
    LOCAL_FIXTURE = "local_fixture"
    DESKTOP_AGENT_RUNTIME = "desktop_agent_runtime"


def resolve_execution_target(value: ExecutionTarget | str | None) -> ExecutionTarget:
    """Return the persisted target, treating legacy empty values as control plane."""
    if value is None or not str(value).strip():
        return ExecutionTarget.CONTROL_PLANE
    return ExecutionTarget(str(value))


def is_local_runtime_target(value: ExecutionTarget | str | None) -> bool:
    return resolve_execution_target(value) in {
        ExecutionTarget.LOCAL_FIXTURE,
        ExecutionTarget.DESKTOP_AGENT_RUNTIME,
    }


def is_desktop_agent_runtime_target(value: ExecutionTarget | str | None) -> bool:
    return resolve_execution_target(value) is ExecutionTarget.DESKTOP_AGENT_RUNTIME
