from __future__ import annotations

import hashlib
import json
from types import SimpleNamespace
from uuid import UUID

import pytest
from sqlalchemy import select

from app.models import Application
from app.models.ai_chat import (
    AIChatSession,
    CodeRuntimeAgentSession,
    CodeRuntimeBinding,
    CodeRuntimeBrowserSession,
)


def _runtime_service_session_enc() -> str:
    from app.code_runtime.sandbox_auth import encrypt_runtime_cookie

    return encrypt_runtime_cookie("test-runtime-cookie")


def _ctx(user_id: int = 11, tenant_id: int = 7, role: str = "member"):
    return SimpleNamespace(user=SimpleNamespace(id=user_id), tenant_id=tenant_id, tenant_role=role)


def _request(headers: dict[str, str] | None = None):
    from starlette.datastructures import Headers

    return SimpleNamespace(headers=Headers(headers or {}))


def _proxy_request(
    session_id: str,
    *,
    cookie: str = "",
    query_string: bytes = b"",
    authorization: str = "",
    forwarded_prefix: str = "",
):
    from starlette.requests import Request

    headers = [(b"host", b"builder.test")]
    if cookie:
        headers.append((b"cookie", cookie.encode("latin-1")))
    if authorization:
        headers.append((b"authorization", authorization.encode("latin-1")))
    if forwarded_prefix:
        headers.append((b"x-forwarded-prefix", forwarded_prefix.encode("latin-1")))
    return Request({
        "type": "http",
        "method": "GET",
        "scheme": "https",
        "server": ("builder.test", 443),
        "client": ("127.0.0.1", 12345),
        "root_path": "",
        "path": f"/api/code-runtime/{session_id}/builder",
        "raw_path": f"/api/code-runtime/{session_id}/builder".encode("ascii"),
        "query_string": query_string,
        "headers": headers,
    })


async def _seed_browser_runtime(
    db_session,
    *,
    public_id: str = "11111111-1111-1111-1111-111111111111",
    browser_cookies: tuple[tuple[str, str], ...] = (("browser-a", "db-cookie-a"),),
    runtime_service_cookie: str | None = "service-cookie",
):
    from app.code_runtime.sandbox_auth import encrypt_runtime_cookie

    session = AIChatSession(
        public_id=public_id,
        tenant_id=7,
        user_id=11,
        title="CRM Code",
        mode="code",
        status="active",
        external_application_id="crm",
        external_app_name="CRM",
    )
    db_session.add(session)
    await db_session.flush()
    binding = CodeRuntimeBinding(
        tenant_id=7,
        user_id=11,
        session_id=session.id,
        external_application_id="crm",
        runtime_base_url="https://runtime.test/workspaces/crm",
        builder_url="https://runtime.test/workspaces/crm/builder",
        runtime_service_session_enc=(
            encrypt_runtime_cookie(runtime_service_cookie)
            if runtime_service_cookie is not None
            else None
        ),
        auth_generation=7,
        status="ready",
    )
    db_session.add(binding)
    await db_session.flush()
    rows = {}
    for generation, (browser_session_id, runtime_cookie) in enumerate(browser_cookies, start=3):
        row = CodeRuntimeBrowserSession(
            binding_id=binding.id,
            browser_session_id=browser_session_id,
            runtime_session_cookie_enc=encrypt_runtime_cookie(runtime_cookie),
            runtime_session_hash=hashlib.sha256(runtime_cookie.encode("utf-8")).hexdigest(),
            generation=generation,
        )
        db_session.add(row)
        rows[browser_session_id] = row
    await db_session.commit()
    return session, binding, rows


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
async def test_authorize_shell_request_requires_proxy_cookie_for_authenticated_builder_request(
    db_session,
):
    from fastapi import HTTPException
    from app.routes.code_runtime import _authorize_shell_request

    session, binding, _rows = await _seed_browser_runtime(db_session)
    request = _proxy_request(
        session.public_id,
        authorization="Bearer builder-token",
    )

    with pytest.raises(HTTPException) as exc_info:
        await _authorize_shell_request(
            request,
            session.public_id,
            db=db_session,
            binding=binding,
            legacy_session_id=session.id,
            ctx=_ctx(),
        )

    assert exc_info.value.status_code == 401


