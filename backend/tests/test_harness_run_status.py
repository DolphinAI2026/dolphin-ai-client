"""coding run-status 端点 + 发送守卫(切会话不丢 run T3/T5)。

直接调路由处理函数(不用 ctx 内容),用假 RunHandle 驱动 RunRegistry。
"""
import asyncio
from types import SimpleNamespace

import pytest

from app.harness.run_registry import RunHandle, run_registry


@pytest.mark.asyncio
async def test_run_status_running():
    from app.routes.harness import coding_run_status

    async def _sleep():
        await asyncio.sleep(0.3)

    task = asyncio.create_task(_sleep())
    run_registry.register(
        404, RunHandle(task=task, event_bus=SimpleNamespace(current_seq=5), run_id="rX", thread_id=9)
    )
    try:
        res = await coding_run_status(404, ctx=SimpleNamespace())
        assert res == {"running": True, "last_seq": 5, "run_id": "rX"}
    finally:
        run_registry.unregister(404)
        task.cancel()


@pytest.mark.asyncio
async def test_run_status_not_running():
    from app.routes.harness import coding_run_status

    res = await coding_run_status(987654, ctx=SimpleNamespace())
    assert res["running"] is False
    assert res["run_id"] is None


@pytest.mark.asyncio
async def test_coding_stop_cancels_run():
    from app.routes.harness import coding_stop

    started = asyncio.Event()

    async def _long():
        started.set()
        await asyncio.sleep(10)

    task = asyncio.create_task(_long())
    await started.wait()
    run_registry.register(
        707, RunHandle(task=task, event_bus=SimpleNamespace(current_seq=0), run_id="r", thread_id=1)
    )
    try:
        res = await coding_stop(707, ctx=SimpleNamespace())
        assert res["stopped"] is True
        await asyncio.sleep(0.02)
        assert task.cancelled()
    finally:
        run_registry.unregister(707)


@pytest.mark.asyncio
async def test_coding_stop_noop_when_not_running():
    from app.routes.harness import coding_stop

    res = await coding_stop(888888, ctx=SimpleNamespace())
    assert res["stopped"] is False


@pytest.mark.asyncio
async def test_pipeline_guard_blocks_when_running():
    from fastapi import HTTPException

    from app.routes.harness import _start_coding_turn_sse

    async def _sleep():
        await asyncio.sleep(0.3)

    task = asyncio.create_task(_sleep())
    run_registry.register(
        505, RunHandle(task=task, event_bus=SimpleNamespace(current_seq=1), run_id="r", thread_id=1)
    )
    try:
        with pytest.raises(HTTPException) as exc:
            await _start_coding_turn_sse(
                None, tenant_id=1, user_id=1, conversation_id=505, message="hi", metadata={}
            )
        assert exc.value.status_code == 409
    finally:
        run_registry.unregister(505)
        task.cancel()
