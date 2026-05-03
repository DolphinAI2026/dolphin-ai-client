"""租户切换接口测试 — switch-tenant + me/tenants + 租户管理 CRUD。"""
import pytest
from jose import jwt
from fastapi import HTTPException

from app.auth import get_password_hash
from app.config import settings
from app.deps import AuthContext
from app.models import User
from app.models.tenant import Tenant, UserTenant
from app.routes.auth import (
    TenantCreateRequest,
    TenantMemberAddRequest,
    TenantMemberRoleUpdateRequest,
    TenantStatusRequest,
    TenantSwitchRequest,
    TenantUpdateRequest,
    add_tenant_member,
    create_new_tenant,
    delete_tenant,
    list_all_tenants,
    list_my_tenants,
    list_tenant_members,
    remove_tenant_member,
    switch_tenant,
    update_tenant,
    update_tenant_member_role,
    update_tenant_status,
)


async def _seed_user_and_tenants(db_session, *, num_tenants: int, member_indices: list[int]):
    tenants: list[Tenant] = []
    for i in range(num_tenants):
        t = Tenant(tenant_name=f"T{i}", tenant_code=f"t{i}", status=1)
        db_session.add(t)
        tenants.append(t)
    user = User(
        username="alice",
        hashed_password=get_password_hash("secret"),
        is_active=True,
    )
    db_session.add(user)
    await db_session.flush()

    for idx in member_indices:
        db_session.add(
            UserTenant(
                user_id=user.id,
                tenant_id=tenants[idx].id,
                status=1,
                is_default=(idx == member_indices[0]),
            )
        )
    await db_session.flush()
    return user, tenants