@pytest.mark.asyncio
async def test_authorize_shell_request_keeps_proxy_token_check_without_builder_auth(monkeypatch):
    import app.routes.code_runtime as code_runtime_routes
    from starlette.datastructures import Headers

    expected = SimpleNamespace(response=SimpleNamespace(status_code=307))

    async def fake_authorize_proxy_request(request, session_id, **kwargs):
        assert request.headers.get("authorization") is None
        assert session_id == 20
        assert kwargs["db"] == "db"
        assert kwargs["binding"] == "binding"
        return expected

    monkeypatch.setattr(
        code_runtime_routes,
        "_authorize_proxy_request",
        fake_authorize_proxy_request,
    )
    request = SimpleNamespace(headers=Headers({}))

    assert await code_runtime_routes._authorize_shell_request(
        request,
        20,
        db="db",
        binding="binding",
    ) is expected


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


def test_runtime_request_headers_strip_browser_auth_cookies_and_inject_server_cookie():
    from starlette.datastructures import Headers
    from app.routes.code_runtime import _runtime_request_headers

    request = SimpleNamespace(headers=Headers({
        "host": "127.0.0.1:8000",
        "cookie": (
            "dolphin_code_runtime_12=proxy-token; "
            "apaas_sandbox_token=browser-cookie; runtime_theme=dark"
        ),
        "accept": "text/event-stream",
    }))
    binding = CodeRuntimeBinding(
        session_id=12,
        runtime_base_url="https://runtime.example.com/workspaces/ws-1",
        builder_url="https://runtime.example.com/workspaces/ws-1/builder",
    )

    headers = _runtime_request_headers(
        request,
        12,
        binding,
        runtime_cookie="database-cookie",
    )

    assert headers["accept"] == "text/event-stream"
    assert headers["cookie"] == "runtime_theme=dark; apaas_sandbox_token=database-cookie"
    assert "dolphin_code_runtime_12" not in headers["cookie"]
    assert "browser-cookie" not in headers["cookie"]
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
async def test_browser_runtime_request_uses_server_runtime_cookie(monkeypatch):
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
        "cookie": "dolphin_code_runtime_12=proxy-token; apaas_sandbox_token=browser-cookie",
        "accept": "application/json",
    }))

    def handler(upstream: httpx.Request) -> httpx.Response:
        assert "authorization" not in upstream.headers
        assert upstream.headers["cookie"] == "apaas_sandbox_token=database-cookie"
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
        runtime_cookie="database-cookie",
    )

    assert result == {"sessions": []}


@pytest.mark.asyncio
async def test_browser_runtime_request_keeps_local_binding_without_runtime_cookie(monkeypatch):
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
        "cookie": "dolphin_code_runtime_12=proxy-token; apaas_sandbox_token=browser-cookie",
        "accept": "application/json",
    }))

    def handler(upstream: httpx.Request) -> httpx.Response:
        assert "authorization" not in upstream.headers
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
@pytest.mark.parametrize(
    ("incoming_runtime_cookie", "cookie_reissue_required"),
    [
        ("db-cookie-a", False),
        ("wrong-browser-cookie", True),
        ("", True),
    ],
)
async def test_proxy_uses_server_owned_browser_runtime_cookie(
    db_session,
    monkeypatch,
    incoming_runtime_cookie,
    cookie_reissue_required,
):
    import httpx
    import app.routes.code_runtime as code_runtime_routes
    from app.code_runtime.service import create_proxy_cookie_token
    from app.routes.code_runtime import proxy_code_runtime

    session, binding, rows = await _seed_browser_runtime(
        db_session,
        browser_cookies=(
            ("browser-a", "db-cookie-a"),
            ("browser-b", "db-cookie-b"),
        ),
    )
    proxy_token = create_proxy_cookie_token(
        session_id=session.public_id,
        user_id=11,
        tenant_id=7,
        browser_session_id="browser-a",
    )
    cookies = [f"dolphin_code_runtime_{session.public_id}={proxy_token}"]
    if incoming_runtime_cookie:
        cookies.append(f"apaas_sandbox_token={incoming_runtime_cookie}")
    request = _proxy_request(session.public_id, cookie="; ".join(cookies))
    upstream_cookies: list[str] = []

    def handler(upstream: httpx.Request) -> httpx.Response:
        upstream_cookies.append(upstream.headers["cookie"])
        return httpx.Response(200, content=b"export default true", headers={
            "content-type": "application/javascript",
        })

    async def unexpected_open(*_args, **_kwargs):
        raise AssertionError("cookie recovery must not call workspace/open")

    transport = httpx.MockTransport(handler)
    original = code_runtime_routes.httpx.AsyncClient
    monkeypatch.setattr(
        code_runtime_routes.httpx,
        "AsyncClient",
        lambda **kwargs: original(transport=transport, **kwargs),
    )
    monkeypatch.setattr(code_runtime_routes, "open_code_session", unexpected_open)

    response = await proxy_code_runtime(
        session.public_id,
        "src/main.ts",
        request,
        db_session,
    )

    assert upstream_cookies == ["apaas_sandbox_token=db-cookie-a"]
    set_cookies = response.headers.getlist("set-cookie")
    assert any("apaas_sandbox_token=db-cookie-a" in value for value in set_cookies) is (
        cookie_reissue_required
    )
    assert rows["browser-a"].generation == 3
    assert rows["browser-b"].generation == 4
    assert binding.auth_generation == 7


