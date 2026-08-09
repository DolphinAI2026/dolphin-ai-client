"""Route boundary tests for authentication, tenant context, and source failures."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.database import get_db
from app.deps import get_auth_context
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
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/system-assistant/bootstrap")

    assert response.status_code == 200
    body = response.json()
    assert body["source_status"]["baseline"] == "unavailable"
    assert all(node["status"] == "unavailable" for node in body["baseline_snapshot"]["nodes"])
    assert body["recommended_action"]["status"] == "partial"
