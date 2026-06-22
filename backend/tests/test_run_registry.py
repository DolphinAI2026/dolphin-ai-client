"""进程级在跑 run 注册表 —— 切会话不丢 run 的地基。

强引用后台 task(否则 asyncio 弱引用 + 客户端断开后闭包 GC → task 被取消)。
按 conversation_id 持有,一会话单 run,重连据此接回同一条在跑 EventBus。
"""
import asyncio

import pytest

from app.harness.run_registry import RunHandle, run_registry


@pytest.mark.asyncio
async def test_register_get_unregister():
    async def _noop():
        await asyncio.sleep(0.01)

    task = asyncio.create_task(_noop())
    h = RunHandle(task=task, event_bus=object(), run_id="r1", thread_id=7)
    run_registry.register(101, h)
    assert run_registry.is_running(101) is True
    assert run_registry.get(101) is h
    await task
    # task 跑完后 is_running 为 False(即便还没 unregister)
    assert run_registry.is_running(101) is False
    run_registry.unregister(101)
    assert run_registry.get(101) is None


@pytest.mark.asyncio
async def test_register_replaces_single_per_conversation():
    async def _noop():
        await asyncio.sleep(0.01)

    t1 = asyncio.create_task(_noop())
    t2 = asyncio.create_task(_noop())
    run_registry.register(202, RunHandle(task=t1, event_bus=object(), run_id="a", thread_id=1))
    run_registry.register(202, RunHandle(task=t2, event_bus=object(), run_id="b", thread_id=2))
    assert run_registry.get(202).run_id == "b"  # 后者覆盖,单会话单 run
    await asyncio.gather(t1, t2)
    run_registry.unregister(202)


def test_is_running_false_for_unknown():
    assert run_registry.is_running(999999) is False
    assert run_registry.get(999999) is None
