"""Spec API 路由集成测试。

跑 FastAPI TestClient + 内存 SQLite。覆盖：
- GET /api/spec/{id} / /versions
- POST /api/spec/{id}/confirm / /refine / /rollback
- 租户隔离：其他租户用户不能读
"""
import asyncio
import os
import secrets
import sys
from datetime import datetime
from pathlib import Path

os.environ.setdefault("LLM_API_KEY", "test-key")
os.environ.setdefault("JWT_SECRET_KEY", "test-secret")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///file::memory:?cache=shared&uri=true")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession  # noqa: E402

from app.deps import AuthContext  # noqa: E402
from app.main import app  # noqa: E402
from app.database import AsyncSessionLocal, Base, engine  # noqa: E402
import app.models as models  # noqa: E402
import app.models.agent_models as agent_models  # noqa: E402
from app.services import brainstorm_session_service as bs_svc  # noqa: E402
from app.services import spec_service  # noqa: E402


# ══════════════════════════════════════════════════════════════
# 环境
# ══════════════════════════════════════════════════════════════

TENANT_A = 1
TENANT_B = 2


class _FakeUser:
    def __init__(self, user_id: int, tenant_id: int):
        self.id = user_id
        self.tenant_id = tenant_id
        self.username = f"u{user_id}"
        self.is_platform_admin = False


def _mock_auth_factory(tenant_id: int, user_id: int = 1):
    async def _auth() -> AuthContext:
        return AuthContext(
            user=_FakeUser(user_id, tenant_id),
            tenant_id=tenant_id,
            tenant_role="member",
            org_permissions={},
        )
    return _auth


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


async def _ensure_tables():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


def _uniq() -> str:
    return secrets.token_hex(4)


async def _seed_spec(tenant_id: int = TENANT_A) -> tuple[str, str, int]:
    """创建一个 brainstorm session + 存一个 Spec，返回 (spec_id, bs_id, conversation_id)"""
    async with AsyncSessionLocal() as db:
        # 确保 user + conversation 存在
        u = models.User(username=f"api_u_{tenant_id}_{_uniq()}", hashed_password="x")
        db.add(u)
        await db.flush()
        conv = models.Conversation(
            user_id=u.id, tenant_id=tenant_id, title="t",
            agent_type="coding", status="active",
        )
        db.add(conv)
        await db.flush()
        bs_row = await bs_svc.create_session(
            db, conversation_id=conv.id, user_id=u.id, tenant_id=tenant_id,
        )
        env = _valid_envelope()
        spec = await spec_service.save_spec(
            db, brainstorm_session_id=bs_row.id, envelope=env,
        )
        await db.commit()
        return spec.id, bs_row.id, conv.id


