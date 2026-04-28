from types import SimpleNamespace

import pytest
from jose import jwt

from app.auth import create_access_token, get_password_hash
from app.config import settings
from app.deps import AuthContext, get_auth_context, resolve_effective_tenant_id
from app.models import LLMConfig, PlatformEnv, User
from app.models.tenant import Tenant, UserTenant
from app.routes.llm_configs import list_llm_config_options, list_llm_configs
from app.routes.platform_envs import list_envs
from app.routes.auth import login
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
async def test_platform_admin_login_token_uses_default_tenant(db_session):
    _user, tenant = await _seed_platform_admin(db_session)

    response = await login(UserLogin(username="admin", password="secret"), db_session)

    payload = jwt.decode(
        response.access_token,
        settings.jwt_secret_key,
        algorithms=[settings.jwt_algorithm],
    )
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
