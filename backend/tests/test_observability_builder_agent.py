"""SpecAgent (builder) 可观测埋点。

SpecAgent 是自建 httpx tool loop（不走 BaseAgent / harness），run() 自己 bracket
run 生命周期：start_run → 每轮 record_step(llm) + 每个工具 record_step(tool) → end_run。

两个关键点：
1. 只有传了 tenant_id 才埋点（与 build_prompt_async 一样的「测试可省略身份」约定，
   保护既有 test_spec_agent 不被动到）。
2. builder 原来不采 usage —— payload 补 stream_options.include_usage，并在流里
   `if not choices: continue` 之前捕获 usage chunk，token 才进得了 AgentRun。
"""
from __future__ import annotations

import json

import pytest
import pytest_asyncio
from unittest.mock import patch
from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.pool import StaticPool

import app.database as database
from app.database import Base
from app.models.agent_observability import AgentRun, AgentStep
from app.observability import recorder
from app.builder_spec.agent import SpecAgent
from app.builder_spec.persistence import empty_spec


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


class FakeLLMStream:
    def __init__(self, chunks: list[dict]):
        self.chunks = chunks

    async def __aiter__(self):
        for c in self.chunks:
            yield "data: " + json.dumps(c)
        yield "data: [DONE]"


def _tool_call_chunk(idx, call_id, name, args_json) -> dict:
    return {"choices": [{"delta": {"tool_calls": [{
        "index": idx, "id": call_id,
        "function": {"name": name, "arguments": args_json},
    }]}}]}


def _content_chunk(text) -> dict:
    return {"choices": [{"delta": {"content": text}}]}


def _usage_chunk(prompt, completion) -> dict:
    # OpenAI include_usage: 末尾一个 choices 为空、带 usage 的 chunk
    return {"choices": [], "usage": {"prompt_tokens": prompt, "completion_tokens": completion}}


def _empty_finish_chunk() -> dict:
    return {"choices": [{"delta": {}}]}


def _open_stream_mock(streams):
    it = iter(streams)

    def _fake(*a, **k):
        return next(it)

    return _fake


@pytest.mark.asyncio
async def test_run_with_tenant_records_builder_run_with_tokens_and_tool_step(shared_db):
    spec = empty_spec(created_by=1)
    turn1 = [
        _tool_call_chunk(0, "c0", "set_goal", json.dumps(
            {"title": "预算", "summary": "x", "business_problem": "y"})),
        _usage_chunk(40, 5),
    ]
    turn2 = [_content_chunk("好的"), _empty_finish_chunk(), _usage_chunk(60, 9)]

    agent = SpecAgent(llm_base_url="http://fake", llm_api_key="fake", llm_model="gpt-5.5")
    fake = _open_stream_mock([FakeLLMStream(turn1), FakeLLMStream(turn2)])
    with patch("app.builder_spec.agent._open_stream", side_effect=fake):
        async for _ in agent.run(
            spec, user_message="我想做预算系统",
            tenant_id=7, user_id=3, conversation_id=11,
        ):
            pass

    run = (await shared_db.execute(select(AgentRun))).scalar_one()
    assert run.agent_type == "builder"
    assert run.tenant_id == 7
    assert run.user_id == 3
    assert run.session_id == "11"
    assert run.model == "gpt-5.5"
    assert run.status == "success"
    assert run.turn_count == 2                       # 两个 llm step
    assert run.total_tokens == 40 + 5 + 60 + 9       # usage 被采到

    steps = (await shared_db.execute(
        select(AgentStep).where(AgentStep.run_id == run.run_id).order_by(AgentStep.seq)
    )).scalars().all()
    kinds = [s.step_type for s in steps]
    assert kinds == ["llm", "tool", "llm"]
    assert steps[1].tool_name == "set_goal"
    assert steps[1].status == "success"


@pytest.mark.asyncio
async def test_run_without_tenant_records_nothing(shared_db):
    """既有 test_spec_agent 全部省略 tenant_id —— 不能因为埋点而误写库。"""
    spec = empty_spec(created_by=1)
    turn1 = [_content_chunk("可以"), _empty_finish_chunk()]
    agent = SpecAgent(llm_base_url="http://fake", llm_api_key="fake", llm_model="gpt-5.5")
    fake = _open_stream_mock([FakeLLMStream(turn1)])
    with patch("app.builder_spec.agent._open_stream", side_effect=fake):
        async for _ in agent.run(spec, user_message="hi"):
            pass

    runs = (await shared_db.execute(select(AgentRun))).scalars().all()
    assert runs == []
