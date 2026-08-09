"""AIChat session route regressions for the P0 assistant profile field."""

from __future__ import annotations

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.deps import AuthContext
from app.models import User
from app.models.ai_chat import AIChatAttachment, AIChatSession
from app.models.tenant import Tenant
from app.routes.ai_chat import (
    CreateSessionRequest,
    create_session,
    get_session,
    list_sessions,
)


def _ctx(user: User, tenant_id: int) -> AuthContext:
    return AuthContext(user=user, tenant_id=tenant_id, tenant_role="member", org_permissions={})


@pytest.mark.asyncio
async def test_system_assistant_session_create_and_detail_keep_legacy_mode(db_session):
    tenant = Tenant(tenant_name="sa_route_t", tenant_code="sa_route_t")
    db_session.add(tenant)
    await db_session.flush()
    user = User(username="sa_route_user", hashed_password="x")
    db_session.add(user)
    await db_session.flush()
    ctx = _ctx(user, tenant.id)

    created = await create_session(
        CreateSessionRequest(
            title="系统诊断",
            mode="chat",
            assistant_profile="system_assistant",
        ),
        ctx,
        db_session,
    )

    assert created["assistant_profile"] == "system_assistant"
    assert created["mode"] == "chat"
    detail = await get_session(created["id"], ctx, db_session)
    assert detail["session"]["assistant_profile"] == "system_assistant"
    assert detail["session"]["mode"] == "chat"


@pytest.mark.asyncio
async def test_system_assistant_detail_keeps_existing_attachment_shape(db_session):
    tenant = Tenant(tenant_name="sa_attachment_t", tenant_code="sa_attachment_t")
    db_session.add(tenant)
    await db_session.flush()
    user = User(username="sa_attachment_user", hashed_password="x")
    db_session.add(user)
    await db_session.flush()
    ctx = _ctx(user, tenant.id)

    created = await create_session(
        CreateSessionRequest(mode="chat", assistant_profile="system_assistant"),
        ctx,
        db_session,
    )
    db_session.add(
        AIChatAttachment(
            session_id=created["id"],
            filename="baseline.md",
            kind="md",
            mime="text/markdown",
            size_bytes=12,
            content_text="# baseline",
        )
    )
    await db_session.commit()

    detail = await get_session(created["id"], ctx, db_session)

    assert detail["attachments"][0]["filename"] == "baseline.md"
    assert detail["attachments"][0]["has_content_text"] is True


@pytest.mark.asyncio
async def test_list_sessions_can_filter_assistant_profile_without_changing_mode(db_session):
    tenant = Tenant(tenant_name="sa_filter_t", tenant_code="sa_filter_t")
    db_session.add(tenant)
    await db_session.flush()
    user = User(username="sa_filter_user", hashed_password="x")
    db_session.add(user)
    await db_session.flush()
    db_session.add_all([
        AIChatSession(
            tenant_id=tenant.id,
            user_id=user.id,
            title="系统助手",
            mode="cowork",
            assistant_profile="system_assistant",
            status="active",
        ),
        AIChatSession(
            tenant_id=tenant.id,
            user_id=user.id,
            title="入口助手",
            mode="code",
            assistant_profile="entry_agent",
            status="active",
        ),
    ])
    await db_session.commit()

    result = await list_sessions(
        _ctx(user, tenant.id), db_session, assistant_profile="system_assistant"
    )

    assert [item["title"] for item in result["sessions"]] == ["系统助手"]
    assert result["sessions"][0]["mode"] == "cowork"


def test_unknown_assistant_profile_is_rejected_by_create_request():
    with pytest.raises(ValidationError, match="assistant_profile"):
        CreateSessionRequest(assistant_profile="system_assistant_v2")


@pytest.mark.asyncio
async def test_unknown_assistant_profile_filter_returns_explicit_422(db_session):
    user = User(id=501, username="sa_invalid_filter", hashed_password="x")
    db_session.add(user)
    await db_session.flush()

    with pytest.raises(HTTPException) as exc:
        await list_sessions(_ctx(user, 501), db_session, assistant_profile="system_assistant_v2")

    assert exc.value.status_code == 422
    assert "assistant_profile" in str(exc.value.detail)
