from __future__ import annotations

import json
from types import SimpleNamespace
from uuid import UUID

import pytest
from sqlalchemy import select

from app.models import Application
from app.models.ai_chat import AIChatSession, CodeRuntimeAgentSession, CodeRuntimeBinding


def _ctx(user_id: int = 11, tenant_id: int = 7, role: str = "member"):
    return SimpleNamespace(user=SimpleNamespace(id=user_id), tenant_id=tenant_id, tenant_role=role)


def _request(headers: dict[str, str] | None = None):
    from starlette.datastructures import Headers

    return SimpleNamespace(headers=Headers(headers or {}))


@pytest.mark.asyncio
async def test_resolve_control_plane_tenant_id_uses_workspace_tenant_code(db_session):
    from app.models.tenant import Tenant
    from app.routes.code_runtime import _resolve_control_plane_tenant_id

    tenant = Tenant(tenant_name="Admin Workspace", tenant_code="workspace-0")
    db_session.add(tenant)
    await db_session.flush()
    ctx = SimpleNamespace(
        tenant_id=tenant.id,
        user=SimpleNamespace(coding_tenant_id="new-tenant"),
    )

    assert await _resolve_control_plane_tenant_id(db_session, ctx) == "0"


def test_code_runtime_proxy_rewrites_upstream_location_headers():
    from app.models.ai_chat import CodeRuntimeBinding
    from app.routes.code_runtime import _rewrite_location_header

    binding = CodeRuntimeBinding(
        session_id=12,
        runtime_base_url="https://sandbox.example.com/workspaces/ws-1",
    )

    assert _rewrite_location_header(
        "https://sandbox.example.com/workspaces/ws-1/builder/",
        binding,
        12,
    ) == "/api/code-runtime/12/builder/"
    assert _rewrite_location_header(
        "/workspaces/ws-1/api/readyz",
        binding,
        12,
    ) == "/api/code-runtime/12/api/readyz"
    assert _rewrite_location_header(
        "/api/readyz",
        binding,
        12,
    ) == "/api/code-runtime/12/api/readyz"
    assert _rewrite_location_header(
        "/api/readyz",
        binding,
        12,
        "/ai-builder",
    ) == "/ai-builder/api/code-runtime/12/api/readyz"


@pytest.mark.asyncio
async def test_authorize_shell_request_accepts_authenticated_builder_request():
    from starlette.datastructures import Headers
    from app.routes.code_runtime import _authorize_shell_request

    request = SimpleNamespace(headers=Headers({
        "authorization": "Bearer builder-token",
    }))

    assert await _authorize_shell_request(request, 20) is None


@pytest.mark.asyncio
async def test_authorize_shell_request_keeps_proxy_token_check_without_builder_auth(monkeypatch):
    import app.routes.code_runtime as code_runtime_routes
    from starlette.datastructures import Headers

    expected = SimpleNamespace(status_code=307)

    async def fake_authorize_proxy_request(request, session_id):
        assert request.headers.get("authorization") is None
        assert session_id == 20
        return expected

    monkeypatch.setattr(
        code_runtime_routes,
        "_authorize_proxy_request",
        fake_authorize_proxy_request,
    )
    request = SimpleNamespace(headers=Headers({}))

    assert await code_runtime_routes._authorize_shell_request(request, 20) is expected


def test_code_runtime_proxy_token_redirect_stays_on_current_origin():
    from app.routes.code_runtime import _redirect_target_without_dolphin_token

    assert _redirect_target_without_dolphin_token(
        "/api/code-runtime/12/builder",
        b"token=entry&dolphin_token=embed&handoffId=h1",
    ) == "/api/code-runtime/12/builder?token=entry&handoffId=h1"
    assert _redirect_target_without_dolphin_token(
        "/api/code-runtime/12/builder",
        b"dolphin_token=embed",
    ) == "/api/code-runtime/12/builder"
    assert _redirect_target_without_dolphin_token(
        "/api/code-runtime/12/builder",
        b"token=entry&dolphin_token=embed",
        "/ai-builder",
    ) == "/ai-builder/api/code-runtime/12/builder?token=entry"


def test_code_runtime_proxy_preserves_vite_bare_url_query():
    from app.models.ai_chat import CodeRuntimeBinding
    from app.routes.code_runtime import _query_string_without_key, _target_url

    assert _query_string_without_key(b"url&dolphin_token=embed&v=1", "dolphin_token") == "url&v=1"

    binding = CodeRuntimeBinding(
        session_id=12,
        runtime_base_url="http://127.0.0.1:5173",
    )
    request = SimpleNamespace(
        scope={"query_string": b"url&token=entry&dolphin_token=embed&v=1"}
    )

    assert _target_url(
        binding,
        "node_modules/pdfjs-dist/build/pdf.worker.mjs",
        request,
    ) == (
        "http://127.0.0.1:5173/node_modules/pdfjs-dist/build/pdf.worker.mjs"
        "?url&token=entry&v=1"
    )


def test_code_runtime_proxy_rewrites_unicode_content_disposition_header():
    from app.routes.code_runtime import _copyable_response_headers

    copied = _copyable_response_headers({
        "content-disposition": 'inline; filename="项目启动文档.md"',
        "content-type": "text/markdown",
    })

    value = copied["content-disposition"]
    value.encode("latin-1")
    assert 'filename="download.md"' in value
    assert "filename*=UTF-8''%E9%A1%B9%E7%9B%AE%E5%90%AF%E5%8A%A8%E6%96%87%E6%A1%A3.md" in value
    assert copied["content-type"] == "text/markdown"


def test_code_runtime_proxy_rewrites_vite_dev_asset_paths():
    from app.routes.code_runtime import _rewrite_runtime_dev_asset_paths

    content = (
        b'<script type="module" src="/@vite/client"></script>'
        b'import React from "/node_modules/.vite/deps/react.js?v=1";'
        b'import App from "/src/app/App.tsx";'
        b"import Refresh from '/@react-refresh';"
    )

    rewritten = _rewrite_runtime_dev_asset_paths(content, 12)

    assert b'src="/api/code-runtime/12/@vite/client"' in rewritten
    assert b'from "/api/code-runtime/12/node_modules/.vite/deps/react.js?v=1"' in rewritten
    assert b'from "/api/code-runtime/12/src/app/App.tsx"' in rewritten
    assert b"from '/api/code-runtime/12/@react-refresh'" in rewritten

    prefixed = _rewrite_runtime_dev_asset_paths(content, 12, "/ai-builder")
    assert b'src="/ai-builder/api/code-runtime/12/@vite/client"' in prefixed


def test_code_runtime_proxy_only_buffers_vite_dev_asset_paths():
    from app.routes.code_runtime import _should_buffer_dev_asset_path

    assert _should_buffer_dev_asset_path("src/main.tsx")
    assert _should_buffer_dev_asset_path("@vite/client")
    assert _should_buffer_dev_asset_path("node_modules/.vite/deps/react.js")
    assert not _should_buffer_dev_asset_path("api/builder/events")
    assert not _should_buffer_dev_asset_path("api/agent/sessions/current")


def test_code_runtime_proxy_does_not_special_case_runtime_relative_document_paths():
    from app.routes.code_runtime import _should_buffer_dev_asset_path

    assert not _should_buffer_dev_asset_path("docs/demo.md")
    assert not _should_buffer_dev_asset_path("builder/docs/demo.md")
    assert not _should_buffer_dev_asset_path("README.md")


