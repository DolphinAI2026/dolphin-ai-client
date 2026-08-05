"""get_auth_context_from_token 必须像 get_auth_context 一样加载角色权限。

回归：自开发整页预览(custom-page-host)/SSE 走 ?_auth= / ?token= query 形态 token，
经 get_auth_context_from_token 解析。旧实现对非平台管理员一律硬编码
tenant_role="member" + org_permissions={}，从不查 UserTenant→Role，导致一个
拥有 application:view 的普通租户用户在 iframe 预览里被降级成无权限 member →
check_resource_permission Layer1 抛 403「你的角色没有 application:Action.VIEW 权限」，
而同一用户走 Authorization header 的所有其它面板都正常。

同一 user + 同一 token，AuthContext 不应因 token 来自 header 还是 query 而不同。
"""
import pytest
import pytest_asyncio
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.pool import StaticPool

from app.database import Base
from app import models  # noqa: F401  register ORM mappings
from app.models import User
from app.models.tenant import Tenant, UserTenant, Role
from app.auth import create_access_token, create_control_plane_code_token


@pytest_asyncio.fixture
async def shared_db(monkeypatch):
    """StaticPool 内存库 + monkeypatch app.database.AsyncSessionLocal。

    get_auth_context_from_token 内部自己 `from app.database import AsyncSessionLocal`
    开 session，测试 seed 的行必须落在它连的同一个库里。
    """
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    monkeypatch.setattr("app.database.AsyncSessionLocal", Session)
    yield Session
    await engine.dispose()


async def _seed(Session, *, role_code: str, permissions: dict, is_platform_admin: bool = False):
    async with Session() as db:
        tenant = Tenant(tenant_name="t1", tenant_code="t1")
        db.add(tenant)
        await db.flush()
        user = User(username="u1", hashed_password="x", is_platform_admin=is_platform_admin)
        db.add(user)
        await db.flush()
        role = Role(
            tenant_id=tenant.id,
            role_name="r",
            role_code=role_code,
            permissions=permissions,
        )
        db.add(role)
        await db.flush()
        db.add(UserTenant(user_id=user.id, tenant_id=tenant.id, role_id=role.id, status=1))
        await db.commit()
        return user.id, tenant.id


@pytest.mark.asyncio
async def test_token_ctx_loads_tenant_admin_role(shared_db):
    """R_tenant_admin 普通用户(非平台管理员)走 token 路径应解析成 tenant_admin。"""
    from app.deps import get_auth_context_from_token

    user_id, tenant_id = await _seed(
        shared_db,
        role_code="R_tenant_admin",
        permissions={"application:view": True, "application:edit": True},
    )
    token = create_access_token(user_id, tenant_id=tenant_id)
    ctx = await get_auth_context_from_token(token)

    assert ctx.tenant_role == "tenant_admin"
    assert ctx.org_permissions.get("application:view") is True


@pytest.mark.asyncio
async def test_token_ctx_loads_member_permissions(shared_db):
    """普通成员角色但拥有 application:view —— token 路径必须带上该权限(不再被清空)。"""
    from app.deps import get_auth_context_from_token
    from app.permissions import has_org_permission, Action

    user_id, tenant_id = await _seed(
        shared_db,
        role_code="R_member",
        permissions={"application:view": True},
    )
    token = create_access_token(user_id, tenant_id=tenant_id)
    ctx = await get_auth_context_from_token(token)

    assert ctx.tenant_role == "member"
    assert has_org_permission(ctx.org_permissions, "application", Action.VIEW) is True


@pytest.mark.asyncio
async def test_control_plane_tenant_claim_is_preserved_for_header_and_query_contexts(shared_db):
    from app.deps import get_auth_context, get_auth_context_from_token

    user_id, tenant_id = await _seed(
        shared_db,
        role_code="R_tenant_admin",
        permissions={},
    )
    token = create_access_token(
        user_id,
        tenant_id=tenant_id,
        control_plane_tenant_id="0",
    )

    async with shared_db() as db:
        header_ctx = await get_auth_context(
            HTTPAuthorizationCredentials(scheme="Bearer", credentials=token),
            db,
        )
    query_ctx = await get_auth_context_from_token(token)

    assert header_ctx.control_plane_tenant_id == "0"
    assert query_ctx.control_plane_tenant_id == "0"


