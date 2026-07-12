from __future__ import annotations

import base64
from types import SimpleNamespace

import pytest

from app.models import Application
from app.models.ai_chat import AIChatSession


def test_code_runtime_binding_model_is_registered():
    from sqlalchemy import inspect as sa_inspect
    from app.models.ai_chat import CodeRuntimeBinding

    cols = {c.name for c in sa_inspect(CodeRuntimeBinding).columns}
    assert {
        "session_id",
        "app_id",
        "external_application_id",
        "runtime_base_url",
        "builder_url",
        "workspace_id",
        "sandbox_instance_id",
        "runtime_session_id",
    }.issubset(cols)
    assert sa_inspect(CodeRuntimeBinding).columns.app_id.nullable is True


def test_ai_chat_session_model_tracks_external_code_application():
    from sqlalchemy import inspect as sa_inspect
    from app.models.ai_chat import AIChatSession

    cols = {c.name for c in sa_inspect(AIChatSession).columns}
    assert {
        "external_application_id",
        "external_app_name",
        "external_app_code",
    }.issubset(cols)


def test_build_embed_url_keeps_runtime_query_and_adds_dolphin_token():
    from app.code_runtime.service import build_embed_url

    url = build_embed_url(
        session_id=12,
        builder_url="https://sandbox.example.com/workspaces/ws-1/builder?token=entry-token&handoffId=handoff-1",
        dolphin_token="embed-token",
    )

    assert url == (
        "/api/code-runtime/12/builder"
        "?token=entry-token&handoffId=handoff-1"
        "&externalSessionRail=1&hideHistory=1&hideNewSession=1&dolphin_token=embed-token"
    )


def test_build_embed_url_hides_runtime_history_and_new_session_controls():
    from app.code_runtime.service import build_embed_url

    url = build_embed_url(
        session_id=12,
        builder_url="https://sandbox.example.com/workspaces/ws-1/builder",
        dolphin_token="embed-token",
    )

    assert "externalSessionRail=1" in url
    assert "hideHistory=1" in url
    assert "hideNewSession=1" in url


def test_derive_runtime_base_url_strips_builder_suffix():
    from app.code_runtime.service import derive_runtime_base_url

    assert derive_runtime_base_url(
        "https://sandbox.example.com/workspaces/ws-1/builder?token=entry-token"
    ) == "https://sandbox.example.com/workspaces/ws-1"
    assert derive_runtime_base_url("https://sandbox.example.com/builder") == "https://sandbox.example.com"


def test_control_plane_base_url_defaults_to_local_dev_port(monkeypatch):
    from app.code_runtime.service import control_plane_base_url

    monkeypatch.delenv("DOLPHIN_CODE_CONTROL_PLANE_URL", raising=False)

    assert control_plane_base_url() == "http://127.0.0.1:8080"


def test_control_plane_headers_use_settings_token_when_env_is_unset(monkeypatch):
    from app.config import settings
    from app.code_runtime import service

    monkeypatch.delenv("DOLPHIN_CODE_CONTROL_PLANE_TOKEN", raising=False)
    monkeypatch.setattr(settings, "dolphin_code_control_plane_token", "settings-token", raising=False)

    assert service._control_plane_headers("Bearer user-token")["Authorization"] == "Bearer settings-token"


def test_control_plane_headers_include_delegation_secret(monkeypatch):
    from app.config import settings
    from app.code_runtime import service

    ctx = SimpleNamespace(user=SimpleNamespace(id=11), tenant_id=7)
    monkeypatch.setenv("DOLPHIN_CODE_CONTROL_PLANE_DELEGATION_SECRET", "shared-secret")
    monkeypatch.setattr(settings, "dolphin_code_control_plane_delegation_secret", "", raising=False)

    headers = service._control_plane_headers(delegated_context=ctx)

    assert headers["X-AI-Builder-Delegation-Secret"] == "shared-secret"