@pytest.mark.asyncio
async def test_switch_tenant_signs_new_token_for_member(db_session):
    user, tenants = await _seed_user_and_tenants(db_session, num_tenants=2, member_indices=[0, 1])
    ctx = AuthContext(user=user, tenant_id=tenants[0].id, tenant_role="member", org_permissions={})

    res = await switch_tenant(
        TenantSwitchRequest(tenant_id=tenants[1].id),
        ctx,
        db_session,
    )

    payload = jwt.decode(res.access_token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
    assert payload["tid"] == tenants[1].id
    assert int(payload["sub"]) == user.id


@pytest.mark.asyncio
async def test_switch_tenant_rejects_non_member(db_session):
    user, tenants = await _seed_user_and_tenants(db_session, num_tenants=2, member_indices=[0])
    ctx = AuthContext(user=user, tenant_id=tenants[0].id, tenant_role="member", org_permissions={})

    with pytest.raises(HTTPException) as exc:
        await switch_tenant(
            TenantSwitchRequest(tenant_id=tenants[1].id),
            ctx,
            db_session,
        )
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_platform_admin_can_switch_to_any_active_tenant(db_session):
    # 平台管理员，没成员关系也可以切到任意 active 租户
    tenants = []
    for i in range(2):
        t = Tenant(tenant_name=f"T{i}", tenant_code=f"t{i}", status=1)
        db_session.add(t)
        tenants.append(t)
    admin = User(
        username="root",
        hashed_password=get_password_hash("secret"),
        is_active=True,
        is_platform_admin=True,
    )
    db_session.add(admin)
    await db_session.flush()

    ctx = AuthContext(user=admin, tenant_id=tenants[0].id, tenant_role="platform_admin", org_permissions={"*": True})

    res = await switch_tenant(
        TenantSwitchRequest(tenant_id=tenants[1].id),
        ctx,
        db_session,
    )
    payload = jwt.decode(res.access_token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
    assert payload["tid"] == tenants[1].id


@pytest.mark.asyncio
async def test_list_my_tenants_returns_only_active_memberships(db_session):
    # member 关系：T0 active, T1 active, T2 not member
    user, tenants = await _seed_user_and_tenants(db_session, num_tenants=3, member_indices=[0, 1])
    ctx = AuthContext(user=user, tenant_id=tenants[0].id, tenant_role="member", org_permissions={})

    res = await list_my_tenants(ctx, db_session)
    ids = sorted(t.tenant_id for t in res)
    assert ids == sorted([tenants[0].id, tenants[1].id])


@pytest.mark.asyncio
async def test_create_tenant_requires_platform_admin(db_session):
    user, _ = await _seed_user_and_tenants(db_session, num_tenants=1, member_indices=[0])
    ctx = AuthContext(user=user, tenant_id=1, tenant_role="member", org_permissions={})

    with pytest.raises(HTTPException) as exc:
        await create_new_tenant(
            TenantCreateRequest(tenant_name="X", tenant_code="x"),
            ctx,
            db_session,
        )
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_create_and_toggle_tenant(db_session):
    admin = User(
        username="root",
        hashed_password=get_password_hash("secret"),
        is_active=True,
        is_platform_admin=True,
    )
    db_session.add(admin)
    await db_session.flush()
    ctx = AuthContext(user=admin, tenant_id=0, tenant_role="platform_admin", org_permissions={"*": True})

    created = await create_new_tenant(
        TenantCreateRequest(tenant_name="Acme", tenant_code="acme", max_applications=50),
        ctx,
        db_session,
    )
    assert created.tenant_code == "acme"
    assert created.status == 1

    # 重复 code 应 409
    with pytest.raises(HTTPException) as exc:
        await create_new_tenant(
            TenantCreateRequest(tenant_name="Other", tenant_code="acme"),
            ctx,
            db_session,
        )
    assert exc.value.status_code == 409

    # toggle status
    disabled = await update_tenant_status(
        created.id, TenantStatusRequest(status=0), ctx, db_session
    )
    assert disabled.status == 0

    # list 包含
    listed = await list_all_tenants(ctx, db_session)
    assert any(t.id == created.id for t in listed)


@pytest.mark.asyncio
async def test_update_tenant_changes_fields(db_session):
    admin = User(
        username="root2",
        hashed_password=get_password_hash("secret"),
        is_active=True,
        is_platform_admin=True,
    )
    db_session.add(admin)
    await db_session.flush()
    ctx = AuthContext(user=admin, tenant_id=0, tenant_role="platform_admin", org_permissions={"*": True})

    created = await create_new_tenant(
        TenantCreateRequest(tenant_name="A", tenant_code="aaa1"),
        ctx, db_session,
    )

    updated = await update_tenant(
        created.id,
        TenantUpdateRequest(tenant_name="A2", max_workspaces=99),
        ctx, db_session,
    )
    assert updated.tenant_name == "A2"
    assert updated.max_workspaces == 99
    # tenant_code 不可改
    assert updated.tenant_code == "aaa1"


@pytest.mark.asyncio
async def test_delete_empty_tenant_works(db_session, monkeypatch):
    # 测试 db 与本地真实 _online_coding/<tenant_id>/ 冲突时（SQLite autoincrement 从 1 起）
    # 会误把真实 workspace 计入新建 tenant，要 mock 掉文件系统扫描
    from app import tenant_quota
    monkeypatch.setattr(tenant_quota, "_count_workspaces", lambda _tid: 0)

    admin = User(
        username="root3",
        hashed_password=get_password_hash("secret"),
        is_active=True,
        is_platform_admin=True,
    )
    db_session.add(admin)
    await db_session.flush()
    ctx = AuthContext(user=admin, tenant_id=0, tenant_role="platform_admin", org_permissions={"*": True})
    created = await create_new_tenant(
        TenantCreateRequest(tenant_name="B", tenant_code="bbb1"),
        ctx, db_session,
    )

    res = await delete_tenant(created.id, ctx, db_session, force=False)
    assert res["ok"] is True
    assert res["deleted_tenant_id"] == created.id


@pytest.mark.asyncio
async def test_delete_blocks_when_tenant_is_current(db_session):
    admin = User(
        username="root4",
        hashed_password=get_password_hash("secret"),
        is_active=True,
        is_platform_admin=True,
    )
    db_session.add(admin)
    await db_session.flush()

    # 用 admin 创建一个 tenant 并把 ctx.tenant_id 指向它（模拟"当前激活"）
    ctx_other = AuthContext(user=admin, tenant_id=0, tenant_role="platform_admin", org_permissions={"*": True})
    created = await create_new_tenant(
        TenantCreateRequest(tenant_name="C", tenant_code="ccc1"),
        ctx_other, db_session,
    )
    ctx_self = AuthContext(user=admin, tenant_id=created.id, tenant_role="platform_admin", org_permissions={"*": True})

    with pytest.raises(HTTPException) as exc:
        await delete_tenant(created.id, ctx_self, db_session)
    assert exc.value.status_code == 400


async def _seed_admin_with_default_tenant(db_session, *, tenant_code="d1"):
    from app.models.tenant import Role
    tenant = Tenant(tenant_name="D", tenant_code=tenant_code, status=1)
    db_session.add(tenant)
    await db_session.flush()
    # 给 tenant 建一个 admin role（add_tenant_member fallback 找它）
    role = Role(
        tenant_id=tenant.id,
        role_name="Admin",
        role_code="admin",
        permissions={"*": True},
        is_system=True,
    )
    db_session.add(role)
    admin = User(
        username=f"sa_{tenant_code}",
        hashed_password=get_password_hash("x"),
        is_active=True,
        is_platform_admin=True,
    )
    db_session.add(admin)
    await db_session.flush()
    return tenant, admin, role


@pytest.mark.asyncio
async def test_add_tenant_member_creates_user_and_membership(db_session):
    tenant, admin, role = await _seed_admin_with_default_tenant(db_session, tenant_code="dm1")
    ctx = AuthContext(user=admin, tenant_id=0, tenant_role="platform_admin", org_permissions={"*": True})

    m = await add_tenant_member(
        tenant.id,
        TenantMemberAddRequest(username="alice_new", password="pw123", role_code="admin"),
        ctx,
        db_session,
    )
    assert m.username == "alice_new"
    assert m.role_code == "admin"

    members = await list_tenant_members(tenant.id, ctx, db_session)
    assert any(x.username == "alice_new" for x in members)


@pytest.mark.asyncio
async def test_add_tenant_member_existing_user_no_password_required(db_session):
    tenant, admin, role = await _seed_admin_with_default_tenant(db_session, tenant_code="dm2")
    ctx = AuthContext(user=admin, tenant_id=0, tenant_role="platform_admin", org_permissions={"*": True})

    # 已存在用户
    existing = User(username="bob", hashed_password=get_password_hash("x"), is_active=True)
    db_session.add(existing)
    await db_session.flush()

    m = await add_tenant_member(
        tenant.id,
        TenantMemberAddRequest(username="bob"),  # 不传 password
        ctx, db_session,
    )
    assert m.username == "bob"


@pytest.mark.asyncio
async def test_remove_tenant_member_works(db_session):
    tenant, admin, role = await _seed_admin_with_default_tenant(db_session, tenant_code="dm3")
    ctx = AuthContext(user=admin, tenant_id=0, tenant_role="platform_admin", org_permissions={"*": True})

    m = await add_tenant_member(
        tenant.id,
        TenantMemberAddRequest(username="charlie", password="x"),
        ctx, db_session,
    )

    res = await remove_tenant_member(tenant.id, m.user_id, ctx, db_session)
    assert res["ok"] is True

    members = await list_tenant_members(tenant.id, ctx, db_session)
    assert all(x.user_id != m.user_id for x in members)


@pytest.mark.asyncio
async def test_update_tenant_member_role_changes_role(db_session):
    from app.models.tenant import Role
    tenant, admin, _admin_role = await _seed_admin_with_default_tenant(db_session, tenant_code="r1")
    # 加一个 dev role
    dev_role = Role(tenant_id=tenant.id, role_name="Dev", role_code="R_developer", permissions={}, is_system=False)
    db_session.add(dev_role)
    await db_session.flush()

    ctx = AuthContext(user=admin, tenant_id=0, tenant_role="platform_admin", org_permissions={"*": True})
    m = await add_tenant_member(
        tenant.id,
        TenantMemberAddRequest(username="dave", password="x", role_code="admin"),
        ctx, db_session,
    )
    assert m.role_code == "admin"

    updated = await update_tenant_member_role(
        tenant.id, m.user_id,
        TenantMemberRoleUpdateRequest(role_code="R_developer"),
        ctx, db_session,
    )
    assert updated.role_code == "R_developer"


@pytest.mark.asyncio
async def test_self_demote_from_current_admin_blocked(db_session):
    from app.models.tenant import Role
    tenant, admin, _ = await _seed_admin_with_default_tenant(db_session, tenant_code="r2")
    Role_dev = Role(tenant_id=tenant.id, role_name="Dev", role_code="R_developer", permissions={}, is_system=False)
    db_session.add(Role_dev)
    # 给 admin 自己加 admin 角色 + membership
    ctx_other = AuthContext(user=admin, tenant_id=0, tenant_role="platform_admin", org_permissions={"*": True})
    await add_tenant_member(
        tenant.id,
        TenantMemberAddRequest(username=admin.username, role_code="admin"),
        ctx_other, db_session,
    )

    # 现在 ctx 切到当前 tenant
    ctx_self = AuthContext(user=admin, tenant_id=tenant.id, tenant_role="platform_admin", org_permissions={"*": True})
    with pytest.raises(HTTPException) as exc:
        await update_tenant_member_role(
            tenant.id, admin.id,
            TenantMemberRoleUpdateRequest(role_code="R_developer"),
            ctx_self, db_session,
        )
    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_remove_self_from_current_tenant_blocked(db_session):
    tenant, admin, role = await _seed_admin_with_default_tenant(db_session, tenant_code="dm4")
    ctx = AuthContext(user=admin, tenant_id=tenant.id, tenant_role="platform_admin", org_permissions={"*": True})

    with pytest.raises(HTTPException) as exc:
        await remove_tenant_member(tenant.id, admin.id, ctx, db_session)
    assert exc.value.status_code == 400
