"""P0 system-assistant profile boundary and legacy AIChat regressions."""

from __future__ import annotations

import pytest
from sqlalchemy import inspect as sqlalchemy_inspect, select, text
from sqlalchemy.ext.asyncio import create_async_engine
from pydantic import ValidationError

from app.database import migrate_ai_chat_session_profile
from app.models.ai_chat import AIChatSession
from app.system_assistant.contracts import (
    AssistantProfile,
    AssistantProfileRequest,
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


@pytest.mark.asyncio
async def test_sqlite_old_sessions_are_migrated_in_place():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.execute(text(
            "CREATE TABLE ai_chat_sessions ("
            "id INTEGER PRIMARY KEY, mode VARCHAR(20) NOT NULL"
            ")"
        ))
        await conn.execute(text(
            "INSERT INTO ai_chat_sessions (id, mode) VALUES "
            "(1, 'chat'), (2, 'cowork'), (3, 'code')"
        ))
        await migrate_ai_chat_session_profile(conn)
        columns = await conn.run_sync(
            lambda sync_conn: sqlalchemy_inspect(sync_conn).get_columns("ai_chat_sessions")
        )
        rows = (await conn.execute(
            select(text("id"), text("mode"), text("assistant_profile"))
            .select_from(text("ai_chat_sessions"))
            .order_by(text("id"))
        )).all()
        default_row = (await conn.execute(text(
            "INSERT INTO ai_chat_sessions (id, mode) VALUES (4, 'chat') "
            "RETURNING assistant_profile"
        ))).scalar_one()
    await engine.dispose()

    profile_column = next(column for column in columns if column["name"] == "assistant_profile")
    assert profile_column["nullable"] is False
    assert [tuple(row) for row in rows] == [
        (1, "chat", "entry_agent"),
        (2, "cowork", "entry_agent"),
        (3, "code", "entry_agent"),
    ]
    assert default_row == "entry_agent"
