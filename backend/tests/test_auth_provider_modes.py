from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import select

import app.routes.auth  # noqa: F401 - ensure login submodule is loaded
from app.auth import decode_token, get_password_hash
from app.config import settings
from app.models import User
from app.models.tenant import Tenant, UserTenant
from app.routes.auth import login
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
async def test_coding_auth_provider_uses_coding_login_and_creates_local_user(db_session, monkeypatch):
    _set_auth_provider(monkeypatch, "coding")
    monkeypatch.setattr(settings, "apaas_base_url", "")
    calls = []

    async def fake_coding_login(username, password):
        calls.append((username, password))
        return SimpleNamespace(
            username="coding_admin",
            display_name="Coding Admin",
            external_user_id="code-user-1",
            roles=["CONTROL_PLANE_ADMIN"],
            access_token="coding-access-token",
            refresh_token="coding-refresh-token",
        )

    monkeypatch.setattr(auth_routes, "login_to_coding_control_plane", fake_coding_login, raising=False)

    response = await login(UserLogin(username="coding_admin", password="password"), db_session)

    assert calls == [("coding_admin", "password")]
    assert response.access_token

    result = await db_session.execute(
        select(User).where(
            User.username == "coding_admin",
            User.account_source == "coding",
        )
    )
    user = result.scalar_one()
    assert user.display_name == "Coding Admin"
    assert user.coding_user_id == "code-user-1"

    payload = decode_token(response.access_token)
    assert payload["sub"] == str(user.id)
