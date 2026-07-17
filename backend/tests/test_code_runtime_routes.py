from __future__ import annotations

import asyncio
import hashlib
import json
from types import SimpleNamespace
from uuid import UUID

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.models import Application
from app.models.ai_chat import (
    AIChatSession,
    CodeRuntimeAgentSession,
    CodeRuntimeBinding,
    CodeRuntimeBrowserSession,
)


async def _renewal_session_factory(tmp_path):
    from app.database import Base

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'renewal.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return engine, async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


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
    method: str = "GET",
    body: bytes = b"",
    path: str = "builder",
):
    from starlette.requests import Request

    headers = [(b"host", b"builder.test")]
    if cookie:
        headers.append((b"cookie", cookie.encode("latin-1")))
    if authorization:
        headers.append((b"authorization", authorization.encode("latin-1")))
    if forwarded_prefix:
        headers.append((b"x-forwarded-prefix", forwarded_prefix.encode("latin-1")))
    sent = False

    async def receive():
        nonlocal sent
        if sent:
            return {"type": "http.request", "body": b"", "more_body": False}
        sent = True
        return {"type": "http.request", "body": body, "more_body": False}

    request_path = f"/api/code-runtime/{session_id}/{path.lstrip('/')}"
    return Request({
        "type": "http",
        "method": method,
        "scheme": "https",
        "server": ("builder.test", 443),
        "client": ("127.0.0.1", 12345),
        "root_path": "",
        "path": request_path,
        "raw_path": request_path.encode("ascii"),
        "query_string": query_string,
        "headers": headers,
    }, receive)


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
async def test_server_runtime_write_does_not_replay_when_refresh_commit_fails(monkeypatch):
    from fastapi import HTTPException
    import app.routes.code_runtime as code_runtime_routes

    session = SimpleNamespace(id=12, app_id=None, external_application_id="code-app-1")
    binding = CodeRuntimeBinding(
        session_id=12,
        runtime_base_url="https://runtime.example.com/workspaces/ws-1",
        builder_url="https://runtime.example.com/workspaces/ws-1/builder",
    )
    runtime_calls = 0

    async def fake_runtime_request(*_args, **_kwargs):
        nonlocal runtime_calls
        runtime_calls += 1
        raise HTTPException(
            status_code=401,
            detail="Runtime session expired",
            headers={"X-APAAS-Sandbox-Auth-Error": "sandbox_session_expired"},
        )

    async def fake_open_code_session(**_kwargs):
        binding.runtime_service_session_enc = "enc:v1:fresh-cookie"

    class FailingCommitDb:
        async def commit(self):
            raise RuntimeError("commit failed")

    async def fake_control_plane_request_auth(*_args, **_kwargs):
        return "Bearer token", "control-plane"

    monkeypatch.setattr(code_runtime_routes, "_runtime_json_request", fake_runtime_request)
    monkeypatch.setattr(code_runtime_routes, "open_code_session", fake_open_code_session)
    monkeypatch.setattr(
        code_runtime_routes,
        "_control_plane_request_auth",
        fake_control_plane_request_auth,
    )

    with pytest.raises(RuntimeError, match="commit failed"):
        await code_runtime_routes._runtime_json_request_for_session(
            session,
            binding,
            "POST",
            "/api/agent/sessions",
            request=_request(),
            ctx=_ctx(),
            db=FailingCommitDb(),
            json_body={},
        )

    assert runtime_calls == 1


@pytest.mark.asyncio
async def test_browser_runtime_json_request_renews_once_from_stable_header(monkeypatch):
    from dataclasses import replace
    from fastapi import HTTPException
    import app.routes.code_runtime as code_runtime_routes

    binding = CodeRuntimeBinding(
        id=42,
        session_id=12,
        runtime_base_url="https://runtime.example.com/workspaces/ws-1",
        builder_url="https://runtime.example.com/workspaces/ws-1/builder",
    )
    session = SimpleNamespace(id=12, user_id=11)
    authorization = code_runtime_routes.ProxyAuthorization(
        browser_session_id="browser-a",
        runtime_cookie="old-cookie",
        runtime_cookie_hash="old-hash",
        observed_generation=1,
    )
    calls: list[str] = []

    async def fake_browser_request(*_args, runtime_cookie=None, **_kwargs):
        calls.append(str(runtime_cookie))
        if len(calls) == 1:
            raise HTTPException(
                status_code=401,
                detail="Runtime session expired",
                headers={"X-APAAS-Sandbox-Auth-Error": "sandbox_session_expired"},
            )
        return {"sessions": []}

    async def fake_renew(*_args, **_kwargs):
        return replace(
            authorization,
            runtime_cookie="new-cookie",
            runtime_cookie_hash="new-hash",
            observed_generation=2,
        )

    monkeypatch.setattr(code_runtime_routes, "_browser_runtime_json_request", fake_browser_request)
    monkeypatch.setattr(code_runtime_routes, "_renew_proxy_runtime_authorization", fake_renew)

    payload, renewed = await code_runtime_routes._browser_runtime_json_request_for_session(
        session,
        binding,
        authorization,
        "GET",
        "/api/agent/sessions",
        request=_request(),
        session_id="shell-12",
        db=SimpleNamespace(),
    )

    assert payload == {"sessions": []}
    assert renewed.runtime_cookie == "new-cookie"
    assert calls == ["old-cookie", "new-cookie"]