def test_code_runtime_proxy_forwards_runtime_cookies_without_proxy_cookie():
    from starlette.datastructures import Headers
    from app.routes.code_runtime import _copyable_request_headers

    request = SimpleNamespace(headers=Headers({
        "host": "127.0.0.1:8000",
        "cookie": "dolphin_code_runtime_12=proxy-token; runtime_sid=abc; runtime_theme=dark",
        "accept": "text/event-stream",
    }))

    headers = _copyable_request_headers(request, 12)

    assert headers["accept"] == "text/event-stream"
    assert headers["cookie"] == "runtime_sid=abc; runtime_theme=dark"
    assert "dolphin_code_runtime_12" not in headers["cookie"]
    assert "host" not in {key.lower() for key in headers}


def test_runtime_request_headers_preserve_query_token_bootstrap_without_bearer():
    from starlette.datastructures import Headers
    from app.routes.code_runtime import _runtime_request_headers

    binding = CodeRuntimeBinding(
        session_id=12,
        runtime_base_url="https://runtime.example.com/workspaces/ws-1",
        builder_url="https://runtime.example.com/workspaces/ws-1/builder?token=entry-token",
    )
    request = SimpleNamespace(
        headers=Headers({
            "authorization": "Bearer builder-token",
            "cookie": "dolphin_code_runtime_12=proxy-token",
        }),
        scope={"query_string": b"token=entry-token&externalSessionRail=1"},
    )

    headers = _runtime_request_headers(
        request,
        12,
        binding,
        allow_query_token=True,
    )

    assert "authorization" not in headers
    assert "cookie" not in headers


@pytest.mark.asyncio
async def test_browser_runtime_request_prefers_runtime_cookie_over_entry_token(monkeypatch):
    import httpx
    import app.routes.code_runtime as code_runtime_routes
    from starlette.datastructures import Headers
    from app.routes.code_runtime import _browser_runtime_json_request

    binding = CodeRuntimeBinding(
        session_id=12,
        runtime_base_url="https://runtime.example.com/workspaces/ws-1",
        builder_url="https://runtime.example.com/workspaces/ws-1/builder?token=entry-token",
    )
    request = SimpleNamespace(headers=Headers({
        "authorization": "Bearer builder-token",
        "cookie": "dolphin_code_runtime_12=proxy-token; apaas_sandbox_token=runtime-cookie",
        "accept": "application/json",
    }))

    def handler(upstream: httpx.Request) -> httpx.Response:
        assert "authorization" not in upstream.headers
        assert upstream.headers["cookie"] == "apaas_sandbox_token=runtime-cookie"
        return httpx.Response(200, json={"sessions": []})

    transport = httpx.MockTransport(handler)
    original = code_runtime_routes.httpx.AsyncClient
    monkeypatch.setattr(
        code_runtime_routes.httpx,
        "AsyncClient",
        lambda **kwargs: original(transport=transport, **kwargs),
    )

    result = await _browser_runtime_json_request(
        binding,
        "GET",
        "/api/agent/sessions",
        request=request,
        session_id=12,
    )

    assert result == {"sessions": []}


@pytest.mark.asyncio
async def test_browser_runtime_request_uses_entry_token_without_runtime_cookie(monkeypatch):
    import httpx
    import app.routes.code_runtime as code_runtime_routes
    from starlette.datastructures import Headers
    from app.routes.code_runtime import _browser_runtime_json_request

    binding = CodeRuntimeBinding(
        session_id=12,
        runtime_base_url="https://runtime.example.com/workspaces/ws-1",
        builder_url="https://runtime.example.com/workspaces/ws-1/builder?token=entry-token",
    )
    request = SimpleNamespace(headers=Headers({
        "authorization": "Bearer builder-token",
        "cookie": "dolphin_code_runtime_12=proxy-token",
        "accept": "application/json",
    }))

    def handler(upstream: httpx.Request) -> httpx.Response:
        assert upstream.headers["authorization"] == "Bearer entry-token"
        assert "cookie" not in upstream.headers
        return httpx.Response(200, json={"sessions": []})

    transport = httpx.MockTransport(handler)
    original = code_runtime_routes.httpx.AsyncClient
    monkeypatch.setattr(
        code_runtime_routes.httpx,
        "AsyncClient",
        lambda **kwargs: original(transport=transport, **kwargs),
    )

    result = await _browser_runtime_json_request(
        binding,
        "GET",
        "/api/agent/sessions",
        request=request,
        session_id=12,
    )

    assert result == {"sessions": []}


@pytest.mark.asyncio
async def test_server_runtime_request_uses_runtime_entry_token(monkeypatch):
    import httpx
    import app.routes.code_runtime as code_runtime_routes
    from app.routes.code_runtime import _runtime_json_request

    binding = CodeRuntimeBinding(
        session_id=12,
        runtime_base_url="https://runtime.example.com/workspaces/ws-1",
        builder_url=(
            "https://runtime.example.com/workspaces/ws-1/builder"
            "?tab=spec&token=entry-token&externalSessionRail=1"
        ),
    )

    def handler(upstream: httpx.Request) -> httpx.Response:
        assert upstream.headers["authorization"] == "Bearer entry-token"
        return httpx.Response(200, json={"sessions": []})

    transport = httpx.MockTransport(handler)
    original = code_runtime_routes.httpx.AsyncClient
    monkeypatch.setattr(
        code_runtime_routes.httpx,
        "AsyncClient",
        lambda **kwargs: original(transport=transport, **kwargs),
    )

    result = await _runtime_json_request(binding, "GET", "/api/agent/sessions")

    assert result == {"sessions": []}


@pytest.mark.asyncio
async def test_server_runtime_request_refreshes_binding_once_after_unauthorized(monkeypatch):
    from fastapi import HTTPException
    import app.routes.code_runtime as code_runtime_routes

    session = SimpleNamespace(
        id=12,
        app_id=None,
        external_application_id="code-app-1",
    )
    binding = CodeRuntimeBinding(
        session_id=12,
        runtime_base_url="https://runtime.example.com/workspaces/ws-1",
        builder_url="https://runtime.example.com/workspaces/ws-1/builder?token=stale-token",
    )
    calls: list[str] = []

    async def fake_runtime_request(current_binding, method, path, **kwargs):
        calls.append(str(current_binding.builder_url))
        if len(calls) == 1:
            raise HTTPException(status_code=401, detail="entry token expired")
        return {"sessions": []}

    async def fake_refresh(session_arg, binding_arg, request_arg, ctx_arg, db_arg):
        assert session_arg is session
        assert binding_arg is binding
        binding_arg.builder_url = (
            "https://runtime.example.com/workspaces/ws-1/builder?token=fresh-token"
        )

    monkeypatch.setattr(code_runtime_routes, "_runtime_json_request", fake_runtime_request)
    monkeypatch.setattr(code_runtime_routes, "_refresh_runtime_binding", fake_refresh)

    result = await code_runtime_routes._runtime_json_request_for_session(
        session,
        binding,
        "GET",
        "/api/agent/sessions",
        request=_request(),
        ctx=_ctx(),
        db=SimpleNamespace(),
    )

    assert result == {"sessions": []}
    assert calls == [
        "https://runtime.example.com/workspaces/ws-1/builder?token=stale-token",
        "https://runtime.example.com/workspaces/ws-1/builder?token=fresh-token",
    ]