@pytest.mark.asyncio
async def test_default_workspace_open_reports_control_plane_connection_target(monkeypatch):
    import httpx
    from fastapi import HTTPException
    from app.config import settings
    from app.code_runtime import service

    class FailingClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return False

        async def post(self, url: str, **_kwargs):
            raise httpx.ConnectError("connection refused", request=httpx.Request("POST", url))

    monkeypatch.delenv("DOLPHIN_CODE_CONTROL_PLANE_URL", raising=False)
    monkeypatch.setattr(settings, "dolphin_code_control_plane_url", "")
    monkeypatch.setattr(settings, "dolphin_code_builder_url", "")
    monkeypatch.setattr(service.httpx, "AsyncClient", FailingClient)

    with pytest.raises(HTTPException) as exc:
        await service.default_workspace_open("app-1")

    assert exc.value.status_code == 503
    assert "http://127.0.0.1:8080" in str(exc.value.detail)


@pytest.mark.asyncio
async def test_default_workspace_open_falls_back_to_configured_builder_url(monkeypatch):
    import httpx
    from app.code_runtime import service

    class FailingClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return False

        async def post(self, url: str, **_kwargs):
            raise httpx.ConnectError("connection refused", request=httpx.Request("POST", url))

    monkeypatch.delenv("DOLPHIN_CODE_CONTROL_PLANE_URL", raising=False)
    monkeypatch.setenv("DOLPHIN_CODE_BUILDER_URL", "http://127.0.0.1:5173/builder/")
    monkeypatch.setattr(service.httpx, "AsyncClient", FailingClient)

    opened = await service.default_workspace_open("app-1")

    assert opened["applicationId"] == "app-1"
    assert opened["workspaceId"] == "local-builder-app-1"
    assert opened["sandboxInstanceId"] == "local-builder"
    assert opened["specReviewUrl"] == "http://127.0.0.1:5173/builder/"


@pytest.mark.asyncio
async def test_default_workspace_open_rebases_builder_urls_to_local_builder(monkeypatch):
    from app.code_runtime import service

    class FakeResponse:
        status_code = 200
        text = ""

        def json(self):
            return {
                "applicationId": "app-1",
                "workspaceId": "ws-1",
                "sandboxInstanceId": "sandbox-1",
                "chatUrl": "https://sandbox.mock/workspaces/ws-1/builder/?token=entry-token",
                "specReviewUrl": "https://sandbox.mock/workspaces/ws-1/builder/?tab=spec&token=entry-token",
                "webideUrl": "https://sandbox.mock/workspaces/ws-1/ide/?token=entry-token",
            }

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return False

        async def post(self, _url: str, **_kwargs):
            return FakeResponse()

    monkeypatch.setenv("DOLPHIN_CODE_CONTROL_PLANE_URL", "http://127.0.0.1:8080")
    monkeypatch.setenv("DOLPHIN_CODE_BUILDER_URL", "http://127.0.0.1:5173/builder/")
    monkeypatch.setattr(service.httpx, "AsyncClient", FakeClient)

    opened = await service.default_workspace_open("app-1")

    assert opened["chatUrl"] == "http://127.0.0.1:5173/builder?token=entry-token"
    assert opened["specReviewUrl"] == "http://127.0.0.1:5173/builder?tab=spec&token=entry-token"
    assert opened["webideUrl"] == "https://sandbox.mock/workspaces/ws-1/ide/?token=entry-token"


