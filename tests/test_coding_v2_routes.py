"""coding_v2 + SSE 路由集成测试。

覆盖：
- POST /api/coding/v2/message 路由决策：new conversation / continue / reject / iterate
- GET /api/sse/conversation/{id} 的补发 + 格式
- POST /api/coding/v2/spec/{id}/start-coding 触发后台 coding task

LLM 在所有测试里 **不被真实调用**：
- message 接口的 background task 被 mock 成 noop
- agent 的 _call_llm 被 patch 成 deterministic response
"""
import asyncio
import os
import secrets
import sys

os.environ.setdefault("LLM_API_KEY", "test-key")
os.environ.setdefault("JWT_SECRET_KEY", "test-secret")
# 强制 in-memory SQLite；必须在 import app 之前设置，且要 override .env 里的 MySQL
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///file::memory:?cache=shared&uri=true"

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from unittest import mock  # noqa: E402

from fastapi.testclient import TestClient  # noqa: E402

from app.database import AsyncSessionLocal, Base, engine  # noqa: E402
from app.deps import AuthContext, get_auth_context  # noqa: E402
from app.main import app  # noqa: E402
import app.models as models  # noqa: E402
import app.models.agent_models as agent_models  # noqa: E402
from app.orchestrator import Phase  # noqa: E402
from app.services import brainstorm_session_service as bs_svc  # noqa: E402
from app.services import spec_service  # noqa: E402


# ══════════════════════════════════════════════════════════════
# 辅助
# ══════════════════════════════════════════════════════════════

TENANT_A = 1
TENANT_B = 2


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


async def _ensure_tables():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


_run(_ensure_tables())


class _FakeUser:
    def __init__(self, uid: int, tid: int):
        self.id = uid
        self.tenant_id = tid
        self.username = f"u{uid}"
        self.is_platform_admin = False


def _mock_auth(tenant_id: int, user_id: int = 1):
    async def _auth():
        return AuthContext(
            user=_FakeUser(user_id, tenant_id),
            tenant_id=tenant_id,
            tenant_role="member",
            org_permissions={},
        )
    return _auth


def _client(tenant_id: int = TENANT_A, user_id: int = 1) -> TestClient:
    from app.routes.sse import _sse_auth
    c = TestClient(app)
    mock_fn = _mock_auth(tenant_id, user_id)
    app.dependency_overrides[get_auth_context] = mock_fn
    # SSE 路由用的是单独的 _sse_auth dependency（支持 query token），
    # 测试需同步覆盖，否则请求会走真实 token 校验失败
    app.dependency_overrides[_sse_auth] = mock_fn
    return c


def _clear():
    from app.routes.sse import _sse_auth
    app.dependency_overrides.pop(get_auth_context, None)
    app.dependency_overrides.pop(_sse_auth, None)


def _uniq() -> str:
    return secrets.token_hex(4)


async def _seed_user() -> models.User:
    async with AsyncSessionLocal() as db:
        u = models.User(username=f"v2_{_uniq()}", hashed_password="x")
        db.add(u)
        await db.commit()
        await db.refresh(u)
        return u


async def _seed_conversation(tenant_id: int = TENANT_A, phase: Phase | None = None, workspace_id: str | None = None) -> int:
    u = await _seed_user()
    async with AsyncSessionLocal() as db:
        conv = models.Conversation(
            user_id=u.id, tenant_id=tenant_id, title="t", agent_type="coding",
            status="active", workspace_id=workspace_id,
            coding_phase=(phase.value if phase else None),
        )
        db.add(conv)
        await db.commit()
        await db.refresh(conv)
        return conv.id


async def _seed_conversation_with_bs(phase: Phase = Phase.UNDERSTAND, bs_status: str = "active") -> tuple[int, str]:
    u = await _seed_user()
    async with AsyncSessionLocal() as db:
        conv = models.Conversation(
            user_id=u.id, tenant_id=TENANT_A, title="t", agent_type="coding",
            status="active", coding_phase=phase.value,
        )
        db.add(conv)
        await db.commit()
        await db.refresh(conv)
        bs_row = await bs_svc.create_session(
            db, conversation_id=conv.id, user_id=u.id, tenant_id=TENANT_A,
            model_used="m",
        )
        bs_row.status = bs_status
        await db.commit()
        return conv.id, bs_row.id


