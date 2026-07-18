from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.auth import create_access_token, decode_token, get_password_hash
from app.config import settings
from app.deps import AuthContext, get_auth_context, resolve_effective_tenant_id
from app.models import APaaSPlatformCredential, APaaSUserCredential, LLMConfig, PlatformEnv, User
from app.models.tenant import Role, Tenant, UserTenant
import sys
import app.routes.auth  # 确保包（含子模块）已加载
auth_routes = sys.modules["app.routes.auth.login"]  # login 子模块，monkeypatch 在此生效
from app.routes.auth import _ensure_apaas_tenant, _try_apaas_login_flow, login
from app.routes.llm_configs import list_llm_config_options, list_llm_configs
from app.routes.platform_envs import list_envs
from app.schemas import UserLogin


async def _seed_platform_admin(db_session):
    tenant = Tenant(tenant_name="Default Tenant", tenant_code="default")
    db_session.add(tenant)
    await db_session.flush()

    user = User(
        username="admin",
        hashed_password=get_password_hash("secret"),
        is_platform_admin=True,
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
async def test_platform_admin_login_token_uses_default_tenant(db_session, monkeypatch):
    _user, tenant = await _seed_platform_admin(db_session)

    async def no_apaas_login(_user_data, _db):
        return None

    monkeypatch.setattr(auth_routes, "_try_apaas_login_flow", no_apaas_login)

    response = await login(UserLogin(username="admin", password="secret"), db_session)

    payload = decode_token(response.access_token)
    assert payload["tid"] == tenant.id


@pytest.mark.asyncio
async def test_platform_admin_legacy_token_resolves_default_tenant(db_session):
    user, tenant = await _seed_platform_admin(db_session)
    token_without_tenant = create_access_token({"sub": user.id}, tenant_id=None)

    ctx = await get_auth_context(SimpleNamespace(credentials=token_without_tenant), db_session)

    assert ctx.user.id == user.id
    assert ctx.tenant_id == tenant.id
    assert ctx.tenant_role == "platform_admin"
    assert ctx.org_permissions == {"*": True}


@pytest.mark.asyncio
async def test_control_plane_context_normalizes_stale_token_to_current_platform_tenant(
    db_session,
    monkeypatch,
):
    monkeypatch.setattr(settings, "control_plane_binding_enabled", False)
    current = Tenant(tenant_name="Current", tenant_code="default")
    stale = Tenant(tenant_name="Stale", tenant_code="workspace-other")
    user = User(
        username="control-plane-admin",
        hashed_password=get_password_hash("secret"),
        account_source="control_plane",
        coding_tenant_id="default",
        is_platform_admin=True,
        is_active=True,
    )
    db_session.add_all([current, stale, user])
    await db_session.flush()
    db_session.add_all([
        UserTenant(
            user_id=user.id,
            tenant_id=current.id,
            status=1,
            is_default=True,
        ),
        UserTenant(
            user_id=user.id,
            tenant_id=stale.id,
            status=1,
            is_default=False,
        ),
    ])
    await db_session.commit()
    stale_token = create_access_token(user.id, tenant_id=stale.id)

    ctx = await get_auth_context(SimpleNamespace(credentials=stale_token), db_session)

    assert ctx.tenant_id == current.id


@pytest.mark.asyncio
async def test_auth_context_uses_bound_apaas_tenant_for_current_local_tenant(db_session):
    tenant = Tenant(
        tenant_name="Bound Tenant",
        tenant_code="bound",
        apaas_tenant_id_str="apaas-tenant-current",
    )
    db_session.add(tenant)
    await db_session.flush()

    user = User(
        username="tenant-admin",
        hashed_password=get_password_hash("secret"),
        apaas_user_id="apaas-user-1",
        apaas_tenant_id="apaas-tenant-stale",
        is_active=True,
    )
    db_session.add(user)
    await db_session.flush()

    role = Role(
        tenant_id=tenant.id,
        role_name="租户管理员",
        role_code="R_tenant_admin",
        permissions={"application:create": True},
    )
    db_session.add(role)
    await db_session.flush()
    db_session.add(UserTenant(user_id=user.id, tenant_id=tenant.id, role_id=role.id, status=1))
    await db_session.commit()

    token = create_access_token(user.id, tenant_id=tenant.id)
    ctx = await get_auth_context(SimpleNamespace(credentials=token), db_session)

    assert ctx.apaas_user_id == "apaas-user-1"
    assert ctx.apaas_tenant_id == "apaas-tenant-current"


@pytest.mark.asyncio
async def test_platform_admin_routes_fall_back_to_active_tenant_without_membership(db_session):
    tenant = Tenant(tenant_name="Default Tenant", tenant_code="default")
    db_session.add(tenant)
    await db_session.flush()

    user = User(
        username="admin-no-membership",
        hashed_password=get_password_hash("secret"),
        is_platform_admin=True,
        is_active=True,
    )
    db_session.add(user)
    await db_session.flush()

    db_session.add(
        LLMConfig(
            tenant_id=tenant.id,
            config_name="内置通用模型 (gpt-5.5)",
            provider="dolphin",
            base_url="http://ai-agent.dfy.definesys.cn/omnigate/0",
            api_key_enc="test-key",
            model="gpt-5.5",
            purpose="all",
            is_default=True,
            status="active",
        )
    )
    db_session.add(
        PlatformEnv(
            tenant_id=tenant.id,
            env_name="测试环境",
            base_url="https://apaas-trial.definesys.cn/backend",
            platform_tenant_id="tenant-001",
            username="admin",
            status="connected",
        )
    )
    await db_session.commit()

    ctx = AuthContext(
        user=user,
        tenant_id=0,
        tenant_role="platform_admin",
        org_permissions={"*": True},
    )

    assert await resolve_effective_tenant_id(db_session, ctx) == tenant.id

    llm_rows = await list_llm_configs(ctx, db_session)
    assert [row.model for row in llm_rows] == ["gpt-5.5"]

    llm_options = await list_llm_config_options(ctx, db_session, purpose="builder")
    assert [row.model for row in llm_options] == ["gpt-5.5"]

    env_rows = await list_envs(ctx, db_session)
    assert [row["env_name"] for row in env_rows] == ["测试环境"]


@pytest.mark.asyncio
async def test_apaas_platform_admin_login_syncs_all_tenants_but_returns_loginable_tenants(
    db_session,
    monkeypatch,
):
    monkeypatch.setattr(settings, "apaas_base_url", "https://apaas-trial.definesys.cn/backend")
    monkeypatch.setattr(settings, "apaas_tenant_id", "")

    async def fake_platform_login(_username, _password):
        return "platform.token.sig", {"data": {"token": "platform.token.sig"}}

    async def fake_backend_login(_username, _password, _tenant_id=""):
        return "backend.token.sig", {
            "data": {
                "token": "backend.token.sig",
                "defaultTenantId": "822902364821258241",
                "user": {"id": "apaas-user-1", "username": "admin"},
            }
        }

    async def fake_all_tenants(_platform_token):
        return [
            {
                "tenantId": "822902364821258241",
                "tenantName": "得帆",
                "tenantCode": "df",
            },
            {
                "tenantId": "828940713101099009",
                "tenantName": "火星团队",
                "tenantCode": "mars",
            },
        ]

    monkeypatch.setattr(auth_routes, "_apaas_platform_login", fake_platform_login)
    monkeypatch.setattr(auth_routes, "_apaas_backend_login", fake_backend_login)
    monkeypatch.setattr(auth_routes, "_apaas_all_tenants", fake_all_tenants)

    response = await _try_apaas_login_flow(UserLogin(username="admin", password="secret"), db_session)

    assert response is not None
    assert response.is_platform_admin is True
    assert response.has_tenant_context is True
    assert [(t.tenant_name, t.tenant_code) for t in response.tenants] == [
        ("得帆", "df"),
    ]

    tenants = (await db_session.execute(select(Tenant).order_by(Tenant.id))).scalars().all()
    assert len(tenants) == 2
    assert [t.apaas_tenant_id_str for t in tenants] == [
        "822902364821258241",
        "828940713101099009",
    ]

    llm_rows = (await db_session.execute(select(LLMConfig))).scalars().all()
    assert llm_rows == []

    platform_creds = (await db_session.execute(select(APaaSPlatformCredential))).scalars().all()
    user_creds = (await db_session.execute(select(APaaSUserCredential))).scalars().all()
    assert len(platform_creds) == 1
    assert len(user_creds) == 1
    assert user_creds[0].apaas_tenant_id == "822902364821258241"


@pytest.mark.asyncio
async def test_apaas_platform_admin_without_tenant_access_enters_platform_admin(
    db_session,
    monkeypatch,
):
    monkeypatch.setattr(settings, "apaas_base_url", "https://apaas-trial.definesys.cn/backend")

    async def fake_platform_login(_username, _password):
        return "platform.token.sig", {"data": {"token": "platform.token.sig"}}

    async def fake_backend_login(_username, _password, _tenant_id=""):
        return None, {"code": "error", "message": "no tenant access"}

    async def fake_all_tenants(_platform_token):
        return [
            {
                "tenantId": "822902364821258241",
                "tenantName": "得帆",
                "tenantCode": "df",
            },
        ]

    monkeypatch.setattr(auth_routes, "_apaas_platform_login", fake_platform_login)
    monkeypatch.setattr(auth_routes, "_apaas_backend_login", fake_backend_login)
    monkeypatch.setattr(auth_routes, "_apaas_all_tenants", fake_all_tenants)

    response = await _try_apaas_login_flow(UserLogin(username="admin", password="secret"), db_session)

    assert response is not None
    assert response.is_platform_admin is True
    assert response.has_tenant_context is False
    assert response.entry_path == "/platform-admin"
    assert response.tenants is None

    tenants = (await db_session.execute(select(Tenant))).scalars().all()
    assert len(tenants) == 1
    assert tenants[0].tenant_name == "得帆"


@pytest.mark.asyncio
async def test_apaas_platform_admin_probe_timeout_preserves_cached_identity(
    db_session,
    monkeypatch,
):
    monkeypatch.setattr(settings, "apaas_base_url", "https://apaas-trial.definesys.cn/backend")

    user = User(
        username="admin",
        display_name="管理",
        hashed_password=get_password_hash("secret"),
        account_source="apaas",
        is_platform_admin=False,
        is_active=True,
        apaas_user_id="apaas-user-1",
    )
    db_session.add(user)
    await db_session.flush()
    db_session.add(
        APaaSPlatformCredential(
            user_id=user.id,
            base_url="https://apaas-trial.definesys.cn",
            account="admin",
            password_enc="enc",
            token="cached-platform-token",
            status="connected",
        )
    )
    await db_session.flush()

    async def timeout_platform_login(_username, _password):
        raise TimeoutError("platform probe timed out")

    async def fake_backend_login(_username, _password, _tenant_id=""):
        return "backend.token.sig", {
            "data": {
                "token": "backend.token.sig",
                "defaultTenantId": "822902364821258241",
                "user": {"id": "apaas-user-1", "username": "admin"},
                "tenant": {
                    "tenantId": "822902364821258241",
                    "tenantName": "得帆",
                    "tenantCode": "df",
                },
            }
        }

    async def fake_switchable_tenants(_backend_token, _default_tenant_id):
        return []

    monkeypatch.setattr(auth_routes, "_apaas_platform_login", timeout_platform_login)
    monkeypatch.setattr(auth_routes, "_apaas_backend_login", fake_backend_login)
    monkeypatch.setattr(auth_routes, "_apaas_switchable_tenants", fake_switchable_tenants)

    response = await _try_apaas_login_flow(UserLogin(username="admin", password="secret"), db_session)

    assert response is not None
    assert response.is_platform_admin is True
    refreshed = (await db_session.execute(select(User).where(User.id == user.id))).scalar_one()
    assert refreshed.is_platform_admin is True


@pytest.mark.asyncio
async def test_ensure_apaas_tenant_reuses_existing_env_for_tenant(db_session, monkeypatch):
    monkeypatch.setattr(settings, "apaas_base_url", "https://apaas-trial.definesys.cn/backend")

    tenant = Tenant(
        tenant_name="得帆-旧",
        tenant_code="df",
        status=1,
        apaas_tenant_id_str="822902364821258241",
    )
    db_session.add(tenant)
    await db_session.flush()

    env = PlatformEnv(
        tenant_id=tenant.id,
        env_name="得帆-旧",
        alias="df",
        base_url="https://old.example/backend",
        platform_tenant_id="old-platform-tenant",
        is_default=True,
        status="connected",
    )
    db_session.add(env)
    await db_session.flush()

    result = await _ensure_apaas_tenant(
        db_session,
        {
            "tenantId": "822902364821258241",
            "tenantName": "得帆-新",
            "tenantCode": "df",
        },
        login_username="admin",
        login_password="secret",
    )
    await db_session.flush()

    assert result.id == tenant.id
    env_rows = (await db_session.execute(select(PlatformEnv))).scalars().all()
    assert len(env_rows) == 1
    assert env_rows[0].id == env.id
    assert env_rows[0].env_name == "得帆-新"
    assert env_rows[0].base_url == "https://apaas-trial.definesys.cn/backend"
    assert env_rows[0].platform_tenant_id == "822902364821258241"
    assert env_rows[0].username == "admin"
    assert env_rows[0].password_enc
