"""recorder 生命周期 + 聚合 + 吞异常。

注意：recorder 内部用 app.database.AsyncSessionLocal 开会话，所以本测试要把
AsyncSessionLocal 指到一个共享的内存 SQLite engine（而不是用 db_session fixture
那个 per-test engine），否则 recorder 写的行跟断言查的不是同一个库。
"""
from __future__ import annotations

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

import app.database as database
from app.database import Base
from app.models.agent_observability import AgentRun, AgentStep
from app.observability import recorder


@pytest_asyncio.fixture
async def shared_db(monkeypatch):
    """共享内存 SQLite：用 StaticPool 让所有连接看同一个 :memory: 库。"""
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
    # recorder 用 AsyncSessionLocal，把它指到本 engine
    monkeypatch.setattr(database, "AsyncSessionLocal", Session)
    monkeypatch.setattr(recorder, "AsyncSessionLocal", Session)
    async with Session() as s:
        yield s
    await engine.dispose()


@pytest.mark.asyncio
async def test_full_lifecycle_aggregates_tokens(shared_db):
    run_id = await recorder.start_run(
        agent_type="ai_builder", tenant_id=7, user_id=3, session_id=42, model="gpt-5.5"
    )
    assert run_id and isinstance(run_id, str)

    await recorder.record_step(run_id, step_type="llm", seq=1, prompt_tokens=100, completion_tokens=20)
    await recorder.record_step(
        run_id, step_type="tool", seq=2, tool_name="read_attachment",
        args={"id": 1}, result_text="ok", status="success", duration_ms=12,
    )
    await recorder.record_step(run_id, step_type="llm", seq=3, prompt_tokens=80, completion_tokens=10)

    await recorder.end_run(run_id, status="success")

    run = (
        await shared_db.execute(select(AgentRun).where(AgentRun.run_id == run_id))
    ).scalar_one()
    assert run.status == "success"
    assert run.total_prompt_tokens == 180
    assert run.total_completion_tokens == 30
    assert run.total_tokens == 210
    assert run.turn_count == 2  # 两个 llm step
    assert run.ended_at is not None
    assert run.duration_ms is not None and run.duration_ms >= 0

    steps = (
        await shared_db.execute(
            select(AgentStep).where(AgentStep.run_id == run_id).order_by(AgentStep.seq)
        )
    ).scalars().all()
    assert [s.seq for s in steps] == [1, 2, 3]


@pytest.mark.asyncio
async def test_end_run_missing_run_is_noop(shared_db):
    # 不存在的 run_id：不抛，安静返回
    await recorder.end_run("does_not_exist", status="success")


@pytest.mark.asyncio
async def test_recorder_swallows_internal_errors(shared_db, monkeypatch):
    # 让 record_step 内部建会话就炸 —— recorder 必须吞掉，不能往外抛
    def _boom():
        raise RuntimeError("db down")

    monkeypatch.setattr(recorder, "AsyncSessionLocal", _boom)
    # 不抛异常即通过
    await recorder.record_step("run_x", step_type="llm", seq=1, prompt_tokens=1)
    rid = await recorder.start_run(agent_type="ai_builder")
    assert isinstance(rid, str)  # start_run 即便写库失败也返回 id
    await recorder.end_run("run_x", status="error")