@pytest.mark.asyncio
async def test_list_code_applications_fetches_and_maps_control_plane_apps(monkeypatch):
    from app.code_runtime import service

    calls: list[dict] = []

    class FakeResponse:
        status_code = 200
        text = ""

        def json(self):
            return {
                "items": [
                    {
                        "applicationId": "code-app-1",
                        "appCode": "crm_portal",
                        "appName": "客户门户",
                        "description": "全代码应用",
                        "provisionStatus": "READY",
                        "repository": {"url": "https://git.example.com/acme/crm.git"},
                        "owner": {"userId": "u-1", "displayName": "Admin"},
                        "createdAt": "2026-06-30T10:00:00Z",
                        "updatedAt": "2026-06-30T11:00:00Z",
                    }
                ],
                "page": 2,
                "pageSize": 5,
                "total": 21,
            }

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return False

        async def get(self, url: str, **kwargs):
            calls.append({"url": url, **kwargs})
            return FakeResponse()

    monkeypatch.setenv("DOLPHIN_CODE_CONTROL_PLANE_URL", "https://code.example.com/control-plane")
    monkeypatch.setenv("DOLPHIN_CODE_CONTROL_PLANE_TOKEN", "cp-token")
    monkeypatch.setattr(service.httpx, "AsyncClient", FakeClient)

    result = await service.list_code_applications(keyword="crm", page=2, page_size=5)

    assert calls == [{
        "url": "https://code.example.com/control-plane/api/applications",
        "headers": {"Authorization": "Bearer cp-token"},
        "params": {"page": 2, "pageSize": 5, "keyword": "crm"},
    }]
    assert result["page"] == 2
    assert result["pageSize"] == 5
    assert result["total"] == 21
    assert result["items"][0] == {
        "id": "code-app-1",
        "external_application_id": "code-app-1",
        "app_name": "客户门户",
        "app_code": "crm_portal",
        "description": "全代码应用",
        "source": "d-ai-code",
        "app_type": "ai-code",
        "status": "READY",
        "local_status": "completed",
        "remote_status": "READY",
        "models": 0,
        "forms": 0,
        "roles": 0,
        "dicts": 0,
        "repository": {"url": "https://git.example.com/acme/crm.git"},
        "owner": {"userId": "u-1", "displayName": "Admin"},
        "created_at": "2026-06-30T10:00:00Z",
        "updated_at": "2026-06-30T11:00:00Z",
    }


@pytest.mark.asyncio
async def test_create_code_application_posts_to_control_plane_with_default_seed(monkeypatch):
    from app.code_runtime import service

    calls: list[dict] = []

    class FakeResponse:
        status_code = 201
        text = ""

        def json(self):
            return {
                "applicationId": "code-app-new",
                "appCode": "sales-lead-helper",
                "appName": "销售线索评分助手",
                "description": None,
                "provisionStatus": "READY",
                "seedProjectId": "1781233861147",
                "repository": {"repositoryUrl": "https://git.example.com/sales.git"},
                "createdAt": "2026-07-02T07:00:00Z",
                "updatedAt": "2026-07-02T07:00:01Z",
            }

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return False

        async def post(self, url: str, **kwargs):
            calls.append({"url": url, **kwargs})
            return FakeResponse()

    monkeypatch.setenv("DOLPHIN_CODE_CONTROL_PLANE_URL", "https://code.example.com/control-plane")
    monkeypatch.setenv("DOLPHIN_CODE_CONTROL_PLANE_TOKEN", "cp-token")
    monkeypatch.delenv("DOLPHIN_CODE_DEFAULT_SEED_PROJECT_ID", raising=False)
    monkeypatch.setattr(service.httpx, "AsyncClient", FakeClient)

    result = await service.create_code_application(
        app_name="销售线索评分助手",
        app_code="sales-lead-helper",
    )

    assert calls == [{
        "url": "https://code.example.com/control-plane/api/applications",
        "headers": {"Authorization": "Bearer cp-token", "Content-Type": "application/json"},
        "json": {
            "appCode": "sales-lead-helper",
            "appName": "销售线索评分助手",
            "seedProjectId": "1781233861147",
        },
    }]
    assert result["external_application_id"] == "code-app-new"
    assert result["app_name"] == "销售线索评分助手"
    assert result["app_code"] == "sales-lead-helper"
    assert result["local_status"] == "completed"


@pytest.mark.asyncio
async def test_create_code_application_uses_seed_project_override(monkeypatch):
    from app.code_runtime import service
    from app.config import settings

    calls: list[dict] = []

    class FakeResponse:
        status_code = 201
        text = ""

        def json(self):
            return {
                "applicationId": "code-app-new",
                "appCode": "inventory-copilot",
                "appName": "库存助手",
                "provisionStatus": "PENDING",
            }

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return False

        async def post(self, url: str, **kwargs):
            calls.append({"url": url, **kwargs})
            return FakeResponse()

    monkeypatch.setenv("DOLPHIN_CODE_CONTROL_PLANE_URL", "https://code.example.com/control-plane")
    monkeypatch.setenv("DOLPHIN_CODE_DEFAULT_SEED_PROJECT_ID", "90001")
    monkeypatch.delenv("DOLPHIN_CODE_CONTROL_PLANE_TOKEN", raising=False)
    monkeypatch.setattr(settings, "dolphin_code_control_plane_token", "", raising=False)
    monkeypatch.setattr(service.httpx, "AsyncClient", FakeClient)

    await service.create_code_application(
        app_name="库存助手",
        app_code="inventory-copilot",
        seed_project_id="90002",
        authorization_header="Bearer user-token",
    )

    assert calls[0]["headers"]["Authorization"] == "Bearer user-token"
    assert calls[0]["json"]["seedProjectId"] == "90002"


