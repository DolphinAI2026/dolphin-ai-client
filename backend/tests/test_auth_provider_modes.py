from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select

import app.routes.auth  # noqa: F401 - ensure login submodule is loaded
import app.seed_data as seed_data
from app.auth import decode_token, get_password_hash, verify_password
from app.config import settings
from app.models import PlatformEnv, User
from app.models.tenant import Role, Tenant, UserTenant
from app.routes.auth import login
from app.routes.mcp_platform import _sync_platform_user
from app.code_runtime.auth import control_plane_access_token
import sys
from app.schemas import UserLogin

auth_routes = sys.modules["app.routes.auth.login"]


def _set_auth_provider(monkeypatch, provider: str) -> None:
    monkeypatch.setattr(
        settings.__class__,
        "auth_provider",
        property(lambda _settings: provider),
        raising=False,
    )


def _set_control_plane_captcha_enabled(monkeypatch, enabled: bool) -> None:
    monkeypatch.setattr(
        settings.__class__,
        "control_plane_captcha_enabled",
        property(lambda _settings: enabled),
        raising=False,
    )


async def _seed_login_user(
    db_session,
    *,
    username: str = "auth_admin",
    password: str = "secret",
    source: str = "apaas",
    platform_admin: bool = True,
):
    tenant = Tenant(
        tenant_name=f"{username} tenant",
        tenant_code=f"{username}-tenant",
    )
    db_session.add(tenant)
    await db_session.flush()

    user = User(
        username=username,
        display_name=username,
        hashed_password=get_password_hash(password),
        account_source=source,
        is_platform_admin=platform_admin,
        is_active=True,
    )
    db_session.add(user)
    await db_session.flush()

    db_session.add(
        UserTenant(
            user_id=user.id,
            tenant_id=tenant.id,
            status=1,
            is_default=True,
        )
    )
    await db_session.flush()
    return user, tenant


@pytest.mark.asyncio
async def test_apaas_identity_does_not_store_external_password_for_local_login(db_session):
    user = await auth_routes._ensure_apaas_user(
        db_session,
        "apaas_identity",
        "external-password",
        {"id": "apaas-user-1"},
        is_platform_admin=False,
    )

    assert verify_password("external-password", user.hashed_password) is False


@pytest.mark.asyncio
async def test_apaas_identity_sync_invalidates_existing_local_password(db_session):
    user, _tenant = await _seed_login_user(
        db_session,
        username="legacy_local_identity",
        password="legacy-local-password",
        source="apaas",
    )

    await auth_routes._ensure_apaas_user(
        db_session,
        user.username,
        "external-password",
        {"id": "apaas-user-2"},
        is_platform_admin=True,
    )

    assert verify_password("legacy-local-password", user.hashed_password) is False
    assert verify_password("external-password", user.hashed_password) is False


@pytest.mark.asyncio
async def test_platform_credential_sync_does_not_create_local_login_password(db_session):
    user, _tenant = await _seed_login_user(
        db_session,
        username="platform_credential_admin",
        password="legacy-local-password",
        source="apaas",
    )

    await _sync_platform_user(
        db_session,
        {
            "account": user.username,
            "base_url": "https://apaas.example/backend",
            "password_enc": "encrypted-password",
            "status": "connected",
        },
        plain_password="external-password",
    )

    assert verify_password("legacy-local-password", user.hashed_password) is False
    assert verify_password("external-password", user.hashed_password) is False


@pytest.mark.asyncio
async def test_local_auth_provider_skips_apaas_and_uses_local_password(db_session, monkeypatch):
    _set_auth_provider(monkeypatch, "local")
    monkeypatch.setattr(settings, "apaas_base_url", "https://apaas.example/backend")
    _user, tenant = await _seed_login_user(db_session, username="local_admin")

    async def unexpected_apaas_login(_user_data, _db):
        raise AssertionError("local auth provider must not call aPaaS login")

    monkeypatch.setattr(auth_routes, "_try_apaas_login_flow", unexpected_apaas_login)

    response = await login(UserLogin(username="local_admin", password="secret"), db_session)

    assert response.access_token
    payload = decode_token(response.access_token)
    assert payload["username"] == "local_admin"
    assert payload["tid"] == tenant.id


@pytest.mark.asyncio
async def test_apaas_auth_provider_does_not_fall_back_to_local_password(db_session, monkeypatch):
    _set_auth_provider(monkeypatch, "apaas")
    monkeypatch.setattr(settings, "apaas_base_url", "")
    await _seed_login_user(db_session, username="apaas_admin")

    async def no_apaas_response(_user_data, _db):
        return None

    monkeypatch.setattr(auth_routes, "_try_apaas_login_flow", no_apaas_response)

    with pytest.raises(HTTPException) as exc_info:
        await login(UserLogin(username="apaas_admin", password="secret"), db_session)

    assert exc_info.value.status_code == 401


