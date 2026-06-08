from __future__ import annotations

import pytest

from app.models import PlatformEnv, Tenant
from app.routes.applications._helpers import _resolve_platform_env_for_tenant


@pytest.mark.asyncio
async def test_resolve_platform_env_falls_back_to_connected_env(db_session):
    tenant = Tenant(tenant_name="t-env-resolve", tenant_code="t-env-resolve")
    db_session.add(tenant)
    await db_session.flush()

    env = PlatformEnv(
        tenant_id=tenant.id,
        env_name="main-connected",
        base_url="https://apaas.example.com",
        platform_tenant_id="TID_MAIN",
        token="tok-main",
        is_default=False,
        status="connected",
    )
    db_session.add(env)
    await db_session.commit()

    resolved = await _resolve_platform_env_for_tenant(db_session, tenant.id)

    assert resolved is not None
    assert resolved.id == env.id


@pytest.mark.asyncio
async def test_resolve_platform_env_prefers_default_over_connected(db_session):
    tenant = Tenant(tenant_name="t-env-default", tenant_code="t-env-default")
    db_session.add(tenant)
    await db_session.flush()

    connected = PlatformEnv(
        tenant_id=tenant.id,
        env_name="connected",
        base_url="https://apaas-connected.example.com",
        platform_tenant_id="TID_CONNECTED",
        token="tok-connected",
        is_default=False,
        status="connected",
    )
    default = PlatformEnv(
        tenant_id=tenant.id,
        env_name="default",
        base_url="https://apaas-default.example.com",
        platform_tenant_id="TID_DEFAULT",
        token="tok-default",
        is_default=True,
        status="disconnected",
    )
    db_session.add_all([connected, default])
    await db_session.commit()

    resolved = await _resolve_platform_env_for_tenant(db_session, tenant.id)

    assert resolved is not None
    assert resolved.id == default.id