@pytest.mark.asyncio
async def test_default_workspace_open_forwards_request_authorization_when_no_service_token(monkeypatch):
    from app.config import settings
    from app.code_runtime import service

    calls: list[dict] = []

    class FakeResponse:
        status_code = 200
        text = ""

        def json(self):
            return {"specReviewUrl": "https://sandbox.example.com/builder"}

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return False

        async def post(self, url: str, **kwargs):
            calls.append({"url": url, **kwargs})
            return FakeResponse()

    monkeypatch.setenv("DOLPHIN_CODE_CONTROL_PLANE_URL", "https://code.example.com/control-plane")
    monkeypatch.delenv("DOLPHIN_CODE_CONTROL_PLANE_TOKEN", raising=False)
    monkeypatch.setattr(settings, "dolphin_code_control_plane_token", "")
    monkeypatch.setattr(service.httpx, "AsyncClient", FakeClient)

    await service.default_workspace_open("code-app-1", authorization_header="Bearer user-token")

    assert calls[0]["headers"]["Authorization"] == "Bearer user-token"


@pytest.mark.asyncio
async def test_default_workspace_open_sends_delegated_identity_with_service_token(monkeypatch):
    from app.code_runtime import service

    calls: list[dict] = []

    class FakeResponse:
        status_code = 200
        text = ""

        def json(self):
            return {"specReviewUrl": "https://sandbox.example.com/builder"}

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return False

        async def post(self, url: str, **kwargs):
            calls.append({"url": url, **kwargs})
            return FakeResponse()

    ctx = SimpleNamespace(
        user=SimpleNamespace(id=11, username="admin", display_name="张三"),
        tenant_id=7,
        tenant_role="platform_admin",
        apaas_user_id="100169876816012509184",
        apaas_tenant_id="844246516607483905",
    )

    monkeypatch.setenv("DOLPHIN_CODE_CONTROL_PLANE_URL", "https://code.example.com/control-plane")
    monkeypatch.setenv("DOLPHIN_CODE_CONTROL_PLANE_TOKEN", "cp-token")
    monkeypatch.setenv("DOLPHIN_CODE_CONTROL_PLANE_DELEGATION_SECRET", "shared-secret")
    monkeypatch.setattr(service.httpx, "AsyncClient", FakeClient)

    await service.default_workspace_open(
        "code-app-1",
        authorization_header="Bearer user-token",
        delegated_context=ctx,
        shell_session_id=42,
    )

    headers = calls[0]["headers"]
    assert headers["Authorization"] == "Bearer cp-token"
    assert headers["X-AI-Builder-Delegation-Secret"] == "shared-secret"
    assert headers["X-AI-Builder-Delegated-User-Id"] == "100169876816012509184"
    assert headers["X-AI-Builder-Delegated-Tenant-Id"] == "844246516607483905"
    assert headers["X-AI-Builder-Local-User-Id"] == "11"
    assert headers["X-AI-Builder-Local-Tenant-Id"] == "7"
    assert headers["X-AI-Builder-Delegated-Username"] == "admin"
    assert headers["X-AI-Builder-Shell-Session-Id"] == "42"
    assert base64.urlsafe_b64decode(headers["X-AI-Builder-Delegated-Display-Name-B64"]).decode() == "张三"


