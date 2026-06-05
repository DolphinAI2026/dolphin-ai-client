"""Task 5: reconstruct active deferred tools from session history.

Tests for _parse_activated and _reconstruct_active_tools in agent.py.
"""
import json
import pytest
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.pool import StaticPool
from app.database import Base
import app.models.ai_chat  # noqa: F401  (register tables)
from app.models.ai_chat import AIChatSession, AIChatToolCall
from app.ai_chat.agent import _reconstruct_active_tools, _parse_activated


def test_parse_activated():
    assert set(_parse_activated(json.dumps({"activated": ["a", "b"]}))) == {"a", "b"}
    assert _parse_activated("not json") == []
    assert _parse_activated(json.dumps({"ok": True})) == []   # no activated key
    assert _parse_activated("") == []


@pytest.mark.asyncio
async def test_reconstruct_active_from_history():
    from sqlalchemy.ext.asyncio import async_sessionmaker
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False}, poolclass=StaticPool,
    )
    async with engine.begin() as c:
        await c.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with Session() as db:
        s = AIChatSession(tenant_id=1, user_id=1, title="t")
        db.add(s); await db.flush()
        db.add(AIChatToolCall(session_id=s.id, tool_name="search_tools", status="success",
                              result_text=json.dumps({"activated": ["update_apaas_model_field"]})))
        db.add(AIChatToolCall(session_id=s.id, tool_name="list_apaas_app_models", status="success", result_text="..."))
        await db.commit()
        active = await _reconstruct_active_tools(db, s)
    assert "update_apaas_model_field" in active   # from search_tools activated
    assert "list_apaas_app_models" in active      # fallback: already-called tool stays available