@pytest.mark.asyncio
async def test_shell_agent_sessions_renews_expired_proxy_cookie_for_authenticated_builder_user(monkeypatch):
    from starlette.datastructures import Headers
    from starlette.responses import Response

    import app.routes.code_runtime as code_runtime_routes
    from app.code_runtime.service import validate_proxy_cookie_token
    from app.routes.code_runtime import list_browser_authenticated_agent_sessions

    binding = CodeRuntimeBinding(
        session_id=13,
        runtime_base_url="https://runtime.example.com/workspaces/ws-13",
    )

    async def fake_authorized_binding(_db, session_id, ctx):
        assert session_id == 13
        assert ctx.user.id == 11
        return SimpleNamespace(id=13), binding

    async def fake_browser_request(_binding, method, path, **_kwargs):
        assert method == "GET"
        assert path == "/api/agent/sessions"
        return {"sessions": []}

    async def fake_other_scoped_ids(_db, session_id):
        assert session_id == 13
        return set()

    monkeypatch.setattr(code_runtime_routes, "_authorized_code_runtime_binding", fake_authorized_binding)
    monkeypatch.setattr(code_runtime_routes, "_browser_runtime_json_request", fake_browser_request)
    monkeypatch.setattr(
        code_runtime_routes,
        "_runtime_session_ids_scoped_to_other_shells",
        fake_other_scoped_ids,
    )

    request = SimpleNamespace(
        headers=Headers({
            "authorization": "Bearer builder-token",
            "x-forwarded-prefix": "/ai-builder",
        }),
        query_params={},
        cookies={"dolphin_code_runtime_13": "expired-proxy-cookie"},
    )
    response = Response()

    result = await list_browser_authenticated_agent_sessions(
        session_id=13,
        request=request,
        response=response,
        ctx=_ctx(),
        db=SimpleNamespace(),
    )

    assert result == {"sessions": []}
    set_cookie = response.headers["set-cookie"]
    assert "dolphin_code_runtime_13=" in set_cookie
    assert "Max-Age=43200" in set_cookie
    assert "Path=/ai-builder/api/code-runtime/13" in set_cookie
    proxy_token = set_cookie.split("dolphin_code_runtime_13=", 1)[1].split(";", 1)[0]
    payload = validate_proxy_cookie_token(proxy_token, session_id=13)
    assert payload["sub"] == "11"
    assert payload["tid"] == 7


def test_code_runtime_proxy_scopes_runtime_cookie_to_forwarded_prefix():
    from app.routes.code_runtime import _rewrite_set_cookie_path

    assert _rewrite_set_cookie_path(
        "runtime_sid=abc; Path=/; HttpOnly",
        12,
        "/ai-builder",
    ) == "runtime_sid=abc; Path=/ai-builder/api/code-runtime/12; HttpOnly"


def test_browser_session_filter_keeps_unscoped_history_and_excludes_other_shells():
    from app.routes.code_runtime import _filter_browser_runtime_sessions

    sessions = [
        {"runtimeSessionId": "runtime-old", "title": "历史会话"},
        {"runtimeSessionId": "runtime-current", "title": "当前会话"},
        {"runtimeSessionId": "runtime-other", "title": "其它应用会话"},
    ]

    filtered = _filter_browser_runtime_sessions(
        sessions,
        other_scoped_ids={"runtime-other"},
    )

    assert [item["runtimeSessionId"] for item in filtered] == [
        "runtime-old",
        "runtime-current",
    ]


def test_code_runtime_shell_origin_prefers_referer_over_backend_base():
    from starlette.datastructures import Headers
    from app.routes.code_runtime import _browser_origin_from_headers

    headers = Headers({
        "host": "localhost:8000",
        "referer": "http://127.0.0.1:5273/ai-builder/code/12",
    })

    assert _browser_origin_from_headers(headers, "http://localhost:8000") == "http://127.0.0.1:5273"


def test_code_runtime_shell_config_exposes_external_session_rail_flag():
    from app.routes.code_runtime import _inject_shell_config

    injected = _inject_shell_config(
        b"<html><head></head><body><div id=\"root\"></div></body></html>",
        12,
        "http://127.0.0.1:5273",
    )

    assert b'"externalSessionRail":true' in injected
    assert b'"hideHistory":true' in injected
    assert b'"hideNewSession":true' in injected
    assert b"window.__APAAS_SHELL__" in injected
    assert b"MutationObserver" not in injected
    assert b"querySelectorAll" not in injected
    assert b"<style>" not in injected
    assert b"!important" not in injected
    assert b"rewriteWorkspaceRelativeLink" not in injected
    assert b"/api/workspace/files/content?" not in injected

    prefixed = _inject_shell_config(
        b"<html><head></head><body></body></html>",
        12,
        "https://om-demo.dfy.definesys.cn",
        "/ai-builder",
    )
    assert b'"externalBasePath":"/ai-builder/api/code-runtime/12"' in prefixed
    assert b'closest(".markdown-view,.workspace-file-viewer-preview")' not in injected
    assert b'document.addEventListener("click"' not in injected
    assert b"window.location.assign" not in injected
    assert b"window.open(" not in injected


def test_code_runtime_shell_config_uses_script_safe_json():
    from app.routes.code_runtime import _inject_shell_config

    dangerous_origin = 'https://console.example.com/"quoted"</script><script>alert(1)</script>'
    injected = _inject_shell_config(
        b"<html><head></head><body></body></html>",
        12,
        dangerous_origin,
        '/ai-builder/"quoted"</script>',
    ).decode("utf-8")
    config_source = injected.split("window.__APAAS_SHELL__||{},", 1)[1].split(
        ");})();</script>",
        1,
    )[0]

    assert "</script>" not in config_source.lower()
    assert "\\u003c/script\\u003e" in config_source.lower()
    assert json.loads(config_source) == {
        "externalBasePath": '/ai-builder/"quoted"</script>/api/code-runtime/12',
        "webConsoleOrigin": dangerous_origin,
        "externalSessionRail": True,
        "hideHistory": True,
        "hideNewSession": True,
    }


@pytest.mark.asyncio
async def test_create_code_runtime_application_delegates_to_control_plane(
    db_session,
    monkeypatch,
):
    import app.routes.code_runtime as code_runtime_routes
    from app.config import settings
    from app.code_runtime.auth import store_control_plane_credentials
    from app.routes.code_runtime import CreateCodeApplicationRequest, create_code_runtime_application

    calls: list[dict] = []

    async def fake_create_code_application(**kwargs):
        calls.append(kwargs)
        return {
            "external_application_id": "code-app-new",
            "app_name": "销售线索评分助手",
            "app_code": "sales-lead-helper",
        }

    monkeypatch.setattr(code_runtime_routes, "create_code_application", fake_create_code_application)
    monkeypatch.setattr(settings, "auth_provider", "control_plane")
    monkeypatch.setattr(settings, "control_plane_binding_enabled", False)
    ctx = _ctx()
    store_control_plane_credentials(ctx.user, "user-token")
    ctx.user.coding_tenant_id = "default"

    result = await create_code_runtime_application(
        CreateCodeApplicationRequest(
            app_name="销售线索评分助手",
            app_code="sales-lead-helper",
            seed_project_id="90001",
        ),
        SimpleNamespace(headers={"authorization": "Bearer builder-token"}),
        ctx,
        db_session,
    )

    assert result["external_application_id"] == "code-app-new"
    assert calls == [{
        "app_name": "销售线索评分助手",
        "app_code": "sales-lead-helper",
        "seed_project_id": "90001",
        "authorization_header": "Bearer user-token",
        "delegated_context": ctx,
        "auth_provider": None,
    }]