def test_proxy_route_registers_head_method():
    import app.routes.code_runtime as code_runtime_routes

    route = next(
        item
        for item in code_runtime_routes.proxy_router.routes
        if getattr(item, "endpoint", None) is code_runtime_routes.proxy_code_runtime
    )

    assert "HEAD" in route.methods


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
    await db_session.commit()
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
async def test_open_code_runtime_session_serializes_same_session_first_open(monkeypatch):
    import app.routes.code_runtime as code_runtime_routes
    from app.routes.code_runtime import open_code_runtime_session

    session = SimpleNamespace(
        app_id=None,
        external_application_id="app-e2e",
    )
    active = 0
    max_active = 0

    async def fake_resolve(*_args, **_kwargs):
        return session

    async def fake_auth(*_args, **_kwargs):
        return "Bearer access", None

    async def fake_open_code_session(*_args, **_kwargs):
        nonlocal active, max_active
        active += 1
        max_active = max(max_active, active)
        await asyncio.sleep(0.02)
        active -= 1
        return {"ok": True}

    class FakeDB:
        async def commit(self):
            return None

        async def rollback(self):
            return None

    monkeypatch.setattr(code_runtime_routes, "resolve_code_session", fake_resolve)
    monkeypatch.setattr(code_runtime_routes, "_control_plane_request_auth", fake_auth)
    monkeypatch.setattr(code_runtime_routes, "open_code_session", fake_open_code_session)

    results = await asyncio.gather(
        open_code_runtime_session("same-session", _request(), _ctx(), FakeDB()),
        open_code_runtime_session("same-session", _request(), _ctx(), FakeDB()),
    )

    assert results == [{"ok": True}, {"ok": True}]
    assert max_active == 1


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


@pytest.mark.asyncio
async def test_concurrent_browser_renewal_singleflight_joins_new_generation(
    tmp_path,
):
    from app.code_runtime.sandbox_auth import (
        RuntimeBootstrap,
        renew_browser_runtime_session,
    )
    from app.code_runtime.sandbox_metrics import SandboxAuthMetricsRegistry

    engine, Session = await _renewal_session_factory(tmp_path)
    metrics = SandboxAuthMetricsRegistry()
    async with Session() as db:
        session, binding, rows = await _seed_browser_runtime(db)
        binding_id = binding.id
        observed_generation = rows["browser-a"].generation

    open_started = asyncio.Event()
    release_open = asyncio.Event()
    open_calls = 0
    bootstrap_calls = 0

    async def authorization_provider(*, force_refresh=False, rejected_access_token=None):
        assert force_refresh is False
        assert rejected_access_token is None
        return "Bearer user-token"

    async def workspace_open(authorization):
        nonlocal open_calls
        assert authorization == "Bearer user-token"
        open_calls += 1
        open_started.set()
        await asyncio.wait_for(release_open.wait(), timeout=5)
        return {
            "specReviewUrl": "https://runtime.test/workspaces/crm/builder?token=launch",
            "workspaceId": "workspace-1",
            "sandboxInstanceId": "sandbox-1",
        }

    async def bootstrap(builder_url):
        nonlocal bootstrap_calls
        assert builder_url.endswith("?token=launch")
        bootstrap_calls += 1
        return RuntimeBootstrap(
            clean_builder_url="https://runtime.test/workspaces/crm/builder",
            runtime_base_url="https://runtime.test/workspaces/crm",
            runtime_cookie="renewed-cookie",
            runtime_cookie_hash=hashlib.sha256(b"renewed-cookie").hexdigest(),
            expires_at=None,
        )

    tasks = [
        asyncio.create_task(renew_browser_runtime_session(
            binding_id=binding_id,
            browser_session_id="browser-a",
            observed_generation=observed_generation,
            session_factory=Session,
            authorization_provider=authorization_provider,
            workspace_open=workspace_open,
            bootstrap=bootstrap,
            metrics=metrics,
        ))
        for _ in range(6)
    ]
    await asyncio.wait_for(open_started.wait(), timeout=5)
    await asyncio.sleep(0)
    release_open.set()
    results = await asyncio.wait_for(asyncio.gather(*tasks), timeout=30)

    assert open_calls == 1
    assert bootstrap_calls == 1
    assert {result.generation for result in results} == {8}
    assert sum(result.joined for result in results) == 5
    snapshot = metrics.snapshot()
    assert snapshot[
        'sandbox_auth_renew_total{reason="sandbox_session_expired",result="success"}'
    ] == 1
    assert snapshot[
        'sandbox_auth_renew_total{reason="joined",result="success"}'
    ] == 5
    assert snapshot["sandbox_auth_singleflight_join_total"] == 5
    async with Session() as db:
        row = (await db.execute(select(CodeRuntimeBrowserSession))).scalar_one()
        assert row.generation == 8
    await engine.dispose()


