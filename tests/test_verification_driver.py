"""verification_report_service + drive_verification + drive_coding_with_autofix 集成测试。

场景（都用脚本化 agent + 临时 workspace 目录，不调真实 LLM）：
- drive_verification：agent 跑 → 落 verification_reports 表
- drive_coding_with_autofix：first round verify failed → 第二轮 coding → passed
- drive_coding_with_autofix：达到 max rounds 仍 failed → final_status=failed
- drive_coding_with_autofix：verify partial（needs_review）→ 不重跑，返回 partial
"""
import asyncio
import json
import os
import secrets
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("LLM_API_KEY", "test-key")
os.environ.setdefault("JWT_SECRET_KEY", "test-secret")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine  # noqa: E402

from app.agents.coding import CodingAgent  # noqa: E402
from app.agents.publisher import InMemoryEventPublisher  # noqa: E402
from app.agents.trace_writer import InMemoryTraceWriter  # noqa: E402
from app.agents.types import AgentContext, LLMResponse, ToolCall  # noqa: E402
from app.agents.verification import VerificationAgent  # noqa: E402
from app.database import Base  # noqa: E402
import app.models  # noqa: F401,E402
import app.models.agent_models as agent_models  # noqa: E402
from app.models import Conversation, User  # noqa: E402
from app.orchestrator import Phase, driver, transition_phase  # noqa: E402
from app.services import brainstorm_session_service as bs_svc  # noqa: E402
from app.services import spec_service  # noqa: E402
from app.services import verification_report_service as vr_svc  # noqa: E402


def _run(coro_factory):
    async def w():
        return await coro_factory()
    asyncio.run(w())


async def _make_db() -> tuple[AsyncSession, Conversation, User, "Any"]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    sm = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    session = sm()
    u = User(username=f"vd_{secrets.token_hex(3)}", hashed_password="x")
    session.add(u)
    await session.flush()
    conv = Conversation(
        user_id=u.id, tenant_id=1, title="t", agent_type="coding", status="active",
    )
    session.add(conv)
    await session.flush()
    return session, conv, u, engine


async def _close(session: AsyncSession, engine) -> None:
    try:
        await session.close()
    finally:
        await engine.dispose()


def _envelope(spec_id: str = "spec_vd") -> dict:
    return {
        "schema_version": "1.0",
        "scene_type": "web_component_dual",
        "spec_id": spec_id,
        "provenance": {
            "brainstorm_session_id": "bs_x",
            "created_at": "2026-04-20T00:00:00+00:00",
            "created_by": "agent",
            "model": "fake",
            "version": 1,
            "confidence": 0.95,
            "open_questions": [],
        },
        "identity": {
            "code_name": "rating-star",
            "display_name": "评分",
            "description_cn": "x",
            "widget_code": "FORM_CUSTOM_RATING_STAR",
        },
        "intent": {
            "original_requirement": "做评分",
            "core_purpose": "1-5 星",
            "acceptance_criteria": ["可点击 1-5 星", "主色可配"],
        },
        "spec": {
            "data": {
                "bof_type": "BOF_NUMBER", "component_model_field": ["NUM"],
                "form_value_shape": "scalar", "default_value": 0, "storage_note": "x",
            },
            "config_properties": [],
            "scenes_required": ["edit", "read"],
            "scenes_optional": [],
            "constraints_hard": [],
            "constraints_soft": [],
        },
    }


def _tc(tool_id: str, name: str, args: dict) -> ToolCall:
    return ToolCall(id=tool_id, name=name, arguments_json=json.dumps(args, ensure_ascii=False))


def _llm(tool_calls: list[ToolCall], content: str = "") -> LLMResponse:
    return LLMResponse(
        content=content, tool_calls=tool_calls,
        finish_reason="tool_calls" if tool_calls else "stop",
        tokens_input=10, tokens_output=5,
    )


# ══════════════════════════════════════════════════════════════
# ScriptedVerificationAgent：按预定 tool_call 序列推进
# ══════════════════════════════════════════════════════════════