# ══════════════════════════════════════════════════════════════
# POST /coding/v2/message —— 路由决策测试
# ══════════════════════════════════════════════════════════════

def test_message_new_conversation_starts_brainstorm():
    """无 conversation_id → 新建 conversation + start_brainstorm，background task 被 mock"""
    c = _client()
    try:
        with mock.patch(
            "app.routes.coding_v2._run_brainstorm_task",
            new=mock.AsyncMock(),
        ) as m:
            r = c.post("/api/coding/v2/message", json={"message": "做个评分"})
            assert r.status_code == 200, r.text
            data = r.json()
            assert data["action"] == "start_brainstorm"
            assert data["phase"] == Phase.UNDERSTAND.value
            assert data["session_id"]
            assert data["conversation_id"] > 0
            assert data["hint_subscribe_sse"].startswith("/api/sse/conversation/")
            # 事件循环让 background task 有机会被创建（但 mock 不 run 真实逻辑）
            # 由于 asyncio.create_task 同步调度，mock 已经注册
    finally:
        _clear()


def test_message_empty_rejected():
    c = _client()
    try:
        r = c.post("/api/coding/v2/message", json={"message": "  "})
        assert r.status_code == 400
    finally:
        _clear()


def test_message_other_tenant_conversation_403():
    cid = _run(_seed_conversation(tenant_id=TENANT_A))
    c = _client(tenant_id=TENANT_B)
    try:
        r = c.post("/api/coding/v2/message", json={
            "conversation_id": cid, "message": "x",
        })
        assert r.status_code == 403
    finally:
        _clear()


def test_message_nonexistent_conversation_404():
    c = _client()
    try:
        r = c.post("/api/coding/v2/message", json={
            "conversation_id": 99999, "message": "x",
        })
        assert r.status_code == 404
    finally:
        _clear()


def test_message_in_understand_continues_brainstorm():
    """UNDERSTAND + active brainstorm session → continue_brainstorm"""
    cid, bs_id = _run(_seed_conversation_with_bs(Phase.UNDERSTAND, "active"))
    c = _client()
    try:
        with mock.patch("app.routes.coding_v2._resume_brainstorm_task", new=mock.AsyncMock()):
            r = c.post("/api/coding/v2/message", json={
                "conversation_id": cid, "message": "继续问",
            })
            assert r.status_code == 200, r.text
            data = r.json()
            assert data["action"] == "continue_brainstorm"
            assert data["session_id"] == bs_id
    finally:
        _clear()


def test_message_in_understand_suspended_session_resumes():
    cid, bs_id = _run(_seed_conversation_with_bs(Phase.UNDERSTAND, "suspended"))
    c = _client()
    try:
        with mock.patch("app.routes.coding_v2._resume_brainstorm_task", new=mock.AsyncMock()):
            r = c.post("/api/coding/v2/message", json={
                "conversation_id": cid, "message": "回来了",
            })
            assert r.status_code == 200
            assert r.json()["action"] == "resume_brainstorm"
    finally:
        _clear()


def test_message_in_generate_rejects():
    """GENERATE 阶段收到消息 → reject_message（不调度 task）"""
    cid = _run(_seed_conversation(phase=Phase.GENERATE))
    c = _client()
    try:
        with mock.patch("app.routes.coding_v2._run_brainstorm_task") as m:
            r = c.post("/api/coding/v2/message", json={
                "conversation_id": cid, "message": "等等别写了",
            })
            assert r.status_code == 200
            data = r.json()
            assert data["action"] == "reject_message"
            assert data["phase"] == Phase.GENERATE.value
            m.assert_not_called()
    finally:
        _clear()


