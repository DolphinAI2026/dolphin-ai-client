"""P0 system-assistant profile boundary and legacy AIChat regressions."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.models.ai_chat import AIChatAttachment, AIChatSession
from app.system_assistant.contracts import (
    AssistantAttachmentRef,
    AssistantProfile,
    AssistantProfileRequest,
    AssistantSessionRecovery,
    DEFAULT_ASSISTANT_PROFILE,
    normalize_assistant_profile,
)


def test_supported_profiles_are_separate_from_legacy_modes():
    assert normalize_assistant_profile(None) == DEFAULT_ASSISTANT_PROFILE
    assert AssistantProfileRequest().assistant_profile == "entry_agent"
    assert AssistantProfileRequest(assistant_profile="system_assistant").assistant_profile == "system_assistant"
    assert {"chat", "cowork", "code"}.isdisjoint({p.value for p in AssistantProfile})


def test_unknown_profile_is_rejected():
    with pytest.raises(ValueError, match="未知 assistant_profile"):
        normalize_assistant_profile("system_assistant_v2")
    with pytest.raises(ValidationError):
        AssistantProfileRequest(assistant_profile="system_assistant_v2")


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["chat", "cowork", "code"])
async def test_legacy_session_defaults_to_entry_agent_without_changing_mode(db_session, mode):
    column = AIChatSession.__table__.c.assistant_profile
    assert column.nullable is False
    assert str(column.server_default.arg) == DEFAULT_ASSISTANT_PROFILE

    session = AIChatSession(tenant_id=1, user_id=1, mode=mode, title="legacy")
    assert session.mode == mode
    db_session.add(session)
    await db_session.flush()
    # An omitted profile persists as entry_agent without callers rewriting the
    # existing code mode.
    assert session.assistant_profile == DEFAULT_ASSISTANT_PROFILE


def test_existing_attachment_reference_and_recovery_shapes_remain_stable():
    ref = AssistantAttachmentRef(attachment_ids=[3, 3, 8])
    assert ref.attachment_ids == [3, 8]

    recovery = AssistantSessionRecovery(running=True, last_seq=12, run_id="run-1")
    assert recovery.model_dump() == {"running": True, "last_seq": 12, "run_id": "run-1"}

    attachment = AIChatAttachment(
        session_id=7,
        filename="requirements.md",
        kind="md",
        mime="text/markdown",
        size_bytes=42,
        content_text="# Requirements",
    )
    assert attachment.filename == "requirements.md"
    assert attachment.kind == "md"
    assert attachment.content_text == "# Requirements"
    assert attachment.image_data_url is None