@pytest.mark.asyncio
async def test_two_browser_forced_control_plane_refresh_is_singleflight(
    tmp_path,
    monkeypatch,
):
    from jose import jwt

    import app.routes.code_runtime as code_runtime_routes
    from app.auth import get_password_hash
    from app.code_runtime.auth import store_control_plane_credentials
    from app.models import User

    engine, Session = await _renewal_session_factory(tmp_path)
    expired = jwt.encode({"exp": 1}, "test", algorithm="HS256")
    async with Session() as db:
        user = User(
            username="two-browser-refresh",
            hashed_password=get_password_hash("unused"),
            account_source="control_plane",
            is_active=True,
        )
        store_control_plane_credentials(user, expired, "refresh-token")
        db.add(user)
        await db.commit()
        user_id = user.id

    refresh_started = asyncio.Event()
    release_refresh = asyncio.Event()
    refresh_calls = 0

    async def fake_refresh(refresh_token):
        nonlocal refresh_calls
        assert refresh_token == "refresh-token"
        refresh_calls += 1
        refresh_started.set()
        await asyncio.wait_for(release_refresh.wait(), timeout=5)
        return SimpleNamespace(
            access_token="fresh-access-token",
            refresh_token="fresh-refresh-token",
        )

    monkeypatch.setattr(code_runtime_routes, "refresh_control_plane_token", fake_refresh)
    calls = [
        asyncio.create_task(code_runtime_routes._locked_control_plane_user_authorization(
            user_id=user_id,
            session_factory=Session,
            force_refresh=True,
            rejected_access_token=expired,
        ))
        for _browser in ("browser-a", "browser-b")
    ]
    await asyncio.wait_for(refresh_started.wait(), timeout=5)
    release_refresh.set()
    authorizations = await asyncio.wait_for(asyncio.gather(*calls), timeout=30)

    assert authorizations == ["Bearer fresh-access-token"] * 2
    assert refresh_calls == 1
    await engine.dispose()


@pytest.mark.asyncio
async def test_renew_bootstrap_failure_reopens_once_without_loop(
    tmp_path,
):
    from fastapi import HTTPException
    from app.code_runtime.sandbox_auth import (
        RuntimeBootstrap,
        renew_browser_runtime_session,
    )

    engine, Session = await _renewal_session_factory(tmp_path)
    async with Session() as db:
        _session, binding, rows = await _seed_browser_runtime(db)
        binding_id = binding.id
        observed_generation = rows["browser-a"].generation
    open_calls = 0
    bootstrap_calls = 0

    async def authorization_provider(**_kwargs):
        return "Bearer user-token"

    async def workspace_open(_authorization):
        nonlocal open_calls
        open_calls += 1
        return {"specReviewUrl": f"https://runtime.test/builder?token=launch-{open_calls}"}

    async def bootstrap(builder_url):
        nonlocal bootstrap_calls
        bootstrap_calls += 1
        if bootstrap_calls == 1:
            raise HTTPException(status_code=503, detail="Runtime bootstrap unavailable")
        return RuntimeBootstrap(
            clean_builder_url="https://runtime.test/builder",
            runtime_base_url="https://runtime.test",
            runtime_cookie="renewed-cookie",
            runtime_cookie_hash=hashlib.sha256(b"renewed-cookie").hexdigest(),
            expires_at=None,
        )

    result = await renew_browser_runtime_session(
        binding_id=binding_id,
        browser_session_id="browser-a",
        observed_generation=observed_generation,
        session_factory=Session,
        authorization_provider=authorization_provider,
        workspace_open=workspace_open,
        bootstrap=bootstrap,
    )

    assert result.generation == 8
    assert open_calls == 2
    assert bootstrap_calls == 2
    await engine.dispose()


@pytest.mark.asyncio
async def test_renew_forces_control_plane_refresh_at_most_once_across_reopen(
    tmp_path,
):
    from fastapi import HTTPException
    from app.code_runtime.sandbox_auth import (
        RuntimeBootstrap,
        SandboxRenewalFailure,
        renew_browser_runtime_session,
    )

    engine, Session = await _renewal_session_factory(tmp_path)
    async with Session() as db:
        _session, binding, rows = await _seed_browser_runtime(db)
        binding_id = binding.id
        observed_generation = rows["browser-a"].generation
    refresh_calls = 0
    open_calls = 0
    bootstrap_calls = 0

    async def authorization_provider(*, force_refresh, rejected_access_token):
        nonlocal refresh_calls
        if force_refresh:
            refresh_calls += 1
            assert rejected_access_token == "stale-token"
            return "Bearer fresh-token"
        return "Bearer stale-token"

    async def workspace_open(authorization):
        nonlocal open_calls
        open_calls += 1
        if open_calls == 1:
            raise HTTPException(status_code=401, detail="expired access token")
        if open_calls == 3:
            assert authorization == "Bearer fresh-token"
            raise HTTPException(status_code=401, detail="rejected again")
        return {"specReviewUrl": "https://runtime.test/builder?token=launch"}

    async def bootstrap(_builder_url):
        nonlocal bootstrap_calls
        bootstrap_calls += 1
        if bootstrap_calls == 1:
            raise HTTPException(status_code=503, detail="bootstrap failed")
        return RuntimeBootstrap(
            clean_builder_url="https://runtime.test/builder",
            runtime_base_url="https://runtime.test",
            runtime_cookie="unused",
            runtime_cookie_hash=hashlib.sha256(b"unused").hexdigest(),
            expires_at=None,
        )

    with pytest.raises(SandboxRenewalFailure) as exc_info:
        await renew_browser_runtime_session(
            binding_id=binding_id,
            browser_session_id="browser-a",
            observed_generation=observed_generation,
            session_factory=Session,
            authorization_provider=authorization_provider,
            workspace_open=workspace_open,
            bootstrap=bootstrap,
        )

    assert exc_info.value.code == "login_required"
    assert refresh_calls == 1
    assert open_calls == 3
    assert bootstrap_calls == 1
    await engine.dispose()


