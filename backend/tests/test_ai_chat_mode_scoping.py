"""SP2b go-live: Code 会话是统一 Builder 会话列表和路由的一等公民。

删除了 SP1 两道 mode!='code' 闸后:
  - _load_session_or_404 允许 code 会话(不再 404)
  - list_sessions 包含 code 会话

保留 user/tenant 作用域回归测(他人会话仍 404,cowork 照常出现)。
"""
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
async def test_load_session_allows_code(db_session):
    """SP2b: code 会话现在可通过 _load_session_or_404(不再 404)。"""
    ctx, s = await _seed_session(db_session, username="scopecode", mode="code")
    out = await _load_session_or_404(db_session, s.id, ctx)
    assert out.id == s.id


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
async def test_list_sessions_includes_code(db_session):
    """SP2b: 同一 user 的 chat + code 两会话,列表都返回。"""
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
    assert code_id in ids, "code 会话应出现在统一 Builder 列表(SP2b go-live)"


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