@pytest.mark.asyncio
async def test_control_plane_request_refreshes_expired_user_token(
    db_session,
    monkeypatch,
):
    from jose import jwt

    import app.routes.code_runtime as code_runtime_routes
    from app.auth import get_password_hash
    from app.code_runtime.auth import (
        control_plane_access_token,
        store_control_plane_credentials,
    )
    from app.config import settings
    from app.models import User

    user = User(
        username="refresh-user",
        hashed_password=get_password_hash("unused"),
        account_source="control_plane",
        is_active=True,
    )
    expired = jwt.encode({"exp": 1}, "test", algorithm="HS256")
    store_control_plane_credentials(user, expired, "refresh-token")
    db_session.add(user)
    await db_session.flush()
    user.coding_tenant_id = "default"
    ctx = SimpleNamespace(user=user, apaas_tenant_id="apaas-tenant-1")

    async def fake_refresh(refresh_token):
        assert refresh_token == "refresh-token"
        return SimpleNamespace(
            access_token="fresh-access-token",
            refresh_token="fresh-refresh-token",
        )

    monkeypatch.setattr(settings, "auth_provider", "control_plane")
    monkeypatch.setattr(settings, "control_plane_binding_enabled", False)
    monkeypatch.setattr(code_runtime_routes, "refresh_control_plane_token", fake_refresh)

    authorization, provider = await code_runtime_routes._control_plane_request_auth(
        SimpleNamespace(headers={}),
        ctx,
        db_session,
    )

    assert authorization == "Bearer fresh-access-token"
    assert provider is None
    assert control_plane_access_token(user) == "fresh-access-token"


@pytest.mark.asyncio
async def test_open_local_code_runtime_session_does_not_require_control_plane_auth(
    db_session,
    monkeypatch,
):
    import app.routes.code_runtime as code_runtime_routes
    from app.routes.code_runtime import open_code_runtime_session

    session = AIChatSession(
        tenant_id=7,
        user_id=11,
        title="本地 Code",
        mode="code",
        status="active",
        external_application_id="local-code-smoke",
        external_app_name="本地 Code",
        external_app_code="local-code-smoke",
    )
    db_session.add(session)
    await db_session.flush()
    monkeypatch.setenv("DOLPHIN_CODE_BUILDER_URL", "http://127.0.0.1:61137/builder/")

    async def fail_if_control_plane_auth_is_requested(*_args, **_kwargs):
        raise AssertionError("local Code sessions must not request Control Plane auth")

    monkeypatch.setattr(
        code_runtime_routes,
        "_control_plane_request_auth",
        fail_if_control_plane_auth_is_requested,
    )

    result = await open_code_runtime_session(
        session.public_id,
        SimpleNamespace(headers={}),
        _ctx(),
        db_session,
    )

    assert result["external_application_id"] == "local-code-smoke"
    assert result["embed_url"].startswith(
        f"/api/code-runtime/{session.public_id}/builder/?"
    )


@pytest.mark.asyncio
async def test_code_runtime_proxy_aligns_current_requests_to_bound_runtime_session(monkeypatch):
    import httpx
    import app.routes.code_runtime as code_runtime_routes
    from app.routes.code_runtime import _ensure_runtime_current_session

    binding = CodeRuntimeBinding(
        session_id=14,
        runtime_base_url="http://runtime.local/shared",
        runtime_session_id="runtime-demo",
    )
    seen: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.method, request.url.path))
        assert request.method == "POST"
        assert request.url.path == "/shared/api/agent/sessions/runtime-demo/activate"
        return httpx.Response(200, json={"runtimeSessionId": "runtime-demo"})

    transport = httpx.MockTransport(handler)
    original = code_runtime_routes.httpx.AsyncClient
    monkeypatch.setattr(
        code_runtime_routes.httpx,
        "AsyncClient",
        lambda **kwargs: original(transport=transport, **kwargs),
    )

    await _ensure_runtime_current_session(binding, "api/agent/sessions/current/conversation")

    assert seen == [("POST", "/shared/api/agent/sessions/runtime-demo/activate")]


@pytest.mark.asyncio
async def test_code_runtime_proxy_recovers_when_bound_runtime_session_is_missing(monkeypatch):
    from fastapi import HTTPException

    import app.routes.code_runtime as code_runtime_routes
    from app.routes.code_runtime import _ensure_runtime_current_session

    binding = CodeRuntimeBinding(
        session_id=14,
        runtime_base_url="http://runtime.local/shared",
        runtime_session_id="runtime-stale",
    )
    calls: list[tuple[str, str]] = []

    async def fake_browser_request(
        _binding,
        method,
        path,
        *,
        request,
        session_id,
        json_body=None,
    ):
        calls.append((method, path))
        if method == "POST":
            raise HTTPException(status_code=404, detail="agent session not found")
        return {"runtimeSessionId": "runtime-current"}

    monkeypatch.setattr(
        code_runtime_routes,
        "_browser_runtime_json_request",
        fake_browser_request,
    )

    changed = await _ensure_runtime_current_session(
        binding,
        "api/agent/sessions/current",
        request=SimpleNamespace(),
        session_id="shell-public-id",
    )

    assert changed is True
    assert binding.runtime_session_id == "runtime-current"
    assert calls == [
        ("POST", "/api/agent/sessions/runtime-stale/activate"),
        ("GET", "/api/agent/sessions/current"),
    ]


@pytest.mark.asyncio
async def test_code_runtime_proxy_does_not_align_non_current_requests(monkeypatch):
    import httpx
    import app.routes.code_runtime as code_runtime_routes
    from app.routes.code_runtime import _ensure_runtime_current_session

    binding = CodeRuntimeBinding(
        session_id=14,
        runtime_base_url="http://runtime.local/shared",
        runtime_session_id="runtime-demo",
    )
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(500)

    transport = httpx.MockTransport(handler)
    original = code_runtime_routes.httpx.AsyncClient
    monkeypatch.setattr(
        code_runtime_routes.httpx,
        "AsyncClient",
        lambda **kwargs: original(transport=transport, **kwargs),
    )

    await _ensure_runtime_current_session(binding, "api/agent/sessions")

    assert calls == 0


@pytest.mark.asyncio
async def test_code_runtime_proxy_aligns_current_session_with_browser_runtime_cookie(monkeypatch):
    import app.routes.code_runtime as code_runtime_routes
    from starlette.datastructures import Headers
    from app.routes.code_runtime import _ensure_runtime_current_session

    binding = CodeRuntimeBinding(
        session_id=14,
        runtime_base_url="http://runtime.local/shared",
        runtime_session_id="runtime-demo",
    )
    request = SimpleNamespace(headers=Headers({
        "authorization": "Bearer builder-token",
        "cookie": "dolphin_code_runtime_14=proxy-token; apaas_sandbox_token=runtime-cookie",
    }))
    seen: dict = {}

    async def fake_browser_request(binding, method, path, *, request, session_id, json_body=None):
        seen.update({
            "method": method,
            "path": path,
            "request": request,
            "session_id": session_id,
        })
        return {"runtimeSessionId": "runtime-demo"}

    monkeypatch.setattr(code_runtime_routes, "_browser_runtime_json_request", fake_browser_request)

    await _ensure_runtime_current_session(
        binding,
        "api/agent/sessions/current/conversation",
        request=request,
        session_id=14,
    )

    assert seen["method"] == "POST"
    assert seen["path"] == "/api/agent/sessions/runtime-demo/activate"
    assert seen["request"] is request
    assert seen["session_id"] == 14