@pytest.mark.asyncio
async def test_streaming_proxy_rewrites_runtime_cookie_and_reissues_database_cookie(
    db_session,
    monkeypatch,
):
    import httpx
    import app.routes.code_runtime as code_runtime_routes
    from app.code_runtime.service import create_proxy_cookie_token
    from app.routes.code_runtime import proxy_code_runtime

    session, _binding, _rows = await _seed_browser_runtime(db_session)
    proxy_token = create_proxy_cookie_token(
        session_id=session.public_id,
        user_id=11,
        tenant_id=7,
        browser_session_id="browser-a",
    )
    request = _proxy_request(
        session.public_id,
        cookie=(
            f"dolphin_code_runtime_{session.public_id}={proxy_token}; "
            "apaas_sandbox_token=wrong-cookie"
        ),
        forwarded_prefix="/ai-builder",
    )

    def handler(upstream: httpx.Request) -> httpx.Response:
        assert upstream.headers["cookie"] == "apaas_sandbox_token=db-cookie-a"
        return httpx.Response(
            200,
            content=b"ok",
            headers=[
                ("content-type", "text/plain"),
                ("set-cookie", "apaas_sandbox_token=runtime-cookie; Path=/; HttpOnly"),
            ],
        )

    transport = httpx.MockTransport(handler)
    original = code_runtime_routes.httpx.AsyncClient
    monkeypatch.setattr(
        code_runtime_routes.httpx,
        "AsyncClient",
        lambda **kwargs: original(transport=transport, **kwargs),
    )

    response = await proxy_code_runtime(
        session.public_id,
        "api/readyz",
        request,
        db_session,
    )

    set_cookies = response.headers.getlist("set-cookie")
    assert any(
        "apaas_sandbox_token=runtime-cookie" in value
        and "Path=/ai-builder/api/code-runtime/" in value
        for value in set_cookies
    )
    assert any(
        "apaas_sandbox_token=db-cookie-a" in value
        and "Path=/ai-builder/api/code-runtime/" in value
        for value in set_cookies
    )
    await response.background()


@pytest.mark.asyncio
async def test_dolphin_token_redirect_sets_proxy_and_database_runtime_cookies(
    db_session,
):
    from app.code_runtime.service import create_embed_token, validate_proxy_cookie_token
    from app.routes.code_runtime import proxy_code_runtime

    session, _binding, _rows = await _seed_browser_runtime(db_session)
    embed_token = create_embed_token(
        session_id=session.public_id,
        user_id=11,
        tenant_id=7,
        browser_session_id="browser-a",
    )
    request = _proxy_request(
        session.public_id,
        query_string=f"dolphin_token={embed_token}&tab=spec".encode("ascii"),
    )

    response = await proxy_code_runtime(
        session.public_id,
        "builder",
        request,
        db_session,
    )

    assert response.status_code == 307
    set_cookies = response.headers.getlist("set-cookie")
    proxy_cookie = next(
        value for value in set_cookies
        if value.startswith(f"dolphin_code_runtime_{session.public_id}=")
    )
    proxy_token = proxy_cookie.split("=", 1)[1].split(";", 1)[0]
    payload = validate_proxy_cookie_token(proxy_token, session_id=session.public_id)
    assert payload["bsid"] == "browser-a"
    assert any("apaas_sandbox_token=db-cookie-a" in value for value in set_cookies)


