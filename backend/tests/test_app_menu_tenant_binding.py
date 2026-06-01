from types import SimpleNamespace

import pytest

from app.routes.applications import _resolve_current_apaas_tenant_id


class _ScalarResult:
    def __init__(self, value):
        self.value = value

    def scalar_one_or_none(self):
        return self.value


class _FakeDb:
    def __init__(self, value):
        self.value = value

    async def execute(self, _stmt):
        return _ScalarResult(self.value)


@pytest.mark.asyncio
async def test_menu_tenant_context_uses_current_local_tenant_binding():
    ctx = SimpleNamespace(tenant_id=59, apaas_tenant_id="user-jwt-tenant")

    tenant_id = await _resolve_current_apaas_tenant_id(_FakeDb("current-bound-tenant"), ctx)

    assert tenant_id == "current-bound-tenant"


@pytest.mark.asyncio
async def test_menu_tenant_context_missing_binding_is_empty():
    ctx = SimpleNamespace(tenant_id=59, apaas_tenant_id="user-jwt-tenant")

    tenant_id = await _resolve_current_apaas_tenant_id(_FakeDb(None), ctx)

    assert tenant_id == ""
