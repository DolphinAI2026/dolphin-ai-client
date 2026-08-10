"""ai-chat run 进程内总线 + 注册表(切会话不丢 run Phase2 地基)。

ai-chat 走 session_id(非 conversation_id),且没有现成总线 → 自建轻量内存总线:
承载原始 SSE 事件 dict + seq,支持 replay_after(补缺口)+ subscribe(实时)。进程内,不落库
(历史由 loadSession REST 覆盖)。
"""
import asyncio

import pytest

from app.ai_chat.run_bus import AiChatRunBus, ai_chat_run_registry
from app.harness.run_registry import RunHandle


@pytest.mark.asyncio
async def test_bus_publish_replay_and_subscribe():
    bus = AiChatRunBus()
    await bus.publish({"event": "user_message", "data": "{}"})   # seq1
    await bus.publish({"event": "assistant_delta", "data": "a"})  # seq2
    assert bus.current_seq == 2

    # replay_after(1) → 只补 seq>1
    rep = bus.replay_after(1)
    assert [s for s, _ in rep] == [2]

    # subscribe 拿实时
    q = bus.subscribe()
    await bus.publish({"event": "done", "data": "{}"})  # seq3
    seq, ev = await asyncio.wait_for(q.get(), timeout=1.0)
    assert seq == 3 and ev["event"] == "done"
    bus.unsubscribe(q)


@pytest.mark.asyncio
async def test_subscribe_run_events_replay_then_live_to_sentinel():
    from app.ai_chat.run_bus import subscribe_run_events

    bus = AiChatRunBus()
    await bus.publish({"event": "a", "data": "1"})  # seq1
    await bus.publish({"event": "b", "data": "2"})  # seq2

    async def _live():
        await asyncio.sleep(0.05)
        await bus.publish({"event": "c", "data": "3"})  # seq3
        await asyncio.sleep(0.05)
        await bus.send_sentinel()

    t = asyncio.create_task(_live())
    out = []
    async for ev in subscribe_run_events(bus, after_seq=1):
        if ev.get("event") == "ping":
            continue
        out.append(ev["event"])
    await t
    assert out == ["b", "c"]  # 补 seq>1=b,跟实时 c,sentinel 停


@pytest.mark.asyncio
async def test_send_runs_agent_in_background_and_publishes_to_bus(monkeypatch):
    """send_message 把 run_agent 跑进后台任务、事件发到 bus、完成后摘除注册表。
    (即便没人消费 SSE,后台 run 照常跑完 = 切会话不丢 run 的后端保证)
    """
    import json as _json
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
    from sqlalchemy.pool import StaticPool

    import app.routes.ai_chat as aichat
    from app.ai_chat.run_bus import ai_chat_run_registry
    from app.database import Base
    from app.models import AIChatSession

    engine = create_async_engine(
        "sqlite+aiosqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    monkeypatch.setattr(aichat, "AsyncSessionLocal", Session)

    async def fake_run_agent(db, s, msg, abort, **kw):
        yield {"event": "assistant_delta", "data": _json.dumps({"text": "hi"})}
        yield {"event": "done", "data": _json.dumps({"ok": True})}

    monkeypatch.setattr(aichat, "run_agent", fake_run_agent)

    db = Session()
    sess = AIChatSession(tenant_id=1, user_id=1, title="我的应用")  # 非默认标题 → 跳过 title 生成
    db.add(sess)
    await db.commit()
    await db.refresh(sess)
    sid = sess.id

    monkeypatch.setattr(aichat, "_load_session_or_404", AsyncMock(return_value=sess))
    ctx = SimpleNamespace(user=SimpleNamespace(id=1), tenant_id=1)
    body = aichat.SendMessageRequest(message="hello")

    await aichat.send_message(sid, body, ctx=ctx, db=db)

    h = ai_chat_run_registry.get(sid)
    assert h is not None  # 后台 run 已注册
    await asyncio.wait_for(h.task, timeout=3.0)  # 等后台跑完

    names = [e.get("event") for _, e in h.event_bus.replay_after(0)]
    assert "user_message" in names
    assert "assistant_delta" in names
    assert "done" in names
    assert ai_chat_run_registry.is_running(sid) is False  # 完成后摘除


@pytest.mark.asyncio
async def test_abort_cancels_background_task(monkeypatch):
    """Builder 停止键:abort 必须显式 cancel 后台 task。

    send 解耦后 run 是 RunRegistry 强引用的 detached 后台 task —— 断 SSE 不影响它,
    只 set abort_event 在 LLM I/O 阻塞时也来不及检查 → 必须像 coding /coding/stop
    那样 task.cancel()。否则点停止「AI 思考中」停不掉(线上 bug)。
    """
    from types import SimpleNamespace
    from unittest.mock import AsyncMock, MagicMock

    import app.routes.ai_chat as aichat
    from app.ai_chat.run_bus import AiChatRunBus, ai_chat_run_registry

    started = asyncio.Event()

    async def _long():
        started.set()
        await asyncio.sleep(10)

    task = asyncio.create_task(_long())
    await started.wait()
    sid = 90909
    ai_chat_run_registry.register(
        sid, RunHandle(task=task, event_bus=AiChatRunBus(), run_id="r", thread_id=sid)
    )
    monkeypatch.setattr(
        aichat, "_load_session_or_404", AsyncMock(return_value=SimpleNamespace(id=sid))
    )
    running_tool = SimpleNamespace(
        status="running",
        result_text=None,
        error_message=None,
        started_at=None,
        ended_at=None,
        duration_ms=None,
    )
    result = MagicMock()
    result.scalars.return_value.all.return_value = [running_tool]
    db = SimpleNamespace(
        execute=AsyncMock(return_value=result),
        commit=AsyncMock(),
    )
    try:
        res = await aichat.abort_session(sid, ctx=SimpleNamespace(), db=db)
        assert res.get("stopped") is True
        db.commit.assert_awaited_once()
        assert running_tool.status == "aborted"
        assert running_tool.error_message == "用户已停止本轮执行"
        assert '"error_code": "ABORTED"' in running_tool.result_text
        assert running_tool.ended_at is not None
        await asyncio.sleep(0.02)
        assert task.cancelled()
    finally:
        ai_chat_run_registry.unregister(sid)
        if not task.done():
            task.cancel()


@pytest.mark.asyncio
async def test_abort_noop_when_not_running(monkeypatch):
    """该会话没有在跑 run → abort 不报 stopped:True(不崩)。"""
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    import app.routes.ai_chat as aichat

    monkeypatch.setattr(
        aichat, "_load_session_or_404", AsyncMock(return_value=SimpleNamespace(id=1))
    )
    res = await aichat.abort_session(778899, ctx=SimpleNamespace(), db=AsyncMock())
    assert res.get("stopped") is not True


@pytest.mark.asyncio
async def test_registry_tracks_running_per_session():
    async def _noop():
        await asyncio.sleep(0.01)

    task = asyncio.create_task(_noop())
    ai_chat_run_registry.register(
        42, RunHandle(task=task, event_bus=AiChatRunBus(), run_id="r", thread_id=42)
    )
    assert ai_chat_run_registry.is_running(42) is True
    await task
    assert ai_chat_run_registry.is_running(42) is False
    ai_chat_run_registry.unregister(42)
    assert ai_chat_run_registry.get(42) is None
