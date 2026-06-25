"""代码会话标题派生:mode=code + workspace_id 时,标题取工作区显示名,而非通用「代码会话」。"""
from __future__ import annotations

from unittest.mock import patch

import pytest

from app.deps import AuthContext
from app.models import User
from app.models.tenant import Tenant
from app.routes.ai_chat import CreateSessionRequest, create_session


def _ctx(user: User, tenant_id: int) -> AuthContext:
    return AuthContext(user=user, tenant_id=tenant_id, tenant_role="member", org_permissions={})


@pytest.mark.asyncio
async def test_code_session_title_uses_workspace_display_name(db_session):
    tenant = Tenant(tenant_name="t_t", tenant_code="t_t"); db_session.add(tenant); await db_session.flush()
    user = User(username="title_user", hashed_password="x"); db_session.add(user); await db_session.flush()
    ctx = _ctx(user, tenant.id)

    body = CreateSessionRequest(mode="code", workspace_id="1_abc", title="代码会话")
    with patch("app.routes.ai_chat.workspace_mgr.get_workspace_info",
               return_value={"display_name": "Acme CRM", "project_name": "acme-crm"}):
        result = await create_session(body, ctx, db_session)
    assert result["title"] == "Acme CRM"


@pytest.mark.asyncio
async def test_code_session_title_falls_back_when_workspace_lookup_fails(db_session):
    tenant = Tenant(tenant_name="t_f", tenant_code="t_f"); db_session.add(tenant); await db_session.flush()
    user = User(username="fb_user", hashed_password="x"); db_session.add(user); await db_session.flush()
    ctx = _ctx(user, tenant.id)

    body = CreateSessionRequest(mode="code", workspace_id="1_missing", title="代码会话")
    with patch("app.routes.ai_chat.workspace_mgr.get_workspace_info", side_effect=FileNotFoundError):
        result = await create_session(body, ctx, db_session)
    assert result["title"] == "代码会话"  # lookup 失败 → 回退前端传的标题


@pytest.mark.asyncio
async def test_chat_session_title_unaffected(db_session):
    tenant = Tenant(tenant_name="t_c", tenant_code="t_c"); db_session.add(tenant); await db_session.flush()
    user = User(username="chat_user", hashed_password="x"); db_session.add(user); await db_session.flush()
    ctx = _ctx(user, tenant.id)

    body = CreateSessionRequest(title="新会话")  # 非 code、无 workspace_id → 不派生
    result = await create_session(body, ctx, db_session)
    assert result["title"] == "新会话"