@pytest.mark.asyncio
async def test_create_code_session_from_app_creates_mode_code_session(db_session):
    from app.routes.code_runtime import CreateCodeSessionRequest, create_code_session_from_app

    db_session.add(Application(
        tenant_id=7,
        user_id=11,
        created_by=11,
        app_name="销售应用",
        app_code="sales",
        app_type="ai-code",
        status="completed",
    ))
    await db_session.commit()

    result = await create_code_session_from_app(
        CreateCodeSessionRequest(app_id=1),
        _ctx(),
        db_session,
    )

    assert result["mode"] == "code"
    assert result["app_id"] == 1
    assert result["title"] == "销售应用 Code"


@pytest.mark.asyncio
async def test_create_code_session_from_external_app_creates_mode_code_session_without_local_app(db_session):
    from app.routes.code_runtime import (
        CreateExternalCodeSessionRequest,
        create_code_session_from_external_app,
    )

    result = await create_code_session_from_external_app(
        CreateExternalCodeSessionRequest(
            external_application_id="code-app-1",
            app_name="客户门户",
            app_code="crm_portal",
        ),
        _ctx(),
        db_session,
    )

    assert result["mode"] == "code"
    assert str(UUID(result["public_id"])) == result["public_id"]
    assert result["app_id"] is None
    assert result["external_application_id"] == "code-app-1"
    assert result["external_app_name"] == "客户门户"
    assert result["external_app_code"] == "crm_portal"
    assert result["title"] == "客户门户 Code"


@pytest.mark.asyncio
async def test_create_code_session_from_external_app_reuses_existing_app_shell_session(db_session):
    from sqlalchemy import select
    from app.routes.code_runtime import (
        CreateExternalCodeSessionRequest,
        create_code_session_from_external_app,
    )

    first = await create_code_session_from_external_app(
        CreateExternalCodeSessionRequest(
            external_application_id="code-app-1",
            app_name="客户门户",
            app_code="crm_portal",
        ),
        _ctx(),
        db_session,
    )
    second = await create_code_session_from_external_app(
        CreateExternalCodeSessionRequest(
            external_application_id="code-app-1",
            app_name="客户门户",
            app_code="crm_portal",
        ),
        _ctx(),
        db_session,
    )

    rows = (
        await db_session.execute(
            select(AIChatSession).where(
                AIChatSession.mode == "code",
                AIChatSession.external_application_id == "code-app-1",
            )
        )
    ).scalars().all()
    assert second["id"] == first["id"]
    assert len(rows) == 1


@pytest.mark.asyncio
async def test_list_code_runtime_rail_history_includes_shell_session_without_binding(db_session):
    from app.routes.code_runtime import list_code_runtime_rail_history

    db_session.add(AIChatSession(
        tenant_id=7,
        user_id=11,
        title="CRM Code",
        mode="code",
        status="active",
        external_application_id="crm",
        external_app_name="CRM",
        external_app_code="crm",
    ))
    await db_session.commit()

    result = await list_code_runtime_rail_history(_request(), _ctx(), db_session)

    assert len(result["apps"]) == 1
    app = result["apps"][0]
    assert app["shell_session_id"] != "1"
    assert len(app["shell_session_id"]) == 36
    assert app == {
        "shell_session_id": app["shell_session_id"],
        "external_application_id": "crm",
        "app_name": "CRM",
        "app_code": "crm",
        "runtime_session_id": None,
        "sessions": [],
    }


@pytest.mark.asyncio
async def test_list_code_runtime_rail_history_excludes_builder_workspace_code_sessions(db_session):
    from app.routes.code_runtime import list_code_runtime_rail_history

    low_code_app = Application(
        tenant_id=7,
        user_id=11,
        created_by=11,
        app_name="类 JIRA 项目管理系统",
        app_code="jira_demo",
        app_type="low-code",
        status="completed",
    )
    db_session.add(low_code_app)
    await db_session.flush()
    db_session.add_all([
        AIChatSession(
            tenant_id=7,
            user_id=11,
            title="Sprint 燃尽图列表视图",
            mode="code",
            status="active",
            app_id=low_code_app.id,
            workspace_id="workspace-low-code",
        ),
        AIChatSession(
            tenant_id=7,
            user_id=11,
            title="CRM Code",
            mode="code",
            status="active",
            external_application_id="crm",
            external_app_name="CRM",
            external_app_code="crm",
        ),
    ])
    await db_session.commit()

    result = await list_code_runtime_rail_history(_request(), _ctx(), db_session)

    assert [app["app_name"] for app in result["apps"]] == ["CRM"]
    assert all(app["shell_session_id"] != 1 for app in result["apps"])


@pytest.mark.asyncio
async def test_create_code_session_from_app_rejects_low_code_app(db_session):
    from fastapi import HTTPException
    from app.routes.code_runtime import CreateCodeSessionRequest, create_code_session_from_app

    db_session.add(Application(
        tenant_id=7,
        user_id=11,
        created_by=11,
        app_name="低代码应用",
        app_code="lowcode",
        app_type="low-code",
        status="completed",
    ))
    await db_session.commit()

    with pytest.raises(HTTPException) as exc:
        await create_code_session_from_app(CreateCodeSessionRequest(app_id=1), _ctx(), db_session)

    assert exc.value.status_code == 400
    assert "Code" in str(exc.value.detail)


@pytest.mark.asyncio
async def test_create_code_session_from_app_rejects_cross_tenant_app(db_session):
    from fastapi import HTTPException
    from app.routes.code_runtime import CreateCodeSessionRequest, create_code_session_from_app

    db_session.add(Application(
        tenant_id=99,
        user_id=11,
        created_by=11,
        app_name="其它租户",
        app_code="other",
        status="completed",
    ))
    await db_session.commit()

    with pytest.raises(HTTPException) as exc:
        await create_code_session_from_app(CreateCodeSessionRequest(app_id=1), _ctx(), db_session)

    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_list_ai_chat_sessions_can_filter_code_mode(db_session):
    from app.routes.ai_chat import list_sessions

    db_session.add_all([
        AIChatSession(tenant_id=7, user_id=11, title="Builder", mode="chat", status="active"),
        AIChatSession(tenant_id=7, user_id=11, title="Code", mode="code", status="active", app_id=3),
    ])
    await db_session.commit()

    result = await list_sessions(_ctx(), db_session, mode="code")

    assert [s["title"] for s in result["sessions"]] == ["Code"]


@pytest.mark.asyncio
async def test_list_ai_chat_sessions_returns_external_code_app_fields(db_session):
    from app.routes.ai_chat import list_sessions

    db_session.add(AIChatSession(
        tenant_id=7,
        user_id=11,
        title="客户门户 Code",
        mode="code",
        status="active",
        external_application_id="code-app-1",
        external_app_name="客户门户",
        external_app_code="crm_portal",
    ))
    await db_session.commit()

    result = await list_sessions(_ctx(), db_session, mode="code")

    assert result["sessions"][0]["external_application_id"] == "code-app-1"
    assert result["sessions"][0]["external_app_name"] == "客户门户"
    assert result["sessions"][0]["external_app_code"] == "crm_portal"


