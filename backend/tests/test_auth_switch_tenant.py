"""租户切换接口测试 — switch-tenant + me/tenants + 租户管理 CRUD。"""
import pytest
import sys
from jose import jwt
from fastapi import HTTPException
from sqlalchemy import select

from app.auth import decode_token, get_password_hash
from app.code_runtime.auth import store_control_plane_credentials
from app.config import settings
from app.deps import AuthContext
from app.models import APaaSUserCredential, User
from app.models.tenant import Tenant, UserTenant
from app.routes.auth import (
    ResetPasswordRequest,
    TenantCreateRequest,
    TenantMemberAddRequest,
    TenantMemberRoleUpdateRequest,
    TenantStatusRequest,
    TenantSwitchRequest,
    TenantUpdateRequest,
    add_tenant_member,
    admin_reset_user_password,
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
    _apaas_membership_role_preference,
    _sync_user_membership,
)
from app.routes.auth.tenants_admin import get_me


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

    payload = jwt.decode(
        res.access_token,
        settings.jwt_secret_key,
        algorithms=[settings.jwt_algorithm],
        options={"verify_aud": False},
    )
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
        account_source="control_plane",
    )
    db_session.add(admin)
    await db_session.flush()

    ctx = AuthContext(user=admin, tenant_id=tenants[0].id, tenant_role="platform_admin", org_permissions={"*": True})

    res = await switch_tenant(
        TenantSwitchRequest(tenant_id=tenants[1].id),
        ctx,
        db_session,
    )
    payload = jwt.decode(
        res.access_token,
        settings.jwt_secret_key,
        algorithms=[settings.jwt_algorithm],
        options={"verify_aud": False},
    )
    assert payload["tid"] == tenants[1].id


@pytest.mark.asyncio
async def test_coding_platform_admin_lists_only_membership_tenants(db_session):
    tenants = []
    for i in range(2):
        t = Tenant(tenant_name=f"T{i}", tenant_code=f"coding-list-{i}", status=1)
        db_session.add(t)
        tenants.append(t)
    user = User(
        username="code_admin",
        hashed_password=get_password_hash("secret"),
        account_source="coding",
        is_active=True,
        is_platform_admin=True,
    )
    db_session.add(user)
    await db_session.flush()
    db_session.add(
        UserTenant(
            user_id=user.id,
            tenant_id=tenants[0].id,
            status=1,
            is_default=True,
        )
    )
    await db_session.flush()

    ctx = AuthContext(user=user, tenant_id=tenants[0].id, tenant_role="platform_admin", org_permissions={"*": True})

    res = await list_my_tenants(ctx, db_session)

    assert [item.tenant_id for item in res] == [tenants[0].id]


@pytest.mark.asyncio
async def test_coding_platform_admin_cannot_switch_to_unbound_tenant(db_session):
    tenants = []
    for i in range(2):
        t = Tenant(tenant_name=f"T{i}", tenant_code=f"coding-switch-{i}", status=1)
        db_session.add(t)
        tenants.append(t)
    user = User(
        username="code_admin_switch",
        hashed_password=get_password_hash("secret"),
        account_source="coding",
        is_active=True,
        is_platform_admin=True,
    )
    db_session.add(user)
    await db_session.flush()
    db_session.add(
        UserTenant(
            user_id=user.id,
            tenant_id=tenants[0].id,
            status=1,
            is_default=True,
        )
    )
    await db_session.flush()

    ctx = AuthContext(user=user, tenant_id=tenants[0].id, tenant_role="platform_admin", org_permissions={"*": True})

    with pytest.raises(HTTPException) as exc:
        await switch_tenant(
            TenantSwitchRequest(tenant_id=tenants[1].id),
            ctx,
            db_session,
        )

    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_list_my_tenants_returns_only_active_memberships(db_session):
    # member 关系：T0 active, T1 active, T2 not member
    user, tenants = await _seed_user_and_tenants(db_session, num_tenants=3, member_indices=[0, 1])
    ctx = AuthContext(user=user, tenant_id=tenants[0].id, tenant_role="member", org_permissions={})

    res = await list_my_tenants(ctx, db_session)
    ids = sorted(t.tenant_id for t in res)
    assert ids == sorted([tenants[0].id, tenants[1].id])


