"""spec_service + brainstorm_session_service 单元测试（in-memory SQLite）。

覆盖：
- save_spec：Pydantic 校验 / 业务规则校验 / 版本号递增 / parent_version 链
- get_spec / get_spec_versions / rollback_to_version
- brainstorm session：create / suspend / resume / mark_completed / suspend_idle_sessions
"""
import asyncio
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

os.environ.setdefault("LLM_API_KEY", "test-key")
os.environ.setdefault("JWT_SECRET_KEY", "test-secret")
# 用内存 SQLite；必须在 import app 之前设置
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine  # noqa: E402

from app.database import Base  # noqa: E402
import app.models  # noqa: F401,E402  —— 确保 User/Conversation 等表被 Base 注册
import app.models.agent_models as agent_models  # noqa: E402
from app.agents.brainstorm import BrainstormAgent  # noqa: E402
from app.agents.publisher import InMemoryEventPublisher  # noqa: E402
from app.agents.trace_writer import InMemoryTraceWriter  # noqa: E402
from app.agents.types import AgentContext  # noqa: E402
from app.services import brainstorm_session_service as bs_svc  # noqa: E402
from app.services import spec_service  # noqa: E402
from app.spec.schema import SceneType  # noqa: E402
from app.spec.validators import SpecValidationError  # noqa: E402


# ══════════════════════════════════════════════════════════════
# 独立的 test DB fixture
# ══════════════════════════════════════════════════════════════

def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


async def _make_db() -> tuple[AsyncSession, any]:
    """每个测试一个独立内存库"""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    sessionmaker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    session = sessionmaker()
    # 需要一个 conversation 行做 FK
    from app.models import Conversation, User

    user = User(username="u1", hashed_password="x")
    session.add(user)
    await session.flush()
    conv = Conversation(
        user_id=user.id, tenant_id=1, title="t", agent_type="coding", status="active"
    )
    session.add(conv)
    await session.flush()
    return session, conv


# ══════════════════════════════════════════════════════════════
# 辅助构造
# ══════════════════════════════════════════════════════════════

def _valid_envelope(*, code_name: str = "rating-star", version: int = 1, parent_version=None) -> dict:
    return {
        "schema_version": "1.0",
        "scene_type": "web_component_dual",
        "spec_id": f"spec_test_{code_name}_{version}",
        "provenance": {
            "brainstorm_session_id": "bs_will_be_overridden",
            "created_at": datetime.utcnow().isoformat(),
            "created_by": "agent",
            "model": "test-model",
            "version": version,
            "parent_version": parent_version,
            "confidence": 0.9,
            "open_questions": [],
        },
        "identity": {
            "code_name": code_name,
            "display_name": "评分",
            "description_cn": "评分组件",
            "widget_code": "FORM_CUSTOM_RATING_STAR",
        },
        "intent": {
            "original_requirement": "做评分",
            "core_purpose": "1-5 星打分",
            "acceptance_criteria": ["用户可点击 1~5 星打分"],
        },
        "metadata": {},
        "references": [],
        "spec": {
            "data": {
                "bof_type": "BOF_NUMBER",
                "component_model_field": ["NUM"],
                "form_value_shape": "scalar",
                "default_value": 0,
                "storage_note": "1-5 整数",
            },
            "config_properties": [],
            "scenes_required": ["edit", "read"],
            "scenes_optional": [],
        },
    }


async def _make_session(db, conv) -> agent_models.BrainstormSession:
    return await bs_svc.create_session(
        db,
        conversation_id=conv.id,
        user_id=1,
        tenant_id=1,
        model_used="test-model",
    )


# ══════════════════════════════════════════════════════════════
# spec_service tests
# ══════════════════════════════════════════════════════════════

def test_save_spec_first_version():
    async def run():
        db, conv = await _make_db()
        bs = await _make_session(db, conv)
        row = await spec_service.save_spec(
            db, brainstorm_session_id=bs.id, envelope=_valid_envelope(),
        )
        assert row.version == 1
        assert row.parent_version is None
        assert row.code_name == "rating-star"
        assert row.widget_code == "FORM_CUSTOM_RATING_STAR"
        assert row.confidence == 0.9
        # envelope 内 spec_id 应该与 row.id 一致
        assert row.content["spec_id"] == row.id
        # provenance.version 被覆盖
        assert row.content["provenance"]["version"] == 1
    _run(run())


