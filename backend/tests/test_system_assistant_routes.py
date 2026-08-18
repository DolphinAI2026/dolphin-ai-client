"""Route boundary tests for authentication, tenant context, and source failures."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.database import get_db
from app.deps import get_auth_context
from app.routes import code_runtime
from app.routes import system_assistant


@pytest.mark.asyncio
async def test_bootstrap_requires_authentication():
    app = FastAPI()
    app.include_router(system_assistant.router, prefix="/api")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/system-assistant/bootstrap")
    assert response.status_code in (401, 403)


@pytest.mark.asyncio
async def test_bootstrap_passes_current_tenant_to_read_only_collector(monkeypatch):
    app = FastAPI()
    app.include_router(system_assistant.router, prefix="/api")
    ctx = SimpleNamespace(user=SimpleNamespace(id=11), tenant_id=42, tenant_role="member", org_permissions={})
    calls = []

    async def collect(db, received_ctx):
        calls.append((db, received_ctx.tenant_id, received_ctx.user.id))
        return {"workspace": {"status": "missing", "source_status": "ready", "items": []}}

    monkeypatch.setattr(system_assistant, "collect_baseline_facts", collect)
    app.dependency_overrides[get_auth_context] = lambda: ctx
    app.dependency_overrides[get_db] = lambda: object()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/system-assistant/bootstrap")

    assert response.status_code == 200, response.text
    assert calls == [(calls[0][0], 42, 11)]
    body = response.json()
    assert body["baseline_snapshot"]["tenant_id"] == 42
    assert body["baseline_snapshot"]["readonly"] is True


@pytest.mark.asyncio
async def test_bootstrap_keeps_source_failure_as_unavailable(monkeypatch):
    app = FastAPI()
    app.include_router(system_assistant.router, prefix="/api")
    app.dependency_overrides[get_auth_context] = lambda: SimpleNamespace(
        user=SimpleNamespace(id=11), tenant_id=42, tenant_role="member", org_permissions={}
    )
    app.dependency_overrides[get_db] = lambda: object()

    async def fail(_db, _ctx):
        raise RuntimeError("knowledge source down")

    monkeypatch.setattr(system_assistant, "collect_baseline_facts", fail)
    async with AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://test",
    ) as client:
        response = await client.get("/api/system-assistant/bootstrap")

    assert response.status_code == 500


@pytest.mark.asyncio
async def test_models_exposes_shared_coding_catalog_for_control_plane_identity(monkeypatch):
    app = FastAPI()
    app.include_router(system_assistant.router, prefix="/api")
    ctx = SimpleNamespace(user=SimpleNamespace(id=11), tenant_id=0)
    calls = []

    async def list_models(_db, tenant_id, purpose):
        calls.append((tenant_id, purpose))
        return [SimpleNamespace(
            id=7,
            config_name="企业 Coding 模型",
            provider="dolphin",
            model="gpt-5.5",
            purpose="coding",
            is_default=True,
        )]

    monkeypatch.setattr(system_assistant, "list_llm_configs_for_purpose", list_models)
    app.dependency_overrides[get_auth_context] = lambda: ctx
    app.dependency_overrides[get_db] = lambda: object()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/system-assistant/models")

    assert response.status_code == 200, response.text
    assert calls == [(None, "coding")]
    assert response.json() == [{
        "id": 7,
        "config_name": "企业 Coding 模型",
        "provider": "dolphin",
        "model": "gpt-5.5",
        "purpose": "coding",
        "is_default": True,
    }]


@pytest.mark.asyncio
async def test_desktop_models_merge_local_and_control_plane_catalog(monkeypatch):
    app = FastAPI()
    app.include_router(system_assistant.router, prefix="/api")
    ctx = SimpleNamespace(user=SimpleNamespace(id=11), tenant_id=42)

    async def local_models(_db, tenant_id, purpose):
        assert (tenant_id, purpose) == (42, "coding")
        return [SimpleNamespace(
            id=7,
            config_name="本地 GLM",
            provider="custom",
            model="GLM-5.1",
            purpose="all",
            is_default=False,
        )]

    async def auth(*_args, **_kwargs):
        return "Bearer control-plane-token", "control_plane"

    async def remote_models(**_kwargs):
        return [{
            "id": -7,
            "config_name": "线上 Coding",
            "provider": "dolphin",
            "model": "online-coding",
            "purpose": "coding",
            "is_default": True,
        }]

    monkeypatch.setattr(system_assistant, "is_control_plane_context", lambda _ctx: True)
    monkeypatch.setattr(system_assistant.runtime, "is_desktop", lambda: True)
    monkeypatch.setattr(system_assistant, "list_llm_configs_for_purpose", local_models)
    monkeypatch.setattr(system_assistant, "list_control_plane_model_options", remote_models)
    monkeypatch.setattr(code_runtime, "_control_plane_request_auth", auth)
    app.dependency_overrides[get_auth_context] = lambda: ctx
    app.dependency_overrides[get_db] = lambda: object()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/system-assistant/models")

    assert response.status_code == 200, response.text
    assert [item["id"] for item in response.json()] == [7, -7]


def test_bootstrap_openapi_uses_typed_response_contract():
    app = FastAPI()
    app.include_router(system_assistant.router, prefix="/api")

    schema = app.openapi()
    response_schema = schema["paths"]["/api/system-assistant/bootstrap"]["get"]["responses"]["200"]["content"]["application/json"]["schema"]

    assert response_schema["$ref"].endswith("/BootstrapResponse")
