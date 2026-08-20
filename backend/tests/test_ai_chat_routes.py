"""AIChat session route regressions for the P0 assistant profile field."""

from __future__ import annotations

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.crypto import encrypt_password
from app.deps import AuthContext
from app.models import LLMConfig, User
from app.models.ai_chat import AIChatAttachment, AIChatSession
from app.models.tenant import Tenant
from app.routes.ai_chat import (
    CreateSessionRequest,
    create_session,
    get_session,
    list_sessions,
)
from app import runtime
from app.routes import ai_chat as ai_chat_routes


def _ctx(
    user: User,
    tenant_id: int,
    *,
    control_plane_tenant_id: str | None = None,
) -> AuthContext:
    return AuthContext(
        user=user,
        tenant_id=tenant_id,
        tenant_role="member",
        org_permissions={},
        control_plane_tenant_id=control_plane_tenant_id,
    )


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
    assert created["execution_location"] == "local"
    detail = await get_session(created["id"], ctx, db_session)
    assert detail["session"]["assistant_profile"] == "system_assistant"
    assert detail["session"]["mode"] == "chat"


@pytest.mark.asyncio
async def test_system_assistant_remote_session_requires_advertised_remote_runtime(db_session, monkeypatch):
    tenant = Tenant(tenant_name="sa_remote_t", tenant_code="sa_remote_t")
    db_session.add(tenant)
    await db_session.flush()
    user = User(username="sa_remote_user", hashed_password="x")
    db_session.add(user)
    await db_session.flush()

    monkeypatch.setattr(ai_chat_routes.runtime, "system_assistant_execution_mode", lambda: "remote")
    monkeypatch.setattr(ai_chat_routes.runtime, "system_assistant_remote_enabled", lambda: False)
    with pytest.raises(HTTPException, match="SYSTEM_ASSISTANT_REMOTE_RUNTIME_UNAVAILABLE"):
        await create_session(
            CreateSessionRequest(assistant_profile="system_assistant"),
            _ctx(user, tenant.id),
            db_session,
        )


@pytest.mark.asyncio
async def test_system_assistant_session_accepts_only_coding_model_selection(db_session):
    tenant = Tenant(tenant_name="sa_model_t", tenant_code="sa_model_t")
    db_session.add(tenant)
    await db_session.flush()
    user = User(username="sa_model_user", hashed_password="x")
    db_session.add(user)
    coding = LLMConfig(
        tenant_id=tenant.id,
        config_name="Coding",
        provider="dolphin",
        base_url="https://models.example/v1",
        api_key_enc=encrypt_password("k"),
        model="gpt-5.5",
        purpose="coding",
        is_default=True,
        status="active",
    )
    builder = LLMConfig(
        tenant_id=tenant.id,
        config_name="Builder",
        provider="dolphin",
        base_url="https://models.example/v1",
        api_key_enc=encrypt_password("k"),
        model="gpt-5.5",
        purpose="builder",
        is_default=True,
        status="active",
    )
    db_session.add_all([coding, builder])
    await db_session.flush()
    ctx = _ctx(user, tenant.id)

    created = await create_session(
        CreateSessionRequest(
            assistant_profile="system_assistant",
            selected_llm_config_id=coding.id,
        ),
        ctx,
        db_session,
    )
    assert created["selected_llm_config_id"] == coding.id

    with pytest.raises(HTTPException, match="当前助手"):
        await create_session(
            CreateSessionRequest(
                assistant_profile="system_assistant",
                selected_llm_config_id=builder.id,
            ),
            ctx,
            db_session,
        )


@pytest.mark.asyncio
async def test_desktop_builder_can_persist_a_selected_control_plane_model(
    db_session,
    monkeypatch,
):
    tenant = Tenant(tenant_name="desktop_cp_models", tenant_code="desktop_cp_models")
    user = User(
        username="desktop_cp_models_user",
        hashed_password="x",
        account_source="control_plane",
    )
    db_session.add_all([tenant, user])
    await db_session.flush()
    ctx = _ctx(user, tenant.id, control_plane_tenant_id="cp-tenant-models")

    async def fake_catalog(**_kwargs):
        return [{"id": -1001, "model": "online-model", "is_default": True}]

    monkeypatch.setattr(runtime, "is_desktop", lambda: True)
    monkeypatch.setattr(ai_chat_routes, "control_plane_access_token", lambda _user: "token")
    monkeypatch.setattr(ai_chat_routes, "list_control_plane_model_options", fake_catalog)

    created = await create_session(
        CreateSessionRequest(selected_llm_config_id=-1001),
        ctx,
        db_session,
    )

    assert created["selected_llm_config_id"] == -1001


