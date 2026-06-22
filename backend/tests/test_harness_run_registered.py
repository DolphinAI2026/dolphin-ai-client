"""start_turn 把在跑 turn 注册进 RunRegistry,完成后摘除(切会话不丢 run T2)。

用 NullProfile(echo,秒回)+ StaticPool 内存库 + monkeypatch AsyncSessionLocal。
"""
import asyncio

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

import app.harness.manager as mgr_mod
from app.database import Base
from app.harness.manager import HarnessManager
from app.harness.run_registry import run_registry


@pytest.mark.asyncio
async def test_start_turn_registers_then_unregisters(monkeypatch):
    engine = create_async_engine(
        "sqlite+aiosqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    # _run_turn_background 与 EventBus 都用 manager 命名空间里的 AsyncSessionLocal
    monkeypatch.setattr(mgr_mod, "AsyncSessionLocal", Session)

    db = Session()
    mgr = HarnessManager(db)
    thread_ctx = await mgr.create_thread(
        tenant_id=1, user_id=1, profile_name="null", conversation_id=303
    )
    await db.commit()

    stream = await mgr.start_turn(thread_ctx, "hello")
    # start_turn 刚返回:后台 task 已建未跑完 → 已注册
    assert run_registry.is_running(303) is True

    async for _ev in stream:
        pass

    # 后台 task 的 finally 摘除注册 —— 给它跑完的时间
    for _ in range(100):
        if run_registry.get(303) is None:
            break
        await asyncio.sleep(0.02)

    assert run_registry.is_running(303) is False
    assert run_registry.get(303) is None