@pytest.mark.asyncio
async def test_list_code_runtime_rail_history_returns_opened_app_agent_sessions(db_session, monkeypatch):
    import httpx
    import app.routes.code_runtime as code_runtime_routes
    from app.routes.code_runtime import list_code_runtime_rail_history

    db_session.add(AIChatSession(
        tenant_id=7,
        user_id=11,
        title="CRM Code",
        mode="code",
        status="active",
        external_application_id="crm",
        external_app_name="CRM",
        external_app_code="crm",
    ))
    db_session.add(AIChatSession(
        tenant_id=7,
        user_id=11,
        title="未打开 Code",
        mode="code",
        status="active",
        external_application_id="never-opened",
        external_app_name="未打开",
    ))
    await db_session.flush()
    db_session.add(CodeRuntimeBinding(
        tenant_id=7,
        user_id=11,
        session_id=1,
        external_application_id="crm",
        runtime_base_url="http://runtime.local/workspaces/crm",
        builder_url="http://runtime.local/workspaces/crm/builder",
        runtime_session_id="runtime-1",
        status="ready",
    ))
    await db_session.commit()

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert request.url.path == "/workspaces/crm/api/agent/sessions"
        return httpx.Response(200, json={
            "sessions": [
                {
                    "runtimeSessionId": "runtime-2",
                    "title": "修复登录问题",
                    "state": "waiting_input",
                    "createdAt": "2026-07-01T06:00:00Z",
                    "updatedAt": "2026-07-01T07:00:00Z",
                    "lastActiveAt": "2026-07-01T07:00:00Z",
                    "current": False,
                    "deletedAt": None,
                    "capabilityStale": False,
                    "codexSessionResumable": True,
                },
                {
                    "runtimeSessionId": "runtime-1",
                    "title": "需求梳理",
                    "state": "busy",
                    "createdAt": "2026-07-01T05:00:00Z",
                    "updatedAt": "2026-07-01T06:30:00Z",
                    "lastActiveAt": "2026-07-01T06:30:00Z",
                    "current": True,
                    "deletedAt": None,
                    "capabilityStale": False,
                    "codexSessionResumable": True,
                },
            ]
        })

    transport = httpx.MockTransport(handler)
    original = code_runtime_routes.httpx.AsyncClient
    monkeypatch.setattr(
        code_runtime_routes.httpx,
        "AsyncClient",
        lambda **kwargs: original(transport=transport, **kwargs),
    )

    result = await list_code_runtime_rail_history(_request(), _ctx(), db_session)

    apps_by_external_id = {app["external_application_id"]: app for app in result["apps"]}
    unopened_shell_id = apps_by_external_id["never-opened"]["shell_session_id"]
    assert str(UUID(unopened_shell_id)) == unopened_shell_id
    assert apps_by_external_id["never-opened"] == {
        "shell_session_id": unopened_shell_id,
        "external_application_id": "never-opened",
        "app_name": "未打开",
        "app_code": None,
        "runtime_session_id": None,
        "sessions": [],
    }
    crm_shell_id = apps_by_external_id["crm"]["shell_session_id"]
    assert str(UUID(crm_shell_id)) == crm_shell_id
    assert apps_by_external_id["crm"] == {
        "shell_session_id": crm_shell_id,
        "external_application_id": "crm",
        "app_name": "CRM",
        "app_code": "crm",
        "runtime_session_id": "runtime-1",
        "sessions": [
            {
                "runtimeSessionId": "runtime-2",
                "title": "修复登录问题",
                "state": "waiting_input",
                "createdAt": "2026-07-01T06:00:00Z",
                "updatedAt": "2026-07-01T07:00:00Z",
                "lastActiveAt": "2026-07-01T07:00:00Z",
                "current": False,
                "deletedAt": None,
                "capabilityStale": False,
                "codexSessionResumable": True,
            },
            {
                "runtimeSessionId": "runtime-1",
                "title": "需求梳理",
                "state": "busy",
                "createdAt": "2026-07-01T05:00:00Z",
                "updatedAt": "2026-07-01T06:30:00Z",
                "lastActiveAt": "2026-07-01T06:30:00Z",
                "current": True,
                "deletedAt": None,
                "capabilityStale": False,
                "codexSessionResumable": True,
            },
        ],
    }


@pytest.mark.asyncio
async def test_list_code_runtime_rail_history_filters_sessions_by_shell_scope(db_session, monkeypatch):
    import httpx
    import app.routes.code_runtime as code_runtime_routes
    from app.routes.code_runtime import list_code_runtime_rail_history

    db_session.add(AIChatSession(
        tenant_id=7,
        user_id=11,
        title="发布会 Demo Code",
        mode="code",
        status="active",
        external_application_id="demo-app",
        external_app_name="发布会 Demo",
        external_app_code="demo",
    ))
    await db_session.flush()
    db_session.add(CodeRuntimeBinding(
        tenant_id=7,
        user_id=11,
        session_id=1,
        external_application_id="demo-app",
        runtime_base_url="http://runtime.local/shared",
        builder_url="http://runtime.local/shared/builder",
        runtime_session_id="runtime-demo",
        status="ready",
    ))
    db_session.add(CodeRuntimeAgentSession(
        tenant_id=7,
        user_id=11,
        session_id=1,
        external_application_id="demo-app",
        runtime_session_id="runtime-demo",
    ))
    await db_session.commit()

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert request.url.path == "/shared/api/agent/sessions"
        return httpx.Response(200, json={
            "sessions": [
                {
                    "runtimeSessionId": "runtime-crm",
                    "title": "CRM 历史",
                    "state": "waiting_input",
                    "current": False,
                },
                {
                    "runtimeSessionId": "runtime-demo",
                    "title": "Demo 1：AI Native 应用设计",
                    "state": "waiting_input",
                    "current": False,
                },
            ]
        })

    transport = httpx.MockTransport(handler)
    original = code_runtime_routes.httpx.AsyncClient
    monkeypatch.setattr(
        code_runtime_routes.httpx,
        "AsyncClient",
        lambda **kwargs: original(transport=transport, **kwargs),
    )

    result = await list_code_runtime_rail_history(_request(), _ctx(), db_session)

    assert result["apps"][0]["external_application_id"] == "demo-app"
    assert [item["runtimeSessionId"] for item in result["apps"][0]["sessions"]] == ["runtime-demo"]
    assert result["apps"][0]["sessions"][0]["current"] is True


