from types import SimpleNamespace

import pytest
from fastapi import HTTPException

import app.routes.llm_configs as llm_config_routes
from app.crypto import encrypt_password
from app.models import LLMConfig, User
from app.models.tenant import Tenant


@pytest.mark.asyncio
async def test_control_plane_code_model_options_use_remote_catalog_without_local_tenant(
    db_session, monkeypatch,
):
    ctx = SimpleNamespace(
        user=SimpleNamespace(
            id=17,
            is_platform_admin=False,
            account_source="control_plane",
        ),
        tenant_id=0,
        tenant_role="member",
        tenant_access_scope="control_plane_code",
        control_plane_tenant_id="2077284540335579137",
    )

    async def fake_auth(*_args, **_kwargs):
        return "Bearer remote-token", "control_plane"

    async def fake_catalog(**kwargs):
        assert kwargs["purpose"] == "coding"
        assert kwargs["authorization_header"] == "Bearer remote-token"
        assert kwargs["delegated_context"] is ctx
        return [{
            "id": -17,
            "config_name": "企业 Coding 模型",
            "provider": "openai",
            "model": "gpt-5.5",
            "purpose": "coding",
            "is_default": True,
        }]

    import app.routes.code_runtime as code_runtime_routes

    monkeypatch.setattr(code_runtime_routes, "_control_plane_request_auth", fake_auth)
    monkeypatch.setattr(llm_config_routes, "list_control_plane_model_options", fake_catalog)

    result = await llm_config_routes.list_llm_config_options(
        ctx,
        db_session,
        purpose="coding",
    )

    assert [item.model for item in result] == ["gpt-5.5"]


@pytest.mark.asyncio
async def test_control_plane_model_catalog_accepts_code_generation_capability(monkeypatch):
    from app.code_runtime import control_plane_models

    class Response:
        status_code = 200
        text = ""

        def json(self):
            return [{
                "modelCode": "gpt-code",
                "displayName": "GPT Code",
                "capabilities": ["code_generation"],
                "status": "enabled",
            }]

    class Client:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return False

        async def get(self, *_args, **_kwargs):
            return Response()

    monkeypatch.setattr(control_plane_models.httpx, "AsyncClient", Client)
    monkeypatch.setattr(control_plane_models, "control_plane_base_url", lambda: "https://cp.example")

    result = await control_plane_models.list_control_plane_model_options(
        purpose="coding",
        authorization_header="Bearer token",
        delegated_context=SimpleNamespace(control_plane_tenant_id="tenant-1"),
    )

    assert [item["model"] for item in result] == ["gpt-code"]


@pytest.mark.asyncio
async def test_desktop_control_plane_options_include_private_local_models_first(
    db_session, monkeypatch,
):
    """Desktop users can select a local key without losing online models."""
    monkeypatch.setenv("DESKTOP_MODE", "1")
    tenant = Tenant(tenant_name="local", tenant_code="desktop-local")
    user = User(username="desktop-user", hashed_password="x", account_source="control_plane")
    db_session.add_all([tenant, user])
    await db_session.flush()
    local = LLMConfig(
        tenant_id=tenant.id,
        config_name="本机 OpenAI",
        provider="openai",
        base_url="https://local.example/v1",
        api_key_enc=encrypt_password("local-key"),
        model="gpt-local",
        purpose="coding",
        is_default=True,
        status="active",
    )
    db_session.add(local)
    await db_session.flush()
    ctx = SimpleNamespace(
        user=user,
        tenant_id=tenant.id,
        tenant_role="tenant_admin",
        tenant_access_scope="tenant",
        control_plane_tenant_id="remote-tenant",
    )

    async def fake_auth(*_args, **_kwargs):
        return "Bearer remote-token", "control_plane"

    async def fake_catalog(**_kwargs):
        return [{
            "id": -17,
            "config_name": "组织 Coding 模型",
            "provider": "openai",
            "model": "gpt-online",
            "purpose": "coding",
            "is_default": True,
        }]

    import app.routes.code_runtime as code_runtime_routes

    monkeypatch.setattr(code_runtime_routes, "_control_plane_request_auth", fake_auth)
    monkeypatch.setattr(llm_config_routes, "list_control_plane_model_options", fake_catalog)

    result = await llm_config_routes.list_llm_config_options(ctx, db_session, purpose="coding")

    assert [(item.id, item.model) for item in result] == [
        (local.id, "gpt-local"),
        (-17, "gpt-online"),
    ]