@pytest.mark.asyncio
async def test_desktop_control_plane_me_hides_local_storage_tenant(db_session, monkeypatch):
    monkeypatch.setenv("DESKTOP_MODE", "1")
    local_tenant = Tenant(
        tenant_name="本地缓存租户",
        tenant_code="workspace-2077284540335579137",
        status=1,
    )
    user = User(
        username="remote-admin",
        hashed_password=get_password_hash("secret"),
        account_source="control_plane",
        coding_tenant_id="2077284540335579137",
        is_active=True,
    )
    db_session.add_all([local_tenant, user])
    await db_session.flush()
    db_session.add(
        UserTenant(
            user_id=user.id,
            tenant_id=local_tenant.id,
            status=1,
            is_default=True,
        )
    )
    await db_session.flush()
    store_control_plane_credentials(user, "remote-access-token")

    async def fake_fetch_control_plane_identity(_token):
        return type(
            "Identity",
            (),
            {
                "tenant_id": "2077284540335579137",
                "tenant_name": "示例租户",
                "org_permissions": {"system.*": True},
            },
        )()

    monkeypatch.setattr(
        "app.routes.auth.tenants_admin.fetch_control_plane_identity",
        fake_fetch_control_plane_identity,
    )

    ctx = AuthContext(
        user=user,
        tenant_id=local_tenant.id,
        tenant_role="tenant_admin",
        org_permissions={},
    )

    me = await get_me(ctx, db_session)

    assert me.tenant_id == "2077284540335579137"
    assert me.tenant_name == "示例租户"
    assert me.control_plane_tenant_id == "2077284540335579137"
    assert me.control_plane_tenant_name == "示例租户"
    assert me.org_permissions == {"system.*": True}


@pytest.mark.asyncio
async def test_desktop_control_plane_me_preserves_selected_remote_tenant(db_session, monkeypatch):
    monkeypatch.setenv("DESKTOP_MODE", "1")
    user = User(
        username="remote-admin",
        hashed_password=get_password_hash("secret"),
        account_source="control_plane",
        coding_tenant_id="0",
        is_active=True,
    )
    db_session.add(user)
    await db_session.flush()
    store_control_plane_credentials(user, "remote-access-token")

    async def fake_fetch_control_plane_identity(_token):
        return type(
            "Identity",
            (),
            {
                "tenant_id": "2077284540335579137",
                "tenant_name": "示例租户",
                "org_permissions": {"system.*": True},
            },
        )()

    monkeypatch.setattr(
        "app.routes.auth.tenants_admin.fetch_control_plane_identity",
        fake_fetch_control_plane_identity,
    )
    ctx = AuthContext(
        user=user,
        tenant_id=0,
        tenant_role="platform_admin",
        org_permissions={},
        control_plane_tenant_id="0",
        control_plane_tenant_name="admin 的组织",
    )

    me = await get_me(ctx, db_session)

    assert me.tenant_id == "0"
    assert me.tenant_name == "admin 的组织"
    assert me.org_permissions == {"system.*": True}


@pytest.mark.asyncio
async def test_desktop_control_plane_lists_remote_available_tenants(db_session, monkeypatch):
    monkeypatch.setenv("DESKTOP_MODE", "1")
    user = User(
        username="remote-admin",
        hashed_password=get_password_hash("secret"),
        account_source="control_plane",
        coding_tenant_id="2077284540335579137",
        is_active=True,
    )
    db_session.add(user)
    await db_session.flush()
    store_control_plane_credentials(user, "remote-access-token")

    async def fake_fetch_control_plane_identity(_token):
        return type(
            "Identity",
            (),
            {
                "available_tenants": [
                    {"tenant_id": "0", "tenant_name": "默认组织"},
                    {"tenant_id": "2077284540335579137", "tenant_name": "示例租户"},
                ],
            },
        )()

    monkeypatch.setattr(
        "app.routes.auth.tenants_admin.fetch_control_plane_identity",
        fake_fetch_control_plane_identity,
        raising=False,
    )
    ctx = AuthContext(user=user, tenant_id=0, tenant_role="platform_admin", org_permissions={"*": True})

    options = await list_my_tenants(ctx, db_session)

    assert [(item.tenant_id, item.tenant_name) for item in options] == [
        ("0", "默认组织"),
        ("2077284540335579137", "示例租户"),
    ]