@pytest.mark.asyncio
async def test_web_system_assistant_can_persist_a_selected_control_plane_model(
    db_session,
    monkeypatch,
):
    tenant = Tenant(tenant_name="web_cp_models", tenant_code="web_cp_models")
    user = User(
        username="web_cp_models_user",
        hashed_password="x",
        account_source="control_plane",
    )
    db_session.add_all([tenant, user])
    await db_session.flush()
    ctx = _ctx(user, tenant.id, control_plane_tenant_id="cp-tenant-models")

    async def fake_catalog(**kwargs):
        assert kwargs["purpose"] == "coding"
        return [{"id": -1001, "model": "online-model", "is_default": True}]

    monkeypatch.setattr(runtime, "is_desktop", lambda: False)
    monkeypatch.setattr(ai_chat_routes, "control_plane_access_token", lambda _user: "token")
    monkeypatch.setattr(ai_chat_routes, "list_control_plane_model_options", fake_catalog)

    created = await create_session(
        CreateSessionRequest(
            assistant_profile="system_assistant",
            mode="code",
            selected_llm_config_id=-1001,
        ),
        ctx,
        db_session,
    )

    assert created["selected_llm_config_id"] == -1001


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
async def test_system_assistant_session_drops_application_context(db_session):
    tenant = Tenant(tenant_name="sa_code_only_t", tenant_code="sa_code_only_t")
    db_session.add(tenant)
    await db_session.flush()
    user = User(username="sa_code_only_user", hashed_password="x")
    db_session.add(user)
    await db_session.flush()

    created = await create_session(
        CreateSessionRequest(
            mode="code",
            assistant_profile="system_assistant",
            app_id=987,
        ),
        _ctx(user, tenant.id),
        db_session,
    )

    assert created["assistant_profile"] == "system_assistant"
    assert created["app_id"] is None


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


@pytest.mark.asyncio
async def test_list_sessions_hides_archived_conversations(db_session):
    tenant = Tenant(tenant_name="archived_session_t", tenant_code="archived_session_t")
    db_session.add(tenant)
    await db_session.flush()
    user = User(username="archived_session_user", hashed_password="x")
    db_session.add(user)
    await db_session.flush()
    db_session.add_all([
        AIChatSession(tenant_id=tenant.id, user_id=user.id, title="进行中的会话", status="active"),
        AIChatSession(tenant_id=tenant.id, user_id=user.id, title="已归档会话", status="archived"),
    ])
    await db_session.commit()

    result = await list_sessions(_ctx(user, tenant.id), db_session)

    assert [item["title"] for item in result["sessions"]] == ["进行中的会话"]


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


@pytest.mark.asyncio
async def test_system_assistant_sessions_are_isolated_by_control_plane_organization(db_session):
    tenant = Tenant(tenant_name="sa_cp_t", tenant_code="sa_cp_t")
    db_session.add(tenant)
    await db_session.flush()
    user = User(username="sa_cp_user", hashed_password="x", account_source="control_plane")
    db_session.add(user)
    await db_session.flush()

    org_a = _ctx(user, tenant.id, control_plane_tenant_id="cp-a")
    org_b = _ctx(user, tenant.id, control_plane_tenant_id="cp-b")
    created = await create_session(
        CreateSessionRequest(mode="code", assistant_profile="system_assistant"),
        org_a,
        db_session,
    )

    visible_a = await list_sessions(
        org_a,
        db_session,
        assistant_profile="system_assistant",
    )
    visible_b = await list_sessions(
        org_b,
        db_session,
        assistant_profile="system_assistant",
    )

    assert [item["id"] for item in visible_a["sessions"]] == [created["id"]]
    assert visible_b["sessions"] == []
    with pytest.raises(HTTPException) as exc:
        await get_session(created["id"], org_b, db_session)
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_entry_agent_session_keeps_legacy_local_tenant_scope_across_cp_orgs(db_session):
    tenant = Tenant(tenant_name="entry_cp_t", tenant_code="entry_cp_t")
    db_session.add(tenant)
    await db_session.flush()
    user = User(username="entry_cp_user", hashed_password="x", account_source="control_plane")
    db_session.add(user)
    await db_session.flush()
    db_session.add(
        AIChatSession(
            tenant_id=tenant.id,
            user_id=user.id,
            title="旧 Code 会话",
            mode="code",
            assistant_profile="entry_agent",
            status="active",
        )
    )
    await db_session.commit()

    result = await list_sessions(
        _ctx(user, tenant.id, control_plane_tenant_id="cp-b"),
        db_session,
        assistant_profile="entry_agent",
    )

    assert [item["title"] for item in result["sessions"]] == ["旧 Code 会话"]
