"""E2E 集成测试：BrainstormAgent → Spec 持久化 → CodingAgent，LLM 被 mock。

验证：
- drive_brainstorm 跑通 → Spec 落 specs 表 → phase 从 UNDERSTAND 到 CONFIRM
- drive_coding_from_spec 跑通 → phase 到 DONE
- CodingAgent 的 user message 注入了 Structured Spec 段
- emit_spec event 被 publisher 收到

mock 策略：子类化 Agent 覆盖 `_call_llm`，返回脚本化的 LLMResponse 序列。
避免真实 HTTP / LLMClient，测试可离线运行。
"""
import asyncio
import json
import os
import secrets
import sys

os.environ.setdefault("LLM_API_KEY", "test-key")
os.environ.setdefault("JWT_SECRET_KEY", "test-secret")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine  # noqa: E402

import app.models  # noqa: F401,E402
import app.models.agent_models as agent_models  # noqa: E402
from app.agents.brainstorm import BrainstormAgent  # noqa: E402
from app.agents.coding import CodingAgent  # noqa: E402
from app.agents.publisher import InMemoryEventPublisher  # noqa: E402
from app.agents.trace_writer import InMemoryTraceWriter  # noqa: E402
from app.agents.types import AgentContext, LLMResponse, ToolCall  # noqa: E402
from app.database import Base  # noqa: E402
from app.models import Conversation, User  # noqa: E402
from app.orchestrator import Phase, driver, get_phase, start_brainstorm, transition_phase  # noqa: E402
from app.services import spec_service  # noqa: E402


# ══════════════════════════════════════════════════════════════
# DB fixture
# ══════════════════════════════════════════════════════════════

def _run(coro_factory):
    """跑一个返回 coroutine 的 factory；保证 engine 在 loop 退出前 dispose。

    coro_factory: callable returning coroutine。内部 test 用 `async def run(): ...`
                  然后 `_run(run)`。
    """
    async def wrapped():
        engines = []
        # 把 make_db 注入到 test 命名空间 — 这里用一个简易 context：
        # 测试函数通过 `db, conv, user, eng = await _make_db()` 获取 engine 并在末尾 dispose
        return await coro_factory()

    asyncio.run(wrapped())


async def _make_db() -> tuple[AsyncSession, Conversation, User, "Any"]:
    """返回 (session, conv, user, engine)；测试函数负责最后 await engine.dispose()"""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    sm = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    session = sm()
    u = User(username=f"e2e_u_{secrets.token_hex(3)}", hashed_password="x")
    session.add(u)
    await session.flush()
    conv = Conversation(
        user_id=u.id, tenant_id=1, title="t", agent_type="coding", status="active",
    )
    session.add(conv)
    await session.flush()
    return session, conv, u, engine


async def _close(session: AsyncSession, engine) -> None:
    """必须调用 —— 释放 aiosqlite 线程（否则 asyncio.run 退出时会 hang）"""
    try:
        await session.close()
    finally:
        await engine.dispose()


# ══════════════════════════════════════════════════════════════
# Mock LLM responses
# ══════════════════════════════════════════════════════════════

def _tool_call(tool_id: str, name: str, args: dict) -> ToolCall:
    return ToolCall(id=tool_id, name=name, arguments_json=json.dumps(args, ensure_ascii=False))


def _llm_response(tool_calls: list[ToolCall], content: str = "") -> LLMResponse:
    return LLMResponse(
        content=content,
        tool_calls=tool_calls,
        finish_reason="tool_calls" if tool_calls else "stop",
        tokens_input=100,
        tokens_output=50,
    )


_VALID_SPEC_ARGS = {
    "scene_type": "web_component_dual",
    "identity": {
        "code_name": "rating-star",
        "display_name": "评分",
        "description_cn": "星级评分组件",
        "widget_code": "FORM_CUSTOM_RATING_STAR",
    },
    "intent": {
        "original_requirement": "做个评分组件",
        "core_purpose": "1-5 星点击打分",
        "acceptance_criteria": ["用户可点击 1~5 星完成评分"],
    },
    "spec": {
        "data": {
            "bof_type": "BOF_NUMBER",
            "component_model_field": ["NUM"],
            "form_value_shape": "scalar",
            "default_value": 0,
            "storage_note": "整数 1~5",
        },
        "config_properties": [],
        "scenes_required": ["edit", "read"],
        "scenes_optional": [],
    },
    "open_questions": [{"question": "主色?", "assumed_answer": "#409EFF"}],
}


