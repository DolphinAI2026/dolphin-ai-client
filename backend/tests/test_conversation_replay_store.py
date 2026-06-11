"""会话富回放落库(conversation_replays) — replay_store 单测。

背景: 旧方案是工作区单文件 chat-replay.json 按 conversation_id 独占,
同工作区多会话互踩(实测踩过)。DB 按会话各存一行, append 时与已有内容
用 ─── 分隔 merge。
"""
from __future__ import annotations

import json

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.database import Base
from app.coding.replay_store import (
    _MAX_REPLAY_MESSAGES,
    append_conversation_replay,
    load_conversation_replay,
)
from app.models.conversation_replay import ConversationReplay


@pytest_asyncio.fixture
async def session():
    from sqlalchemy.pool import StaticPool

    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with Session() as s:
        yield s
    await engine.dispose()


@pytest.mark.asyncio
async def test_append_then_load_roundtrip(session):
    turn1 = [{"type": "user", "content": "问"}, {"type": "message", "content": "答"}]
    await append_conversation_replay(session, 11, turn1)
    assert await load_conversation_replay(session, 11) == turn1
    # 别的会话互不影响
    assert await load_conversation_replay(session, 12) == []


@pytest.mark.asyncio
async def test_append_merges_with_separator(session):
    await append_conversation_replay(session, 11, [{"type": "user", "content": "第一轮"}])
    await append_conversation_replay(session, 11, [{"type": "user", "content": "第二轮"}])
    out = await load_conversation_replay(session, 11)
    assert [m["content"] for m in out] == ["第一轮", "───", "第二轮"]
    assert out[1]["type"] == "status"


@pytest.mark.asyncio
async def test_two_conversations_do_not_clobber(session):
    """核心回归: 同工作区两个会话各自保留回放(旧文件方案会互踩)。"""
    await append_conversation_replay(session, 11, [{"type": "message", "content": "会话A"}])
    await append_conversation_replay(session, 22, [{"type": "message", "content": "会话B"}])
    assert (await load_conversation_replay(session, 11))[0]["content"] == "会话A"
    assert (await load_conversation_replay(session, 22))[0]["content"] == "会话B"


@pytest.mark.asyncio
async def test_cap_keeps_latest(session):
    big = [{"type": "status", "content": str(i)} for i in range(_MAX_REPLAY_MESSAGES + 50)]
    await append_conversation_replay(session, 11, big)
    out = await load_conversation_replay(session, 11)
    assert len(out) == _MAX_REPLAY_MESSAGES
    assert out[-1]["content"] == str(_MAX_REPLAY_MESSAGES + 49)


@pytest.mark.asyncio
async def test_corrupt_existing_row_overwritten_not_crash(session):
    session.add(ConversationReplay(conversation_id=11, stream_messages="not-json"))
    await session.commit()
    await append_conversation_replay(session, 11, [{"type": "user", "content": "新"}])
    out = await load_conversation_replay(session, 11)
    assert [m["content"] for m in out] == ["新"]
    # 落库的是合法 JSON
    row = (await session.execute(
        select(ConversationReplay).where(ConversationReplay.conversation_id == 11)
    )).scalar_one()
    assert json.loads(row.stream_messages)


@pytest.mark.asyncio
async def test_empty_append_is_noop(session):
    await append_conversation_replay(session, 11, [])
    assert await load_conversation_replay(session, 11) == []
