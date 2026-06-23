"""CodingAgent 可观测埋点（接 app.observability.recorder）。

CodingAgent 走 BaseAgent，run 生命周期通过 before_run/after_run/on_llm_response/
after_tool_call 四个 hook 落 AgentRun/AgentStep。这里直接驱动 hook 验证落库，
不必拉起完整 pipeline。

跟其它 observability 测试一样：把 AsyncSessionLocal 指到共享内存库，让 recorder
自开会话写的行能被断言查到。
"""
from __future__ import annotations

import types

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.pool import StaticPool

import app.database as database
from app.database import Base
from app.models.agent_observability import AgentRun, AgentStep
from app.observability import recorder
from app.agents.coding.agent import CodingAgent
from app.agents.types import AgentContext, AgentResult, AgentStatus, LLMResponse, ToolResult


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


def _agent() -> CodingAgent:
    ctx = AgentContext(
        conversation_id=9,
        user_id=3,
        tenant_id=42,
        session_id="s-coding",
        model="gpt-5.5",
        input={},
    )
    return CodingAgent(ctx)


@pytest.mark.asyncio
async def test_before_run_opens_coding_run(shared_db):
    agent = _agent()
    await agent.before_run()

    assert agent._obs_run_id
    run = (
        await shared_db.execute(select(AgentRun).where(AgentRun.run_id == agent._obs_run_id))
    ).scalar_one()
    assert run.agent_type == "coding"
    assert run.tenant_id == 42
    assert run.user_id == 3
    assert run.session_id == "9"
    assert run.model == "gpt-5.5"
    assert run.status == "running"


@pytest.mark.asyncio
async def test_on_llm_response_records_llm_step_with_tokens(shared_db):
    agent = _agent()
    await agent.before_run()

    # 无 tool_call 的回复也要记 llm step（埋点在 hook 顶部，先于 done 早退）
    await agent.on_llm_response(
        LLMResponse(content="完成了", tool_calls=[], tokens_input=50, tokens_output=8)
    )

    steps = (
        await shared_db.execute(
            select(AgentStep).where(AgentStep.run_id == agent._obs_run_id)
        )
    ).scalars().all()
    assert len(steps) == 1
    assert steps[0].step_type == "llm"
    assert steps[0].prompt_tokens == 50
    assert steps[0].completion_tokens == 8


@pytest.mark.asyncio
async def test_after_tool_call_records_success_tool_step(shared_db):
    agent = _agent()
    await agent.before_run()

    tool = types.SimpleNamespace(name="glob_files")
    await agent.after_tool_call(tool, ToolResult(success=True, content="hit a.ts"))

    steps = (
        await shared_db.execute(
            select(AgentStep).where(AgentStep.run_id == agent._obs_run_id)
        )
    ).scalars().all()
    assert len(steps) == 1
    assert steps[0].step_type == "tool"
    assert steps[0].tool_name == "glob_files"
    assert steps[0].status == "success"


@pytest.mark.asyncio
async def test_after_tool_call_records_failed_tool_step(shared_db):
    """取代被删的死 error_recorder：工具失败要记一条 status=error 的 tool step。"""
    agent = _agent()
    await agent.before_run()

    tool = types.SimpleNamespace(name="write_file")
    await agent.after_tool_call(
        tool, ToolResult(success=False, content="", error="permission denied")
    )

    steps = (
        await shared_db.execute(
            select(AgentStep).where(AgentStep.run_id == agent._obs_run_id)
        )
    ).scalars().all()
    assert len(steps) == 1
    assert steps[0].step_type == "tool"
    assert steps[0].tool_name == "write_file"
    assert steps[0].status == "error"


@pytest.mark.asyncio
async def test_after_run_finalizes_with_success_and_token_aggregate(shared_db):
    agent = _agent()
    await agent.before_run()
    await agent.on_llm_response(
        LLMResponse(content="x", tool_calls=[], tokens_input=40, tokens_output=6)
    )
    await agent.after_run(AgentResult(status=AgentStatus.COMPLETED))

    run = (
        await shared_db.execute(select(AgentRun).where(AgentRun.run_id == agent._obs_run_id))
    ).scalar_one()
    assert run.status == "success"
    assert run.total_prompt_tokens == 40
    assert run.total_completion_tokens == 6
    assert run.total_tokens == 46
    assert run.turn_count == 1


@pytest.mark.asyncio
async def test_after_run_maps_failed_status_to_error(shared_db):
    agent = _agent()
    await agent.before_run()
    await agent.after_run(AgentResult(status=AgentStatus.FAILED, error_message="boom"))

    run = (
        await shared_db.execute(select(AgentRun).where(AgentRun.run_id == agent._obs_run_id))
    ).scalar_one()
    assert run.status == "error"
    assert run.error_message == "boom"


@pytest.mark.asyncio
async def test_hooks_noop_without_before_run(shared_db):
    """没调 before_run（_obs_run_id 为 None）时，hook 不应写任何观测行 —— 保护
    那些直接驱动单个 hook 的既有单测。"""
    agent = _agent()
    await agent.on_llm_response(
        LLMResponse(content="x", tool_calls=[], tokens_input=1, tokens_output=1)
    )
    await agent.after_tool_call(
        types.SimpleNamespace(name="read_file"), ToolResult(success=True, content="ok")
    )
    await agent.after_run(AgentResult(status=AgentStatus.COMPLETED))

    runs = (await shared_db.execute(select(AgentRun))).scalars().all()
    steps = (await shared_db.execute(select(AgentStep))).scalars().all()
    assert runs == []
    assert steps == []