@pytest.mark.asyncio
async def test_renew_commit_failure_is_temporary_and_does_not_loop(
    tmp_path,
):
    from app.code_runtime.sandbox_auth import (
        RuntimeBootstrap,
        SandboxRenewalFailure,
        renew_browser_runtime_session,
    )
    from app.code_runtime.sandbox_metrics import SandboxAuthMetricsRegistry

    engine, Session = await _renewal_session_factory(tmp_path)
    metrics = SandboxAuthMetricsRegistry()
    async with Session() as db:
        _session, binding, rows = await _seed_browser_runtime(db)
        binding_id = binding.id
        observed_generation = rows["browser-a"].generation

    class FailingCommitSession(AsyncSession):
        async def commit(self):
            raise RuntimeError("commit failed")

    FailingSession = async_sessionmaker(
        engine,
        expire_on_commit=False,
        class_=FailingCommitSession,
    )
    open_calls = 0
    bootstrap_calls = 0

    async def authorization_provider(**_kwargs):
        return "Bearer user-token"

    async def workspace_open(_authorization):
        nonlocal open_calls
        open_calls += 1
        return {"specReviewUrl": "https://runtime.test/builder?token=launch"}

    async def bootstrap(_builder_url):
        nonlocal bootstrap_calls
        bootstrap_calls += 1
        return RuntimeBootstrap(
            clean_builder_url="https://runtime.test/builder",
            runtime_base_url="https://runtime.test",
            runtime_cookie="orphan-cookie",
            runtime_cookie_hash=hashlib.sha256(b"orphan-cookie").hexdigest(),
            expires_at=None,
        )

    with pytest.raises(SandboxRenewalFailure) as exc_info:
        await renew_browser_runtime_session(
            binding_id=binding_id,
            browser_session_id="browser-a",
            observed_generation=observed_generation,
            session_factory=FailingSession,
            authorization_provider=authorization_provider,
            workspace_open=workspace_open,
            bootstrap=bootstrap,
            metrics=metrics,
        )

    assert exc_info.value.code == "workspace_temporarily_unavailable"
    assert exc_info.value.clear_cookies is False
    assert open_calls == 1
    assert bootstrap_calls == 1
    snapshot = metrics.snapshot()
    assert snapshot[
        'sandbox_auth_renew_total{reason="workspace_temporarily_unavailable",result="failure"}'
    ] == 1
    assert snapshot[
        'sandbox_auth_orphan_session_total{stage="commit"}'
    ] == 1
    assert snapshot[
        'sandbox_auth_renew_total{reason="workspace_temporarily_unavailable",result="success"}'
    ] == 0
    async with Session() as db:
        row = (await db.execute(select(CodeRuntimeBrowserSession))).scalar_one()
        assert row.generation == observed_generation
    await engine.dispose()


@pytest.mark.asyncio
async def test_renew_invalid_launch_token_does_not_reopen_or_clear_login(tmp_path):
    from fastapi import HTTPException
    from app.code_runtime.sandbox_auth import SandboxRenewalFailure, renew_browser_runtime_session

    engine, Session = await _renewal_session_factory(tmp_path)
    async with Session() as db:
        _session, binding, rows = await _seed_browser_runtime(db)
        binding_id = binding.id
        observed_generation = rows["browser-a"].generation
    open_calls = 0
    bootstrap_calls = 0

    async def authorization_provider(**_kwargs):
        return "Bearer user-token"

    async def workspace_open(_authorization):
        nonlocal open_calls
        open_calls += 1
        return {"specReviewUrl": "https://runtime.test/builder?token=launch"}

    async def bootstrap(_builder_url):
        nonlocal bootstrap_calls
        bootstrap_calls += 1
        raise HTTPException(
            status_code=401,
            detail="Runtime launch authorization invalid",
            headers={"X-APAAS-Sandbox-Auth-Error": "sandbox_launch_token_invalid"},
        )

    with pytest.raises(SandboxRenewalFailure) as exc_info:
        await renew_browser_runtime_session(
            binding_id=binding_id,
            browser_session_id="browser-a",
            observed_generation=observed_generation,
            session_factory=Session,
            authorization_provider=authorization_provider,
            workspace_open=workspace_open,
            bootstrap=bootstrap,
        )

    assert exc_info.value.code == "workspace_temporarily_unavailable"
    assert exc_info.value.clear_cookies is False
    assert open_calls == 1
    assert bootstrap_calls == 1
    await engine.dispose()