def test_save_spec_version_auto_increment():
    async def run():
        db, conv = await _make_db()
        bs = await _make_session(db, conv)
        r1 = await spec_service.save_spec(
            db, brainstorm_session_id=bs.id, envelope=_valid_envelope(),
        )
        # 传 parent_version=1 应得到 v2
        r2 = await spec_service.save_spec(
            db, brainstorm_session_id=bs.id, envelope=_valid_envelope(version=2, parent_version=1),
            parent_version=1,
        )
        assert r1.version == 1
        assert r2.version == 2
        assert r2.parent_version == 1
    _run(run())


def test_save_spec_auto_version_without_parent():
    """不传 parent_version 时，系统自动按 session+code_name 找上一版 +1"""
    async def run():
        db, conv = await _make_db()
        bs = await _make_session(db, conv)
        r1 = await spec_service.save_spec(
            db, brainstorm_session_id=bs.id, envelope=_valid_envelope(),
        )
        r2 = await spec_service.save_spec(
            db, brainstorm_session_id=bs.id, envelope=_valid_envelope(),
        )
        assert r1.version == 1
        assert r2.version == 2
    _run(run())


def test_save_spec_pydantic_failure_raises():
    async def run():
        db, conv = await _make_db()
        bs = await _make_session(db, conv)
        bad = _valid_envelope()
        bad["identity"]["widget_code"] = "lowercase_invalid"  # 正则违反
        try:
            await spec_service.save_spec(db, brainstorm_session_id=bs.id, envelope=bad)
        except ValueError as e:
            assert "Spec schema invalid" in str(e)
            return
        raise AssertionError("expected ValueError")
    _run(run())


def test_save_spec_business_rule_failure_raises():
    async def run():
        db, conv = await _make_db()
        bs = await _make_session(db, conv)
        bad = _valid_envelope()
        bad["identity"]["widget_code"] = None  # 组件场景必填
        try:
            await spec_service.save_spec(db, brainstorm_session_id=bs.id, envelope=bad)
        except SpecValidationError:
            return
        raise AssertionError("expected SpecValidationError")
    _run(run())


def test_save_spec_skip_validation_flag():
    """validate=False 不走业务校验（仅做基础 code_name 必填检查）"""
    async def run():
        db, conv = await _make_db()
        bs = await _make_session(db, conv)
        env = _valid_envelope()
        env["identity"]["widget_code"] = None  # 正常校验会失败
        row = await spec_service.save_spec(
            db, brainstorm_session_id=bs.id, envelope=env, validate=False,
        )
        assert row.version == 1
    _run(run())


def test_get_spec_versions_returns_desc():
    async def run():
        db, conv = await _make_db()
        bs = await _make_session(db, conv)
        await spec_service.save_spec(db, brainstorm_session_id=bs.id, envelope=_valid_envelope())
        await spec_service.save_spec(db, brainstorm_session_id=bs.id, envelope=_valid_envelope())
        await spec_service.save_spec(db, brainstorm_session_id=bs.id, envelope=_valid_envelope())
        versions = await spec_service.get_spec_versions(
            db, brainstorm_session_id=bs.id, code_name="rating-star"
        )
        assert [v.version for v in versions] == [3, 2, 1]
    _run(run())


def test_get_spec_versions_without_filter_returns_empty():
    async def run():
        db, _ = await _make_db()
        vs = await spec_service.get_spec_versions(db)
        assert vs == []
    _run(run())


def test_rollback_creates_new_version_with_same_content():
    async def run():
        db, conv = await _make_db()
        bs = await _make_session(db, conv)
        # v1, v2
        r1 = await spec_service.save_spec(db, brainstorm_session_id=bs.id, envelope=_valid_envelope())
        env_v2 = _valid_envelope()
        env_v2["intent"]["core_purpose"] = "v2 的不同目的"
        r2 = await spec_service.save_spec(db, brainstorm_session_id=bs.id, envelope=env_v2)
        assert r2.version == 2

        # 回滚到 v1
        r3 = await spec_service.rollback_to_version(db, spec_id=r1.id)
        assert r3.version == 3
        assert r3.parent_version == 1
        assert r3.created_by == "user"
        # content 应该和 r1 一致（除了 spec_id / provenance.version 等）
        assert r3.content["intent"]["core_purpose"] == r1.content["intent"]["core_purpose"]
    _run(run())


def test_rollback_missing_spec_raises():
    async def run():
        db, _ = await _make_db()
        try:
            await spec_service.rollback_to_version(db, spec_id="nonexistent")
        except ValueError:
            return
        raise AssertionError("expected ValueError")
    _run(run())


# ══════════════════════════════════════════════════════════════
# brainstorm_session_service tests
# ══════════════════════════════════════════════════════════════

def test_create_session_default_active():
    async def run():
        db, conv = await _make_db()
        row = await bs_svc.create_session(
            db, conversation_id=conv.id, user_id=1, tenant_id=1,
        )
        assert row.status == bs_svc.BsStatus.ACTIVE
        assert row.id.startswith("bs_")
    _run(run())


