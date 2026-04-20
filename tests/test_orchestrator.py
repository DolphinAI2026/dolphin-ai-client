"""Orchestrator 单元测试（phase 状态机 + coordinator）。

覆盖：
- Phase 合法/非法转移表
- parse_phase 容错 / 语义查询（is_terminal/is_running/is_awaiting_user）
- transition_phase 持久化 / strict=False 绕行
- route_user_message 各 phase 的 RouteDecision
- start_brainstorm / on_spec_confirmed / on_coding_done 一体化流程
"""
import asyncio
import os
import secrets
import sys

os.environ.setdefault("LLM_API_KEY", "test-key")
os.environ.setdefault("JWT_SECRET_KEY", "test-secret")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine  # noqa: E402

from app.database import Base  # noqa: E402
import app.models  # noqa: F401,E402
from app.models import Conversation, User  # noqa: E402
from app.orchestrator import (  # noqa: E402
    Phase,
    PhaseTransitionError,
    can_transition,
    get_phase,
    is_awaiting_user,
    is_running,
    is_terminal,
    on_agent_failed,
    on_brainstorm_emit,
    on_coding_done,
    on_spec_confirmed,
    on_user_cancel,
    parse_phase,
    reset_phase,
    route_user_message,
    start_brainstorm,
    transition_phase,
)
from app.orchestrator.phases import assert_transition  # noqa: E402
from app.services import brainstorm_session_service as bs_svc  # noqa: E402


# ══════════════════════════════════════════════════════════════
# DB fixture（每测一个内存库）
# ══════════════════════════════════════════════════════════════

def _run(coro):
    """跑 coroutine。用 new_event_loop + close 以容忍 aiosqlite 连接未 dispose。
    （asyncio.run 会等 aiosqlite 线程退出，若未 dispose engine 会挂起）"""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


async def _make_db() -> tuple[AsyncSession, Conversation, "Any"]:
    """返回 (session, conv, engine)；测试必须 finally 里 await _close(session, engine)
    —— 否则 aiosqlite 线程会卡住 asyncio.run cleanup。
    """
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    sm = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    session = sm()
    u = User(username=f"o_u_{secrets.token_hex(3)}", hashed_password="x")
    session.add(u)
    await session.flush()
    conv = Conversation(
        user_id=u.id, tenant_id=1, title="t", agent_type="coding", status="active",
        coding_phase=None,
    )
    session.add(conv)
    await session.flush()
    return session, conv, engine


async def _close(session: AsyncSession, engine) -> None:
    try:
        await session.close()
    finally:
        await engine.dispose()


# ══════════════════════════════════════════════════════════════
# phases.py 表驱动测试
# ══════════════════════════════════════════════════════════════

def test_parse_phase_none_is_idle():
    assert parse_phase(None) == Phase.IDLE
    assert parse_phase("") == Phase.IDLE


def test_parse_phase_unknown_falls_back_to_idle():
    assert parse_phase("nonsense") == Phase.IDLE


def test_can_transition_basic_happy_path():
    """IDLE → UNDERSTAND → CONFIRM → GENERATE → DONE → UNDERSTAND"""
    flow = [Phase.IDLE, Phase.UNDERSTAND, Phase.CONFIRM, Phase.GENERATE, Phase.DONE, Phase.UNDERSTAND]
    for a, b in zip(flow, flow[1:]):
        assert can_transition(a, b), f"{a} → {b} 应合法"


def test_cannot_skip_confirm_from_understand_to_generate():
    assert not can_transition(Phase.UNDERSTAND, Phase.GENERATE)


def test_cannot_transition_from_aborted():
    for target in Phase:
        if target == Phase.ABORTED:
            continue
        assert not can_transition(Phase.ABORTED, target), f"ABORTED → {target} 应禁止"


def test_confirm_can_refine_back_to_understand():
    assert can_transition(Phase.CONFIRM, Phase.UNDERSTAND)


def test_verify_can_fallback_to_generate():
    """AC 失败时重跑 coding"""
    assert can_transition(Phase.VERIFY, Phase.GENERATE)


def test_assert_transition_raises():
    try:
        assert_transition(Phase.IDLE, Phase.DONE)
    except PhaseTransitionError:
        return
    raise AssertionError("expected PhaseTransitionError")


def test_is_terminal():
    assert is_terminal(Phase.DONE)
    assert is_terminal(Phase.FAILED)
    assert is_terminal(Phase.ABORTED)
    assert not is_terminal(Phase.UNDERSTAND)


def test_is_running():
    assert is_running(Phase.GENERATE)
    assert is_running(Phase.UNDERSTAND)
    assert not is_running(Phase.CONFIRM)
    assert not is_running(Phase.DONE)


def test_is_awaiting_user():
    assert is_awaiting_user(Phase.IDLE)
    assert is_awaiting_user(Phase.CONFIRM)
    assert is_awaiting_user(Phase.DONE)
    assert is_awaiting_user(Phase.FAILED)
    assert not is_awaiting_user(Phase.GENERATE)


# ══════════════════════════════════════════════════════════════
# coordinator transition_phase
# ══════════════════════════════════════════════════════════════

