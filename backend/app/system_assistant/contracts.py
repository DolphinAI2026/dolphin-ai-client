"""Stable P0 contracts for the Code system-assistant conversation profile.

The profile is deliberately orthogonal to ``AIChatSession.mode``.  ``mode``
continues to select the legacy chat/cowork/code behavior while this contract
only identifies the conversation entry point.  Runtime operation and asset
contracts belong to a later phase and should not be added here.
"""

from __future__ import annotations

from enum import Enum
from datetime import datetime
from typing import Any, Literal, TypeAlias, cast

from pydantic import BaseModel, Field, field_validator


class AssistantProfile(str, Enum):
    """Conversation entry profiles supported by the P0 migration boundary."""

    ENTRY_AGENT = "entry_agent"
    SYSTEM_ASSISTANT = "system_assistant"


AssistantProfileValue: TypeAlias = Literal["entry_agent", "system_assistant"]
AssistantModelPurpose: TypeAlias = Literal["builder", "coding"]
DEFAULT_ASSISTANT_PROFILE = AssistantProfile.ENTRY_AGENT.value
SUPPORTED_ASSISTANT_PROFILES = frozenset(profile.value for profile in AssistantProfile)

BaselineStatus: TypeAlias = Literal[
    "ready", "partial", "missing", "stale", "unavailable", "not_needed"
]
SourceStatus: TypeAlias = Literal["ready", "partial", "unavailable"]
SystemAssistantExecutionMode: TypeAlias = Literal["local", "remote"]


class BaselineNode(BaseModel):
    """A category in the read-only P0 baseline snapshot."""

    id: str
    label: str
    status: BaselineStatus
    source_status: SourceStatus
    items: list[dict[str, Any]] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class RecommendedAction(BaseModel):
    """At most one route draft is recommended in P0."""

    id: str
    status: BaselineStatus
    title: str
    reason: str


class BaselineSnapshotMetadata(BaseModel):
    """P0 source coverage diagnostics without inventing a runtime plan."""

    plan_created: Literal[False] = False
    dynamic_plan_source: Literal["not_available_in_p0"] = "not_available_in_p0"
    unavailable_sources: list[str] = Field(default_factory=list)
    partial_sources: list[str] = Field(default_factory=list)


class BaselineSnapshot(BaseModel):
    """Typed read-only baseline returned to the Code client."""

    version: Literal["p0"] = "p0"
    readonly: Literal[True] = True
    tenant_id: int
    generated_at: datetime
    nodes: list[BaselineNode]
    metadata: BaselineSnapshotMetadata


class SystemAssistantExecution(BaseModel):
    """Configured execution boundary, distinct from model and asset sources."""

    configured_mode: SystemAssistantExecutionMode
    remote_runtime_available: bool
    local_directory_access: bool


class BootstrapResponse(BaseModel):
    """Stable response shape for ``GET /system-assistant/bootstrap``."""

    baseline_snapshot: BaselineSnapshot
    recommended_action: RecommendedAction
    available_actions: list[str]
    source_status: dict[str, SourceStatus]
    execution: SystemAssistantExecution


def normalize_assistant_profile(value: str | AssistantProfile | None) -> AssistantProfileValue:
    """Return a canonical profile value, defaulting legacy sessions safely.

    ``None`` and whitespace-only values represent an omitted field.  Any other
    unknown value is rejected instead of silently changing the session's
    behavior.
    """

    if value is None:
        return cast(AssistantProfileValue, DEFAULT_ASSISTANT_PROFILE)
    normalized = value.value if isinstance(value, AssistantProfile) else str(value).strip()
    if not normalized:
        return cast(AssistantProfileValue, DEFAULT_ASSISTANT_PROFILE)
    if normalized not in SUPPORTED_ASSISTANT_PROFILES:
        raise ValueError(
            f"未知 assistant_profile: {normalized!r} "
            f"(已知: {sorted(SUPPORTED_ASSISTANT_PROFILES)})"
        )
    return cast(AssistantProfileValue, normalized)


def assistant_model_purpose(
    value: str | AssistantProfile | None,
) -> AssistantModelPurpose:
    """Use Coding models only for the Code system-assistant profile."""

    profile = normalize_assistant_profile(value)
    return "coding" if profile == AssistantProfile.SYSTEM_ASSISTANT.value else "builder"


class AssistantProfileRequest(BaseModel):
    """Reusable request fragment for session create/update APIs."""

    assistant_profile: AssistantProfileValue = DEFAULT_ASSISTANT_PROFILE

    @field_validator("assistant_profile", mode="before")
    @classmethod
    def _normalize_profile(cls, value: str | AssistantProfile | None) -> AssistantProfileValue:
        return normalize_assistant_profile(value)

class AssistantProfileResponse(BaseModel):
    """The profile field returned in a session representation."""

    assistant_profile: AssistantProfileValue = DEFAULT_ASSISTANT_PROFILE

    @field_validator("assistant_profile", mode="before")
    @classmethod
    def _normalize_profile(cls, value: str | AssistantProfile | None) -> AssistantProfileValue:
        return normalize_assistant_profile(value)