class ScriptedBrainstormAgent(BrainstormAgent):
    """脚本化 BrainstormAgent：turn 0 detect_scene，turn 1 emit_spec，无需真实 LLM"""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._scripted_turn = 0

    async def _call_llm(self) -> LLMResponse:
        turn = self._scripted_turn
        self._scripted_turn += 1
        if turn == 0:
            return _llm_response([
                _tool_call("t1", "detect_scene", {
                    "scene_type": "web_component_dual",
                    "confidence": 0.95,
                    "reason": "『评分组件』明确是双端组件",
                }),
            ], content="")
        if turn == 1:
            # 跳过反问，直接人工把 P1 标为 answered（见测试里的 hook）
            return _llm_response([
                _tool_call("t2", "emit_spec", _VALID_SPEC_ARGS),
            ], content="")
        # 兜底（正常不该走到）
        return _llm_response([], content="ok")


class ScriptedCodingAgent(CodingAgent):
    """脚本化 CodingAgent：turn 0 返回无 tool_call 直接结束（最简版）"""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._scripted_turn = 0
        self.seen_user_message: str | None = None

    async def _call_llm(self) -> LLMResponse:
        # 抓到第一次 LLM 调用时的 user message 供测试断言
        if self.seen_user_message is None:
            for m in self._messages:
                if m.get("role") == "user":
                    self.seen_user_message = m.get("content", "")
                    break
        turn = self._scripted_turn
        self._scripted_turn += 1
        if turn == 0:
            # 不 call tool → LLM_NO_TOOL_CALL → 退出循环，COMPLETED
            return _llm_response([], content="已完成评分组件开发")
        return _llm_response([], content="ok")


# ══════════════════════════════════════════════════════════════
# 公共 fixture
# ══════════════════════════════════════════════════════════════

def _ctx(*, session_id: str, conv_id: int, user_id: int, input_data: dict | None = None) -> AgentContext:
    return AgentContext(
        session_id=session_id,
        conversation_id=conv_id,
        user_id=user_id,
        tenant_id=1,
        model="fake-model",
        input=input_data or {"requirement": "做个评分组件"},
        publisher=InMemoryEventPublisher(),
        trace_writer=InMemoryTraceWriter(),
        llm_client=object(),  # 仅占位，mock 覆盖了 _call_llm
    )


# ══════════════════════════════════════════════════════════════
# 核心 E2E 测试
# ══════════════════════════════════════════════════════════════

def test_brainstorm_emits_persists_transitions_phase():
    """阶段 1：Brainstorm → Spec 落库 + phase UNDERSTAND → CONFIRM"""
    async def run():
        db, conv, user, engine = await _make_db()
        try:
            bs_row = await start_brainstorm(
                db, conversation_id=conv.id, user_id=user.id, tenant_id=1, model="fake-model",
            )
            assert await get_phase(db, conv.id) == Phase.UNDERSTAND

            ctx = _ctx(session_id=bs_row.id, conv_id=conv.id, user_id=user.id)
            agent = ScriptedBrainstormAgent(ctx)

            # 把 P1 在 scene 设好后自动标 answered
            orig_call = agent._call_llm

            async def patched():
                resp = await orig_call()
                if agent.state.scene_type:
                    for q in agent.state.p1_questions:
                        if not q.answered:
                            q.answered = True
                            q.answer = "默认"
                return resp

            agent._call_llm = patched  # type: ignore[method-assign]

            result = await driver.drive_brainstorm(db, agent=agent, session_id=bs_row.id)
            assert result.status == "emitted", f"expected emitted got {result.status}"
            assert result.spec_id is not None
            assert result.spec_envelope is not None
            assert result.spec_envelope["identity"]["code_name"] == "rating-star"

            spec_row = await spec_service.get_spec(db, result.spec_id)
            assert spec_row is not None
            assert spec_row.code_name == "rating-star"
            assert spec_row.confidence >= 0.9
            assert await get_phase(db, conv.id) == Phase.CONFIRM
        finally:
            await _close(db, engine)

    _run(run)


def test_coding_from_spec_consumes_structured_spec_and_finishes():
    """阶段 2：Spec → CodingAgent 注入 Structured Spec 段 + 完成运行"""
    async def run():
        db, conv, user, engine = await _make_db()
        try:
            from app.services import brainstorm_session_service as bs_svc
            bs_row = await bs_svc.create_session(
                db, conversation_id=conv.id, user_id=user.id, tenant_id=1,
                model_used="fake-model",
            )
            envelope = {
                "schema_version": "1.0",
                "scene_type": "web_component_dual",
                "spec_id": "unused_will_be_replaced",
                "provenance": {
                    "brainstorm_session_id": bs_row.id,
                    "created_at": "2026-04-20T00:00:00+00:00",
                    "created_by": "agent",
                    "model": "fake-model",
                    "version": 1,
                    "confidence": 0.95,
                    "open_questions": [{"question": "主色?", "assumed_answer": "#409EFF"}],
                },
                "identity": {
                    "code_name": "rating-star",
                    "display_name": "评分",
                    "description_cn": "星级评分",
                    "widget_code": "FORM_CUSTOM_RATING_STAR",
                },
                "intent": _VALID_SPEC_ARGS["intent"],
                "spec": _VALID_SPEC_ARGS["spec"],
            }
            spec_row = await spec_service.save_spec(
                db, brainstorm_session_id=bs_row.id, envelope=envelope,
            )
            await transition_phase(db, conversation_id=conv.id, to=Phase.UNDERSTAND)
            await transition_phase(db, conversation_id=conv.id, to=Phase.CONFIRM)
            await transition_phase(db, conversation_id=conv.id, to=Phase.GENERATE)

            ctx = _ctx(session_id="c_s1", conv_id=conv.id, user_id=user.id, input_data={})

            import app.orchestrator.driver as drv
            orig_cls = drv.CodingAgent
            drv.CodingAgent = ScriptedCodingAgent  # type: ignore[misc,assignment]
            try:
                result = await driver.drive_coding_from_spec(
                    db, spec_envelope=spec_row.content, ctx=ctx, max_turns=5,
                )
            finally:
                drv.CodingAgent = orig_cls  # type: ignore[misc,assignment]

            assert result.status == "done", f"expected done got {result.status}"
            assert await get_phase(db, conv.id) == Phase.DONE
            assert ctx.input.get("spec_brief") is not None
            assert "rating-star" in ctx.input["spec_brief"]
            assert ctx.input["project_type"] == "form-component-dual"
        finally:
            await _close(db, engine)

    _run(run)