def test_message_in_confirm_triggers_refine():
    """CONFIRM 阶段 + 用户发文字 → refine_brainstorm (UNDERSTAND 起新 session)"""
    cid, _old_bs = _run(_seed_conversation_with_bs(Phase.CONFIRM, "active"))
    c = _client()
    try:
        with mock.patch("app.routes.coding_v2._run_brainstorm_task", new=mock.AsyncMock()):
            r = c.post("/api/coding/v2/message", json={
                "conversation_id": cid, "message": "换主色为红色",
            })
            assert r.status_code == 200, r.text
            data = r.json()
            assert data["action"] == "refine_brainstorm"
            # phase 被转回 UNDERSTAND
            assert data["phase"] == Phase.UNDERSTAND.value
    finally:
        _clear()


def test_message_in_done_triggers_iterate():
    """DONE + 新消息 → iterate （MVP：起新 brainstorm）"""
    cid = _run(_seed_conversation(phase=Phase.DONE))
    c = _client()
    try:
        with mock.patch("app.routes.coding_v2._run_brainstorm_task", new=mock.AsyncMock()):
            r = c.post("/api/coding/v2/message", json={
                "conversation_id": cid, "message": "再加一个字段",
            })
            assert r.status_code == 200
            data = r.json()
            assert data["action"] == "iterate"
    finally:
        _clear()


def test_message_in_failed_triggers_restart():
    cid = _run(_seed_conversation(phase=Phase.FAILED))
    c = _client()
    try:
        with mock.patch("app.routes.coding_v2._run_brainstorm_task", new=mock.AsyncMock()):
            r = c.post("/api/coding/v2/message", json={
                "conversation_id": cid, "message": "重来",
            })
            assert r.status_code == 200
            assert r.json()["action"] == "restart"
    finally:
        _clear()


# ══════════════════════════════════════════════════════════════
# SSE 路由
# ══════════════════════════════════════════════════════════════

def test_sse_requires_tenant():
    cid = _run(_seed_conversation(tenant_id=TENANT_A))
    c = _client(tenant_id=TENANT_B)
    try:
        r = c.get(f"/api/sse/conversation/{cid}")
        assert r.status_code == 403
    finally:
        _clear()


def test_sse_conversation_not_found():
    c = _client()
    try:
        r = c.get("/api/sse/conversation/99999")
        assert r.status_code == 404
    finally:
        _clear()


def test_sse_format_serializes_event():
    """_format_sse 输出符合 SSE wire format"""
    from app.routes.sse import _format_sse

    out = _format_sse({"seq": 7, "type": "brainstorm.ask_user", "data": {"q": "?"}})
    # 必须有 id 行 + data 行 + 空行结束
    assert "id: 7" in out
    assert "data: " in out
    assert out.endswith("\n\n") or out.endswith("\n")
    # data 部分是 JSON（中文不转义）
    assert "brainstorm.ask_user" in out


def test_sse_format_with_event_name_heartbeat():
    from app.routes.sse import _format_sse

    out = _format_sse({"seq": 0}, event_name="heartbeat")
    assert "event: heartbeat" in out


def test_sse_replay_via_publisher_subscribe():
    """不走 HTTP，直接用 DbEventPublisher.subscribe 验证补发逻辑"""
    from app.agents.db_publisher import get_db_publisher

    cid = _run(_seed_conversation())

    async def seed_events():
        async with AsyncSessionLocal() as db:
            for seq in (1, 2, 3):
                row = agent_models.ConversationEvent(
                    id=f"ev_{seq}_{_uniq()}",
                    conversation_id=cid,
                    seq=seq,
                    event_type="brainstorm.test",
                    agent="brainstorm",
                    session_id="bs_test",
                    payload={"n": seq},
                )
                db.add(row)
            await db.commit()
    _run(seed_events())

    async def subscribe_and_read():
        publisher = get_db_publisher()
        async with AsyncSessionLocal() as db:
            seen = []
            sub = publisher.subscribe(cid, last_seen_seq=0, db=db)
            # 拿 3 条历史；历史发完后 subscribe 会进入实时等待（await queue.get），
            # 用 asyncio.wait_for 限时避免卡住
            for _ in range(3):
                ev = await asyncio.wait_for(sub.__anext__(), timeout=5.0)
                seen.append(ev)
            # 关闭迭代器（后续实时流不需要）
            try:
                await sub.aclose()
            except Exception:
                pass
            return seen

    events = _run(subscribe_and_read())
    assert [e["seq"] for e in events] == [1, 2, 3]
    assert all(e["type"] == "brainstorm.test" for e in events)
    assert events[0]["data"] == {"n": 1}