@pytest.mark.asyncio
async def test_renew_locks_browser_row_but_not_shared_binding_row():
    from app.code_runtime.sandbox_auth import encrypt_runtime_cookie, renew_browser_runtime_session

    browser_session = SimpleNamespace(
        generation=2,
        runtime_session_cookie_enc=encrypt_runtime_cookie("fresh-cookie"),
        runtime_session_hash=hashlib.sha256(b"fresh-cookie").hexdigest(),
        runtime_session_expires_at=None,
    )
    binding = SimpleNamespace(id=42)
    statements = []

    class ScalarResult:
        def __init__(self, value):
            self.value = value

        def scalar_one_or_none(self):
            return self.value

    class FakeDb:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def execute(self, statement):
            statements.append(statement)
            return ScalarResult(browser_session if len(statements) == 1 else binding)

    result = await renew_browser_runtime_session(
        binding_id=42,
        browser_session_id="browser-a",
        observed_generation=1,
        session_factory=FakeDb,
        authorization_provider=lambda **_kwargs: None,
        workspace_open=lambda _authorization: None,
        bootstrap=lambda _builder_url: None,
    )

    assert result.joined is True
    assert statements[0]._for_update_arg is not None
    assert statements[1]._for_update_arg is None


@pytest.mark.parametrize(
    ("code", "clear_cookies"),
    [
        ("login_required", True),
        ("workspace_forbidden", True),
        ("sandbox_unavailable", True),
        ("workspace_temporarily_unavailable", False),
    ],
)
def test_hard_failure_response_clears_only_current_browser_cookies(
    code,
    clear_cookies,
):
    from app.code_runtime.sandbox_auth import SandboxRenewalFailure
    from app.routes.code_runtime import _sandbox_renewal_failure_response

    response = _sandbox_renewal_failure_response(
        SandboxRenewalFailure(code),
        session_id="session-1",
        forwarded_prefix="/ai-builder",
    )

    assert response.status_code in {401, 403, 404, 503}
    assert response.body == json.dumps(
        {"detail": code},
        separators=(",", ":"),
    ).encode()
    set_cookies = response.headers.getlist("set-cookie")
    assert bool(set_cookies) is clear_cookies
    if clear_cookies:
        assert any("dolphin_code_runtime_session-1=" in value for value in set_cookies)
        assert any("apaas_sandbox_token=" in value for value in set_cookies)


def test_sandbox_auth_metrics_registry_keeps_fixed_low_cardinality_labels():
    from app.code_runtime.sandbox_metrics import SandboxAuthMetricsRegistry

    metrics = SandboxAuthMetricsRegistry()
    metrics.record_renew("success", "sandbox_session_expired", 0.25)
    metrics.record_replay("POST", "success")
    metrics.record_hard_failure("tenant-7-canary")
    metrics.record_builder_url_cleanup("success")

    snapshot = metrics.snapshot()
    assert snapshot[
        'sandbox_auth_renew_total{reason="sandbox_session_expired",result="success"}'
    ] == 1
    assert snapshot[
        'sandbox_auth_replay_total{method="POST",result="success"}'
    ] == 1
    assert snapshot[
        'sandbox_auth_hard_failure_total{reason="other"}'
    ] == 1
    assert snapshot[
        'sandbox_builder_url_cleanup_total{result="success"}'
    ] == 1
    assert snapshot["sandbox_auth_renew_duration_count"] == 1
    rendered = metrics.render()
    assert "tenant-7-canary" not in rendered
    assert "http://" not in rendered
    assert "https://" not in rendered


@pytest.mark.asyncio
async def test_sandbox_auth_metrics_endpoint_is_hidden_and_renders_prometheus_text():
    import app.routes.code_runtime as code_runtime_routes

    route = next(
        item
        for item in code_runtime_routes.router.routes
        if item.path == "/code/internal/sandbox-auth-metrics"
    )
    assert route.include_in_schema is False

    response = await code_runtime_routes.sandbox_auth_metrics_endpoint()

    assert response.status_code == 200
    assert b"sandbox_auth_renew_total" in response.body
    assert b"sandbox_auth_singleflight_join_total" in response.body


