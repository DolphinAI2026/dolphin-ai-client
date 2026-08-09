"""Stable P0 contracts for the Code system-assistant conversation profile.

The profile is deliberately orthogonal to ``AIChatSession.mode``.  ``mode``
continues to select the legacy chat/cowork/code behavior while this contract
only identifies the conversation entry point.  Runtime operation and asset
contracts belong to a later phase and should not be added here.
"""

from __future__ import annotations

from enum import Enum
from typing import Literal, TypeAlias, cast

from pydantic import BaseModel, field_validator


class AssistantProfile(str, Enum):
    """Conversation entry profiles supported by the P0 migration boundary."""

    ENTRY_AGENT = "entry_agent"
    SYSTEM_ASSISTANT = "system_assistant"


AssistantProfileValue: TypeAlias = Literal["entry_agent", "system_assistant"]
DEFAULT_ASSISTANT_PROFILE = AssistantProfile.ENTRY_AGENT.value
SUPPORTED_ASSISTANT_PROFILES = frozenset(profile.value for profile in AssistantProfile)


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
