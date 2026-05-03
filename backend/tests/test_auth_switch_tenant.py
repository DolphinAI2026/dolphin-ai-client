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
    TenantStatusRequest,
    TenantSwitchRequest,
    create_new_tenant,
    list_all_tenants,
    list_my_tenants,
    switch_tenant,
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
        TenantCreateRequest(tenant_name="Acme", tenant_code="acme", plan_type="pro", max_applications=50),
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