def test_transition_phase_persists():
    async def run():
        db, conv, _engine = await _make_db()
        assert await get_phase(db, conv.id) == Phase.IDLE
        await transition_phase(db, conversation_id=conv.id, to=Phase.UNDERSTAND)
        assert await get_phase(db, conv.id) == Phase.UNDERSTAND
    _run(run())


def test_transition_phase_raises_on_invalid():
    async def run():
        db, conv, _engine = await _make_db()
        try:
            await transition_phase(db, conversation_id=conv.id, to=Phase.DONE)
        except PhaseTransitionError:
            return
        raise AssertionError("expected PhaseTransitionError")
    _run(run())


def test_transition_phase_non_strict_allows_invalid():
    async def run():
        db, conv, _engine = await _make_db()
        await transition_phase(
            db, conversation_id=conv.id, to=Phase.FAILED, strict=False,
        )
        assert await get_phase(db, conv.id) == Phase.FAILED
    _run(run())


def test_transition_phase_same_is_noop():
    async def run():
        db, conv, _engine = await _make_db()
        await transition_phase(db, conversation_id=conv.id, to=Phase.UNDERSTAND)
        # 同 phase 不报错
        await transition_phase(db, conversation_id=conv.id, to=Phase.UNDERSTAND)
        assert await get_phase(db, conv.id) == Phase.UNDERSTAND
    _run(run())


def test_reset_phase_back_to_idle():
    async def run():
        db, conv, _engine = await _make_db()
        await transition_phase(db, conversation_id=conv.id, to=Phase.UNDERSTAND)
        await reset_phase(db, conv.id)
        assert await get_phase(db, conv.id) == Phase.IDLE
    _run(run())


# ══════════════════════════════════════════════════════════════
# route_user_message
# ══════════════════════════════════════════════════════════════

def test_route_idle_starts_brainstorm():
    async def run():
        db, conv, _engine = await _make_db()
        d = await route_user_message(db, conversation_id=conv.id)
        assert d.action == "start_brainstorm"
        assert d.phase == Phase.IDLE
    _run(run())


def test_route_understand_without_session_starts_new():
    async def run():
        db, conv, _engine = await _make_db()
        await transition_phase(db, conversation_id=conv.id, to=Phase.UNDERSTAND)
        d = await route_user_message(db, conversation_id=conv.id)
        assert d.action == "start_brainstorm"
    _run(run())


def test_route_understand_with_active_session_continues():
    async def run():
        db, conv, _engine = await _make_db()
        await transition_phase(db, conversation_id=conv.id, to=Phase.UNDERSTAND)
        bs = await bs_svc.create_session(db, conversation_id=conv.id, user_id=1, tenant_id=1)
        d = await route_user_message(db, conversation_id=conv.id)
        assert d.action == "continue_brainstorm"
        assert d.session_id == bs.id
    _run(run())


def test_route_understand_with_suspended_session_resumes():
    async def run():
        db, conv, _engine = await _make_db()
        await transition_phase(db, conversation_id=conv.id, to=Phase.UNDERSTAND)
        bs = await bs_svc.create_session(db, conversation_id=conv.id, user_id=1, tenant_id=1)
        bs.status = bs_svc.BsStatus.SUSPENDED
        await db.flush()
        d = await route_user_message(db, conversation_id=conv.id)
        assert d.action == "resume_brainstorm"
        assert d.session_id == bs.id
    _run(run())


def test_route_confirm_user_text_triggers_refine():
    async def run():
        db, conv, _engine = await _make_db()
        await transition_phase(db, conversation_id=conv.id, to=Phase.UNDERSTAND)
        await transition_phase(db, conversation_id=conv.id, to=Phase.CONFIRM)
        bs = await bs_svc.create_session(db, conversation_id=conv.id, user_id=1, tenant_id=1)
        d = await route_user_message(db, conversation_id=conv.id)
        assert d.action == "refine_brainstorm"
        assert d.session_id == bs.id
    _run(run())


def test_route_generate_rejects_message():
    async def run():
        db, conv, _engine = await _make_db()
        for p in [Phase.UNDERSTAND, Phase.CONFIRM, Phase.SCAFFOLD, Phase.GENERATE]:
            await transition_phase(db, conversation_id=conv.id, to=p)
        d = await route_user_message(db, conversation_id=conv.id)
        assert d.action == "reject_message"
        assert d.phase == Phase.GENERATE
    _run(run())


def test_route_done_triggers_iterate():
    async def run():
        db, conv, _engine = await _make_db()
        # 走完整流程到 DONE
        for p in [Phase.UNDERSTAND, Phase.CONFIRM, Phase.GENERATE, Phase.DONE]:
            await transition_phase(db, conversation_id=conv.id, to=p)
        d = await route_user_message(db, conversation_id=conv.id)
        assert d.action == "iterate"
    _run(run())


def test_route_failed_asks_restart():
    async def run():
        db, conv, _engine = await _make_db()
        await transition_phase(db, conversation_id=conv.id, to=Phase.UNDERSTAND)
        await transition_phase(db, conversation_id=conv.id, to=Phase.FAILED, strict=False)
        d = await route_user_message(db, conversation_id=conv.id)
        assert d.action == "restart"
    _run(run())


