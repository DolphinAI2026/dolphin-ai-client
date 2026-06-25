"""SP1: Builder 会话路由按 mode 收口 —— Code(mode='code')会话不得漏进 Builder。"""
import pytest
from fastapi import HTTPException

from app.deps import AuthContext
from app.models import User
from app.models.tenant import Tenant
from app.models.ai_chat import AIChatSession
from app.routes.ai_chat import _load_session_or_404, list_sessions


async def _make_user(db, username: str) -> User:
    u = User(username=username, hashed_password="x")
    db.add(u)
    await db.flush()
    return u


def _ctx_for(user: User, tenant_id: int) -> AuthContext:
    return AuthContext(
        user=user, tenant_id=tenant_id, tenant_role="member", org_permissions={}
    )


async def _seed_session(db, *, username: str, mode: str):
    """建 tenant+user+一个指定 mode 的 AIChatSession,返回 (ctx, session)。"""
    tenant = Tenant(tenant_name="t_scope", tenant_code=f"t_scope_{username[:8]}")
    db.add(tenant)
    await db.flush()
    user = await _make_user(db, username)
    s = AIChatSession(tenant_id=tenant.id, user_id=user.id, title="t", mode=mode)
    db.add(s)
    await db.flush()
    return _ctx_for(user, tenant.id), s


@pytest.mark.asyncio
async def test_load_session_rejects_code(db_session):
    ctx, s = await _seed_session(db_session, username="scopecode", mode="code")
    with pytest.raises(HTTPException) as exc:
        await _load_session_or_404(db_session, s.id, ctx)
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_load_session_allows_chat(db_session):
    ctx, s = await _seed_session(db_session, username="scopechat", mode="chat")
    out = await _load_session_or_404(db_session, s.id, ctx)
    assert out.id == s.id


@pytest.mark.asyncio
async def test_load_session_other_user_still_404(db_session):
    """回归:他人的 chat 会话仍 404(收口不破坏既有 user 作用域)。"""
    ctx, s = await _seed_session(db_session, username="scopeowner", mode="chat")
    thief = await _make_user(db_session, "scopethief")
    thief_ctx = _ctx_for(thief, ctx.tenant_id)
    with pytest.raises(HTTPException) as exc:
        await _load_session_or_404(db_session, s.id, thief_ctx)
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_list_sessions_excludes_code(db_session):
    """同一 user 的 chat + code 两会话,列表只返回 chat。"""
    tenant = Tenant(tenant_name="t_list", tenant_code="t_list_scope")
    db_session.add(tenant)
    await db_session.flush()
    user = await _make_user(db_session, "listscopeuser")
    chat = AIChatSession(tenant_id=tenant.id, user_id=user.id, title="chat one", mode="chat")
    code = AIChatSession(tenant_id=tenant.id, user_id=user.id, title="code one", mode="code")
    db_session.add_all([chat, code])
    await db_session.flush()
    chat_id, code_id = chat.id, code.id

    out = await list_sessions(_ctx_for(user, tenant.id), db_session)
    ids = {s["id"] for s in out["sessions"]}
    assert chat_id in ids, "chat 会话应出现在 Builder 列表"
    assert code_id not in ids, "code 会话不应出现在 Builder 列表"


@pytest.mark.asyncio
async def test_list_sessions_keeps_cowork(db_session):
    """回归:cowork 会话照常出现在列表。"""
    tenant = Tenant(tenant_name="t_cowork", tenant_code="t_cowork_scope")
    db_session.add(tenant)
    await db_session.flush()
    user = await _make_user(db_session, "coworkuser")
    cw = AIChatSession(tenant_id=tenant.id, user_id=user.id, title="cw", mode="cowork")
    db_session.add(cw)
    await db_session.flush()
    cw_id = cw.id

    out = await list_sessions(_ctx_for(user, tenant.id), db_session)
    assert cw_id in {s["id"] for s in out["sessions"]}
