from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy import func, select

import app.routes.auth  # noqa: F401 - ensure login submodule is loaded
import app.seed_data as seed_data
from app.auth import create_access_token, decode_token, get_password_hash, verify_password
from app.config import settings
from app.deps import get_auth_context
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
    assert user.coding_tenant_id is None
    assert control_plane_access_token(user) == "control-plane-access-token"
    assert user.coding_refresh_token.startswith("enc:v1:")
    assert await db_session.scalar(select(func.count(Tenant.id))) == tenant_count_before
    assert apaas_user.coding_user_id is None

    payload = decode_token(response.access_token)
    assert payload["sub"] == str(user.id)
    assert payload["type"] == "control_plane_code"
    assert payload["cp_tid"] == "default"
    assert "tid" not in payload


@pytest.mark.asyncio
async def test_control_plane_auth_provider_allows_login_without_captcha_when_disabled(
    db_session,
    monkeypatch,
):
    _set_auth_provider(monkeypatch, "control_plane")
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
    assert user is not None
    assert user.coding_tenant_id is None
    assert payload["type"] == "control_plane_code"
    assert payload["cp_tid"] == "tenant-1"
    assert "tid" not in payload


@pytest.mark.asyncio
async def test_control_plane_login_prefers_the_users_own_organization_over_shared_default(
    db_session,
    monkeypatch,
):
    _set_auth_provider(monkeypatch, "control_plane")
    monkeypatch.setattr(settings, "control_plane_binding_enabled", False)

    async def fake_control_plane_login(*_args):
        return auth_routes.ControlPlaneAuthResult(
            username="admin",
            display_name="Admin",
            external_user_id="admin-user",
            roles=["CONTROL_PLANE_ADMIN"],
            tenant_id="2077284540335579137",
            tenant_name="示例租户",
            available_tenants=[
                {"tenant_id": "0", "tenant_name": "admin 的组织"},
                {"tenant_id": "2077284540335579137", "tenant_name": "示例租户"},
            ],
            access_token="control-plane-access-token",
        )

    monkeypatch.setattr(auth_routes, "login_to_control_plane", fake_control_plane_login)

    response = await login(UserLogin(username="admin", password="password"), db_session)

    payload = decode_token(response.access_token)
    assert payload["type"] == "control_plane_code"
    assert payload["cp_tid"] == "0"
    assert payload["cp_tname"] == "admin 的组织"


@pytest.mark.asyncio
async def test_desktop_control_plane_login_keeps_identity_as_cache_only(
    db_session,
    monkeypatch,
):
    _set_auth_provider(monkeypatch, "control_plane")
    monkeypatch.setenv("DESKTOP_MODE", "1")
    monkeypatch.setattr(settings, "control_plane_binding_enabled", False)
    monkeypatch.setattr(settings, "accepted_token_issuers", "ai-builder,desktop-sidecar")
    tenant_count_before = await db_session.scalar(select(func.count(Tenant.id)))

    async def fake_control_plane_login(*_args):
        return SimpleNamespace(
            username="desktop_admin",
            display_name="Desktop Admin",
            external_user_id="remote-user-1",
            roles=["CONTROL_PLANE_ADMIN"],
            org_permissions={"system.*": True},
            tenant_id="2077284540335579137",
            tenant_name="示例租户",
            access_token="desktop-control-plane-token",
            refresh_token="desktop-refresh-token",
        )

    monkeypatch.setattr(auth_routes, "login_to_control_plane", fake_control_plane_login)

    response = await login(
        UserLogin(username="desktop_admin", password="password"),
        db_session,
    )

    payload = decode_token(response.access_token)
    user = await db_session.get(User, int(payload["sub"]))
    memberships = (
        await db_session.execute(
            select(UserTenant).where(UserTenant.user_id == user.id)
        )
    ).scalars().all()

    assert payload["iss"] == "desktop-sidecar"
    assert "tid" not in payload
    assert payload["cp_tid"] == "2077284540335579137"
    assert payload["cp_tname"] == "示例租户"
    assert payload["cp_trole"] == "platform_admin"
    assert response.entry_path == "/code/apps"
    assert user.coding_tenant_id == "2077284540335579137"
    assert memberships == []
    assert await db_session.scalar(select(func.count(Tenant.id))) == tenant_count_before