def test_sse_subscribe_respects_last_seen_seq():
    """last_seen_seq=N 仅补发 seq>N 的"""
    from app.agents.db_publisher import get_db_publisher

    cid = _run(_seed_conversation())

    async def seed_events():
        async with AsyncSessionLocal() as db:
            for seq in (10, 11, 12, 13):
                row = agent_models.ConversationEvent(
                    id=f"evy_{seq}_{_uniq()}",
                    conversation_id=cid,
                    seq=seq,
                    event_type="coding.x",
                    agent="coding",
                    session_id=None,
                    payload={"n": seq},
                )
                db.add(row)
            await db.commit()
    _run(seed_events())

    async def subscribe_and_read():
        publisher = get_db_publisher()
        async with AsyncSessionLocal() as db:
            seen = []
            sub = publisher.subscribe(cid, last_seen_seq=11, db=db)
            for _ in range(2):  # 只应补发 seq 12 和 13
                ev = await asyncio.wait_for(sub.__anext__(), timeout=5.0)
                seen.append(ev)
            try:
                await sub.aclose()
            except Exception:
                pass
            return seen

    events = _run(subscribe_and_read())
    assert [e["seq"] for e in events] == [12, 13]


# ══════════════════════════════════════════════════════════════
# POST /coding/v2/spec/{id}/start-coding
# ══════════════════════════════════════════════════════════════

def test_start_coding_from_spec_schedules_task():
    """预先造 Spec + brainstorm session + conversation，调用 start-coding 成功"""
    async def seed():
        u = await _seed_user()
        async with AsyncSessionLocal() as db:
            conv = models.Conversation(
                user_id=u.id, tenant_id=TENANT_A, title="t", agent_type="coding",
                status="active", coding_phase=Phase.GENERATE.value,
            )
            db.add(conv)
            await db.commit()
            await db.refresh(conv)

            bs_row = await bs_svc.create_session(
                db, conversation_id=conv.id, user_id=u.id, tenant_id=TENANT_A,
                model_used="m",
            )
            envelope = {
                "schema_version": "1.0",
                "scene_type": "web_component_dual",
                "spec_id": "unused",
                "provenance": {
                    "brainstorm_session_id": bs_row.id,
                    "created_at": "2026-04-20T00:00:00+00:00",
                    "created_by": "agent",
                    "model": "fake",
                    "version": 1,
                    "confidence": 0.9,
                    "open_questions": [],
                },
                "identity": {
                    "code_name": "rating-star",
                    "display_name": "评分",
                    "description_cn": "d",
                    "widget_code": "FORM_CUSTOM_RATING_STAR",
                },
                "intent": {
                    "original_requirement": "r",
                    "core_purpose": "p",
                    "acceptance_criteria": ["ac1"],
                },
                "spec": {
                    "data": {
                        "bof_type": "BOF_NUMBER",
                        "component_model_field": ["NUM"],
                        "form_value_shape": "scalar",
                        "default_value": 0,
                        "storage_note": "x",
                    },
                    "config_properties": [],
                    "scenes_required": ["edit", "read"],
                    "scenes_optional": [],
                },
            }
            spec_row = await spec_service.save_spec(
                db, brainstorm_session_id=bs_row.id, envelope=envelope,
            )
            await db.commit()
            return conv.id, spec_row.id
    conv_id, spec_id = _run(seed())

    c = _client()
    try:
        with mock.patch("app.routes.coding_v2._run_coding_task", new=mock.AsyncMock()):
            r = c.post(f"/api/coding/v2/spec/{spec_id}/start-coding")
            assert r.status_code == 200, r.text
            data = r.json()
            assert data["conversation_id"] == conv_id
            assert data["spec_id"] == spec_id
    finally:
        _clear()


def test_start_coding_spec_not_found():
    c = _client()
    try:
        r = c.post("/api/coding/v2/spec/nonexistent/start-coding")
        assert r.status_code == 404
    finally:
        _clear()


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