def test_full_pipeline_brainstorm_to_coding():
    """阶段 1+2：一次跑通 Brainstorm → Spec → 用户确认 → Coding → DONE"""
    async def run():
        db, conv, user, engine = await _make_db()
        try:
            # 阶段 1：Brainstorm
            bs_row = await start_brainstorm(
                db, conversation_id=conv.id, user_id=user.id, tenant_id=1, model="fake-model",
            )
            ctx_bs = _ctx(session_id=bs_row.id, conv_id=conv.id, user_id=user.id)
            brainstorm_agent = ScriptedBrainstormAgent(ctx_bs)
            orig_call = brainstorm_agent._call_llm

            async def patched_bs_call():
                resp = await orig_call()
                if brainstorm_agent.state.scene_type:
                    for q in brainstorm_agent.state.p1_questions:
                        q.answered = True
                        q.answer = "默认"
                return resp

            brainstorm_agent._call_llm = patched_bs_call  # type: ignore[method-assign]

            bs_result = await driver.drive_brainstorm(
                db, agent=brainstorm_agent, session_id=bs_row.id,
            )
            assert bs_result.status == "emitted"
            assert await get_phase(db, conv.id) == Phase.CONFIRM

            # 阶段 2：用户确认 Spec
            envelope = await driver.confirm_spec_and_prepare_coding(
                db, conversation_id=conv.id, spec_id=bs_result.spec_id, need_scaffold=False,
            )
            assert await get_phase(db, conv.id) == Phase.GENERATE
            assert envelope["scene_type"] == "web_component_dual"

            # 阶段 3：CodingAgent 运行
            ctx_c = _ctx(session_id="c_s2", conv_id=conv.id, user_id=user.id, input_data={})
            import app.orchestrator.driver as drv
            orig_cls = drv.CodingAgent
            drv.CodingAgent = ScriptedCodingAgent  # type: ignore[misc,assignment]
            try:
                coding_result = await driver.drive_coding_from_spec(
                    db, spec_envelope=envelope, ctx=ctx_c, max_turns=5,
                )
            finally:
                drv.CodingAgent = orig_cls  # type: ignore[misc,assignment]

            assert coding_result.status == "done"
            assert await get_phase(db, conv.id) == Phase.DONE

            # publisher 事件中应包含 scene_detected 和 spec_emitted
            bs_pub = ctx_bs.publisher
            assert hasattr(bs_pub, "events")
            event_types = {e["type"] for e in bs_pub.events}
            assert any("scene_detected" in t for t in event_types), (
                f"missing scene_detected in {event_types}"
            )
            assert any("spec_emitted" in t for t in event_types), (
                f"missing spec_emitted in {event_types}"
            )
        finally:
            await _close(db, engine)

    _run(run)


def test_brainstorm_degraded_path_no_emit():
    """未 emit 就结束：brainstorm status=degraded，phase 不推进"""
    async def run():
        db, conv, user, engine = await _make_db()
        try:
            bs_row = await start_brainstorm(
                db, conversation_id=conv.id, user_id=user.id, tenant_id=1, model="fake-model",
            )
            ctx = _ctx(session_id=bs_row.id, conv_id=conv.id, user_id=user.id)

            class IdleAgent(BrainstormAgent):
                async def _call_llm(self):
                    return _llm_response([], content="不做任何事")

            agent = IdleAgent(ctx)
            result = await driver.drive_brainstorm(db, agent=agent, session_id=bs_row.id)
            assert result.status == "degraded"
            assert result.spec_id is None
            assert await get_phase(db, conv.id) == Phase.UNDERSTAND
        finally:
            await _close(db, engine)

    _run(run)


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