class _VerifyAllPassAgent(VerificationAgent):
    """逐个 check_ac passed，然后 emit_report"""

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self._script_turn = 0

    async def _call_llm(self):
        t = self._script_turn
        self._script_turn += 1
        if t < len(self.state.ac_items):
            return _llm([_tc(
                f"t{t}", "check_ac",
                {
                    "ac_index": self.state.ac_items[t].index,
                    "status": "passed",
                    "evidence": f"见 edit.vue 的实现（第 {t+1} 项）",
                    "confidence": 0.95,
                },
            )])
        return _llm([_tc(
            f"emit_{t}", "emit_report",
            {"summary": "全部通过"},
        )])


class _VerifyAllFailAgent(VerificationAgent):
    """逐个 check_ac failed，然后 emit_report"""

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self._script_turn = 0

    async def _call_llm(self):
        t = self._script_turn
        self._script_turn += 1
        if t < len(self.state.ac_items):
            return _llm([_tc(
                f"t{t}", "check_ac",
                {
                    "ac_index": self.state.ac_items[t].index,
                    "status": "failed",
                    "evidence": f"AC #{t} 未实现：缺少对应代码",
                    "confidence": 0.95,
                },
            )])
        return _llm([_tc(
            f"emit_{t}", "emit_report",
            {"summary": "全部失败"},
        )])


class _VerifyNeedsReviewAgent(VerificationAgent):
    """所有 AC 标 needs_review → overall=partial"""

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self._script_turn = 0

    async def _call_llm(self):
        t = self._script_turn
        self._script_turn += 1
        if t < len(self.state.ac_items):
            return _llm([_tc(
                f"t{t}", "check_ac",
                {
                    "ac_index": self.state.ac_items[t].index,
                    "status": "needs_review",
                    "evidence": "代码风格不清晰，无法确定",
                    "confidence": 0.6,
                },
            )])
        return _llm([_tc(f"emit_{t}", "emit_report", {"summary": "需人工审核"})])


class _NoopCodingAgent(CodingAgent):
    """CodingAgent 不做事直接返回 COMPLETED（LLM 无 tool_call）"""

    async def _call_llm(self):
        return _llm([], content="done")


# ══════════════════════════════════════════════════════════════
# Fake retry CodingAgent：第一轮跑完，第二轮跑完（都 noop，但测试里检查调用次数）
# ══════════════════════════════════════════════════════════════

class _CountingCodingAgent(CodingAgent):
    instance_count = 0
    call_count_total = 0

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        _CountingCodingAgent.instance_count += 1

    async def _call_llm(self):
        _CountingCodingAgent.call_count_total += 1
        return _llm([], content="coding done")


# ══════════════════════════════════════════════════════════════
# 辅助：构造 AgentContext
# ══════════════════════════════════════════════════════════════

def _agent_ctx(session_id: str, conv_id: int, user_id: int, input_data: dict | None = None) -> AgentContext:
    return AgentContext(
        session_id=session_id,
        conversation_id=conv_id,
        user_id=user_id,
        tenant_id=1,
        model="fake-model",
        input=input_data or {},
        publisher=InMemoryEventPublisher(),
        trace_writer=InMemoryTraceWriter(),
        llm_client=object(),
    )


# ══════════════════════════════════════════════════════════════
# drive_verification
# ══════════════════════════════════════════════════════════════

def test_drive_verification_all_pass_persists_report():
    async def run():
        db, conv, user, engine = await _make_db()
        try:
            with tempfile.TemporaryDirectory() as td:
                envelope = _envelope()

                # mock VerificationAgent constructor
                import app.orchestrator.driver as drv
                orig = drv.VerificationAgent
                drv.VerificationAgent = _VerifyAllPassAgent  # type: ignore[assignment]
                try:
                    ctx = _agent_ctx("v1", conv.id, user.id)
                    result = await driver.drive_verification(
                        db,
                        ctx=ctx,
                        spec_envelope=envelope,
                        workspace_root=td,
                        coding_session_id="c_xxx",
                    )
                finally:
                    drv.VerificationAgent = orig  # type: ignore[assignment]

                assert result.status == "emitted"
                assert result.overall_status == "passed"
                assert result.passed_count == 2
                assert result.failed_count == 0
                assert result.report_id is not None

                # DB 验证
                row = await vr_svc.get_report(db, result.report_id)
                assert row is not None
                assert row.coding_session_id == "c_xxx"
                assert row.spec_id == envelope["spec_id"]
                assert row.overall_status == "passed"
                assert len(row.items) == 2
        finally:
            await _close(db, engine)
    _run(run)