def test_embed_token_round_trip_is_bound_to_session():
    from fastapi import HTTPException
    from app.code_runtime.service import (
        create_embed_token,
        create_proxy_cookie_token,
        validate_embed_token,
        validate_proxy_cookie_token,
    )

    token = create_embed_token(session_id=12, user_id=34, tenant_id=56, minutes=1)

    payload = validate_embed_token(token, session_id=12)
    assert payload["sid"] == 12
    assert payload["sub"] == "34"
    assert payload["tid"] == 56

    with pytest.raises(HTTPException):
        validate_embed_token(token, session_id=13)

    proxy_token = create_proxy_cookie_token(session_id=12, user_id=34, tenant_id=56, minutes=60)
    assert validate_proxy_cookie_token(proxy_token, session_id=12)["type"] == "code_runtime_proxy"

    with pytest.raises(HTTPException):
        validate_proxy_cookie_token(token, session_id=12)


def test_strip_dolphin_token_keeps_runtime_token_query():
    from app.code_runtime.service import strip_dolphin_token_from_url

    assert strip_dolphin_token_from_url(
        "http://test/api/code-runtime/12/builder?token=entry&dolphin_token=embed&handoffId=h1"
    ) == "http://test/api/code-runtime/12/builder?token=entry&handoffId=h1"


@pytest.mark.asyncio
async def test_open_code_session_upserts_runtime_binding(db_session):
    from sqlalchemy import select
    from app.code_runtime.service import open_code_session
    from app.models.ai_chat import CodeRuntimeBinding

    app = Application(
        id=101,
        tenant_id=7,
        user_id=11,
        created_by=11,
        app_name="销售应用",
        app_code="sales",
        app_type="ai-code",
        status="completed",
        apaas_app_id="91001",
    )
    session = AIChatSession(
        tenant_id=7,
        user_id=11,
        app_id=101,
        title="销售应用 Code",
        mode="code",
        status="active",
    )
    db_session.add_all([app, session])
    await db_session.commit()
    await db_session.refresh(session)

    calls: list[str] = []

    async def fake_open(external_application_id: str, handoff_id: str | None = None):
        calls.append(external_application_id)
        return {
            "applicationId": external_application_id,
            "workspaceId": "93001",
            "sandboxInstanceId": "sandbox-93001",
            "conversationId": "conversation-93001",
            "specReviewUrl": "https://sandbox.example.com/workspaces/93001/builder?token=entry-token",
            "handoff": {"handoffId": handoff_id or "handoff-1", "status": "accepted"},
        }

    result = await open_code_session(
        db=db_session,
        session_id=session.id,
        ctx=SimpleNamespace(user=SimpleNamespace(id=11), tenant_id=7, tenant_role="member"),
        workspace_open=fake_open,
        embed_token_factory=lambda **_: "dolphin-embed",
    )

    assert calls == ["91001"]
    assert result["session_id"] == session.id
    assert result["external_base_path"] == f"/api/code-runtime/{session.id}"
    assert result["embed_url"].startswith(f"/api/code-runtime/{session.id}/builder?")
    assert "dolphin_token=dolphin-embed" in result["embed_url"]

    binding = (
        await db_session.execute(
            select(CodeRuntimeBinding).where(CodeRuntimeBinding.session_id == session.id)
        )
    ).scalar_one()
    assert binding.external_application_id == "91001"
    assert binding.workspace_id == "93001"
    assert binding.sandbox_instance_id == "sandbox-93001"
    assert binding.runtime_base_url == "https://sandbox.example.com/workspaces/93001"


@pytest.mark.asyncio
async def test_open_code_session_uses_external_code_application_without_local_app(db_session):
    from sqlalchemy import select
    from app.code_runtime.service import open_code_session
    from app.models.ai_chat import CodeRuntimeBinding

    session = AIChatSession(
        tenant_id=7,
        user_id=11,
        app_id=None,
        external_application_id="code-app-1",
        external_app_name="客户门户",
        external_app_code="crm_portal",
        title="客户门户 Code",
        mode="code",
        status="active",
    )
    db_session.add(session)
    await db_session.commit()
    await db_session.refresh(session)

    calls: list[str] = []

    async def fake_open(external_application_id: str, handoff_id: str | None = None):
        calls.append(external_application_id)
        return {
            "workspaceId": "ws-1",
            "sandboxInstanceId": "sandbox-1",
            "specReviewUrl": "https://sandbox.example.com/workspaces/ws-1/builder?token=entry-token",
        }

    result = await open_code_session(
        db=db_session,
        session_id=session.id,
        ctx=SimpleNamespace(user=SimpleNamespace(id=11), tenant_id=7, tenant_role="member"),
        workspace_open=fake_open,
        embed_token_factory=lambda **_: "dolphin-embed",
    )

    assert calls == ["code-app-1"]
    assert result["app_id"] is None
    assert result["external_application_id"] == "code-app-1"

    binding = (
        await db_session.execute(
            select(CodeRuntimeBinding).where(CodeRuntimeBinding.session_id == session.id)
        )
    ).scalar_one()
    assert binding.app_id is None
    assert binding.external_application_id == "code-app-1"


