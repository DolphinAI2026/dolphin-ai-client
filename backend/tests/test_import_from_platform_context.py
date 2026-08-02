from __future__ import annotations

import pytest

from app.crypto import encrypt_password
from app.deps import AuthContext
from app.models import APaaSUserCredential, Application, PlatformEnv, Tenant, User
from app.routes.applications import crud


class FakeAPaaSClient:
    calls: list[tuple[str, str, str | None]] = []
    failing_tokens: set[str] = set()

    def __init__(self, *, base_url: str, tenant_id: str, token: str | None = None):
        self.base_url = base_url
        self.tenant_id = tenant_id
        self.token = token
        self.__class__.calls.append((base_url, tenant_id, token))

    async def query_app_detail(self, app_id: str) -> dict:
        assert self.token
        if self.token in self.failing_tokens:
            raise RuntimeError("token expired")
        return {
            "id": app_id,
            "appName": "平台导入应用",
            "appCode": "imported-app",
            "description": "from platform",
        }


async def _fake_sync_from_platform_full(client, apaas_app_id: str, app_name: str) -> dict:
    return {
        "appName": app_name,
        "appCode": "imported-app",
        "models": [],
        "forms": [],
        "roles": [],
    }


def _fake_config_to_markdown(config: dict, app_description: str = "") -> str:
    return f"# {config['appName']}\n\n{app_description}"


@pytest.fixture(autouse=True)
def patch_import_dependencies(monkeypatch):
    from app import platform_sync
    from app.services import config_to_spec

    FakeAPaaSClient.calls = []
    FakeAPaaSClient.failing_tokens = set()
    monkeypatch.setattr(crud, "APaaSClient", FakeAPaaSClient)
    monkeypatch.setattr(platform_sync, "sync_from_platform_full", _fake_sync_from_platform_full)
    monkeypatch.setattr(config_to_spec, "config_to_markdown", _fake_config_to_markdown)


@pytest.mark.asyncio
async def test_import_from_platform_falls_back_when_requested_env_belongs_to_other_tenant(db_session):
    current_tenant = Tenant(tenant_name="current", tenant_code="current-import")
    other_tenant = Tenant(tenant_name="other", tenant_code="other-import")
    user = User(username="import-owner", hashed_password="x", is_active=True)
    db_session.add_all([current_tenant, other_tenant, user])
    await db_session.flush()

    current_env = PlatformEnv(
        tenant_id=current_tenant.id,
        env_name="current-default",
        base_url="https://apaas-current.example.com/backend",
        platform_tenant_id="TID_CURRENT",
        token="current-token",
        is_default=True,
        status="connected",
    )
    other_env = PlatformEnv(
        tenant_id=other_tenant.id,
        env_name="other-default",
        base_url="https://apaas-other.example.com/backend",
        platform_tenant_id="TID_OTHER",
        token="other-token",
        is_default=True,
        status="connected",
    )
    db_session.add_all([current_env, other_env])
    await db_session.commit()

    response = await crud.import_from_platform(
        crud.ImportFromPlatformRequest(env_id=other_env.id, apaas_app_id="remote-1"),
        AuthContext(user=user, tenant_id=current_tenant.id, tenant_role="tenant_admin", org_permissions={}),
        db_session,
    )

    assert response.platform_env_id == current_env.id
    assert FakeAPaaSClient.calls[0] == (
        "https://apaas-current.example.com/backend",
        "TID_CURRENT",
        "current-token",
    )

    saved = await db_session.get(Application, response.id)
    assert saved is not None
    assert saved.tenant_id == current_tenant.id
    assert saved.platform_env_id == current_env.id
    assert saved.apaas_app_id == "remote-1"


