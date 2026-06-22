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