@pytest.mark.asyncio
async def test_server_runtime_request_uses_encrypted_runtime_service_cookie(monkeypatch):
    import httpx
    import app.routes.code_runtime as code_runtime_routes
    from app.code_runtime.sandbox_auth import encrypt_runtime_cookie
    from app.routes.code_runtime import _runtime_json_request

    binding = CodeRuntimeBinding(
        session_id=12,
        runtime_base_url="https://runtime.example.com/workspaces/ws-1",
        builder_url="https://runtime.example.com/workspaces/ws-1/builder?tab=spec",
        runtime_service_session_enc=encrypt_runtime_cookie("runtime-cookie-secret"),
    )

    def handler(upstream: httpx.Request) -> httpx.Response:
        assert "authorization" not in upstream.headers
        assert upstream.headers["cookie"] == "apaas_sandbox_token=runtime-cookie-secret"
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
async def test_server_runtime_request_without_service_cookie_forwards_local_json_request(
    monkeypatch,
):
    import httpx
    import app.routes.code_runtime as code_runtime_routes
    from app.routes.code_runtime import _runtime_json_request

    binding = CodeRuntimeBinding(
        session_id=12,
        runtime_base_url="http://127.0.0.1:8100/workspaces/ws-1",
        builder_url="http://127.0.0.1:8100/workspaces/ws-1/builder",
    )

    def handler(upstream: httpx.Request) -> httpx.Response:
        assert "cookie" not in upstream.headers
        assert json.loads(upstream.content) == {"prompt": "hello"}
        return httpx.Response(200, json={"ok": True})

    transport = httpx.MockTransport(handler)
    original = code_runtime_routes.httpx.AsyncClient
    monkeypatch.setattr(
        code_runtime_routes.httpx,
        "AsyncClient",
        lambda **kwargs: original(transport=transport, **kwargs),
    )

    result = await _runtime_json_request(
        binding,
        "POST",
        "/api/agent/sessions",
        json_body={"prompt": "hello"},
    )

    assert result == {"ok": True}


@pytest.mark.asyncio
async def test_server_runtime_request_refreshes_binding_once_after_stable_runtime_unauthorized(monkeypatch):
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
            raise HTTPException(
                status_code=401,
                detail="Runtime session expired",
                headers={"X-APAAS-Sandbox-Auth-Error": "sandbox_session_expired"},
            )
        return {"sessions": []}

    async def fake_refresh(session_arg, binding_arg, request_arg, ctx_arg, db_arg):
        assert session_arg is session
        assert binding_arg is binding
        binding_arg.runtime_service_session_enc = "enc:v1:fresh-cookie"

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
        "https://runtime.example.com/workspaces/ws-1/builder?token=stale-token",
    ]


@pytest.mark.asyncio
async def test_server_runtime_request_does_not_refresh_for_unknown_unauthorized(monkeypatch):
    from fastapi import HTTPException
    import app.routes.code_runtime as code_runtime_routes

    session = SimpleNamespace(id=12, app_id=None, external_application_id="code-app-1")
    binding = CodeRuntimeBinding(
        session_id=12,
        runtime_base_url="https://runtime.example.com/workspaces/ws-1",
        builder_url="https://runtime.example.com/workspaces/ws-1/builder",
    )
    refreshes = 0

    async def fake_runtime_request(*_args, **_kwargs):
        raise HTTPException(status_code=401, detail="unknown unauthorized")

    async def fake_refresh(*_args, **_kwargs):
        nonlocal refreshes
        refreshes += 1

    monkeypatch.setattr(code_runtime_routes, "_runtime_json_request", fake_runtime_request)
    monkeypatch.setattr(code_runtime_routes, "_refresh_runtime_binding", fake_refresh)

    with pytest.raises(HTTPException) as exc_info:
        await code_runtime_routes._runtime_json_request_for_session(
            session,
            binding,
            "GET",
            "/api/agent/sessions",
            request=_request(),
            ctx=_ctx(),
            db=SimpleNamespace(),
        )

    assert exc_info.value.status_code == 401
    assert refreshes == 0


