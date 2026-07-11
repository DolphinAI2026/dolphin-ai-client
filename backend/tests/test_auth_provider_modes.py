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


def _set_account_binding_enabled(monkeypatch, enabled: bool) -> None:
    monkeypatch.setattr(
        settings.__class__,
        "auth_account_binding_enabled",
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


@pytest.mark.parametrize("provider", ["control_plane", "coding"])
def test_control_plane_auth_provider_accepts_canonical_mode_and_coding_alias(
    monkeypatch,
    provider,
):
    _set_auth_provider(monkeypatch, provider)

    assert auth_routes._auth_provider() == "control_plane"


def test_invalid_auth_provider_lists_canonical_modes_and_coding_alias(monkeypatch):
    _set_auth_provider(monkeypatch, "unsupported")

    with pytest.raises(HTTPException) as exc_info:
        auth_routes._auth_provider()

    assert exc_info.value.status_code == 500
    assert exc_info.value.detail == (
        "AUTH_PROVIDER must be one of local, apaas, control_plane "
        "(coding is a compatibility alias)"
    )


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


@pytest.mark.asyncio
async def test_control_plane_login_refreshes_apaas_binding_after_commit(monkeypatch):
    _set_account_binding_enabled(monkeypatch, True)
    events = []
    refresh_calls = []

    class RecordingDb:
        async def commit(self):
            events.append("commit")

    async def fake_coding_login(username, password):
        assert (username, password) == ("login-name", "password")
        return SimpleNamespace(
            username="canonical-name",
            display_name="Control Plane User",
            external_user_id="cp-user-1",
            roles=[],
            access_token="cp-access-token",
            refresh_token="cp-refresh-token",
        )

    async def fake_ensure_coding_user(_db, identity):
        events.append("ensure-user")
        assert identity.username == "canonical-name"
        return (
            SimpleNamespace(id=7, username=identity.username),
            SimpleNamespace(tenant_code="builder-default"),
        )

    async def fake_issue_login_response(_db, user):
        events.append("issue-response")
        assert user.id == 7
        return SimpleNamespace(access_token="builder-token")

    async def fake_refresh(_db, **kwargs):
        events.append("refresh")
        refresh_calls.append(kwargs)
        return SimpleNamespace(account=None, code="ENTERPRISE_AUTH_BINDING_NOT_FOUND")

    monkeypatch.setattr(auth_routes, "login_to_coding_control_plane", fake_coding_login)
    monkeypatch.setattr(auth_routes, "_ensure_coding_user", fake_ensure_coding_user)
    monkeypatch.setattr(auth_routes, "_issue_login_response_for_user", fake_issue_login_response)
    monkeypatch.setattr(auth_routes, "refresh_bound_account_after_login", fake_refresh, raising=False)
    monkeypatch.setattr(auth_routes, "control_plane_base_url", lambda: "https://cp.example")

    response = await auth_routes._coding_login_response(
        UserLogin(username="login-name", password="password"),
        RecordingDb(),
    )

    assert response.access_token == "builder-token"
    assert events == ["ensure-user", "commit", "issue-response", "refresh"]
    assert refresh_calls == [
        {
            "source_provider": "control_plane",
            "source_base_url": "https://cp.example",
            "source_tenant_ref": "builder-default",
            "source_account": "login-name",
            "target_provider": "apaas",
        }
    ]


@pytest.mark.asyncio
async def test_control_plane_login_ignores_binding_refresh_failure(monkeypatch, caplog):
    _set_account_binding_enabled(monkeypatch, True)
    events = []

    class RecordingDb:
        async def commit(self):
            events.append("commit")

    async def fake_coding_login(_username, _password):
        return SimpleNamespace(username="cp-user")

    async def fake_ensure_coding_user(_db, _identity):
        return (
            SimpleNamespace(id=8),
            SimpleNamespace(tenant_code="builder-default"),
        )

    async def fake_issue_login_response(_db, _user):
        events.append("issue-response")
        return SimpleNamespace(access_token="builder-token")

    async def failing_refresh(_db, **_kwargs):
        events.append("refresh")
        raise RuntimeError("secret-bearing upstream error")

    monkeypatch.setattr(auth_routes, "login_to_coding_control_plane", fake_coding_login)
    monkeypatch.setattr(auth_routes, "_ensure_coding_user", fake_ensure_coding_user)
    monkeypatch.setattr(auth_routes, "_issue_login_response_for_user", fake_issue_login_response)
    monkeypatch.setattr(auth_routes, "refresh_bound_account_after_login", failing_refresh, raising=False)
    monkeypatch.setattr(auth_routes, "control_plane_base_url", lambda: "https://cp.example")

    response = await auth_routes._coding_login_response(
        UserLogin(username="cp-user", password="do-not-log"),
        RecordingDb(),
    )

    assert response.access_token == "builder-token"
    assert events == ["commit", "issue-response", "refresh"]
    assert "secret-bearing upstream error" not in caplog.text


@pytest.mark.asyncio
async def test_apaas_login_refreshes_control_plane_binding_after_commit(monkeypatch):
    _set_account_binding_enabled(monkeypatch, True)
    monkeypatch.setattr(settings, "apaas_base_url", "https://apaas.example/backend")
    events = []
    refresh_calls = []

    class RecordingDb:
        async def commit(self):
            events.append("commit")

    async def no_platform_login(_username, _password):
        return None, {}

    async def backend_login(_username, _password, _tenant_id=""):
        return "apaas-token", {
            "data": {
                "defaultTenantId": "apaas-tenant-1",
                "tenantInfos": [
                    {
                        "tenantId": "apaas-tenant-1",
                        "tenantName": "Tenant One",
                        "tenantCode": "tenant-one",
                    }
                ],
                "user": {"id": "apaas-user-1"},
            }
        }

    async def no_switchable_tenants(_token, _tenant_id):
        return []

    async def fake_ensure_user(_db, username, _password, _user_info, is_platform_admin):
        assert is_platform_admin is False
        return SimpleNamespace(
            id=9,
            username=username,
            apaas_user_id="apaas-user-1",
            apaas_tenant_id=None,
        )

    async def fake_ensure_tenant(_db, _item, _username="", _password=""):
        return SimpleNamespace(
            id=10,
            tenant_name="Tenant One",
            tenant_code="tenant-one",
            apaas_tenant_id_str="apaas-tenant-1",
        )

    async def no_op(*_args, **_kwargs):
        return None

    async def fake_refresh(_db, **kwargs):
        events.append("refresh")
        refresh_calls.append(kwargs)
        return SimpleNamespace(account=None, code="ENTERPRISE_AUTH_BINDING_NOT_FOUND")

    monkeypatch.setattr(auth_routes, "_apaas_platform_login", no_platform_login)
    monkeypatch.setattr(auth_routes, "_apaas_backend_login", backend_login)
    monkeypatch.setattr(auth_routes, "_apaas_switchable_tenants", no_switchable_tenants)
    monkeypatch.setattr(auth_routes, "_ensure_apaas_user", fake_ensure_user)
    monkeypatch.setattr(auth_routes, "_ensure_apaas_tenant", fake_ensure_tenant)
    monkeypatch.setattr(auth_routes, "_upsert_user_credential", no_op)
    monkeypatch.setattr(auth_routes, "_sync_user_membership", no_op)
    monkeypatch.setattr(auth_routes, "create_access_token", lambda *_args, **_kwargs: "builder-token")
    monkeypatch.setattr(auth_routes, "refresh_bound_account_after_login", fake_refresh, raising=False)
    monkeypatch.setattr("app.routes.current_app.set_current_app", lambda *_args: None)
    monkeypatch.setattr("app.routes.current_app.set_apaas_user_alias", lambda *_args: None)

    response = await auth_routes._try_apaas_login_flow(
        UserLogin(username="apaas-login", password="password"),
        RecordingDb(),
    )

    assert response.access_token == "builder-token"
    assert events == ["commit", "refresh"]
    assert refresh_calls == [
        {
            "source_provider": "apaas",
            "source_base_url": "https://apaas.example/backend",
            "source_tenant_ref": "apaas-tenant-1",
            "source_account": "apaas-login",
            "target_provider": "control_plane",
        }
    ]


@pytest.mark.asyncio
async def test_apaas_platform_admin_without_tenant_skips_binding_refresh(monkeypatch):
    _set_account_binding_enabled(monkeypatch, True)
    monkeypatch.setattr(settings, "apaas_base_url", "https://apaas.example/backend")
    refresh_calls = []

    class RecordingDb:
        async def commit(self):
            return None

    async def platform_login(_username, _password):
        return "platform-token", {"data": {"user": {"id": "platform-user-1"}}}

    async def no_backend_login(_username, _password, _tenant_id=""):
        return None, {}

    async def no_tenants(_token):
        return []

    async def fake_ensure_user(_db, username, _password, _user_info, is_platform_admin):
        assert is_platform_admin is True
        return SimpleNamespace(
            id=11,
            username=username,
            apaas_user_id="platform-user-1",
            apaas_tenant_id=None,
        )

    async def fake_refresh(_db, **kwargs):
        refresh_calls.append(kwargs)

    async def no_op(*_args, **_kwargs):
        return None

    monkeypatch.setattr(auth_routes, "_apaas_platform_login", platform_login)
    monkeypatch.setattr(auth_routes, "_apaas_backend_login", no_backend_login)
    monkeypatch.setattr(auth_routes, "_apaas_all_tenants", no_tenants)
    monkeypatch.setattr(auth_routes, "_ensure_apaas_user", fake_ensure_user)
    monkeypatch.setattr(auth_routes, "_upsert_platform_credential", no_op)
    monkeypatch.setattr(auth_routes, "create_access_token", lambda *_args, **_kwargs: "builder-token")
    monkeypatch.setattr(auth_routes, "refresh_bound_account_after_login", fake_refresh, raising=False)

    response = await auth_routes._try_apaas_login_flow(
        UserLogin(username="platform-admin", password="password"),
        RecordingDb(),
    )

    assert response.access_token == "builder-token"
    assert response.has_tenant_context is False
    assert refresh_calls == []