def test_recoverable_runtime_auth_error_requires_stable_known_header():
    import httpx
    from app.routes.code_runtime import _recoverable_runtime_auth_error

    assert _recoverable_runtime_auth_error(httpx.Response(
        401,
        headers={"X-APAAS-Sandbox-Auth-Error": "sandbox_session_expired"},
    )) == "sandbox_session_expired"
    assert _recoverable_runtime_auth_error(httpx.Response(
        401,
        headers={"X-APAAS-Sandbox-Auth-Error": "sandbox_session_invalid"},
    )) == "sandbox_session_invalid"
    for response in (
        httpx.Response(401),
        httpx.Response(401, headers={"X-APAAS-Sandbox-Auth-Error": "unknown"}),
        httpx.Response(401, headers={
            "X-APAAS-Sandbox-Auth-Error": "sandbox_credential_missing",
        }),
        httpx.Response(403, headers={
            "X-APAAS-Sandbox-Auth-Error": "sandbox_session_expired",
        }),
    ):
        assert _recoverable_runtime_auth_error(response) is None


@pytest.mark.asyncio
async def test_proxy_replays_post_body_once_after_recoverable_runtime_auth(
    db_session,
    monkeypatch,
):
    from dataclasses import replace

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
    raw_body = b'{"prompt":"same bytes"}'
    request = _proxy_request(
        session.public_id,
        cookie=(
            f"dolphin_code_runtime_{session.public_id}={proxy_token}; "
            "apaas_sandbox_token=db-cookie-a"
        ),
        method="POST",
        body=raw_body,
        path="api/write",
    )
    attempts: list[tuple[bytes, str]] = []
    renew_calls = 0

    def handler(upstream: httpx.Request) -> httpx.Response:
        attempts.append((upstream.content, upstream.headers["cookie"]))
        if len(attempts) == 1:
            return httpx.Response(
                401,
                content=b"expired",
                headers={
                    "X-APAAS-Sandbox-Auth-Error": "sandbox_session_expired",
                },
            )
        return httpx.Response(200, content=b"ok")

    async def fake_renew(_session, _binding, authorization, _db, *, reason):
        nonlocal renew_calls
        assert reason == "sandbox_session_expired"
        renew_calls += 1
        return replace(
            authorization,
            runtime_cookie="renewed-cookie",
            runtime_cookie_hash=hashlib.sha256(b"renewed-cookie").hexdigest(),
            observed_generation=int(authorization.observed_generation or 0) + 1,
        )

    transport = httpx.MockTransport(handler)
    original = code_runtime_routes.httpx.AsyncClient
    monkeypatch.setattr(
        code_runtime_routes.httpx,
        "AsyncClient",
        lambda **kwargs: original(transport=transport, **kwargs),
    )
    monkeypatch.setattr(
        code_runtime_routes,
        "_renew_proxy_runtime_authorization",
        fake_renew,
    )

    response = await proxy_code_runtime(
        session.public_id,
        "api/write",
        request,
        db_session,
    )
    body = b"".join([chunk async for chunk in response.body_iterator])
    if response.background:
        await response.background()

    assert response.status_code == 200
    assert body == b"ok"
    assert attempts == [
        (raw_body, "apaas_sandbox_token=db-cookie-a"),
        (raw_body, "apaas_sandbox_token=renewed-cookie"),
    ]
    assert renew_calls == 1