@pytest.mark.asyncio
async def test_control_plane_session_exchange_issues_builder_token_for_selected_remote_tenant(
    db_session,
    monkeypatch,
):
    monkeypatch.delenv("DESKTOP_MODE", raising=False)
    monkeypatch.setattr(settings, "control_plane_binding_enabled", False)

    async def fake_control_plane_identity(token: str):
        assert token == "control-plane-token"
        return auth_routes.ControlPlaneAuthResult(
            username="remote_admin",
            display_name="Remote Admin",
            external_user_id="remote-user-1",
            roles=["TENANT_ADMIN"],
            tenant_id="tenant-default",
            tenant_name="Default tenant",
            available_tenants=[
                {"tenant_id": "tenant-default", "tenant_name": "Default tenant"},
                {"tenant_id": "tenant-selected", "tenant_name": "Selected tenant"},
            ],
            access_token=token,
        )

    monkeypatch.setattr(
        auth_routes,
        "fetch_control_plane_identity",
        fake_control_plane_identity,
    )

    response = await auth_routes.exchange_control_plane_session(
        HTTPAuthorizationCredentials(scheme="Bearer", credentials="control-plane-token"),
        "tenant-selected",
        db_session,
    )

    payload = decode_token(response.access_token)
    user = await db_session.get(User, int(payload["sub"]))
    assert user is not None
    assert user.coding_tenant_id is None
    assert payload["type"] == "control_plane_code"
    assert payload["cp_tid"] == "tenant-selected"
    assert "tid" not in payload


@pytest.mark.asyncio
async def test_desktop_control_plane_context_ignores_legacy_local_tenant_ticket(
    db_session,
    monkeypatch,
):
    monkeypatch.setenv("DESKTOP_MODE", "1")
    tenant = Tenant(tenant_name="历史本地租户", tenant_code="legacy-local")
    user = User(
        username="desktop_legacy",
        hashed_password=get_password_hash("secret"),
        account_source="control_plane",
        coding_tenant_id="2077284540335579137",
        is_active=True,
    )
    db_session.add_all([tenant, user])
    await db_session.flush()
    db_session.add(UserTenant(user_id=user.id, tenant_id=tenant.id, status=1, is_default=True))
    await db_session.flush()
    legacy_token = create_access_token(user, tenant_id=tenant.id)

    ctx = await get_auth_context(
        SimpleNamespace(credentials=legacy_token),
        db_session,
    )

    assert ctx.tenant_id == 0
    assert ctx.control_plane_tenant_id == "2077284540335579137"
    assert ctx.tenant_role == "member"


@pytest.mark.asyncio
async def test_control_plane_captcha_endpoint_hides_incomplete_upstream_response(monkeypatch):
    _set_auth_provider(monkeypatch, "control_plane")

    async def incomplete_captcha_fetch():
        return None

    monkeypatch.setattr(auth_routes, "fetch_dolphin_captcha", incomplete_captcha_fetch)

    assert await auth_routes.captcha() == {"required": False}


@pytest.mark.asyncio
async def test_control_plane_captcha_shows_complete_upstream_response(monkeypatch):
    _set_auth_provider(monkeypatch, "control_plane")

    async def fake_fetch_dolphin_captcha():
        return {"captcha_id": "remote-captcha-id", "image_data": "data:image/png;base64,abc"}

    monkeypatch.setattr(auth_routes, "fetch_dolphin_captcha", fake_fetch_dolphin_captcha)

    assert await auth_routes.captcha() == {
        "required": True,
        "captcha_id": "remote-captcha-id",
        "image_data": "data:image/png;base64,abc",
    }


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
    assert payload["type"] == "control_plane_code"
    assert payload["cp_tid"] == "default"
    assert "tid" not in payload
    assert await db_session.scalar(select(func.count(Tenant.id))) == tenant_count_before
    assert synced_tenant_ids == []


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
    assert len(memberships) == 1


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