def _valid_envelope() -> dict:
    return {
        "schema_version": "1.0",
        "scene_type": "web_component_dual",
        "spec_id": "ignored_will_be_replaced",
        "provenance": {
            "brainstorm_session_id": "ignored",
            "created_at": datetime.utcnow().isoformat(),
            "created_by": "agent",
            "model": "test-model",
            "version": 1,
            "parent_version": None,
            "confidence": 0.9,
            "open_questions": [],
        },
        "identity": {
            "code_name": "rating-star",
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


# 启动时建表
_run(_ensure_tables())


def _make_client(tenant_id: int = TENANT_A, user_id: int = 1) -> TestClient:
    """每个测试独立覆盖 auth dependency，避免并发污染"""
    from app.deps import get_auth_context

    client = TestClient(app)
    app.dependency_overrides[get_auth_context] = _mock_auth_factory(tenant_id, user_id)
    return client


def _clear_override():
    from app.deps import get_auth_context
    app.dependency_overrides.pop(get_auth_context, None)


# ══════════════════════════════════════════════════════════════
# Tests
# ══════════════════════════════════════════════════════════════

def test_get_spec_returns_detail():
    spec_id, _, _ = _run(_seed_spec())
    client = _make_client()
    try:
        resp = client.get(f"/api/spec/{spec_id}")
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["spec_id"] == spec_id
        assert data["scene_type"] == "web_component_dual"
        assert data["version"] == 1
        assert data["envelope"]["identity"]["code_name"] == "rating-star"
    finally:
        _clear_override()


def test_get_spec_not_found_returns_404():
    client = _make_client()
    try:
        resp = client.get("/api/spec/nonexistent")
        assert resp.status_code == 404
    finally:
        _clear_override()


def test_get_spec_other_tenant_403():
    spec_id, _, _ = _run(_seed_spec(tenant_id=TENANT_A))
    client = _make_client(tenant_id=TENANT_B)
    try:
        resp = client.get(f"/api/spec/{spec_id}")
        assert resp.status_code == 403, resp.text
    finally:
        _clear_override()


def test_list_versions_desc_order():
    async def seed_multi():
        async with AsyncSessionLocal() as db:
            u = models.User(username=f"vu_{_uniq()}", hashed_password="x")
            db.add(u)
            await db.flush()
            conv = models.Conversation(user_id=u.id, tenant_id=TENANT_A, title="t", agent_type="coding", status="active")
            db.add(conv)
            await db.flush()
            bs = await bs_svc.create_session(db, conversation_id=conv.id, user_id=u.id, tenant_id=TENANT_A)
            await spec_service.save_spec(db, brainstorm_session_id=bs.id, envelope=_valid_envelope())
            s2 = await spec_service.save_spec(db, brainstorm_session_id=bs.id, envelope=_valid_envelope())
            await spec_service.save_spec(db, brainstorm_session_id=bs.id, envelope=_valid_envelope())
            await db.commit()
            return s2.id
    spec_id = _run(seed_multi())

    client = _make_client()
    try:
        resp = client.get(f"/api/spec/{spec_id}/versions")
        assert resp.status_code == 200, resp.text
        arr = resp.json()
        assert [v["version"] for v in arr] == [3, 2, 1]
    finally:
        _clear_override()


def test_confirm_marks_session_completed():
    spec_id, bs_id, _ = _run(_seed_spec())
    client = _make_client()
    try:
        resp = client.post(f"/api/spec/{spec_id}/confirm")
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["spec_id"] == spec_id
        # seed conversation has no workspace_id → scaffold; with workspace_id → generate
        assert data["phase_hint"] in {"scaffold", "generate", "already_confirmed"}

        # 再次 confirm 返回 already_confirmed
        resp2 = client.post(f"/api/spec/{spec_id}/confirm")
        assert resp2.status_code == 200
        assert resp2.json()["phase_hint"] == "already_confirmed"
    finally:
        _clear_override()

    # DB 状态验证
    async def verify():
        async with AsyncSessionLocal() as db:
            row = await bs_svc.get_session(db, bs_id)
            assert row.status == bs_svc.BsStatus.COMPLETED
            assert row.final_spec_id == spec_id
    _run(verify())


def test_refine_switches_session_back_to_active():
    spec_id, bs_id, _ = _run(_seed_spec())
    # 先 confirm
    client = _make_client()
    try:
        client.post(f"/api/spec/{spec_id}/confirm")
        resp = client.post(f"/api/spec/{spec_id}/refine", json={"instruction": "提高配置项清晰度"})
        assert resp.status_code == 200, resp.text
        assert resp.json()["brainstorm_session_id"] == bs_id
    finally:
        _clear_override()

    async def verify():
        async with AsyncSessionLocal() as db:
            row = await bs_svc.get_session(db, bs_id)
            assert row.status == bs_svc.BsStatus.ACTIVE
            assert row.final_spec_id is None
    _run(verify())


def test_refine_on_terminal_session_rejected():
    spec_id, bs_id, _ = _run(_seed_spec())
    # 手动设为 failed
    async def set_failed():
        async with AsyncSessionLocal() as db:
            await bs_svc.mark_session_failed(db, session_id=bs_id, error_message="x")
            await db.commit()
    _run(set_failed())

    client = _make_client()
    try:
        resp = client.post(f"/api/spec/{spec_id}/refine", json={})
        assert resp.status_code == 400, resp.text
    finally:
        _clear_override()


def test_rollback_creates_new_version():
    async def seed_two():
        async with AsyncSessionLocal() as db:
            u = models.User(username=f"rb_u_{_uniq()}", hashed_password="x")
            db.add(u)
            await db.flush()
            conv = models.Conversation(user_id=u.id, tenant_id=TENANT_A, title="t", agent_type="coding", status="active")
            db.add(conv)
            await db.flush()
            bs = await bs_svc.create_session(db, conversation_id=conv.id, user_id=u.id, tenant_id=TENANT_A)
            r1 = await spec_service.save_spec(db, brainstorm_session_id=bs.id, envelope=_valid_envelope())
            await spec_service.save_spec(db, brainstorm_session_id=bs.id, envelope=_valid_envelope())
            await db.commit()
            return r1.id, bs.id
    r1_id, bs_id = _run(seed_two())

    client = _make_client()
    try:
        resp = client.post(f"/api/spec/{r1_id}/rollback")
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["parent_version"] == 1
        assert data["new_version"] == 3
        assert data["new_spec_id"] != r1_id
    finally:
        _clear_override()


def test_confirm_other_tenant_403():
    spec_id, _, _ = _run(_seed_spec(tenant_id=TENANT_A))
    client = _make_client(tenant_id=TENANT_B)
    try:
        resp = client.post(f"/api/spec/{spec_id}/confirm")
        assert resp.status_code == 403
    finally:
        _clear_override()


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
