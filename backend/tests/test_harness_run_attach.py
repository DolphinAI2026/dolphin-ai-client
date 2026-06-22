"""attach_stream:补缺口(seq>after_seq 内存历史)+ 跟实时,断开只 unsubscribe 不杀 task。
(切会话不丢 run T4)
"""
import asyncio

import pytest

from app.harness.events import EventBus, ITEM_DELTA
from app.harness.manager import HarnessManager
from app.harness.run_registry import RunHandle, run_registry


@pytest.mark.asyncio
async def test_attach_replays_history_then_live_and_keeps_task():
    bus = EventBus(thread_id=9, db_session_factory=None)
    # 历史 seq1..3(persist=False → 不碰 DB,replay_after 走内存)
    for txt in ("a", "b", "c"):
        await bus.publish(ITEM_DELTA, 1, {"kind": "content", "text": txt}, item_kind="content", persist=False)

    async def _live():
        await asyncio.sleep(0.05)
        await bus.publish(ITEM_DELTA, 1, {"kind": "content", "text": "d"}, item_kind="content", persist=False)  # seq4
        await asyncio.sleep(0.05)
        await bus.send_sentinel()

    run_task = asyncio.create_task(asyncio.sleep(1.0))  # 代表在跑的 run
    live_task = asyncio.create_task(_live())
    run_registry.register(606, RunHandle(task=run_task, event_bus=bus, run_id="r", thread_id=9))

    mgr = HarnessManager(None)
    seqs = []
    task_alive_after_attach = None
    try:
        async for ev in mgr.attach_stream(606, after_seq=1, tenant_id=1):
            if ev.get("type") == "heartbeat":
                continue
            seqs.append(ev["_seq"])
        # attach 结束于 sentinel —— 此刻 run_task 应仍未完成(attach 只 unsubscribe,不杀 task)
        task_alive_after_attach = not run_task.done()
    finally:
        run_registry.unregister(606)
        run_task.cancel()
        await asyncio.gather(live_task, return_exceptions=True)

    assert seqs == [2, 3, 4]              # 补历史 seq>1 = 2,3,再跟实时 4
    assert task_alive_after_attach is True  # attach 断开没杀 run 后台任务


@pytest.mark.asyncio
async def test_attach_not_running_returns_empty():
    mgr = HarnessManager(None)
    out = [ev async for ev in mgr.attach_stream(7777, after_seq=0, tenant_id=1)]
    assert out == []