@pytest.mark.asyncio
async def test_list_code_runtime_rail_history_excludes_sessions_scoped_to_other_shells(db_session, monkeypatch):
    import httpx
    import app.routes.code_runtime as code_runtime_routes
    from app.routes.code_runtime import list_code_runtime_rail_history

    db_session.add_all([
        AIChatSession(
            tenant_id=7,
            user_id=11,
            title="CRM Code",
            mode="code",
            status="active",
            external_application_id="crm",
            external_app_name="CRM",
            external_app_code="crm",
        ),
        AIChatSession(
            tenant_id=7,
            user_id=11,
            title="发布会 Demo Code",
            mode="code",
            status="active",
            external_application_id="demo-app",
            external_app_name="发布会 Demo",
            external_app_code="demo",
        ),
    ])
    await db_session.flush()
    db_session.add_all([
        CodeRuntimeBinding(
            tenant_id=7,
            user_id=11,
            session_id=1,
            external_application_id="crm",
            runtime_base_url="http://runtime.local/shared",
            builder_url="http://runtime.local/shared/builder",
            runtime_session_id="runtime-crm",
            status="ready",
        ),
        CodeRuntimeBinding(
            tenant_id=7,
            user_id=11,
            session_id=2,
            external_application_id="demo-app",
            runtime_base_url="http://runtime.local/shared",
            builder_url="http://runtime.local/shared/builder",
            runtime_session_id="runtime-demo",
            status="ready",
        ),
        CodeRuntimeAgentSession(
            tenant_id=7,
            user_id=11,
            session_id=2,
            external_application_id="demo-app",
            runtime_session_id="runtime-demo",
        ),
    ])
    await db_session.commit()

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert request.url.path == "/shared/api/agent/sessions"
        return httpx.Response(200, json={
            "sessions": [
                {
                    "runtimeSessionId": "runtime-crm",
                    "title": "CRM 历史",
                    "state": "waiting_input",
                    "current": False,
                },
                {
                    "runtimeSessionId": "runtime-demo",
                    "title": "Demo 1：AI Native 应用设计",
                    "state": "waiting_input",
                    "current": False,
                },
            ]
        })

    transport = httpx.MockTransport(handler)
    original = code_runtime_routes.httpx.AsyncClient
    monkeypatch.setattr(
        code_runtime_routes.httpx,
        "AsyncClient",
        lambda **kwargs: original(transport=transport, **kwargs),
    )

    result = await list_code_runtime_rail_history(_request(), _ctx(), db_session)

    apps_by_external_id = {app["external_application_id"]: app for app in result["apps"]}
    assert [item["runtimeSessionId"] for item in apps_by_external_id["crm"]["sessions"]] == ["runtime-crm"]
    assert [item["runtimeSessionId"] for item in apps_by_external_id["demo-app"]["sessions"]] == ["runtime-demo"]


@pytest.mark.asyncio
async def test_list_code_runtime_rail_history_includes_current_empty_session_placeholder(db_session, monkeypatch):
    import httpx
    import app.routes.code_runtime as code_runtime_routes
    from app.routes.code_runtime import list_code_runtime_rail_history

    db_session.add(AIChatSession(
        tenant_id=7,
        user_id=11,
        title="CRM Code",
        mode="code",
        status="active",
        external_application_id="crm",
        external_app_name="CRM",
        external_app_code="crm",
    ))
    await db_session.flush()
    db_session.add(CodeRuntimeBinding(
        tenant_id=7,
        user_id=11,
        session_id=1,
        external_application_id="crm",
        runtime_base_url="http://runtime.local/workspaces/crm",
        builder_url="http://runtime.local/workspaces/crm/builder",
        runtime_session_id="runtime-new-empty",
        status="ready",
    ))
    await db_session.commit()

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        if request.url.path == "/workspaces/crm/api/agent/sessions/runtime-new-empty":
            return httpx.Response(200, json={
                "runtimeSessionId": "runtime-new-empty",
                "title": "",
                "summary": "",
                "state": "running",
                "createdAt": "2026-07-01T08:00:00Z",
                "updatedAt": "2026-07-01T08:00:00Z",
                "lastActiveAt": "2026-07-01T08:00:00Z",
                "current": True,
            })
        assert request.url.path == "/workspaces/crm/api/agent/sessions"
        return httpx.Response(200, json={
            "sessions": [
                {
                    "runtimeSessionId": "runtime-old",
                    "title": "已有对话",
                    "state": "waiting_input",
                    "createdAt": "2026-07-01T06:00:00Z",
                    "updatedAt": "2026-07-01T07:00:00Z",
                    "lastActiveAt": "2026-07-01T07:00:00Z",
                    "current": False,
                },
            ]
        })

    transport = httpx.MockTransport(handler)
    original = code_runtime_routes.httpx.AsyncClient
    monkeypatch.setattr(
        code_runtime_routes.httpx,
        "AsyncClient",
        lambda **kwargs: original(transport=transport, **kwargs),
    )

    result = await list_code_runtime_rail_history(_request(), _ctx(), db_session)

    assert result["apps"][0]["runtime_session_id"] == "runtime-new-empty"
    sessions = result["apps"][0]["sessions"]
    assert [s["runtimeSessionId"] for s in sessions] == ["runtime-new-empty", "runtime-old"]
    assert sessions[0]["current"] is True
    assert sessions[0]["title"] == "CRM Code"


@pytest.mark.asyncio
async def test_list_code_runtime_rail_history_uses_current_session_detail_when_list_filters_it(db_session, monkeypatch):
    import httpx
    import app.routes.code_runtime as code_runtime_routes
    from app.routes.code_runtime import list_code_runtime_rail_history

    db_session.add(AIChatSession(
        tenant_id=7,
        user_id=11,
        title="CRM Code",
        mode="code",
        status="active",
        external_application_id="crm",
        external_app_name="CRM",
        external_app_code="crm",
    ))
    await db_session.flush()
    db_session.add(CodeRuntimeBinding(
        tenant_id=7,
        user_id=11,
        session_id=1,
        external_application_id="crm",
        runtime_base_url="http://runtime.local/workspaces/crm",
        builder_url="http://runtime.local/workspaces/crm/builder",
        runtime_session_id="runtime-new-title",
        status="ready",
    ))
    await db_session.commit()

    paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        paths.append(request.url.path)
        if request.url.path == "/workspaces/crm/api/agent/sessions":
            return httpx.Response(200, json={
                "sessions": [
                    {
                        "runtimeSessionId": "runtime-old",
                        "title": "已有对话",
                        "state": "waiting_input",
                        "createdAt": "2026-07-01T06:00:00Z",
                        "updatedAt": "2026-07-01T07:00:00Z",
                        "lastActiveAt": "2026-07-01T07:00:00Z",
                        "current": False,
                    },
                ]
            })
        if request.url.path == "/workspaces/crm/api/agent/sessions/runtime-new-title":
            return httpx.Response(200, json={
                "runtimeSessionId": "runtime-new-title",
                "title": "你好，请输入XXX",
                "state": "waiting_input",
                "createdAt": "2026-07-01T08:00:00Z",
                "updatedAt": "2026-07-01T08:10:00Z",
                "lastActiveAt": "2026-07-01T08:10:00Z",
                "current": False,
                "deletedAt": None,
                "capabilityStale": False,
                "codexSessionResumable": True,
            })
        return httpx.Response(404, json={"error": "not found"})

    transport = httpx.MockTransport(handler)
    original = code_runtime_routes.httpx.AsyncClient
    monkeypatch.setattr(
        code_runtime_routes.httpx,
        "AsyncClient",
        lambda **kwargs: original(transport=transport, **kwargs),
    )

    result = await list_code_runtime_rail_history(_request(), _ctx(), db_session)

    assert paths == [
        "/workspaces/crm/api/agent/sessions",
        "/workspaces/crm/api/agent/sessions/runtime-new-title",
    ]
    sessions = result["apps"][0]["sessions"]
    assert [s["runtimeSessionId"] for s in sessions] == ["runtime-new-title", "runtime-old"]
    assert sessions[0]["title"] == "你好，请输入XXX"
    assert sessions[0]["current"] is True