@pytest.mark.asyncio
async def test_desktop_control_plane_switches_remote_tenant_context(db_session, monkeypatch):
    monkeypatch.setenv("DESKTOP_MODE", "1")
    monkeypatch.setattr(settings, "accepted_token_issuers", "ai-builder,desktop-sidecar")
    user = User(
        username="remote-admin",
        hashed_password=get_password_hash("secret"),
        account_source="control_plane",
        coding_tenant_id="2077284540335579137",
        is_active=True,
    )
    db_session.add(user)
    await db_session.flush()
    store_control_plane_credentials(user, "remote-access-token")

    async def fake_fetch_control_plane_identity(_token):
        return type(
            "Identity",
            (),
            {
                "available_tenants": [
                    {"tenant_id": "0", "tenant_name": "默认组织"},
                    {"tenant_id": "2077284540335579137", "tenant_name": "示例租户"},
                ],
                "roles": ["PLATFORM_ADMIN"],
                "org_permissions": {"*": True},
            },
        )()

    monkeypatch.setattr(
        sys.modules["app.routes.auth.login"],
        "fetch_control_plane_identity",
        fake_fetch_control_plane_identity,
    )
    ctx = AuthContext(user=user, tenant_id=0, tenant_role="platform_admin", org_permissions={"*": True})

    response = await switch_tenant(TenantSwitchRequest(tenant_id="0"), ctx, db_session)

    assert user.coding_tenant_id == "0"
    assert decode_token(response.access_token)["cp_tid"] == "0"


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
async def test_sync_user_membership_defaults_to_developer_role(db_session):
    from app.models.tenant import Role

    tenant = Tenant(tenant_name="Sync Dev", tenant_code="sync-dev", status=1)
    user = User(username="sync_dev_user", hashed_password=get_password_hash("x"), is_active=True)
    db_session.add_all([tenant, user])
    await db_session.flush()
    dev_role = Role(tenant_id=tenant.id, role_name="Dev", role_code="R_developer", permissions={}, is_system=False)
    admin_role = Role(tenant_id=tenant.id, role_name="Admin", role_code="R_tenant_admin", permissions={}, is_system=True)
    db_session.add_all([dev_role, admin_role])
    await db_session.flush()

    membership = await _sync_user_membership(db_session, user, tenant, is_default=True)

    assert membership.role_id == dev_role.id


@pytest.mark.asyncio
async def test_sync_user_membership_can_prefer_tenant_admin_role(db_session):
    from app.models.tenant import Role

    tenant = Tenant(tenant_name="Sync Admin", tenant_code="sync-admin", status=1)
    user = User(username="sync_admin_user", hashed_password=get_password_hash("x"), is_active=True)
    db_session.add_all([tenant, user])
    await db_session.flush()
    dev_role = Role(tenant_id=tenant.id, role_name="Dev", role_code="R_developer", permissions={}, is_system=False)
    admin_role = Role(tenant_id=tenant.id, role_name="Admin", role_code="R_tenant_admin", permissions={}, is_system=True)
    db_session.add_all([dev_role, admin_role])
    await db_session.flush()

    membership = await _sync_user_membership(
        db_session,
        user,
        tenant,
        is_default=True,
        preferred_role_codes=("R_tenant_admin", "admin", "R_developer"),
    )

    assert membership.role_id == admin_role.id


def test_apaas_membership_role_preference_defaults_to_developer():
    preference = _apaas_membership_role_preference(
        {"tenantId": "t1"},
        "alice",
        {"id": "u1"},
        admin_tenant_ids=set(),
        is_platform_admin=False,
    )

    assert preference == ("R_developer", "R_tenant_admin", "admin")


def test_apaas_membership_role_preference_uses_admin_tenant_list():
    preference = _apaas_membership_role_preference(
        {"tenantId": "t1"},
        "alice",
        {"id": "u1"},
        admin_tenant_ids={"t1"},
        is_platform_admin=False,
    )

    assert preference == ("R_tenant_admin", "admin", "R_developer")


def test_apaas_membership_role_preference_uses_admin_list_match():
    preference = _apaas_membership_role_preference(
        {"tenantId": "t1", "adminList": [{"account": "alice"}]},
        "alice",
        {"id": "u1"},
        admin_tenant_ids=set(),
        is_platform_admin=False,
    )

    assert preference == ("R_tenant_admin", "admin", "R_developer")


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