def test_drive_verification_all_failed():
    async def run():
        db, conv, user, engine = await _make_db()
        try:
            with tempfile.TemporaryDirectory() as td:
                envelope = _envelope()
                import app.orchestrator.driver as drv
                orig = drv.VerificationAgent
                drv.VerificationAgent = _VerifyAllFailAgent  # type: ignore[assignment]
                try:
                    ctx = _agent_ctx("v2", conv.id, user.id)
                    result = await driver.drive_verification(
                        db, ctx=ctx, spec_envelope=envelope,
                        workspace_root=td, coding_session_id="c_zzz",
                    )
                finally:
                    drv.VerificationAgent = orig  # type: ignore[assignment]

                assert result.status == "emitted"
                assert result.overall_status == "failed"
                assert result.failed_count == 2
                row = await vr_svc.get_report(db, result.report_id)
                assert row.overall_status == "failed"
        finally:
            await _close(db, engine)
    _run(run)


def test_drive_verification_needs_review_returns_partial():
    async def run():
        db, conv, user, engine = await _make_db()
        try:
            with tempfile.TemporaryDirectory() as td:
                envelope = _envelope()
                import app.orchestrator.driver as drv
                orig = drv.VerificationAgent
                drv.VerificationAgent = _VerifyNeedsReviewAgent  # type: ignore[assignment]
                try:
                    ctx = _agent_ctx("v3", conv.id, user.id)
                    result = await driver.drive_verification(
                        db, ctx=ctx, spec_envelope=envelope,
                        workspace_root=td, coding_session_id="c_qqq",
                    )
                finally:
                    drv.VerificationAgent = orig  # type: ignore[assignment]

                assert result.overall_status == "partial"
                assert result.passed_count == 0
        finally:
            await _close(db, engine)
    _run(run)


def test_vr_service_list_and_failed_helpers():
    async def run():
        db, conv, user, engine = await _make_db()
        try:
            # seed 3 reports（不同状态）for 同一 spec
            async def save(spec_id, coding_id, overall, items, constraints=None):
                row = agent_models.VerificationReport(
                    id=f"vr_{secrets.token_hex(3)}",
                    coding_session_id=coding_id,
                    spec_id=spec_id,
                    overall_status=overall,
                    passed_count=sum(1 for i in items if i.get("status") == "passed"),
                    failed_count=sum(1 for i in items if i.get("status") == "failed"),
                    items=items,
                    constraint_results=constraints or [],
                )
                db.add(row)
                await db.flush()
                return row

            r1 = await save("spec_a", "c_1", "passed",
                            [{"index": 0, "status": "passed", "description": "x", "evidence": "y", "confidence": 0.9}])
            r2 = await save("spec_a", "c_2", "failed",
                            [{"index": 0, "status": "failed", "description": "x", "evidence": "y", "confidence": 0.9}])
            r3 = await save("spec_b", "c_3", "failed",
                            [],
                            [{"text": "禁止 x", "severity": "hard", "status": "violated", "evidence": ""}])
            await db.commit()

            # list by spec
            rs = await vr_svc.list_reports_for_spec(db, "spec_a")
            assert {r.id for r in rs} == {r1.id, r2.id}
            # 最新在前
            assert rs[0].created_at >= rs[1].created_at

            # list by coding session
            rs = await vr_svc.list_reports_for_coding_session(db, "c_1")
            assert [r.id for r in rs] == [r1.id]

            # failed_ac_items
            failed = vr_svc.failed_ac_items(r2)
            assert len(failed) == 1
            assert failed[0]["index"] == 0

            # has_blocking_issues
            assert vr_svc.has_blocking_issues(r2) is True  # failed
            assert vr_svc.has_blocking_issues(r3) is True  # hard violated
            assert vr_svc.has_blocking_issues(r1) is False
        finally:
            await _close(db, engine)
    _run(run)


# ══════════════════════════════════════════════════════════════
# drive_coding_with_autofix
# ══════════════════════════════════════════════════════════════