@pytest.mark.asyncio
async def test_activate_code_runtime_agent_session_proxies_to_runtime_and_updates_binding(db_session, monkeypatch):
    import httpx
    import app.routes.code_runtime as code_runtime_routes
    from app.routes.code_runtime import activate_code_runtime_agent_session

    db_session.add(AIChatSession(
        tenant_id=7,
        user_id=11,
        title="CRM Code",
        mode="code",
        status="active",
        external_application_id="crm",
        external_app_name="CRM",
    ))
    await db_session.flush()
    db_session.add(CodeRuntimeBinding(
        tenant_id=7,
        user_id=11,
        session_id=1,
        external_application_id="crm",
        runtime_base_url="http://runtime.local/workspaces/crm",
        builder_url="http://runtime.local/workspaces/crm/builder",
        runtime_session_id="runtime-1",
        status="ready",
    ))
    await db_session.commit()

    seen: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.method, request.url.path))
        assert request.method == "POST"
        assert request.url.path == "/workspaces/crm/api/agent/sessions/runtime-2/activate"
        return httpx.Response(200, json={
            "runtimeSessionId": "runtime-2",
            "state": "waiting_input",
            "codexSessionResumable": True,
            "lastActiveAt": "2026-07-01T07:10:00Z",
        })

    transport = httpx.MockTransport(handler)
    original = code_runtime_routes.httpx.AsyncClient
    monkeypatch.setattr(
        code_runtime_routes.httpx,
        "AsyncClient",
        lambda **kwargs: original(transport=transport, **kwargs),
    )

    result = await activate_code_runtime_agent_session(
        1,
        "runtime-2",
        _request(),
        _ctx(),
        db_session,
    )

    assert seen == [("POST", "/workspaces/crm/api/agent/sessions/runtime-2/activate")]
    assert str(UUID(result["shell_session_id"])) == result["shell_session_id"]
    assert result["runtime_session_id"] == "runtime-2"
    assert result["session"]["runtimeSessionId"] == "runtime-2"
    binding = (await db_session.execute(
        select(CodeRuntimeBinding).where(CodeRuntimeBinding.session_id == 1)
    )).scalar_one()
    assert binding.runtime_session_id == "runtime-2"
    scoped = (await db_session.execute(
        select(CodeRuntimeAgentSession).where(
            CodeRuntimeAgentSession.session_id == 1,
            CodeRuntimeAgentSession.runtime_session_id == "runtime-2",
        )
    )).scalar_one()
    assert scoped.external_application_id == "crm"


@pytest.mark.asyncio
async def test_create_code_runtime_agent_session_proxies_to_runtime_and_updates_binding(db_session, monkeypatch):
    import httpx
    import app.routes.code_runtime as code_runtime_routes
    from app.routes.code_runtime import create_code_runtime_agent_session

    db_session.add(AIChatSession(
        tenant_id=7,
        user_id=11,
        title="CRM Code",
        mode="code",
        status="active",
        external_application_id="crm",
        external_app_name="CRM",
    ))
    await db_session.flush()
    db_session.add(CodeRuntimeBinding(
        tenant_id=7,
        user_id=11,
        session_id=1,
        external_application_id="crm",
        runtime_base_url="http://runtime.local/workspaces/crm",
        builder_url="http://runtime.local/workspaces/crm/builder",
        runtime_session_id="runtime-1",
        status="ready",
    ))
    await db_session.commit()

    seen: list[tuple[str, str, bytes]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.method, request.url.path, request.content))
        assert request.method == "POST"
        assert request.url.path == "/workspaces/crm/api/agent/sessions"
        return httpx.Response(200, json={
            "runtimeSessionId": "runtime-new",
            "state": "waiting_input",
            "codexSessionResumable": True,
            "lastActiveAt": "2026-07-01T08:10:00Z",
        })

    transport = httpx.MockTransport(handler)
    original = code_runtime_routes.httpx.AsyncClient
    monkeypatch.setattr(
        code_runtime_routes.httpx,
        "AsyncClient",
        lambda **kwargs: original(transport=transport, **kwargs),
    )

    result = await create_code_runtime_agent_session(1, _request(), _ctx(), db_session)

    assert seen == [("POST", "/workspaces/crm/api/agent/sessions", b"{}")]
    assert str(UUID(result["shell_session_id"])) == result["shell_session_id"]
    assert result["runtime_session_id"] == "runtime-new"
    assert result["session"]["runtimeSessionId"] == "runtime-new"
    binding = (await db_session.execute(
        select(CodeRuntimeBinding).where(CodeRuntimeBinding.session_id == 1)
    )).scalar_one()
    assert binding.runtime_session_id == "runtime-new"
    scoped = (await db_session.execute(
        select(CodeRuntimeAgentSession).where(
            CodeRuntimeAgentSession.session_id == 1,
            CodeRuntimeAgentSession.runtime_session_id == "runtime-new",
        )
    )).scalar_one()
    assert scoped.external_application_id == "crm"


@pytest.mark.asyncio
async def test_create_browser_authenticated_agent_session_forwards_runtime_cookie_and_updates_binding(
    db_session,
    monkeypatch,
):
    import app.routes.code_runtime as code_runtime_routes
    from starlette.datastructures import Headers
    from starlette.responses import Response
    from app.routes.code_runtime import create_browser_authenticated_agent_session

    db_session.add(AIChatSession(
        tenant_id=7,
        user_id=11,
        title="CRM Code",
        mode="code",
        status="active",
        external_application_id="crm",
        external_app_name="CRM",
    ))
    await db_session.flush()
    db_session.add(CodeRuntimeBinding(
        tenant_id=7,
        user_id=11,
        session_id=1,
        external_application_id="crm",
        runtime_base_url="http://runtime.local/workspaces/crm",
        builder_url="http://runtime.local/workspaces/crm/builder",
        status="ready",
    ))
    await db_session.commit()

    request = SimpleNamespace(headers=Headers({
        "authorization": "Bearer builder-token",
        "cookie": "dolphin_code_runtime_1=proxy-token; runtime_sid=sandbox-cookie",
    }))
    response = Response()
    seen: dict = {}

    async def fake_runtime_request(binding, method, path, *, request, session_id, json_body=None):
        seen.update({
            "binding": binding,
            "method": method,
            "path": path,
            "request": request,
            "session_id": session_id,
            "json_body": json_body,
        })
        return {"runtimeSessionId": "runtime-browser"}

    monkeypatch.setattr(code_runtime_routes, "_browser_runtime_json_request", fake_runtime_request)

    result = await create_browser_authenticated_agent_session(
        1,
        request,
        response,
        _ctx(),
        db_session,
    )

    assert seen["method"] == "POST"
    assert seen["path"] == "/api/agent/sessions"
    assert seen["session_id"] == 1
    assert seen["json_body"] == {}
    assert result["runtime_session_id"] == "runtime-browser"
    assert "dolphin_code_runtime_1=" in response.headers["set-cookie"]
    binding = (await db_session.execute(
        select(CodeRuntimeBinding).where(CodeRuntimeBinding.session_id == 1)
    )).scalar_one()
    assert binding.runtime_session_id == "runtime-browser"
    scoped = (await db_session.execute(
        select(CodeRuntimeAgentSession).where(
            CodeRuntimeAgentSession.session_id == 1,
            CodeRuntimeAgentSession.runtime_session_id == "runtime-browser",
        )
    )).scalar_one()
    assert scoped.external_application_id == "crm"