@pytest.mark.asyncio
async def test_shell_agent_sessions_renews_only_expired_owned_proxy_cookie(
    db_session,
    monkeypatch,
):
    from starlette.datastructures import Headers
    from starlette.responses import Response

    import app.routes.code_runtime as code_runtime_routes
    from app.code_runtime.service import create_proxy_cookie_token, validate_proxy_cookie_token
    from app.routes.code_runtime import list_browser_authenticated_agent_sessions

    session, binding, _rows = await _seed_browser_runtime(db_session)
    expired_proxy_cookie = create_proxy_cookie_token(
        session_id=session.public_id,
        user_id=11,
        tenant_id=7,
        browser_session_id="browser-a",
        minutes=-1,
    )

    async def fake_browser_request(_binding, method, path, **kwargs):
        assert method == "GET"
        assert path == "/api/agent/sessions"
        assert kwargs["runtime_cookie"] == "db-cookie-a"
        return {"sessions": []}

    async def fake_other_scoped_ids(_db, session_id):
        assert session_id == session.id
        return set()

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
        cookies={f"dolphin_code_runtime_{session.public_id}": expired_proxy_cookie},
    )
    response = Response()

    result = await list_browser_authenticated_agent_sessions(
        session_id=session.public_id,
        request=request,
        response=response,
        ctx=_ctx(),
        db=db_session,
    )

    assert result == {"sessions": []}
    set_cookie = response.headers["set-cookie"]
    assert f"dolphin_code_runtime_{session.public_id}=" in set_cookie
    assert "Max-Age=43200" in set_cookie
    assert f"Path=/ai-builder/api/code-runtime/{session.public_id}" in set_cookie
    proxy_token = set_cookie.split(
        f"dolphin_code_runtime_{session.public_id}=",
        1,
    )[1].split(";", 1)[0]
    payload = validate_proxy_cookie_token(proxy_token, session_id=session.public_id)
    assert payload["sub"] == "11"
    assert payload["tid"] == 7
    assert payload["bsid"] == "browser-a"


@pytest.mark.asyncio
@pytest.mark.parametrize("cookie_kind", ["missing", "forged", "other-browser"])
async def test_shell_bearer_cannot_select_browser_row_without_owned_proxy_cookie(
    db_session,
    cookie_kind,
):
    from fastapi import HTTPException
    from app.code_runtime.service import create_proxy_cookie_token
    from app.routes.code_runtime import _authorize_shell_request

    session, binding, _rows = await _seed_browser_runtime(
        db_session,
        browser_cookies=(
            ("browser-a", "db-cookie-a"),
            ("browser-b", "db-cookie-b"),
        ),
    )
    if cookie_kind == "missing":
        proxy_cookie = ""
    elif cookie_kind == "forged":
        proxy_cookie = "forged-token"
    else:
        proxy_cookie = create_proxy_cookie_token(
            session_id=session.public_id,
            user_id=99,
            tenant_id=7,
            browser_session_id="browser-b",
        )
    request = _proxy_request(
        session.public_id,
        cookie=(
            f"dolphin_code_runtime_{session.public_id}={proxy_cookie}"
            if proxy_cookie
            else ""
        ),
        authorization="Bearer builder-token",
    )

    with pytest.raises(HTTPException) as exc_info:
        await _authorize_shell_request(
            request,
            session.public_id,
            db=db_session,
            binding=binding,
            legacy_session_id=session.id,
            ctx=_ctx(),
        )

    assert exc_info.value.status_code == 401


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
async def test_open_code_runtime_session_rolls_back_and_does_not_return_canary_on_commit_failure(
    monkeypatch,
):
    from fastapi import HTTPException

    import app.routes.code_runtime as code_runtime_routes
    from app.routes.code_runtime import open_code_runtime_session

    session = SimpleNamespace(
        app_id=None,
        external_application_id="local-code-smoke",
    )
    db = SimpleNamespace()
    rollbacks = 0

    async def fake_resolve(*_args, **_kwargs):
        return session

    async def fake_open_code_session(*_args, **_kwargs):
        return {"canary": "must-not-return"}

    async def fail_commit():
        raise RuntimeError("commit failed")

    async def fake_rollback():
        nonlocal rollbacks
        rollbacks += 1

    db.commit = fail_commit
    db.rollback = fake_rollback
    monkeypatch.setattr(code_runtime_routes, "resolve_code_session", fake_resolve)
    monkeypatch.setattr(code_runtime_routes, "open_code_session", fake_open_code_session)

    with pytest.raises(HTTPException) as exc_info:
        await open_code_runtime_session(
            "session-1",
            _request(),
            _ctx(),
            db,
        )

    assert exc_info.value.status_code == 500
    assert rollbacks == 1
    assert "canary" not in str(exc_info.value.detail)


