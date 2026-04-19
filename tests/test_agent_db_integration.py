"""DbEventPublisher / DbTraceWriter 集成测试 — sqlite in-memory。

验证：
- 表创建 OK
- publisher.publish() → conversation_events 写入 + seq 单调
- trace_writer.write() → agent_traces 写入 + 单调 seq（per session）
- subscribe 断线重连（last_seen_seq 补发）
- ScopedPublisher / ScopedTraceWriter 满足 agent Protocol（可被 BaseAgent 直接调用）
"""
import asyncio
import os
import sys
import uuid

os.environ.setdefault("LLM_API_KEY", "test-key")
os.environ.setdefault("JWT_SECRET_KEY", "test-secret")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker

from app.database import Base
import app.models  # 确保 Base 注册所有表
import app.models.agent_models  # 显式注册 agent 表
from app.models.agent_models import ConversationEvent, AgentTrace
from app.agents.db_publisher import DbEventPublisher
from app.agents.db_trace_writer import DbTraceWriter


# ══════════════════════════════════════════════════════════════
# Helpers
# ══════════════════════════════════════════════════════════════

async def _make_test_db():
    """创建一个独立的 in-memory sqlite engine + session"""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    SessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    return engine, SessionLocal


async def _with_db(fn):
    """为测试提供 db session 的上下文"""
    engine, SessionLocal = await _make_test_db()
    try:
        async with SessionLocal() as db:
            return await fn(db)
    finally:
        await engine.dispose()


# ══════════════════════════════════════════════════════════════
# 1. Publisher: 基础写入 + seq 单调
# ══════════════════════════════════════════════════════════════

def test_publisher_basic_publish():
    async def run(db: AsyncSession):
        pub = DbEventPublisher()
        seq1 = await pub.publish(
            conversation_id=1, event_type="brainstorm.start",
            agent="brainstorm", session_id="bs_1",
            data={"foo": "bar"}, db=db,
        )
        seq2 = await pub.publish(
            conversation_id=1, event_type="brainstorm.ask_user",
            agent="brainstorm", session_id="bs_1",
            data={"q": "hi"}, db=db,
        )
        assert seq1 == 1
        assert seq2 == 2

        # 验证 DB
        result = await db.execute(select(ConversationEvent).order_by(ConversationEvent.seq))
        rows = result.scalars().all()
        assert len(rows) == 2
        assert rows[0].event_type == "brainstorm.start"
        assert rows[1].payload == {"q": "hi"}

    asyncio.run(_with_db(run))


def test_publisher_seq_isolation_per_conversation():
    """不同 conversation 的 seq 独立计数"""
    async def run(db: AsyncSession):
        pub = DbEventPublisher()
        s1a = await pub.publish(
            conversation_id=1, event_type="x", agent="a",
            session_id=None, data={}, db=db,
        )
        s2a = await pub.publish(
            conversation_id=2, event_type="x", agent="a",
            session_id=None, data={}, db=db,
        )
        s1b = await pub.publish(
            conversation_id=1, event_type="y", agent="a",
            session_id=None, data={}, db=db,
        )
        assert s1a == 1
        assert s2a == 1   # conv 2 独立
        assert s1b == 2   # conv 1 继续递增

    asyncio.run(_with_db(run))


def test_publisher_seq_recovers_from_db():
    """Publisher 重启后能从 DB 恢复 seq"""
    async def run(db: AsyncSession):
        pub1 = DbEventPublisher()
        await pub1.publish(
            conversation_id=1, event_type="x", agent="a",
            session_id=None, data={}, db=db,
        )
        await pub1.publish(
            conversation_id=1, event_type="x", agent="a",
            session_id=None, data={}, db=db,
        )

        # 新 publisher 实例 — 内存 counter 为空
        pub2 = DbEventPublisher()
        seq = await pub2.publish(
            conversation_id=1, event_type="y", agent="a",
            session_id=None, data={}, db=db,
        )
        assert seq == 3  # 从 DB 查最大值继续

    asyncio.run(_with_db(run))


# ══════════════════════════════════════════════════════════════
# 2. Publisher: subscribe 断线重连
# ══════════════════════════════════════════════════════════════

