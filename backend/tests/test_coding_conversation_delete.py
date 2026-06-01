"""B1: delete_coding_conversation — 会话↔workspace 1:1 + 删除语义测试

验收条件:
1. 带 workspace_id 的 coding 会话删除后:
   - 会话从 DB 消失
   - workspace_mgr.delete_workspace 以该 workspace_id 被调用
   - 不报错
2. 不带 workspace_id 的 coding 会话删除后:
   - 会话从 DB 消失
   - workspace_mgr.delete_workspace 不被调用
   - 不报错
3. 非本人(user_id 不匹配)的会话 → 404
4. 非 coding agent_type 的会话 → 404
5. workspace 清理抛异常时, 会话仍被删(best-effort)
"""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.deps import AuthContext
from app.models import Conversation, Message, User
from app.models.tenant import Tenant
from app.routes.coding import delete_coding_conversation


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

async def _make_user(db, username: str) -> User:
    u = User(username=username, hashed_password="x")
    db.add(u)
    await db.flush()
    return u


def _ctx_for(user: User, tenant_id: int) -> AuthContext:
    return AuthContext(
        user=user,
        tenant_id=tenant_id,
        tenant_role="member",
        org_permissions={},
    )


async def _seed(db, *, username: str, workspace_id: str | None = "ws-abc123"):
    """Create a tenant + user + coding Conversation, return (ctx, conv)."""
    tenant = Tenant(tenant_name="t_del", tenant_code=f"t_del_{username[:6]}")
    db.add(tenant)
    await db.flush()

    user = await _make_user(db, username)

    conv = Conversation(
        user_id=user.id,
        tenant_id=tenant.id,
        title="删除测试会话",
        agent_type="coding",
        workspace_id=workspace_id,
    )
    db.add(conv)
    await db.commit()
    await db.refresh(conv)

    return _ctx_for(user, tenant.id), conv


# ---------------------------------------------------------------------------
# 1. 带 workspace_id — 会话被删, delete_workspace 被调用
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_delete_conv_with_workspace_removes_conv_and_calls_delete_ws(db_session):
    ctx, conv = await _seed(db_session, username="del_ws_user", workspace_id="ws-abc123")

    mock_delete_ws = AsyncMock()
    with patch("app.routes.coding.workspace_mgr.delete_workspace", mock_delete_ws):
        result = await delete_coding_conversation(conv.id, ctx, db_session)

    assert result == {"status": "ok"}

    # delete_workspace 以正确的 workspace_id 调用
    mock_delete_ws.assert_awaited_once_with("ws-abc123")

    # 会话已从 DB 删除
    remaining = (
        await db_session.execute(select(Conversation).where(Conversation.id == conv.id))
    ).scalar_one_or_none()
    assert remaining is None


# ---------------------------------------------------------------------------
# 2. 不带 workspace_id — 会话被删, delete_workspace 不被调用
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_delete_conv_without_workspace_removes_conv_no_delete_ws(db_session):
    ctx, conv = await _seed(db_session, username="del_nows_user", workspace_id=None)

    mock_delete_ws = AsyncMock()
    with patch("app.routes.coding.workspace_mgr.delete_workspace", mock_delete_ws):
        result = await delete_coding_conversation(conv.id, ctx, db_session)

    assert result == {"status": "ok"}

    # delete_workspace 一次都没调用
    mock_delete_ws.assert_not_awaited()

    # 会话已从 DB 删除
    remaining = (
        await db_session.execute(select(Conversation).where(Conversation.id == conv.id))
    ).scalar_one_or_none()
    assert remaining is None


# ---------------------------------------------------------------------------
# 3. 非本人 → 404
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_delete_conv_other_user_returns_404(db_session):
    """他人的会话返回 404，不泄露存在性。"""
    _, conv = await _seed(db_session, username="del_owner", workspace_id="ws-xyz")

    # 用另一个 user + 同一 tenant 去尝试删
    other = await _make_user(db_session, "del_thief")
    tenant_id = conv.tenant_id  # 同 tenant 但不同 user
    ctx_thief = AuthContext(
        user=other,
        tenant_id=tenant_id,
        tenant_role="member",
        org_permissions={},
    )

    with pytest.raises(HTTPException) as exc_info:
        await delete_coding_conversation(conv.id, ctx_thief, db_session)
    assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------------
# 4. 非 coding agent_type → 404
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_delete_non_coding_conv_returns_404(db_session):
    """agent_type != 'coding' 的会话也返回 404（不对外暴露）。"""
    tenant = Tenant(tenant_name="t_noncoding", tenant_code="t_noncoding")
    db_session.add(tenant)
    await db_session.flush()

    user = await _make_user(db_session, "del_noncoding_user")
    builder_conv = Conversation(
        user_id=user.id,
        tenant_id=tenant.id,
        title="Builder 会话",
        agent_type="builder",
        workspace_id=None,
    )
    db_session.add(builder_conv)
    await db_session.commit()
    await db_session.refresh(builder_conv)

    ctx = _ctx_for(user, tenant.id)

    with pytest.raises(HTTPException) as exc_info:
        await delete_coding_conversation(builder_conv.id, ctx, db_session)
    assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------------
# 5. workspace 清理抛异常 → 会话仍被删(best-effort)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_delete_conv_workspace_error_still_deletes_conv(db_session):
    """workspace 清理失败不阻断会话删除。"""
    ctx, conv = await _seed(db_session, username="del_ws_err_user", workspace_id="ws-broken")

    async def _boom(ws_id: str):
        raise RuntimeError("磁盘满了")

    with patch("app.routes.coding.workspace_mgr.delete_workspace", side_effect=_boom):
        # 不应抛出异常
        result = await delete_coding_conversation(conv.id, ctx, db_session)

    assert result == {"status": "ok"}

    remaining = (
        await db_session.execute(select(Conversation).where(Conversation.id == conv.id))
    ).scalar_one_or_none()
    assert remaining is None


# ---------------------------------------------------------------------------
# 6. 关联消息也被清理
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_delete_conv_also_deletes_messages(db_session):
    """删除会话时关联消息一起清理。"""
    ctx, conv = await _seed(db_session, username="del_msg_user", workspace_id=None)

    msg = Message(
        conversation_id=conv.id,
        role="user",
        content="Hello coding",
    )
    db_session.add(msg)
    await db_session.commit()

    with patch("app.routes.coding.workspace_mgr.delete_workspace", AsyncMock()):
        await delete_coding_conversation(conv.id, ctx, db_session)

    remaining_msg = (
        await db_session.execute(select(Message).where(Message.conversation_id == conv.id))
    ).scalar_one_or_none()
    assert remaining_msg is None