@pytest.mark.asyncio
async def test_control_plane_auth_provider_uses_platform_binding_without_merging_apaas_user(
    db_session,
    monkeypatch,
):
    _set_auth_provider(monkeypatch, "control_plane")
    monkeypatch.setattr(settings, "control_plane_binding_enabled", True)
    monkeypatch.setattr(settings, "apaas_base_url", "")
    calls = []
    apaas_user, tenant = await _seed_login_user(
        db_session,
        username="control_plane_admin",
        source="apaas",
    )
    db_session.add(PlatformEnv(
        tenant_id=tenant.id,
        env_name="tenant binding",
        base_url="https://apaas.example/backend",
        platform_tenant_id="apaas-tenant-1",
        username="control_plane_admin",
        status="connected",
    ))
    await db_session.flush()
    tenant_count_before = await db_session.scalar(select(func.count(Tenant.id)))

    async def fake_control_plane_login(username, password, captcha_id, captcha_code):
        calls.append((username, password, captcha_id, captcha_code))
        return SimpleNamespace(
            username="control_plane_admin",
            display_name="Control Plane Admin",
            external_user_id="code-user-1",
            roles=["CONTROL_PLANE_ADMIN"],
            tenant_id="default",
            access_token="control-plane-access-token",
            refresh_token="control-plane-refresh-token",
        )

    monkeypatch.setattr(
        auth_routes,
        "login_to_control_plane",
        fake_control_plane_login,
        raising=False,
    )

    response = await login(
        UserLogin(
            username="control_plane_admin",
            password="password",
            captcha_id="captcha-1",
            captcha_code="0854",
        ),
        db_session,
    )

    assert calls == [("control_plane_admin", "password", "captcha-1", "0854")]
    assert response.access_token

    result = await db_session.execute(
        select(User).where(
            User.username == "control_plane_admin",
            User.account_source == "control_plane",
        )
    )
    user = result.scalar_one()
    assert user.display_name == "Control Plane Admin"
    assert user.coding_user_id == "code-user-1"
    assert user.coding_tenant_id == "default"
    assert control_plane_access_token(user) == "control-plane-access-token"
    assert user.coding_refresh_token.startswith("enc:v1:")
    assert await db_session.scalar(select(func.count(Tenant.id))) == tenant_count_before
    assert apaas_user.coding_user_id is None

    payload = decode_token(response.access_token)
    assert payload["sub"] == str(user.id)
    assert payload["tid"] == tenant.id


@pytest.mark.asyncio
async def test_control_plane_auth_provider_allows_login_without_captcha_when_disabled(
    db_session,
    monkeypatch,
):
    _set_auth_provider(monkeypatch, "control_plane")
    _set_control_plane_captcha_enabled(monkeypatch, False)
    monkeypatch.setattr(settings, "control_plane_binding_enabled", False)
    calls = []

    async def fake_control_plane_login(username, password, captcha_id, captcha_code):
        calls.append((username, password, captcha_id, captcha_code))
        return SimpleNamespace(
            username="workspace_admin",
            display_name="Workspace Admin",
            external_user_id="workspace-user-1",
            roles=["tenant_admin"],
            org_permissions={},
            tenant_id="tenant-1",
            tenant_name="Tenant 1",
            access_token="workspace-access-token",
            refresh_token="workspace-refresh-token",
        )

    async def fake_sync_builtin_llm_configs(_db, tenant_ids=None, *, commit=True):
        assert tenant_ids
        assert commit is False

    monkeypatch.setattr(auth_routes, "login_to_control_plane", fake_control_plane_login)
    monkeypatch.setattr(seed_data, "sync_builtin_llm_configs", fake_sync_builtin_llm_configs)

    response = await login(
        UserLogin(username="workspace_admin", password="password"),
        db_session,
    )

    assert response.access_token
    assert calls == [("workspace_admin", "password", "", "")]
    payload = decode_token(response.access_token)
    user = await db_session.get(User, int(payload["sub"]))
    tenant = await db_session.get(Tenant, int(payload["tid"]))
    assert user is not None
    assert user.coding_tenant_id == "tenant-1"
    assert tenant is not None
    assert tenant.tenant_code == "workspace-tenant-1"
    assert tenant.tenant_name == "Tenant 1"


@pytest.mark.asyncio
async def test_control_plane_captcha_endpoint_reports_not_required_when_disabled(monkeypatch):
    _set_auth_provider(monkeypatch, "control_plane")
    _set_control_plane_captcha_enabled(monkeypatch, False)

    async def unexpected_captcha_fetch():
        raise AssertionError("disabled captcha must not call the upstream captcha endpoint")

    monkeypatch.setattr(auth_routes, "fetch_dolphin_captcha", unexpected_captcha_fetch)

    assert await auth_routes.captcha() == {"required": False}