def test_publisher_subscribe_replays_history():
    """subscribe(last_seen_seq=N) 应补发 seq > N 的历史事件"""
    async def run(db: AsyncSession):
        pub = DbEventPublisher()
        for i in range(5):
            await pub.publish(
                conversation_id=1, event_type=f"evt_{i}",
                agent="a", session_id=None, data={"i": i}, db=db,
            )

        # 从 seq=2 开始订阅（补发 3, 4, 5）
        events_received = []
        gen = pub.subscribe(conversation_id=1, last_seen_seq=2, db=db)
        # 手动消费前 3 个补发事件（然后生成器会挂起等实时流）
        for _ in range(3):
            events_received.append(await gen.__anext__())

        seqs = [e["seq"] for e in events_received]
        assert seqs == [3, 4, 5]

        # 关闭生成器
        await gen.aclose()

    asyncio.run(_with_db(run))


def test_publisher_realtime_push():
    """subscribe 后，新 publish 的事件实时推送给订阅者"""
    async def run(db: AsyncSession):
        pub = DbEventPublisher()

        events_received = []

        async def consumer():
            gen = pub.subscribe(conversation_id=1, last_seen_seq=0, db=db)
            try:
                # 等一条新事件（忽略初始补发，因为 DB 为空）
                async for e in gen:
                    events_received.append(e)
                    if len(events_received) >= 2:
                        break
            finally:
                await gen.aclose()

        async def producer():
            # 给 consumer 一点时间订阅
            await asyncio.sleep(0.05)
            await pub.publish(
                conversation_id=1, event_type="a",
                agent="t", session_id=None, data={"n": 1}, db=db,
            )
            await pub.publish(
                conversation_id=1, event_type="b",
                agent="t", session_id=None, data={"n": 2}, db=db,
            )

        await asyncio.gather(consumer(), producer())
        assert len(events_received) == 2
        assert events_received[0]["type"] == "a"
        assert events_received[1]["type"] == "b"

    asyncio.run(_with_db(run))


# ══════════════════════════════════════════════════════════════
# 3. TraceWriter: 基础写入 + session-scoped seq
# ══════════════════════════════════════════════════════════════

def test_trace_writer_basic_write():
    async def run(db: AsyncSession):
        writer = DbTraceWriter()
        trace_id = await writer.write(
            session_type="brainstorm", session_id="bs_1",
            turn=0, event_type="llm_request",
            payload={"tokens": 100}, tokens_input=100, tokens_output=0,
            db=db,
        )
        assert trace_id

        result = await db.execute(select(AgentTrace))
        rows = result.scalars().all()
        assert len(rows) == 1
        assert rows[0].session_id == "bs_1"
        assert rows[0].seq == 1
        assert rows[0].event_type == "llm_request"
        assert rows[0].tokens_input == 100

    asyncio.run(_with_db(run))


def test_trace_writer_seq_per_session():
    """不同 session 的 seq 独立"""
    async def run(db: AsyncSession):
        writer = DbTraceWriter()
        await writer.write(
            session_type="brainstorm", session_id="bs_1",
            turn=0, event_type="llm_request", payload={}, db=db,
        )
        await writer.write(
            session_type="brainstorm", session_id="bs_2",
            turn=0, event_type="llm_request", payload={}, db=db,
        )
        await writer.write(
            session_type="brainstorm", session_id="bs_1",
            turn=1, event_type="tool_call", payload={}, db=db,
        )

        result = await db.execute(select(AgentTrace).order_by(AgentTrace.id))
        rows = result.scalars().all()
        seqs_by_session = {}
        for r in rows:
            seqs_by_session.setdefault(r.session_id, []).append(r.seq)

        assert sorted(seqs_by_session["bs_1"]) == [1, 2]
        assert sorted(seqs_by_session["bs_2"]) == [1]

    asyncio.run(_with_db(run))


# ══════════════════════════════════════════════════════════════
# 4. ScopedPublisher / ScopedTraceWriter 满足 Protocol
# ══════════════════════════════════════════════════════════════

def test_scoped_publisher_satisfies_protocol():
    """ScopedDbEventPublisher 的 publish() 签名与 EventPublisher Protocol 一致"""
    async def run(db: AsyncSession):
        pub = DbEventPublisher()
        scoped = pub.scoped(db)

        # 这个调用签名与 BaseAgent._publish 内部调用完全一致
        seq = await scoped.publish(
            conversation_id=1,
            event_type="coding.file_write",
            agent="coding",
            session_id="cs_1",
            data={"path": "a.vue"},
        )
        assert seq == 1

    asyncio.run(_with_db(run))