# ─────────────────────── reset password ───────────────────────


@pytest.mark.asyncio
async def test_platform_admin_can_reset_any_password(db_session):
    from app.auth import verify_password
    admin = User(username="root_pw", hashed_password=get_password_hash("x"), is_active=True, is_platform_admin=True)
    target = User(username="bob_pw", hashed_password=get_password_hash("oldpw"), is_active=True)
    db_session.add_all([admin, target])
    await db_session.flush()

    ctx = AuthContext(user=admin, tenant_id=0, tenant_role="platform_admin", org_permissions={"*": True})
    res = await admin_reset_user_password(
        target.id, ResetPasswordRequest(new_password="newpw123"), ctx, db_session,
    )
    assert res["ok"] is True
    await db_session.refresh(target)
    assert verify_password("newpw123", target.hashed_password)


@pytest.mark.asyncio
async def test_reset_password_too_short_rejected(db_session):
    admin = User(username="root_pw_short", hashed_password=get_password_hash("x"), is_active=True, is_platform_admin=True)
    target = User(username="bob_pw_short", hashed_password=get_password_hash("oldpw"), is_active=True)
    db_session.add_all([admin, target])
    await db_session.flush()
    ctx = AuthContext(user=admin, tenant_id=0, tenant_role="platform_admin", org_permissions={"*": True})

    with pytest.raises(HTTPException) as exc:
        await admin_reset_user_password(
            target.id, ResetPasswordRequest(new_password="123"), ctx, db_session,
        )
    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_reset_self_password_blocked(db_session):
    admin = User(username="root_self", hashed_password=get_password_hash("x"), is_active=True, is_platform_admin=True)
    db_session.add(admin)
    await db_session.flush()
    ctx = AuthContext(user=admin, tenant_id=0, tenant_role="platform_admin", org_permissions={"*": True})

    with pytest.raises(HTTPException) as exc:
        await admin_reset_user_password(
            admin.id, ResetPasswordRequest(new_password="newpw123"), ctx, db_session,
        )
    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_tenant_admin_cannot_reset_platform_admin_password(db_session):
    tenant_admin = User(username="ta_pw", hashed_password=get_password_hash("x"), is_active=True)
    platform_admin = User(username="pa_pw", hashed_password=get_password_hash("x"), is_active=True, is_platform_admin=True)
    db_session.add_all([tenant_admin, platform_admin])
    await db_session.flush()

    ctx = AuthContext(user=tenant_admin, tenant_id=1, tenant_role="tenant_admin", org_permissions={})
    with pytest.raises(HTTPException) as exc:
        await admin_reset_user_password(
            platform_admin.id, ResetPasswordRequest(new_password="newpw123"), ctx, db_session,
        )
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_tenant_admin_can_reset_member_in_same_tenant(db_session):
    from app.models.tenant import Role
    tenant = Tenant(tenant_name="T_pw", tenant_code="t_pw", status=1)
    db_session.add(tenant)
    await db_session.flush()
    role = Role(tenant_id=tenant.id, role_name="Dev", role_code="R_developer", permissions={}, is_system=False)
    db_session.add(role)
    await db_session.flush()

    ta = User(username="ta_ok", hashed_password=get_password_hash("x"), is_active=True)
    member = User(username="m_ok", hashed_password=get_password_hash("x"), is_active=True)
    db_session.add_all([ta, member])
    await db_session.flush()
    db_session.add(UserTenant(user_id=member.id, tenant_id=tenant.id, role_id=role.id, status=1))
    await db_session.flush()

    ctx = AuthContext(user=ta, tenant_id=tenant.id, tenant_role="tenant_admin", org_permissions={})
    res = await admin_reset_user_password(
        member.id, ResetPasswordRequest(new_password="newpw123"), ctx, db_session,
    )
    assert res["ok"] is True


@pytest.mark.asyncio
async def test_normal_user_cannot_reset_password(db_session):
    me = User(username="normie", hashed_password=get_password_hash("x"), is_active=True)
    target = User(username="t_normie", hashed_password=get_password_hash("x"), is_active=True)
    db_session.add_all([me, target])
    await db_session.flush()

    ctx = AuthContext(user=me, tenant_id=1, tenant_role="developer", org_permissions={})
    with pytest.raises(HTTPException) as exc:
        await admin_reset_user_password(
            target.id, ResetPasswordRequest(new_password="newpw123"), ctx, db_session,
        )
    assert exc.value.status_code == 403


