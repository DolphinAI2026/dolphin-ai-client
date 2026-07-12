import pytest
from sqlalchemy import select

from app.deps import AuthContext
from app.models import APaaSPlatformCredential, PlatformEnv, Tenant, User
from app.routes import mcp_platform


async def _seed_admin_and_tenant(db_session):
    tenant = Tenant(tenant_name="客户一", tenant_code="customer-1")
    admin_user = User(
        username="apaas-admin",
        hashed_password="test-hash",
        is_platform_admin=True,
        is_active=True,
    )
    db_session.add_all([tenant, admin_user])
    await db_session.flush()

    credential = APaaSPlatformCredential(
        user_id=admin_user.id,
        base_url="https://apaas.example.com",
        account="apaas-admin",
        password_enc="encrypted-password",
        token="platform-token",
        is_default=True,
        status="connected",
    )
    db_session.add(credential)
    await db_session.commit()

    ctx = AuthContext(
        user=admin_user,
        tenant_id=tenant.id,
        tenant_role="platform_admin",
        org_permissions={"*": True},
    )
    return tenant, credential, ctx


@pytest.mark.asyncio
async def test_bind_apaas_tenant_environment_creates_default_env_with_selected_admin(db_session):
    tenant, credential, ctx = await _seed_admin_and_tenant(db_session)

    request_type = getattr(mcp_platform, "APaaSTenantBindingRequest")
    bind_environment = getattr(mcp_platform, "bind_apaas_tenant_environment")
    result = await bind_environment(
        tenant.id,
        request_type(
            admin_id=f"db_platform_credential_{credential.id}",
            base_url="https://apaas.example.com/backend",
            platform_tenant_id="tenant-100",
        ),
        ctx,
        db_session,
    )

    env = (await db_session.execute(select(PlatformEnv))).scalar_one()
    await db_session.refresh(tenant)
    assert tenant.apaas_env_id == env.id
    assert tenant.apaas_tenant_id_str == "tenant-100"
    assert env.base_url == "https://apaas.example.com/backend"
    assert env.platform_tenant_id == "tenant-100"
    assert env.username == "apaas-admin"
    assert env.password_enc == "encrypted-password"
    assert env.token is None
    assert env.status == "disconnected"
    assert env.is_default is True
    assert result["environmentBound"] is True
    assert result["adminAccount"] == "apaas-admin"
    assert "password_enc" not in result
    assert "token" not in result

    local_rows = await mcp_platform.list_apaas_tenants(
        ctx,
        db_session,
        page_size=500,
        local_only=True,
    )
    row = local_rows["items"][0]
    assert row["baseUrl"] == "https://apaas.example.com/backend"
    assert row["platformTenantId"] == "tenant-100"
    assert row["environmentBound"] is True
    assert row["adminAccount"] == "apaas-admin"
    assert "password_enc" not in row
    assert "token" not in row


@pytest.mark.asyncio
async def test_bind_apaas_tenant_environment_updates_env_and_clears_stale_token(db_session):
    tenant, credential, ctx = await _seed_admin_and_tenant(db_session)
    env = PlatformEnv(
        tenant_id=tenant.id,
        env_name="旧环境",
        base_url="https://old.example.com/backend",
        platform_tenant_id="old-tenant",
        username="old-admin",
        password_enc="old-password",
        token="stale-token",
        is_default=True,
        status="connected",
    )
    db_session.add(env)
    await db_session.flush()
    tenant.apaas_env_id = env.id
    tenant.apaas_tenant_id_str = "old-tenant"
    await db_session.commit()

    request_type = getattr(mcp_platform, "APaaSTenantBindingRequest")
    bind_environment = getattr(mcp_platform, "bind_apaas_tenant_environment")
    await bind_environment(
        tenant.id,
        request_type(
            admin_id=f"db_platform_credential_{credential.id}",
            base_url="https://new.example.com/backend",
            platform_tenant_id="new-tenant",
        ),
        ctx,
        db_session,
    )

    saved = (await db_session.execute(select(PlatformEnv))).scalar_one()
    assert saved.id == env.id
    assert saved.base_url == "https://new.example.com/backend"
    assert saved.platform_tenant_id == "new-tenant"
    assert saved.username == "apaas-admin"
    assert saved.password_enc == "encrypted-password"
    assert saved.token is None
    assert saved.status == "disconnected"