def test_scoped_trace_writer_satisfies_protocol():
    async def run(db: AsyncSession):
        writer = DbTraceWriter()
        scoped = writer.scoped(db)

        trace_id = await scoped.write(
            session_type="coding",
            session_id="cs_1",
            turn=0,
            event_type="llm_request",
            payload={"foo": "bar"},
        )
        assert trace_id

    asyncio.run(_with_db(run))


# ══════════════════════════════════════════════════════════════
# 5. BaseAgent 与真实 DB publisher/writer 集成
# ══════════════════════════════════════════════════════════════

def test_base_agent_with_db_publisher_and_writer():
    """BaseAgent 用 Scoped publisher/writer 跑完整循环，验证事件 + trace 都落盘"""
    from app.agents.base import BaseAgent
    from app.agents.types import (
        AgentContext, AgentStatus, AgentType, StopReason, Tool, ToolResult,
    )

    import json as _json

    # 复用 test_base_agent_unit 的 MockLLM 思路
    class MockLLM:
        def __init__(self, responses):
            self._r = list(responses)

        async def chat_completion(self, messages, *, max_tokens=8192, timeout=120.0,
                                  temperature=0.3, model=None, tools=None, tool_choice=None):
            return self._r.pop(0)

    class TinyAgent(BaseAgent[dict]):
        agent_type = AgentType.BRAINSTORM

        def __init__(self, ctx):
            super().__init__(ctx)
            self._done = False

        def get_system_prompt(self): return "hi"
        def get_tools(self):
            async def finish(args, ctx):
                self._done = True
                return ToolResult(success=True, content="ok")
            return [Tool(name="finish", description="finish", parameters_schema={"type": "object"}, execute=finish)]
        def get_max_turns(self): return 3
        def build_initial_user_message(self): return "hello"
        def should_terminate(self):
            if self._done:
                return True, "done"
            return False, ""
        async def finalize(self): return {"ok": True}

    llm_resp = {
        "id": "m",
        "choices": [{
            "index": 0,
            "message": {
                "role": "assistant",
                "content": "",
                "tool_calls": [{
                    "id": "t1", "type": "function",
                    "function": {"name": "finish", "arguments": "{}"},
                }],
            },
            "finish_reason": "tool_calls",
        }],
        "usage": {"prompt_tokens": 5, "completion_tokens": 3},
    }

    async def run(db: AsyncSession):
        pub = DbEventPublisher()
        writer = DbTraceWriter()

        ctx = AgentContext(
            session_id="bs_agent_test",
            conversation_id=42,
            user_id=1,
            tenant_id=1,
            model="test-model",
            input={},
            publisher=pub.scoped(db),
            trace_writer=writer.scoped(db),
            llm_client=MockLLM([llm_resp]),
        )
        agent = TinyAgent(ctx)
        result = await agent.run()

        assert result.status == AgentStatus.COMPLETED
        assert result.product == {"ok": True}

        # 验证 DB 有事件
        evt_rows = (await db.execute(select(ConversationEvent))).scalars().all()
        evt_types = [e.event_type for e in evt_rows]
        assert "brainstorm.start" in evt_types
        assert "brainstorm.tool_call" in evt_types
        assert "brainstorm.tool_result" in evt_types
        assert "brainstorm.done" in evt_types

        # 验证 seq 单调
        seqs = sorted([e.seq for e in evt_rows])
        assert seqs == list(range(1, len(seqs) + 1))

        # 验证 trace 有记录
        trace_rows = (await db.execute(select(AgentTrace))).scalars().all()
        assert len(trace_rows) > 0
        trace_types = [t.event_type for t in trace_rows]
        assert "llm_request" in trace_types
        assert "llm_response" in trace_types
        assert "tool_call" in trace_types
        assert "tool_result" in trace_types

    asyncio.run(_with_db(run))


if __name__ == "__main__":
    import inspect, traceback as _tb
    current = sys.modules[__name__]
    tests = [
        (n, f) for n, f in inspect.getmembers(current, inspect.isfunction)
        if n.startswith("test_")
    ]
    passed = failed = 0
    for name, func in tests:
        try:
            func()
            print(f"✓ {name}")
            passed += 1
        except Exception as e:
            print(f"✗ {name}: {type(e).__name__}: {e}")
            _tb.print_exc()
            failed += 1
    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)