@pytest.mark.asyncio
async def test_control_plane_login_without_binding_uses_only_control_plane_current_tenant(
    db_session,
    monkeypatch,
):
    _set_auth_provider(monkeypatch, "control_plane")
    monkeypatch.setattr(settings, "control_plane_binding_enabled", False)
    fallback_tenant = Tenant(
        tenant_name="Default Tenant",
        tenant_code="default",
    )
    db_session.add(fallback_tenant)
    await db_session.flush()
    _apaas_user, mapped_tenant = await _seed_login_user(
        db_session,
        username="workspace_admin",
        source="apaas",
    )
    db_session.add(PlatformEnv(
        tenant_id=mapped_tenant.id,
        env_name="legacy mapping",
        base_url="https://apaas.example/backend",
        platform_tenant_id="apaas-tenant-1",
        username="workspace_admin",
        status="connected",
    ))
    await db_session.flush()
    tenant_count_before = await db_session.scalar(select(func.count(Tenant.id)))
    synced_tenant_ids = []

    async def fake_sync_builtin_llm_configs(_db, tenant_ids=None, *, commit=True):
        synced_tenant_ids.extend(tenant_ids or [])
        assert commit is False

    async def fake_control_plane_login(*_args):
        return SimpleNamespace(
            username="workspace_admin",
            display_name="Workspace Admin",
            external_user_id="workspace-user-1",
            roles=["tenant_admin"],
            org_permissions={},
            tenant_id="default",
            tenant_name="Default Tenant",
            access_token="workspace-access-token",
            refresh_token="workspace-refresh-token",
        )

    monkeypatch.setattr(auth_routes, "login_to_control_plane", fake_control_plane_login)
    monkeypatch.setattr(seed_data, "sync_builtin_llm_configs", fake_sync_builtin_llm_configs)

    response = await login(
        UserLogin(
            username="workspace_admin",
            password="password",
            captcha_id="captcha-1",
            captcha_code="0854",
        ),
        db_session,
    )

    assert response.access_token
    assert response.requires_tenant_selection is False
    payload = decode_token(response.access_token)
    tenant = (
        await db_session.execute(
            select(Tenant).where(Tenant.id == payload["tid"])
        )
    ).scalar_one()
    assert tenant.id == fallback_tenant.id
    assert tenant.tenant_code == "default"
    assert await db_session.scalar(select(func.count(Tenant.id))) == tenant_count_before
    membership = (
        await db_session.execute(
            select(UserTenant).where(
                UserTenant.user_id == int(payload["sub"]),
                UserTenant.tenant_id == tenant.id,
            )
        )
    ).scalar_one()
    role = await db_session.get(Role, membership.role_id)
    assert role is not None
    assert role.role_code == "R_tenant_admin"
    assert role.permissions["application:create"] is True
    assert synced_tenant_ids == [tenant.id]


@pytest.mark.asyncio
async def test_control_plane_login_preserves_existing_builder_default_tenant(
    db_session,
    monkeypatch,
):
    monkeypatch.setattr(settings, "control_plane_binding_enabled", False)
    user, existing_tenant = await _seed_login_user(
        db_session,
        username="workspace_admin",
        source="control_plane",
    )
    user.coding_user_id = "workspace-user-1"
    await db_session.flush()

    async def fake_sync_builtin_llm_configs(_db, tenant_ids=None, *, commit=True):
        assert tenant_ids
        assert commit is False

    monkeypatch.setattr(seed_data, "sync_builtin_llm_configs", fake_sync_builtin_llm_configs)

    identity = SimpleNamespace(
        username="workspace_admin",
        display_name="Workspace Admin",
        external_user_id="workspace-user-1",
        roles=["tenant_admin"],
        org_permissions={},
        tenant_id="new-tenant",
        tenant_name="New Tenant",
        access_token="workspace-access-token",
        refresh_token="workspace-refresh-token",
    )

    await auth_routes._ensure_control_plane_user(db_session, identity)

    memberships = (
        await db_session.execute(
            select(UserTenant)
            .where(UserTenant.user_id == user.id)
            .order_by(UserTenant.tenant_id.asc())
        )
    ).scalars().all()
    default_memberships = [membership for membership in memberships if membership.is_default]

    assert len(default_memberships) == 1
    assert default_memberships[0].tenant_id == existing_tenant.id
    assert any(
        membership.tenant_id != existing_tenant.id and not membership.is_default
        for membership in memberships
    )


@pytest.mark.asyncio
async def test_control_plane_system_permission_projects_platform_admin(
    db_session,
    monkeypatch,
):
    _set_auth_provider(monkeypatch, "control_plane")
    monkeypatch.setattr(settings, "control_plane_binding_enabled", False)

    async def fake_control_plane_login(*_args):
        return SimpleNamespace(
            username="system_admin",
            display_name="System Admin",
            external_user_id="system-user-1",
            roles=["tenant_admin"],
            org_permissions={"system.*": True},
            tenant_id="system",
            tenant_name="System Tenant",
            access_token="system-access-token",
            refresh_token="system-refresh-token",
        )

    async def fake_sync_builtin_llm_configs(_db, tenant_ids=None, *, commit=True):
        assert tenant_ids
        assert commit is False

    monkeypatch.setattr(auth_routes, "login_to_control_plane", fake_control_plane_login)
    monkeypatch.setattr(seed_data, "sync_builtin_llm_configs", fake_sync_builtin_llm_configs)

    response = await login(
        UserLogin(
            username="system_admin",
            password="password",
            captcha_id="captcha-1",
            captcha_code="0854",
        ),
        db_session,
    )

    payload = decode_token(response.access_token)
    user = await db_session.get(User, int(payload["sub"]))
    assert user is not None
    assert user.is_platform_admin is True