# ══════════════════════════════════════════════════════════════
# 高级编排
# ══════════════════════════════════════════════════════════════

def test_start_brainstorm_sets_phase_and_binds_session():
    async def run():
        db, conv, _engine = await _make_db()
        bs = await start_brainstorm(
            db,
            conversation_id=conv.id,
            user_id=1,
            tenant_id=1,
            model="test-model",
        )
        assert bs.id.startswith("bs_")
        assert await get_phase(db, conv.id) == Phase.UNDERSTAND
        fresh = await db.get(Conversation, conv.id)
        assert fresh.coding_active_brainstorm_session_id == bs.id
    _run(run())


def test_on_brainstorm_emit_moves_to_confirm():
    async def run():
        db, conv, _engine = await _make_db()
        bs = await start_brainstorm(
            db, conversation_id=conv.id, user_id=1, tenant_id=1, model="m",
        )
        await on_brainstorm_emit(
            db, conversation_id=conv.id, brainstorm_session_id=bs.id, spec_id="spec_x",
        )
        assert await get_phase(db, conv.id) == Phase.CONFIRM
    _run(run())


def test_on_spec_confirmed_first_time_goes_to_scaffold():
    async def run():
        db, conv, _engine = await _make_db()
        bs = await start_brainstorm(
            db, conversation_id=conv.id, user_id=1, tenant_id=1, model="m",
        )
        await on_brainstorm_emit(db, conversation_id=conv.id, brainstorm_session_id=bs.id, spec_id="spec_x")
        await on_spec_confirmed(db, conversation_id=conv.id, spec_id="spec_x", need_scaffold=True)
        assert await get_phase(db, conv.id) == Phase.SCAFFOLD
    _run(run())


def test_on_spec_confirmed_iteration_goes_to_generate():
    async def run():
        db, conv, _engine = await _make_db()
        bs = await start_brainstorm(db, conversation_id=conv.id, user_id=1, tenant_id=1, model="m")
        await on_brainstorm_emit(db, conversation_id=conv.id, brainstorm_session_id=bs.id, spec_id="spec_x")
        await on_spec_confirmed(db, conversation_id=conv.id, spec_id="spec_x", need_scaffold=False)
        assert await get_phase(db, conv.id) == Phase.GENERATE
    _run(run())


def test_on_coding_done_moves_to_done():
    async def run():
        db, conv, _engine = await _make_db()
        bs = await start_brainstorm(db, conversation_id=conv.id, user_id=1, tenant_id=1, model="m")
        await on_brainstorm_emit(db, conversation_id=conv.id, brainstorm_session_id=bs.id, spec_id="s")
        await on_spec_confirmed(db, conversation_id=conv.id, spec_id="s", need_scaffold=False)
        await on_coding_done(db, conversation_id=conv.id)
        assert await get_phase(db, conv.id) == Phase.DONE
    _run(run())


def test_on_agent_failed_short_circuits_to_failed():
    async def run():
        db, conv, _engine = await _make_db()
        await start_brainstorm(db, conversation_id=conv.id, user_id=1, tenant_id=1, model="m")
        await on_agent_failed(db, conversation_id=conv.id, error_message="boom")
        assert await get_phase(db, conv.id) == Phase.FAILED
    _run(run())


def test_on_user_cancel_from_any_phase():
    async def run():
        db, conv, _engine = await _make_db()
        await start_brainstorm(db, conversation_id=conv.id, user_id=1, tenant_id=1, model="m")
        # 非 strict：即使 UNDERSTAND → ABORTED 合法，也演示 FAILED → ABORTED 这种非常规
        await on_user_cancel(db, conversation_id=conv.id)
        assert await get_phase(db, conv.id) == Phase.ABORTED
    _run(run())


def test_full_happy_path():
    """IDLE → UNDERSTAND → CONFIRM → SCAFFOLD → GENERATE → DONE → UNDERSTAND (iterate)"""
    async def run():
        db, conv, _engine = await _make_db()
        bs = await start_brainstorm(db, conversation_id=conv.id, user_id=1, tenant_id=1, model="m")
        assert await get_phase(db, conv.id) == Phase.UNDERSTAND

        await on_brainstorm_emit(db, conversation_id=conv.id, brainstorm_session_id=bs.id, spec_id="s1")
        assert await get_phase(db, conv.id) == Phase.CONFIRM

        await on_spec_confirmed(db, conversation_id=conv.id, spec_id="s1", need_scaffold=True)
        assert await get_phase(db, conv.id) == Phase.SCAFFOLD

        await transition_phase(db, conversation_id=conv.id, to=Phase.GENERATE)
        assert await get_phase(db, conv.id) == Phase.GENERATE

        await on_coding_done(db, conversation_id=conv.id)
        assert await get_phase(db, conv.id) == Phase.DONE

        # 迭代
        await transition_phase(db, conversation_id=conv.id, to=Phase.UNDERSTAND)
        assert await get_phase(db, conv.id) == Phase.UNDERSTAND
    _run(run())


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