def test_autofix_loop_first_round_passes():
    """verify 一次过 → rounds=1 / final_status=passed"""
    async def run():
        db, conv, user, engine = await _make_db()
        try:
            with tempfile.TemporaryDirectory() as td:
                envelope = _envelope()
                import app.orchestrator.driver as drv
                orig_c = drv.CodingAgent
                orig_v = drv.VerificationAgent
                drv.CodingAgent = _NoopCodingAgent  # type: ignore[assignment]
                drv.VerificationAgent = _VerifyAllPassAgent  # type: ignore[assignment]
                try:
                    def coding_ctx():
                        return _agent_ctx(f"c_{secrets.token_hex(3)}", conv.id, user.id)
                    def verify_ctx():
                        return _agent_ctx(f"v_{secrets.token_hex(3)}", conv.id, user.id)

                    result = await driver.drive_coding_with_autofix(
                        db,
                        conversation_id=conv.id,
                        spec_envelope=envelope,
                        coding_ctx_factory=coding_ctx,
                        verification_ctx_factory=verify_ctx,
                        workspace_root=td,
                        coding_session_id="c_auto1",
                        max_fix_rounds=2,
                    )
                finally:
                    drv.CodingAgent = orig_c  # type: ignore[assignment]
                    drv.VerificationAgent = orig_v  # type: ignore[assignment]

                assert result.final_status == "passed"
                assert result.rounds == 1
                assert len(result.reports) == 1
                assert len(result.coding_results) == 1
        finally:
            await _close(db, engine)
    _run(run)


def test_autofix_loop_retries_until_fail():
    """verify 总是失败 → 达到 max rounds 后 final_status=failed，记录所有轮的 report"""
    async def run():
        db, conv, user, engine = await _make_db()
        try:
            with tempfile.TemporaryDirectory() as td:
                envelope = _envelope()
                import app.orchestrator.driver as drv
                orig_c = drv.CodingAgent
                orig_v = drv.VerificationAgent
                _CountingCodingAgent.instance_count = 0
                _CountingCodingAgent.call_count_total = 0
                drv.CodingAgent = _CountingCodingAgent  # type: ignore[assignment]
                drv.VerificationAgent = _VerifyAllFailAgent  # type: ignore[assignment]
                try:
                    def coding_ctx():
                        return _agent_ctx(f"c_{secrets.token_hex(3)}", conv.id, user.id)
                    def verify_ctx():
                        return _agent_ctx(f"v_{secrets.token_hex(3)}", conv.id, user.id)

                    result = await driver.drive_coding_with_autofix(
                        db,
                        conversation_id=conv.id,
                        spec_envelope=envelope,
                        coding_ctx_factory=coding_ctx,
                        verification_ctx_factory=verify_ctx,
                        workspace_root=td,
                        coding_session_id="c_auto2",
                        max_fix_rounds=2,
                    )
                finally:
                    drv.CodingAgent = orig_c  # type: ignore[assignment]
                    drv.VerificationAgent = orig_v  # type: ignore[assignment]

                assert result.final_status == "failed"
                # rounds = 1 + 2 = 3（初始 + 两次重试）
                assert result.rounds == 3
                # CodingAgent 被实例化 3 次
                assert _CountingCodingAgent.instance_count == 3
                # verify 也跑了 3 次
                assert len(result.reports) == 3
                # 第 2/3 轮应该带着 fix_hint（检查 ctx.input）
                # 通过 coding_results 的状态间接验证：3 次都 done
                assert all(r.status == "done" for r in result.coding_results)
        finally:
            await _close(db, engine)
    _run(run)


