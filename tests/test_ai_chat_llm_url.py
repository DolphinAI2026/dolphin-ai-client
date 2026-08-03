import asyncio
import json

import httpx
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.ai_chat.agent import (
    LLMConfigSnapshot,
    _build_initial_messages,
    _compact_tool_result_for_context,
    _format_llm_error,
    _is_retryable_llm_error,
    _llm_chat_completions_url,
)
from app.database import Base
import app.models  # noqa: F401 - register ORM models
from app.models import AIChatMessage, AIChatSession


def test_ai_chat_uses_openai_compatible_v1_chat_url_for_gateway_base():
    cfg = LLMConfigSnapshot(
        base_url="http://ai-agent.dfy.definesys.cn/omnigate/0",
        api_key="test-key",
        model="gpt-5.5",
        max_tokens=1024,
        temperature=0.3,
    )

    assert (
        _llm_chat_completions_url(cfg)
        == "http://ai-agent.dfy.definesys.cn/omnigate/0/v1/chat/completions"
    )


def test_ai_chat_preserves_full_chat_completions_url():
    cfg = LLMConfigSnapshot(
        base_url="http://ai-agent.dfy.definesys.cn/omnigate/0/v1/chat/completions",
        api_key="test-key",
        model="gpt-5.5",
        max_tokens=1024,
        temperature=0.3,
    )

    assert (
        _llm_chat_completions_url(cfg)
        == "http://ai-agent.dfy.definesys.cn/omnigate/0/v1/chat/completions"
    )


def test_ai_chat_treats_read_error_as_retryable_gateway_error():
    exc = httpx.ReadError("server disconnected while reading response")

    assert _is_retryable_llm_error(exc) is True
    assert _format_llm_error(exc) == "模型网关读取响应失败，请稍后重试。"


def test_ai_chat_formats_remote_protocol_error_as_gateway_disconnect():
    exc = httpx.RemoteProtocolError("Server disconnected without sending a response.")

    assert _is_retryable_llm_error(exc) is True
    assert _format_llm_error(exc) == "模型网关连接中途断开，未返回完整响应，请稍后重试。"


def test_ai_chat_compacts_large_provider_tool_result_for_next_request():
    payload = {
        "ok": True,
        "menu_id": "menu-1",
        "message": "保存成功",
        "platform_response": {
            "code": "ok",
            "message": "保存成功",
            "data": {"nodes": [{"id": str(i), "definition": "x" * 2000} for i in range(30)]},
        },
    }

    compacted = _compact_tool_result_for_context(json.dumps(payload, ensure_ascii=False))
    result = json.loads(compacted)

    assert len(compacted) <= 24_000
    assert result["ok"] is True
    assert result["menu_id"] == "menu-1"
    assert result["platform_response"]["_omitted_large_fields"] is True
    assert "data" not in result["platform_response"]


def test_build_initial_messages_skips_llm_error_notices():
    async def run():
        engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        SessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        try:
            async with SessionLocal() as db:
                session = AIChatSession(tenant_id=1, user_id=1, title="测试会话")
                db.add(session)
                await db.commit()
                await db.refresh(session)

                db.add_all([
                    AIChatMessage(session_id=session.id, role="user", content="读取附件"),
                    AIChatMessage(
                        session_id=session.id,
                        role="assistant",
                        content="本轮执行中断：模型调用失败：Server disconnected.",
                        extra_meta={"notice_type": "llm_error", "run_id": "run_1"},
                    ),
                    AIChatMessage(session_id=session.id, role="user", content="继续"),
                ])
                await db.commit()

                messages = await _build_initial_messages(db, session, "继续")
                contents = [m.get("content") for m in messages if isinstance(m.get("content"), str)]

                assert "读取附件" in contents
                assert "继续" in contents
                assert not any("本轮执行中断" in content for content in contents)
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_build_initial_messages_skips_legacy_llm_error_notices():
    async def run():
        engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        SessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        try:
            async with SessionLocal() as db:
                session = AIChatSession(tenant_id=1, user_id=1, title="测试会话")
                db.add(session)
                await db.commit()
                await db.refresh(session)

                db.add_all([
                    AIChatMessage(session_id=session.id, role="user", content="继续"),
                    AIChatMessage(
                        session_id=session.id,
                        role="assistant",
                        content="本轮执行中断：模型调用失败：ReadError。已完成的工具结果会保留，可稍后重试。",
                    ),
                    AIChatMessage(session_id=session.id, role="user", content="继续"),
                ])
                await db.commit()

                messages = await _build_initial_messages(db, session, "继续")
                contents = [m.get("content") for m in messages if isinstance(m.get("content"), str)]

                assert not any("ReadError" in content for content in contents)
        finally:
            await engine.dispose()

    asyncio.run(run())
