from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select

import app.routes.auth  # noqa: F401 - ensure login submodule is loaded
from app.auth import decode_token, get_password_hash
from app.config import settings
from app.models import PlatformEnv, User
from app.models.tenant import Tenant, UserTenant
from app.routes.auth import login
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

    async def fake_control_plane_login(username, password):
        calls.append((username, password))
        return SimpleNamespace(
            username="control_plane_admin",
            display_name="Control Plane Admin",
            external_user_id="code-user-1",
            roles=["CONTROL_PLANE_ADMIN"],
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
        UserLogin(username="control_plane_admin", password="password"),
        db_session,
    )

    assert calls == [("control_plane_admin", "password")]
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
    assert control_plane_access_token(user) == "control-plane-access-token"
    assert user.coding_refresh_token.startswith("enc:v1:")
    assert await db_session.scalar(select(func.count(Tenant.id))) == tenant_count_before
    assert apaas_user.coding_user_id is None

    payload = decode_token(response.access_token)
    assert payload["sub"] == str(user.id)
    assert payload["tid"] == tenant.id


@pytest.mark.asyncio
async def test_control_plane_binding_stores_exchanged_user_token(db_session, monkeypatch):
    user, _tenant = await _seed_login_user(
        db_session,
        username="federated_admin",
        source="apaas",
    )

    async def fake_exchange(subject_token, tenant_id):
        assert subject_token == "apaas-token"
        assert tenant_id == "apaas-tenant-1"
        return SimpleNamespace(
            status="TOKEN_ISSUED",
            access_token="fresh-control-plane-token",
            refresh_token="fresh-refresh-token",
            binding_challenge=None,
            control_plane_user_id="cp-user-1",
        )

    monkeypatch.setattr(auth_routes, "exchange_apaas_identity", fake_exchange)

    await auth_routes._store_federated_control_plane_token(
        user,
        subject_token="apaas-token",
        tenant_id="apaas-tenant-1",
    )

    assert user.coding_user_id == "cp-user-1"
    assert control_plane_access_token(user) == "fresh-control-plane-token"
    assert user.coding_refresh_token.startswith("enc:v1:")


@pytest.mark.asyncio
async def test_apaas_binding_challenge_requires_explicit_control_plane_proof(db_session, monkeypatch):
    user, _tenant = await _seed_login_user(
        db_session,
        username="binding_admin",
        source="apaas",
    )
    async def fake_exchange(_subject_token, _tenant_id):
        return SimpleNamespace(
            status="BINDING_REQUIRED",
            access_token=None,
            refresh_token=None,
            binding_challenge="challenge-1",
            control_plane_user_id=None,
            trace_id="trace-1",
        )

    monkeypatch.setattr(auth_routes, "exchange_apaas_identity", fake_exchange)

    with pytest.raises(HTTPException) as exc_info:
        await auth_routes._store_federated_control_plane_token(
            user,
            subject_token="apaas-token",
            tenant_id="apaas-tenant-2",
        )

    assert exc_info.value.status_code == 403
    assert "管理员预先完成账号绑定" in str(exc_info.value.detail)