def test_autofix_loop_partial_does_not_retry():
    """verify 结果是 partial（needs_review）→ 不重跑"""
    async def run():
        db, conv, user, engine = await _make_db()
        try:
            with tempfile.TemporaryDirectory() as td:
                envelope = _envelope()
                import app.orchestrator.driver as drv
                orig_c = drv.CodingAgent
                orig_v = drv.VerificationAgent
                _CountingCodingAgent.instance_count = 0
                drv.CodingAgent = _CountingCodingAgent  # type: ignore[assignment]
                drv.VerificationAgent = _VerifyNeedsReviewAgent  # type: ignore[assignment]
                try:
                    def coding_ctx():
                        return _agent_ctx(f"c_{secrets.token_hex(3)}", conv.id, user.id)
                    def verify_ctx():
                        return _agent_ctx(f"v_{secrets.token_hex(3)}", conv.id, user.id)

                    result = await driver.drive_coding_with_autofix(
                        db,
                        conversation_id=conv.id,
                        spec_envelope=envelope,
                        coding_ctx_factory=coding_ctx,
                        verification_ctx_factory=verify_ctx,
                        workspace_root=td,
                        coding_session_id="c_auto3",
                        max_fix_rounds=2,
                    )
                finally:
                    drv.CodingAgent = orig_c  # type: ignore[assignment]
                    drv.VerificationAgent = orig_v  # type: ignore[assignment]

                assert result.final_status == "partial"
                assert result.rounds == 1
                # CodingAgent 只实例化一次（partial 不触发重跑）
                assert _CountingCodingAgent.instance_count == 1
        finally:
            await _close(db, engine)
    _run(run)


def test_autofix_loop_second_round_passes_after_fix():
    """第 1 轮 failed，第 2 轮 passed → final_status=passed，rounds=2"""
    # 用一个 stateful VerificationAgent：第一次调用 FailAgent，第二次调用 PassAgent
    # 通过替换 driver.VerificationAgent 的 factory 来实现
    class _AlternatingVA(VerificationAgent):
        _call_count = 0

        def __init__(self, *a, **kw):
            super().__init__(*a, **kw)
            _AlternatingVA._call_count += 1
            self._inner = _VerifyAllFailAgent if _AlternatingVA._call_count == 1 else _VerifyAllPassAgent

        async def _call_llm(self):
            # 根据 invocation count 模拟不同行为
            t = getattr(self, "_script_turn", 0)
            self._script_turn = t + 1  # type: ignore[attr-defined]
            # 用 self._inner 的 _call_llm 逻辑（类方法），但要绑 self
            if self._inner is _VerifyAllFailAgent:
                if t < len(self.state.ac_items):
                    return _llm([_tc(f"t{t}", "check_ac", {
                        "ac_index": self.state.ac_items[t].index,
                        "status": "failed", "evidence": "fix me", "confidence": 0.95,
                    })])
                return _llm([_tc(f"e{t}", "emit_report", {"summary": "有失败"})])
            if t < len(self.state.ac_items):
                return _llm([_tc(f"t{t}", "check_ac", {
                    "ac_index": self.state.ac_items[t].index,
                    "status": "passed", "evidence": "已修复", "confidence": 0.95,
                })])
            return _llm([_tc(f"e{t}", "emit_report", {"summary": "修复完成"})])

    async def run():
        db, conv, user, engine = await _make_db()
        try:
            with tempfile.TemporaryDirectory() as td:
                envelope = _envelope()
                import app.orchestrator.driver as drv
                orig_c = drv.CodingAgent
                orig_v = drv.VerificationAgent
                _AlternatingVA._call_count = 0
                _CountingCodingAgent.instance_count = 0
                drv.CodingAgent = _CountingCodingAgent  # type: ignore[assignment]
                drv.VerificationAgent = _AlternatingVA  # type: ignore[assignment]
                try:
                    def coding_ctx():
                        return _agent_ctx(f"c_{secrets.token_hex(3)}", conv.id, user.id)
                    def verify_ctx():
                        return _agent_ctx(f"v_{secrets.token_hex(3)}", conv.id, user.id)

                    result = await driver.drive_coding_with_autofix(
                        db,
                        conversation_id=conv.id,
                        spec_envelope=envelope,
                        coding_ctx_factory=coding_ctx,
                        verification_ctx_factory=verify_ctx,
                        workspace_root=td,
                        coding_session_id="c_auto4",
                        max_fix_rounds=2,
                    )
                finally:
                    drv.CodingAgent = orig_c  # type: ignore[assignment]
                    drv.VerificationAgent = orig_v  # type: ignore[assignment]

                assert result.final_status == "passed"
                assert result.rounds == 2
                assert _CountingCodingAgent.instance_count == 2
                assert len(result.reports) == 2
                # 第一个 report failed，第二个 passed
                assert result.reports[0].overall_status == "failed"
                assert result.reports[1].overall_status == "passed"
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
