"""run_agent 端到端埋点（mock 掉 LLM 与工具，验证 AgentRun/AgentStep 落库）。

跟 recorder 测试一样，需要把 AsyncSessionLocal 指到共享内存库，让 recorder 写的行
能被断言查到；同时把这个共享 session 传给 run_agent 当主 db。
"""
from __future__ import annotations

import asyncio
import json

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.pool import StaticPool

import app.database as database
import app.ai_chat.agent as agent_mod
from app.database import Base
from app.models import AIChatSession
from app.models.agent_observability import AgentRun, AgentStep
from app.observability import recorder


@pytest_asyncio.fixture
async def shared_db(monkeypatch):
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    monkeypatch.setattr(database, "AsyncSessionLocal", Session)
    monkeypatch.setattr(recorder, "AsyncSessionLocal", Session)
    async with Session() as s:
        yield s
    await engine.dispose()


def _stub_llm(monkeypatch, turns):
    """monkeypatch _call_llm_stream：按 turns 依次产出。每个 turn 是 done 事件 dict。"""
    seq = iter(turns)

    async def _fake_stream(cfg, messages, tools, abort_event, timeout=180):
        yield next(seq)

    monkeypatch.setattr(agent_mod, "_call_llm_stream", _fake_stream)


async def _seed_session(db) -> AIChatSession:
    s = AIChatSession(tenant_id=7, user_id=3, title="t", status="active")
    db.add(s)
    await db.commit()
    await db.refresh(s)
    return s


@pytest.mark.asyncio
async def test_no_tool_run_records_run_and_llm_step(shared_db, monkeypatch):
    s = await _seed_session(shared_db)

    monkeypatch.setattr(
        agent_mod, "_resolve_llm_config",
        _aval(types_ns(model="gpt-5.5")),
    )
    monkeypatch.setattr(
        agent_mod, "_build_initial_messages",
        _aval([{"role": "system", "content": "x"}, {"role": "user", "content": "hi"}]),
    )
    monkeypatch.setattr(agent_mod, "get_all_tool_schemas", _aval([]))
    # 单轮：无 tool_calls + 有 content + 带 usage
    _stub_llm(monkeypatch, [{
        "type": "done",
        "message": {"content": "完成了", "tool_calls": None},
        "usage": {"prompt_tokens": 50, "completion_tokens": 8},
    }])

    abort = asyncio.Event()
    events = []
    async for ev in agent_mod.run_agent(shared_db, s, "hi", abort):
        events.append((ev["event"], ev["data"]))

    # run_started 事件带 run_id
    started = [json.loads(d) for (e, d) in events if e == "run_started"]
    assert started and started[0]["run_id"]
    run_id = started[0]["run_id"]

    # assistant_message 事件带 run_id（前端每条回复挂「查看本次 trace」靠它）
    asst_evt = [json.loads(d) for (e, d) in events if e == "assistant_message"]
    assert asst_evt and asst_evt[0]["run_id"] == run_id

    run = (await shared_db.execute(select(AgentRun).where(AgentRun.run_id == run_id))).scalar_one()
    assert run.agent_type == "ai_builder"
    assert run.tenant_id == 7
    assert run.user_id == 3
    assert run.session_id == str(s.id)
    assert run.status == "success"
    assert run.total_prompt_tokens == 50
    assert run.total_completion_tokens == 8
    assert run.total_tokens == 58
    assert run.turn_count == 1

    steps = (await shared_db.execute(
        select(AgentStep).where(AgentStep.run_id == run_id).order_by(AgentStep.seq)
    )).scalars().all()
    assert len(steps) == 1
    assert steps[0].step_type == "llm"
    assert steps[0].prompt_tokens == 50


@pytest.mark.asyncio
async def test_tool_run_records_tool_step(shared_db, monkeypatch):
    s = await _seed_session(shared_db)
    monkeypatch.setattr(agent_mod, "_resolve_llm_config", _aval(types_ns(model="gpt-5.5")))
    monkeypatch.setattr(
        agent_mod, "_build_initial_messages",
        _aval([{"role": "system", "content": "x"}, {"role": "user", "content": "hi"}]),
    )
    monkeypatch.setattr(agent_mod, "get_all_tool_schemas", _aval([]))

    async def _fake_exec(tool_name, args, session, db):
        return "工具结果 ok"

    monkeypatch.setattr(agent_mod, "execute_tool", _fake_exec)

    # turn1：调一个工具；turn2：收尾文本
    _stub_llm(monkeypatch, [
        {
            "type": "done",
            "message": {
                "content": "",
                "tool_calls": [{"id": "c1", "type": "function",
                                "function": {"name": "read_attachment", "arguments": "{\"id\": 1}"}}],
            },
            "usage": {"prompt_tokens": 40, "completion_tokens": 5},
        },
        {
            "type": "done",
            "message": {"content": "搞定", "tool_calls": None},
            "usage": {"prompt_tokens": 60, "completion_tokens": 9},
        },
    ])

    abort = asyncio.Event()
    events = []
    async for ev in agent_mod.run_agent(shared_db, s, "hi", abort):
        events.append((ev["event"], ev["data"]))

    run_id = [json.loads(d) for (e, d) in events if e == "run_started"][0]["run_id"]
    run = (await shared_db.execute(select(AgentRun).where(AgentRun.run_id == run_id))).scalar_one()
    assert run.status == "success"
    assert run.turn_count == 2          # 两个 llm step
    assert run.total_tokens == 40 + 5 + 60 + 9

    steps = (await shared_db.execute(
        select(AgentStep).where(AgentStep.run_id == run_id).order_by(AgentStep.seq)
    )).scalars().all()
    kinds = [s.step_type for s in steps]
    assert kinds == ["llm", "tool", "llm"]
    tool_step = steps[1]
    assert tool_step.tool_name == "read_attachment"
    assert tool_step.status == "success"
    assert tool_step.args_json == {"id": 1}


# ── 小工具：把一个值包成 async 函数（monkeypatch 用） ──
def _aval(value):
    async def _f(*a, **kw):
        return value
    return _f


def types_ns(**kw):
    import types
    return types.SimpleNamespace(**kw)