@pytest.mark.asyncio
async def test_proxy_second_recoverable_401_is_returned_without_third_attempt(
    db_session,
    monkeypatch,
):
    from dataclasses import replace

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
        cookie=f"dolphin_code_runtime_{session.public_id}={proxy_token}",
        path="api/events",
    )
    attempts = 0
    renew_calls = 0

    def handler(_upstream: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(
            401,
            content=f"expired-{attempts}".encode(),
            headers={
                "content-type": "text/event-stream",
                "X-APAAS-Sandbox-Auth-Error": "sandbox_session_expired",
            },
        )

    async def fake_renew(_session, _binding, authorization, _db, *, reason):
        nonlocal renew_calls
        renew_calls += 1
        return replace(authorization, runtime_cookie="renewed-cookie")

    transport = httpx.MockTransport(handler)
    original = code_runtime_routes.httpx.AsyncClient
    monkeypatch.setattr(
        code_runtime_routes.httpx,
        "AsyncClient",
        lambda **kwargs: original(transport=transport, **kwargs),
    )
    monkeypatch.setattr(
        code_runtime_routes,
        "_renew_proxy_runtime_authorization",
        fake_renew,
    )

    response = await proxy_code_runtime(
        session.public_id,
        "api/events",
        request,
        db_session,
    )
    body = b"".join([chunk async for chunk in response.body_iterator])
    if response.background:
        await response.background()

    assert response.status_code == 401
    assert body == b"expired-2"
    assert attempts == 2
    assert renew_calls == 1


@pytest.mark.asyncio
async def test_sse_response_does_not_start_before_recoverable_auth_renewal(
    db_session,
    monkeypatch,
):
    from dataclasses import replace
    from starlette.requests import Request

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
    template_request = _proxy_request(
        session.public_id,
        cookie=f"dolphin_code_runtime_{session.public_id}={proxy_token}",
        path="api/events",
    )
    attempts = 0
    renew_started = asyncio.Event()
    release_renew = asyncio.Event()
    events: list[dict] = []

    def handler(_upstream: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return httpx.Response(
                401,
                headers={
                    "content-type": "text/event-stream",
                    "X-APAAS-Sandbox-Auth-Error": "sandbox_session_expired",
                },
            )
        return httpx.Response(
            200,
            content=b"data: ready\n\n",
            headers={"content-type": "text/event-stream"},
        )

    async def fake_renew(_session, _binding, authorization, _db, *, reason):
        renew_started.set()
        assert events == []
        await asyncio.wait_for(release_renew.wait(), timeout=5)
        return replace(authorization, runtime_cookie="renewed-cookie")

    transport = httpx.MockTransport(handler)
    original = code_runtime_routes.httpx.AsyncClient
    monkeypatch.setattr(
        code_runtime_routes.httpx,
        "AsyncClient",
        lambda **kwargs: original(transport=transport, **kwargs),
    )
    monkeypatch.setattr(
        code_runtime_routes,
        "_renew_proxy_runtime_authorization",
        fake_renew,
    )

    response_finished = asyncio.Event()
    request_received = False

    async def receive():
        nonlocal request_received
        if not request_received:
            request_received = True
            return {"type": "http.request", "body": b"", "more_body": False}
        await response_finished.wait()
        return {"type": "http.disconnect"}

    async def send(event):
        events.append(event)
        if (
            event["type"] == "http.response.body"
            and not event.get("more_body", False)
        ):
            response_finished.set()

    async def app(scope, receive_callable, send_callable):
        request = Request(scope, receive_callable)
        response = await proxy_code_runtime(
            session.public_id,
            "api/events",
            request,
            db_session,
        )
        await response(scope, receive_callable, send_callable)

    task = asyncio.create_task(app(template_request.scope, receive, send))
    await asyncio.wait_for(renew_started.wait(), timeout=5)
    assert events == []
    release_renew.set()
    await asyncio.wait_for(task, timeout=10)

    assert events[0]["type"] == "http.response.start"
    assert events[0]["status"] == 200
    assert any(
        event["type"] == "http.response.body"
        and event.get("body") == b"data: ready\n\n"
        for event in events
    )
    assert attempts == 2


@pytest.mark.asyncio
async def test_buffered_proxy_closes_upstream_when_body_read_fails(
    db_session,
    monkeypatch,
):
    import httpx
    import app.routes.code_runtime as code_runtime_routes
    from app.code_runtime.service import create_proxy_cookie_token
    from app.routes.code_runtime import proxy_code_runtime

    class FailingStream(httpx.AsyncByteStream):
        def __init__(self):
            self.closed = False

        async def __aiter__(self):
            raise httpx.ReadError("upstream disconnected")
            yield b""

        async def aclose(self):
            self.closed = True

    session, _binding, _rows = await _seed_browser_runtime(db_session)
    proxy_token = create_proxy_cookie_token(
        session_id=session.public_id,
        user_id=11,
        tenant_id=7,
        browser_session_id="browser-a",
    )
    request = _proxy_request(
        session.public_id,
        cookie=f"dolphin_code_runtime_{session.public_id}={proxy_token}",
        path="src/main.ts",
    )
    stream = FailingStream()
    close_calls = 0
    original_close = code_runtime_routes._close_upstream_attempt

    def handler(_upstream: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            stream=stream,
            headers={"content-type": "application/javascript"},
        )

    async def tracked_close(attempt):
        nonlocal close_calls
        close_calls += 1
        await original_close(attempt)

    transport = httpx.MockTransport(handler)
    original_client = code_runtime_routes.httpx.AsyncClient
    monkeypatch.setattr(
        code_runtime_routes.httpx,
        "AsyncClient",
        lambda **kwargs: original_client(transport=transport, **kwargs),
    )
    monkeypatch.setattr(
        code_runtime_routes,
        "_close_upstream_attempt",
        tracked_close,
    )

    with pytest.raises(httpx.ReadError):
        await proxy_code_runtime(
            session.public_id,
            "src/main.ts",
            request,
            db_session,
        )

    assert close_calls == 1
    assert stream.closed is True


def test_remove_builder_entry_tokens_preserves_raw_query_shape_and_fragment():
    from app.code_runtime.sandbox_auth import remove_builder_entry_tokens

    cleaned, removed = remove_builder_entry_tokens(
        "https://runtime.test/builder?x=&token=secret&empty&%74oken=kept"
        "&token=second#panel",
    )

    assert removed == 2
    assert cleaned == (
        "https://runtime.test/builder?x=&empty&%74oken=kept#panel"
    )


@pytest.mark.asyncio
async def test_cleanup_builder_urls_is_batched_dry_run_apply_and_idempotent(
    db_session,
    capsys,
):
    import httpx
    from scripts.cleanup_code_runtime_builder_urls import cleanup_builder_urls

    seeded = []
    for index in range(4):
        session, binding, _rows = await _seed_browser_runtime(
            db_session,
            public_id=f"00000000-0000-0000-0000-0000000000{index + 10}",
        )
        seeded.append((session, binding))
    seeded[0][1].builder_url = (
        "https://runtime.test/builder?token=entry-canary&tab=spec#panel"
    )
    seeded[1][1].builder_url = (
        "https://runtime.test/builder?x=&token=entry-two&empty"
        "&token=entry-three#panel"
    )
    seeded[2][1].builder_url = (
        "https://runtime.test/builder?mytoken=kept&%74oken=kept"
    )
    seeded[3][1].builder_url = "https://runtime.test/builder"
    await db_session.commit()
    Session = async_sessionmaker(
        db_session.bind,
        expire_on_commit=False,
        class_=AsyncSession,
    )
    contract_transport = httpx.MockTransport(
        lambda _request: httpx.Response(
            200,
            json={"writer_contract": "clean_builder_url_v1"},
        )
    )
    contract_client_factory = lambda: httpx.AsyncClient(
        transport=contract_transport
    )

    dry_run = await cleanup_builder_urls(
        session_factory=Session,
        batch_size=2,
        apply=False,
    )
    await db_session.rollback()
    rows = (
        await db_session.execute(
            select(CodeRuntimeBinding).order_by(CodeRuntimeBinding.id)
        )
    ).scalars().all()

    assert dry_run.rows_scanned == 4
    assert dry_run.rows_cleaned == 2
    assert dry_run.rows_recontaminated == 0
    assert dry_run.last_checkpoint == rows[-1].id
    assert "entry-canary" in rows[0].builder_url

    applied = await cleanup_builder_urls(
        session_factory=Session,
        batch_size=2,
        apply=True,
        state_urls=["https://builder.test/internal/sandbox-auth-state"],
        contract_client_factory=contract_client_factory,
    )
    await db_session.rollback()
    rows = (
        await db_session.execute(
            select(CodeRuntimeBinding).order_by(CodeRuntimeBinding.id)
        )
    ).scalars().all()

    assert applied.rows_scanned == 4
    assert applied.rows_cleaned == 2
    assert applied.rows_recontaminated == 0
    assert rows[0].builder_url == (
        "https://runtime.test/builder?tab=spec#panel"
    )
    assert rows[1].builder_url == (
        "https://runtime.test/builder?x=&empty#panel"
    )
    assert rows[2].builder_url.endswith("?mytoken=kept&%74oken=kept")

    repeated = await cleanup_builder_urls(
        session_factory=Session,
        batch_size=2,
        apply=True,
        state_urls=["https://builder.test/internal/sandbox-auth-state"],
        contract_client_factory=contract_client_factory,
    )
    assert repeated.rows_cleaned == 0
    output = capsys.readouterr().out
    assert "entry-canary" not in output
    assert "entry-two" not in output
    assert "runtime.test" not in output


@pytest.mark.asyncio
async def test_sandbox_auth_state_endpoint_is_hidden_and_reports_writer_contract():
    import app.routes.code_runtime as code_runtime_routes
    from app.config import APP_VERSION

    route = next(
        item
        for item in code_runtime_routes.router.routes
        if item.path == "/code/internal/sandbox-auth-state"
    )
    assert route.include_in_schema is False
    assert await code_runtime_routes.sandbox_auth_state_endpoint() == {
        "writer_contract": "clean_builder_url_v1",
        "app_version": APP_VERSION,
    }


@pytest.mark.asyncio
async def test_cleanup_apply_writer_contract_gate_requires_every_instance(
    capsys,
):
    import httpx
    from scripts.cleanup_code_runtime_builder_urls import verify_writer_contract

    responses = {
        "/instance-1": {"writer_contract": "clean_builder_url_v1"},
        "/instance-2": {"writer_contract": "clean_builder_url_v1"},
        "/old-instance": {"writer_contract": "legacy_writer"},
    }

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=responses[request.url.path])

    transport = httpx.MockTransport(handler)
    factory = lambda: httpx.AsyncClient(transport=transport)

    assert await verify_writer_contract(
        [
            "https://builder.test/instance-1",
            "https://builder.test/instance-2",
        ],
        client_factory=factory,
    ) is True
    assert await verify_writer_contract(
        [
            "https://builder.test/instance-1",
            "https://builder.test/old-instance",
        ],
        client_factory=factory,
    ) is False
    assert await verify_writer_contract([], client_factory=factory) is False
    output = capsys.readouterr().out
    assert "builder.test" not in output
    assert "legacy_writer" not in output
    assert "status=blocked" in output


@pytest.mark.asyncio
async def test_cleanup_cli_apply_stops_before_database_without_writer_instances(
):
    import scripts.cleanup_code_runtime_builder_urls as cleanup_script

    exit_code = await cleanup_script._run(SimpleNamespace(
        apply=True,
        batch_size=2,
        builder_state_url=[],
    ))

    assert exit_code == 2


@pytest.mark.asyncio
async def test_cleanup_write_boundary_rejects_apply_without_writer_contract():
    from scripts.cleanup_code_runtime_builder_urls import (
        WriterContractGateError,
        cleanup_builder_urls,
    )

    def unexpected_session_factory():
        raise AssertionError("database must not be opened before writer gate")

    with pytest.raises(WriterContractGateError):
        await cleanup_builder_urls(
            session_factory=unexpected_session_factory,
            apply=True,
            state_urls=[],
        )
