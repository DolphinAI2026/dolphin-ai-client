from __future__ import annotations

import pytest

from app.crypto import encrypt_password
from app.deps import AuthContext
from app.models import PlatformEnv, Tenant
from app.models import User
from app.routes.applications._helpers import _resolve_platform_env_for_tenant
from app.routes.platform_envs import list_remote_apps


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


@pytest.mark.asyncio
async def test_list_remote_apps_logs_in_when_env_has_credentials(db_session, monkeypatch):
    from app.routes import platform_envs

    tenant = Tenant(tenant_name="t-env-login", tenant_code="t-env-login")
    user = User(username="admin", hashed_password="x", is_platform_admin=True, is_active=True)
    db_session.add_all([tenant, user])
    await db_session.flush()

    env = PlatformEnv(
        tenant_id=tenant.id,
        env_name="default",
        base_url="https://apaas.example.com/backend",
        platform_tenant_id="TID_DEFAULT",
        username="admin",
        password_enc=encrypt_password("secret"),
        is_default=True,
        status="disconnected",
    )
    db_session.add(env)
    await db_session.commit()

    calls: list[tuple[str, str | None]] = []

    class FakeAPaaSClient:
        def __init__(self, *, base_url, tenant_id, token=None):
            self.token = token
            calls.append((tenant_id, token))

        async def login(self, username, password):
            assert username == "admin"
            assert password == "secret"
            return {"token": "fresh-token"}

        async def query_app_list(self):
            assert self.token == "fresh-token"
            return [{"id": "remote-1", "appName": "Remote App", "appCode": "remote-app"}]

    monkeypatch.setattr(platform_envs, "APaaSClient", FakeAPaaSClient)

    apps = await list_remote_apps(
        env.id,
        AuthContext(user=user, tenant_id=tenant.id, tenant_role="tenant_admin", org_permissions={}),
        db_session,
    )
    await db_session.refresh(env)

    assert calls == [("TID_DEFAULT", None), ("TID_DEFAULT", "fresh-token")]
    assert env.token == "fresh-token"
    assert env.status == "connected"
    assert apps[0]["apaas_app_id"] == "remote-1"