@pytest.mark.asyncio
async def test_control_plane_code_resolves_bound_local_tenant(shared_db):
    """Code org tickets must use the matching bound Builder tenant for env APIs."""
    from app.deps import get_auth_context, get_auth_context_from_token

    async with shared_db() as db:
        tenant = Tenant(
            tenant_name="admin 的组织",
            tenant_code="admin-org",
            apaas_tenant_id_str="850079360340721665",
        )
        db.add(tenant)
        await db.flush()
        user = User(
            username="admin",
            hashed_password="x",
            account_source="control_plane",
            is_platform_admin=True,
        )
        db.add(user)
        await db.commit()
        user_id = user.id

    token = create_control_plane_code_token(
        user_id,
        control_plane_tenant_id="0",
        control_plane_tenant_name="admin 的组织",
        control_plane_tenant_role="platform_admin",
        control_plane_permissions={"*": True},
    )

    async with shared_db() as db:
        header_ctx = await get_auth_context(
            HTTPAuthorizationCredentials(scheme="Bearer", credentials=token),
            db,
        )
    query_ctx = await get_auth_context_from_token(token)

    assert header_ctx.tenant_id == tenant.id
    assert header_ctx.apaas_tenant_id == "850079360340721665"
    assert query_ctx.tenant_id == tenant.id
    assert query_ctx.apaas_tenant_id == "850079360340721665"

    async with shared_db() as db:
        persisted = await db.get(Tenant, tenant.id)
        assert persisted.control_plane_tenant_id_str == "0"
        assert header_ctx.tenant_access_scope == "control_plane_code"


@pytest.mark.asyncio
async def test_control_plane_code_backfills_unique_apaas_bound_projection(shared_db):
    """A legacy local tenant can be recovered from the user's explicit aPaaS binding."""
    from app.deps import get_auth_context_from_token

    async with shared_db() as db:
        tenant = Tenant(
            tenant_name="Legacy Builder Tenant",
            tenant_code="legacy-builder-tenant",
            apaas_tenant_id_str="apaas-xdg-tenant",
        )
        user = User(
            username="xdg-user",
            hashed_password="x",
            account_source="control_plane",
            is_platform_admin=True,
            apaas_tenant_id="apaas-xdg-tenant",
        )
        db.add_all([tenant, user])
        await db.commit()
        user_id = user.id

    token = create_control_plane_code_token(
        user_id,
        control_plane_tenant_id="cp-xdg-tenant",
        control_plane_tenant_name="兄弟高测试组织",
        control_plane_tenant_role="tenant_admin",
    )
    ctx = await get_auth_context_from_token(token)

    assert ctx.tenant_id == tenant.id
    assert ctx.apaas_tenant_id == "apaas-xdg-tenant"

    async with shared_db() as db:
        persisted = await db.get(Tenant, tenant.id)
        assert persisted.control_plane_tenant_id_str == "cp-xdg-tenant"


@pytest.mark.asyncio
async def test_control_plane_code_prefers_stable_id_over_duplicate_name(shared_db):
    from app.deps import get_auth_context_from_token

    async with shared_db() as db:
        mapped = Tenant(
            tenant_name="同名组织",
            tenant_code="mapped",
            control_plane_tenant_id_str="cp-1",
            apaas_tenant_id_str="apaas-1",
        )
        unrelated = Tenant(
            tenant_name="同名组织",
            tenant_code="unrelated",
            apaas_tenant_id_str="apaas-2",
        )
        user = User(
            username="cp-user",
            hashed_password="x",
            account_source="control_plane",
            is_platform_admin=True,
        )
        db.add_all([mapped, unrelated, user])
        await db.commit()
        user_id = user.id

    token = create_control_plane_code_token(
        user_id,
        control_plane_tenant_id="cp-1",
        control_plane_tenant_name="同名组织",
    )
    ctx = await get_auth_context_from_token(token)
    assert ctx.tenant_id == mapped.id
    assert ctx.apaas_tenant_id == "apaas-1"


@pytest.mark.asyncio
async def test_control_plane_me_keeps_local_projection_as_builder_tenant(shared_db, monkeypatch):
    from app.deps import AuthContext
    from app.routes.auth.tenants_admin import get_me

    async with shared_db() as db:
        tenant = Tenant(
            tenant_name="Builder 投影",
            tenant_code="builder-projection",
            control_plane_tenant_id_str="cp-builder",
        )
        user = User(
            username="cp-builder-user",
            hashed_password="x",
            account_source="control_plane",
            is_platform_admin=True,
        )
        db.add_all([tenant, user])
        await db.flush()
        ctx = AuthContext(
            user=user,
            tenant_id=tenant.id,
            tenant_role="platform_admin",
            org_permissions={"*": True},
            tenant_access_scope="control_plane_code",
            control_plane_tenant_id="cp-builder",
            control_plane_tenant_name="CP 组织",
        )
        monkeypatch.setattr("app.runtime.is_desktop", lambda: False)
        response = await get_me(ctx, db)

    assert response.tenant_id == tenant.id
    assert response.tenant_name == "Builder 投影"
    assert response.control_plane_tenant_id == "cp-builder"
    assert response.control_plane_tenant_name == "CP 组织"
    assert response.tenant_authority == "control_plane"


def test_wildcard_org_permission_allows_specific_actions():
    from app.permissions import has_org_permission, Action

    assert has_org_permission({"*": True}, "application", Action.CREATE) is True
    assert has_org_permission({"*": False}, "application", Action.CREATE) is False