@pytest.mark.asyncio
async def test_code_runtime_proxy_aligns_current_requests_to_bound_runtime_session(monkeypatch):
    import httpx
    import app.routes.code_runtime as code_runtime_routes
    from app.routes.code_runtime import _ensure_runtime_current_session

    binding = CodeRuntimeBinding(
        session_id=14,
        runtime_base_url="http://runtime.local/shared",
        runtime_session_id="runtime-demo",
        runtime_service_session_enc=_runtime_service_session_enc(),
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
        runtime_service_session_enc=_runtime_service_session_enc(),
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
        runtime_service_session_enc=_runtime_service_session_enc(),
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
        runtime_service_session_enc=_runtime_service_session_enc(),
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
        runtime_service_session_enc=_runtime_service_session_enc(),
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
        runtime_service_session_enc=_runtime_service_session_enc(),
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

    from app.code_runtime.service import create_proxy_cookie_token

    session, _binding, _rows = await _seed_browser_runtime(db_session)
    proxy_token = create_proxy_cookie_token(
        session_id=session.public_id,
        user_id=11,
        tenant_id=7,
        browser_session_id="browser-a",
    )

    request = SimpleNamespace(headers=Headers({
        "authorization": "Bearer builder-token",
        "cookie": (
            f"dolphin_code_runtime_{session.public_id}={proxy_token}; "
            "apaas_sandbox_token=browser-cookie"
        ),
    }))
    response = Response()
    seen: dict = {}

    async def fake_runtime_request(
        binding,
        method,
        path,
        *,
        request,
        session_id,
        json_body=None,
        runtime_cookie=None,
    ):
        seen.update({
            "binding": binding,
            "method": method,
            "path": path,
            "request": request,
            "session_id": session_id,
            "json_body": json_body,
            "runtime_cookie": runtime_cookie,
        })
        return {"runtimeSessionId": "runtime-browser"}

    monkeypatch.setattr(code_runtime_routes, "_browser_runtime_json_request", fake_runtime_request)

    result = await create_browser_authenticated_agent_session(
        session.public_id,
        request,
        response,
        _ctx(),
        db_session,
    )

    assert seen["method"] == "POST"
    assert seen["path"] == "/api/agent/sessions"
    assert seen["session_id"] == session.public_id
    assert seen["json_body"] == {}
    assert seen["runtime_cookie"] == "db-cookie-a"
    assert result["runtime_session_id"] == "runtime-browser"
    assert "set-cookie" not in response.headers
    binding = (await db_session.execute(
        select(CodeRuntimeBinding).where(CodeRuntimeBinding.session_id == session.id)
    )).scalar_one()
    assert binding.runtime_session_id == "runtime-browser"
    scoped = (await db_session.execute(
        select(CodeRuntimeAgentSession).where(
            CodeRuntimeAgentSession.session_id == session.id,
            CodeRuntimeAgentSession.runtime_session_id == "runtime-browser",
        )
    )).scalar_one()
    assert scoped.external_application_id == "crm"