@pytest.mark.asyncio
async def test_desktop_control_plane_options_keep_private_models_when_remote_catalog_is_down(
    db_session, monkeypatch,
):
    """A remote outage cannot hide a separately configured desktop model."""
    monkeypatch.setenv("DESKTOP_MODE", "1")
    tenant = Tenant(tenant_name="local", tenant_code="desktop-local-fallback")
    user = User(username="desktop-fallback-user", hashed_password="x", account_source="control_plane")
    db_session.add_all([tenant, user])
    await db_session.flush()
    local = LLMConfig(
        tenant_id=tenant.id,
        config_name="JD-GLM5",
        provider="custom",
        base_url="https://local.example/v1",
        api_key_enc=encrypt_password("local-key"),
        model="GLM-5.1",
        purpose="all",
        is_default=False,
        status="active",
        codex_wire_api="chat",
    )
    db_session.add(local)
    await db_session.flush()
    ctx = SimpleNamespace(
        user=user,
        tenant_id=tenant.id,
        tenant_role="tenant_admin",
        tenant_access_scope="tenant",
        control_plane_tenant_id="remote-tenant",
    )

    async def fake_auth(*_args, **_kwargs):
        return "Bearer remote-token", "control_plane"

    async def unavailable_catalog(**_kwargs):
        raise HTTPException(status_code=503, detail="Control Plane unavailable")

    import app.routes.code_runtime as code_runtime_routes

    monkeypatch.setattr(code_runtime_routes, "_control_plane_request_auth", fake_auth)
    monkeypatch.setattr(llm_config_routes, "list_control_plane_model_options", unavailable_catalog)

    result = await llm_config_routes.list_llm_config_options(ctx, db_session, purpose="coding")

    assert [(item.id, item.model) for item in result] == [(local.id, "GLM-5.1")]


@pytest.mark.asyncio
async def test_desktop_control_plane_options_preserve_remote_error_without_local_fallback(
    db_session, monkeypatch,
):
    monkeypatch.setenv("DESKTOP_MODE", "1")
    tenant = Tenant(tenant_name="empty", tenant_code="desktop-empty-fallback")
    user = User(username="desktop-empty-user", hashed_password="x", account_source="control_plane")
    db_session.add_all([tenant, user])
    await db_session.flush()
    ctx = SimpleNamespace(
        user=user,
        tenant_id=tenant.id,
        tenant_role="tenant_admin",
        tenant_access_scope="tenant",
        control_plane_tenant_id="remote-tenant",
    )

    async def fake_auth(*_args, **_kwargs):
        return "Bearer remote-token", "control_plane"

    async def unavailable_catalog(**_kwargs):
        raise HTTPException(status_code=503, detail="Control Plane unavailable")

    import app.routes.code_runtime as code_runtime_routes

    monkeypatch.setattr(code_runtime_routes, "_control_plane_request_auth", fake_auth)
    monkeypatch.setattr(llm_config_routes, "list_control_plane_model_options", unavailable_catalog)

    with pytest.raises(HTTPException) as exc_info:
        await llm_config_routes.list_llm_config_options(ctx, db_session, purpose="coding")

    assert exc_info.value.status_code == 503


def test_control_plane_html_gateway_error_is_sanitized():
    import httpx

    from app.code_runtime.service import _control_plane_error_detail

    response = httpx.Response(
        503,
        headers={"content-type": "text/html"},
        text="<html><title>503 Service Temporarily Unavailable</title></html>",
    )

    assert _control_plane_error_detail(response) == "Control Plane 服务暂时不可用，请稍后重试"


def test_control_plane_application_not_found_error_is_sanitized():
    import httpx

    from app.code_runtime.service import _control_plane_error_detail

    response = httpx.Response(
        404,
        json={
            "code": "APPLICATION_NOT_FOUND",
            "message": "application not found",
            "traceId": "internal-trace-id",
        },
    )

    assert _control_plane_error_detail(response) == "远端应用不存在或已被删除，请返回应用列表后重新打开"