@pytest.mark.asyncio
async def test_open_code_session_preserves_current_runtime_session_when_open_omits_runtime_id(db_session):
    from sqlalchemy import select
    from app.code_runtime.service import open_code_session
    from app.models.ai_chat import CodeRuntimeBinding

    session = AIChatSession(
        tenant_id=7,
        user_id=11,
        app_id=None,
        external_application_id="code-app-1",
        external_app_name="客户门户",
        external_app_code="crm_portal",
        title="客户门户 Code",
        mode="code",
        status="active",
    )
    db_session.add(session)
    await db_session.flush()
    db_session.add(CodeRuntimeBinding(
        tenant_id=7,
        user_id=11,
        session_id=session.id,
        external_application_id="code-app-1",
        runtime_base_url="https://old.example.com/workspaces/ws-1",
        builder_url="https://old.example.com/workspaces/ws-1/builder",
        runtime_session_id="runtime-current",
        status="ready",
    ))
    await db_session.commit()
    await db_session.refresh(session)

    async def fake_open(_external_application_id: str, _handoff_id: str | None = None):
        return {
            "workspaceId": "ws-1",
            "sandboxInstanceId": "sandbox-1",
            "specReviewUrl": "https://sandbox.example.com/workspaces/ws-1/builder?token=entry-token",
        }

    result = await open_code_session(
        db=db_session,
        session_id=session.id,
        ctx=SimpleNamespace(user=SimpleNamespace(id=11), tenant_id=7, tenant_role="member"),
        workspace_open=fake_open,
        embed_token_factory=lambda **_: "dolphin-embed",
    )

    binding = (
        await db_session.execute(
            select(CodeRuntimeBinding).where(CodeRuntimeBinding.session_id == session.id)
        )
    ).scalar_one()
    assert binding.runtime_session_id == "runtime-current"
    assert result["runtime_session_id"] == "runtime-current"


@pytest.mark.asyncio
async def test_open_code_session_preserves_scoped_runtime_session_when_open_returns_default(db_session):
    from sqlalchemy import select
    from app.code_runtime.service import open_code_session
    from app.models.ai_chat import CodeRuntimeAgentSession, CodeRuntimeBinding

    session = AIChatSession(
        tenant_id=7,
        user_id=11,
        app_id=None,
        external_application_id="code-app-1",
        external_app_name="客户门户",
        external_app_code="crm_portal",
        title="客户门户 Code",
        mode="code",
        status="active",
    )
    db_session.add(session)
    await db_session.flush()
    db_session.add(CodeRuntimeBinding(
        tenant_id=7,
        user_id=11,
        session_id=session.id,
        external_application_id="code-app-1",
        runtime_base_url="https://old.example.com/workspaces/ws-1",
        builder_url="https://old.example.com/workspaces/ws-1/builder",
        runtime_session_id="runtime-selected",
        status="ready",
    ))
    db_session.add(CodeRuntimeAgentSession(
        tenant_id=7,
        user_id=11,
        session_id=session.id,
        external_application_id="code-app-1",
        runtime_session_id="runtime-selected",
    ))
    await db_session.commit()
    await db_session.refresh(session)

    async def fake_open(_external_application_id: str, _handoff_id: str | None = None):
        return {
            "workspaceId": "ws-1",
            "sandboxInstanceId": "sandbox-1",
            "runtimeSessionId": "runtime-default",
            "specReviewUrl": "https://sandbox.example.com/workspaces/ws-1/builder?token=entry-token",
        }

    result = await open_code_session(
        db=db_session,
        session_id=session.id,
        ctx=SimpleNamespace(user=SimpleNamespace(id=11), tenant_id=7, tenant_role="member"),
        workspace_open=fake_open,
        embed_token_factory=lambda **_: "dolphin-embed",
    )

    binding = (
        await db_session.execute(
            select(CodeRuntimeBinding).where(CodeRuntimeBinding.session_id == session.id)
        )
    ).scalar_one()
    assert binding.runtime_session_id == "runtime-selected"
    assert result["runtime_session_id"] == "runtime-selected"