# ─────────────────────── aPaaS account binding ───────────────────────


@pytest.mark.asyncio
async def test_platform_admin_can_bind_coding_user_to_apaas_account(db_session, monkeypatch):
    import app.routes.auth.tenants_admin as tenants_admin

    admin = User(
        username="root_bind",
        hashed_password=get_password_hash("x"),
        is_active=True,
        is_platform_admin=True,
    )
    target = User(
        username="syt_bind",
        hashed_password=get_password_hash("x"),
        account_source="coding",
        coding_user_id="coding-user-1",
        is_active=True,
        is_platform_admin=True,
    )
    old_tenant = Tenant(tenant_name="Default Tenant", tenant_code="default-bind-old", status=1)
    db_session.add_all([admin, target, old_tenant])
    await db_session.flush()
    db_session.add(
        UserTenant(
            user_id=target.id,
            tenant_id=old_tenant.id,
            status=1,
            is_default=True,
        )
    )
    await db_session.flush()

    apaas_tenant = {
        "tenantId": "apaas-tenant-1",
        "tenantName": "三津食品",
        "tenantCode": "sanjin",
        "status": 1,
    }

    async def fake_apaas_backend_login(username: str, password: str, tenant_id: str = ""):
        assert username == "apaas-admin"
        assert password == "secret"
        return "token-for-apaas-tenant-1", {
            "data": {
                "defaultTenantId": "apaas-tenant-1",
                "tenantInfos": [apaas_tenant],
                "user": {
                    "id": "apaas-user-1",
                    "username": "apaas-admin",
                    "displayName": "aPaaS 管理员",
                },
            }
        }

    async def fake_apaas_switchable_tenants(_token: str, _default_tenant_id: str):
        return []

    monkeypatch.setattr(settings, "apaas_base_url", "https://apaas.example.com/backend")
    monkeypatch.setattr(tenants_admin, "_apaas_backend_login", fake_apaas_backend_login)
    monkeypatch.setattr(tenants_admin, "_apaas_switchable_tenants", fake_apaas_switchable_tenants)

    ctx = AuthContext(user=admin, tenant_id=0, tenant_role="platform_admin", org_permissions={"*": True})
    result = await tenants_admin.bind_user_apaas_account(
        target.id,
        tenants_admin.BindApaasAccountRequest(username="apaas-admin", password="secret"),
        ctx,
        db_session,
    )

    await db_session.refresh(target)
    assert target.account_source == "coding"
    assert target.apaas_user_id == "apaas-user-1"
    assert target.apaas_tenant_id == "apaas-tenant-1"
    assert target.apaas_token == "token-for-apaas-tenant-1"
    assert target.display_name == "aPaaS 管理员"

    tenant = (
        await db_session.execute(
            select(Tenant).where(Tenant.apaas_tenant_id_str == "apaas-tenant-1")
        )
    ).scalar_one()
    membership = (
        await db_session.execute(
            select(UserTenant).where(
                UserTenant.user_id == target.id,
                UserTenant.tenant_id == tenant.id,
                UserTenant.status == 1,
            )
        )
    ).scalar_one()
    assert membership.is_default is True
    old_membership = (
        await db_session.execute(
            select(UserTenant).where(
                UserTenant.user_id == target.id,
                UserTenant.tenant_id == old_tenant.id,
            )
        )
    ).scalar_one()
    assert old_membership.is_default is False

    credential = (
        await db_session.execute(
            select(APaaSUserCredential).where(
                APaaSUserCredential.user_id == target.id,
                APaaSUserCredential.local_tenant_id == tenant.id,
            )
        )
    ).scalar_one()
    assert credential.account == "apaas-admin"
    assert credential.apaas_user_id == "apaas-user-1"
    assert credential.apaas_tenant_id == "apaas-tenant-1"
    assert credential.token == "token-for-apaas-tenant-1"

    assert result["id"] == target.id
    assert result["account_source"] == "coding"
    assert result["apaas_bound"] is True
    assert result["apaas_tenant_id"] == "apaas-tenant-1"