@pytest.mark.asyncio
async def test_import_from_platform_uses_user_credential_without_platform_env(db_session):
    tenant = Tenant(
        tenant_name="credential tenant",
        tenant_code="credential-import",
        apaas_tenant_id_str="TID_CRED",
    )
    user = User(username="credential-owner", hashed_password="x", is_active=True)
    db_session.add_all([tenant, user])
    await db_session.flush()
    db_session.add(
        APaaSUserCredential(
            user_id=user.id,
            local_tenant_id=tenant.id,
            apaas_user_id="U1",
            apaas_tenant_id="TID_CRED",
            base_url="https://apaas-credential.example.com/backend",
            account="credential-owner",
            password_enc=encrypt_password("secret"),
            token="credential-token",
            status="connected",
        )
    )
    await db_session.commit()

    response = await crud.import_from_platform(
        crud.ImportFromPlatformRequest(env_id=999999, apaas_app_id="remote-cred"),
        AuthContext(user=user, tenant_id=tenant.id, tenant_role="tenant_admin", org_permissions={}),
        db_session,
    )

    assert response.platform_env_id is None
    assert FakeAPaaSClient.calls[0] == (
        "https://apaas-credential.example.com/backend",
        "TID_CRED",
        "credential-token",
    )

    saved = await db_session.get(Application, response.id)
    assert saved is not None
    assert saved.tenant_id == tenant.id
    assert saved.platform_env_id is None
    assert saved.apaas_app_id == "remote-cred"


@pytest.mark.asyncio
async def test_import_from_platform_falls_back_to_current_user_credential_when_env_token_expired(
    db_session,
):
    tenant = Tenant(
        tenant_name="fallback tenant",
        tenant_code="fallback-import",
        apaas_tenant_id_str="TID_FALLBACK",
    )
    user = User(username="fallback-owner", hashed_password="x", is_active=True)
    db_session.add_all([tenant, user])
    await db_session.flush()
    env = PlatformEnv(
        tenant_id=tenant.id,
        env_name="stale-env",
        base_url="https://apaas-stale.example.com/backend",
        platform_tenant_id="TID_FALLBACK",
        token="stale-token",
        is_default=True,
        status="connected",
    )
    credential = APaaSUserCredential(
        user_id=user.id,
        local_tenant_id=tenant.id,
        apaas_user_id="U_FALLBACK",
        apaas_tenant_id="TID_FALLBACK",
        base_url="https://apaas-current.example.com/backend",
        account="fallback-owner",
        password_enc=encrypt_password("unused-after-token-fallback"),
        token="current-token",
        status="connected",
    )
    db_session.add_all([env, credential])
    await db_session.commit()
    FakeAPaaSClient.failing_tokens = {"stale-token"}

    response = await crud.import_from_platform(
        crud.ImportFromPlatformRequest(env_id=env.id, apaas_app_id="remote-fallback"),
        AuthContext(user=user, tenant_id=tenant.id, tenant_role="tenant_admin", org_permissions={}),
        db_session,
    )

    assert response.apaas_app_id == "remote-fallback"
    assert FakeAPaaSClient.calls[-2:] == [
        ("https://apaas-stale.example.com/backend", "TID_FALLBACK", "stale-token"),
        ("https://apaas-current.example.com/backend", "TID_FALLBACK", "current-token"),
    ]


@pytest.mark.asyncio
async def test_import_from_platform_uses_effective_tenant_when_context_has_no_tenant(
    db_session,
):
    tenant = Tenant(
        tenant_name="effective tenant",
        tenant_code="effective-import",
        apaas_tenant_id_str="TID_EFFECTIVE",
    )
    user = User(username="effective-owner", hashed_password="x", is_active=True)
    db_session.add_all([tenant, user])
    await db_session.flush()
    env = PlatformEnv(
        tenant_id=tenant.id,
        env_name="effective-default",
        base_url="https://apaas-effective.example.com/backend",
        platform_tenant_id="TID_EFFECTIVE",
        token="effective-token",
        is_default=True,
        status="connected",
    )
    db_session.add(env)
    await db_session.commit()

    response = await crud.import_from_platform(
        crud.ImportFromPlatformRequest(env_id=env.id, apaas_app_id="remote-effective"),
        AuthContext(
            user=user,
            tenant_id=0,
            tenant_role="platform_admin",
            org_permissions={"*": True},
            tenant_access_scope="unscoped",
        ),
        db_session,
    )

    assert response.platform_env_id == env.id
    saved = await db_session.get(Application, response.id)
    assert saved is not None
    assert saved.tenant_id == tenant.id