@pytest.mark.asyncio
async def test_open_code_session_passes_auth_context_to_control_plane_open(db_session, monkeypatch):
    from app.code_runtime import service
    from app.code_runtime.service import open_code_session

    session = AIChatSession(
        tenant_id=7,
        user_id=11,
        app_id=None,
        external_application_id="code-app-1",
        external_app_name="客户门户",
        external_app_code="crm_portal",
        title="客户门户 Code",
        mode="code",
        status="active",
    )
    db_session.add(session)
    await db_session.commit()
    await db_session.refresh(session)

    captured: dict = {}

    async def fake_default_workspace_open(
        external_application_id: str,
        handoff_id: str | None = None,
        *,
        authorization_header: str | None = None,
        delegated_context=None,
        shell_session_id: int | None = None,
    ):
        captured.update({
            "external_application_id": external_application_id,
            "handoff_id": handoff_id,
            "authorization_header": authorization_header,
            "delegated_context": delegated_context,
            "shell_session_id": shell_session_id,
        })
        return {
            "workspaceId": "ws-1",
            "sandboxInstanceId": "sandbox-1",
            "specReviewUrl": "https://sandbox.example.com/workspaces/ws-1/builder?token=entry-token",
        }

    monkeypatch.setattr(service, "default_workspace_open", fake_default_workspace_open)
    ctx = SimpleNamespace(
        user=SimpleNamespace(id=11, username="admin", display_name="管理员"),
        tenant_id=7,
        tenant_role="platform_admin",
        apaas_user_id="100169876816012509184",
        apaas_tenant_id="844246516607483905",
    )

    await open_code_session(
        db=db_session,
        session_id=session.id,
        ctx=ctx,
        authorization_header="Bearer user-token",
        embed_token_factory=lambda **_: "dolphin-embed",
    )

    assert captured["external_application_id"] == "code-app-1"
    assert captured["authorization_header"] == "Bearer user-token"
    assert captured["delegated_context"] is ctx
    assert captured["shell_session_id"] == session.id


@pytest.mark.asyncio
async def test_open_code_session_rejects_low_code_app(db_session):
    from fastapi import HTTPException
    from app.code_runtime.service import open_code_session

    app = Application(
        id=101,
        tenant_id=7,
        user_id=11,
        created_by=11,
        app_name="低代码应用",
        app_code="lowcode",
        app_type="low-code",
        status="completed",
    )
    session = AIChatSession(
        tenant_id=7,
        user_id=11,
        app_id=101,
        title="低代码应用 Code",
        mode="code",
        status="active",
    )
    db_session.add_all([app, session])
    await db_session.commit()
    await db_session.refresh(session)

    with pytest.raises(HTTPException) as exc:
        await open_code_session(
            db=db_session,
            session_id=session.id,
            ctx=SimpleNamespace(user=SimpleNamespace(id=11), tenant_id=7, tenant_role="member"),
            workspace_open=lambda *_args, **_kwargs: None,
        )

    assert exc.value.status_code == 400
    assert "Code" in str(exc.value.detail)


@pytest.mark.asyncio
async def test_open_code_session_rejects_non_code_session(db_session):
    from fastapi import HTTPException
    from app.code_runtime.service import open_code_session

    session = AIChatSession(
        tenant_id=7,
        user_id=11,
        title="Builder",
        mode="chat",
        status="active",
    )
    db_session.add(session)
    await db_session.commit()
    await db_session.refresh(session)

    with pytest.raises(HTTPException) as exc:
        await open_code_session(
            db=db_session,
            session_id=session.id,
            ctx=SimpleNamespace(user=SimpleNamespace(id=11), tenant_id=7, tenant_role="member"),
            workspace_open=lambda *_args, **_kwargs: None,
        )

    assert exc.value.status_code == 400