def test_suspend_and_resume_preserves_state():
    async def run():
        db, conv = await _make_db()
        bs_row = await _make_session(db, conv)

        # 构造 agent + 填业务状态
        ctx = AgentContext(
            session_id=bs_row.id, conversation_id=conv.id, user_id=1, tenant_id=1,
            model="test-model", input={"requirement": "t"},
            publisher=InMemoryEventPublisher(), trace_writer=InMemoryTraceWriter(),
        )
        agent = BrainstormAgent(ctx)
        agent.state.scene_type = SceneType.WEB_COMPONENT_DUAL
        agent.state.scene_confidence = 0.8
        agent.state.ask_user_count = 2

        # suspend
        await bs_svc.suspend_session(db, session_id=bs_row.id, agent=agent)
        fresh = await bs_svc.get_session(db, bs_row.id)
        assert fresh.status == bs_svc.BsStatus.SUSPENDED
        assert fresh.agent_snapshot is not None
        assert fresh.scene_type == SceneType.WEB_COMPONENT_DUAL.value

        # resume
        ctx2 = AgentContext(
            session_id=bs_row.id, conversation_id=conv.id, user_id=1, tenant_id=1,
            model="test-model", input={"requirement": "t"},
            publisher=InMemoryEventPublisher(), trace_writer=InMemoryTraceWriter(),
        )
        row, restored = await bs_svc.resume_session(db, session_id=bs_row.id, ctx=ctx2)
        assert row.status == bs_svc.BsStatus.ACTIVE
        assert restored.state.scene_type == SceneType.WEB_COMPONENT_DUAL
        assert restored.state.scene_confidence == 0.8
        assert restored.state.ask_user_count == 2
    _run(run())


def test_resume_terminal_session_raises():
    async def run():
        db, conv = await _make_db()
        bs_row = await _make_session(db, conv)
        await bs_svc.mark_session_completed(db, session_id=bs_row.id, final_spec_id="spec_x")
        ctx = AgentContext(
            session_id=bs_row.id, conversation_id=conv.id, user_id=1, tenant_id=1,
            model="m", input={"requirement": "t"},
            publisher=InMemoryEventPublisher(), trace_writer=InMemoryTraceWriter(),
        )
        try:
            await bs_svc.resume_session(db, session_id=bs_row.id, ctx=ctx)
        except ValueError:
            return
        raise AssertionError("expected ValueError")
    _run(run())


def test_mark_session_completed_sets_final_spec_id():
    async def run():
        db, conv = await _make_db()
        bs_row = await _make_session(db, conv)
        await bs_svc.mark_session_completed(db, session_id=bs_row.id, final_spec_id="spec_xyz")
        fresh = await bs_svc.get_session(db, bs_row.id)
        assert fresh.status == bs_svc.BsStatus.COMPLETED
        assert fresh.final_spec_id == "spec_xyz"
        assert fresh.ended_at is not None
    _run(run())


def test_get_active_session_for_conversation_returns_latest():
    async def run():
        db, conv = await _make_db()
        s1 = await _make_session(db, conv)
        await bs_svc.mark_session_completed(db, session_id=s1.id)
        s2 = await _make_session(db, conv)
        found = await bs_svc.get_active_session_for_conversation(db, conv.id)
        assert found is not None
        assert found.id == s2.id
    _run(run())


def test_suspend_idle_sessions_picks_old_active():
    async def run():
        db, conv = await _make_db()
        old = await _make_session(db, conv)
        old.last_activity_at = datetime.utcnow() - timedelta(hours=2)
        await db.flush()
        fresh = await _make_session(db, conv)

        n = await bs_svc.suspend_idle_sessions(db, idle_minutes=30)
        assert n == 1
        o_fresh = await bs_svc.get_session(db, old.id)
        f_fresh = await bs_svc.get_session(db, fresh.id)
        assert o_fresh.status == bs_svc.BsStatus.SUSPENDED
        assert f_fresh.status == bs_svc.BsStatus.ACTIVE
    _run(run())


def test_abort_stale_sessions_picks_old_suspended():
    async def run():
        db, conv = await _make_db()
        s = await _make_session(db, conv)
        s.status = bs_svc.BsStatus.SUSPENDED
        s.last_activity_at = datetime.utcnow() - timedelta(days=10)
        await db.flush()

        n = await bs_svc.abort_stale_sessions(db, stale_days=7)
        assert n == 1
        fresh = await bs_svc.get_session(db, s.id)
        assert fresh.status == bs_svc.BsStatus.ABORTED
        assert fresh.ended_at is not None
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
