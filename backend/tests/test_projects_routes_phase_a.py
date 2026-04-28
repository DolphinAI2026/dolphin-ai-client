"""Phase A — projects route 接受新 role 名 + 旧名称 alias 兼容

测试目标：
- AddMemberRequest 默认 role='contributor'
- add_member 接受新 role 名 'contributor' / 'maintainer' / 'viewer'
- 旧 'admin' / 'member' 通过 normalize 自动映射
- update_member_role 接受新 role 名

直接 import route handler 函数级调用，绕过 HTTP 层（仍走真实 ORM + DB）。
"""
import pytest
from datetime import datetime
from fastapi import HTTPException
from sqlalchemy import select

from app.deps import AuthContext
from app.models import Project, ProjectMember, User
from app.models.tenant import Tenant, UserTenant
from app.routes.projects import (
    AddMemberRequest,
    UpdateMemberRoleRequest,
    add_member,
    update_member_role,
)


async def _setup(db_session, owner_role: str = "owner"):
    """建一个 tenant + owner user + target user + project + 把两个 user 加到 tenant
    返回 (ctx, project_id, target_user_id)。
    """
    # tenant
    tenant = Tenant(tenant_name="t1", tenant_code="t1")
    db_session.add(tenant)
    await db_session.flush()

    # owner user
    owner = User(username="owner_u", hashed_password="x")
    target = User(username="target_u", hashed_password="x")
    db_session.add_all([owner, target])
    await db_session.flush()

    # 把两人都加到 tenant
    db_session.add_all(
        [
            UserTenant(user_id=owner.id, tenant_id=tenant.id, status=1),
            UserTenant(user_id=target.id, tenant_id=tenant.id, status=1),
        ]
    )

    # project（owner 是 user_id）
    project = Project(name="p1", user_id=owner.id, tenant_id=tenant.id)
    db_session.add(project)
    await db_session.flush()

    # 把 owner 加为 project_member.owner
    db_session.add(
        ProjectMember(project_id=project.id, user_id=owner.id, role="owner")
    )
    await db_session.commit()

    ctx = AuthContext(
        user=owner,
        tenant_id=tenant.id,
        tenant_role="tenant_admin",
        org_permissions={},
    )
    return ctx, project.id, target.id


@pytest.mark.asyncio
async def test_add_member_with_new_role_name_contributor(db_session):
    """新名 contributor 可被接受"""
    ctx, project_id, target_user_id = await _setup(db_session)

    req = AddMemberRequest(user_id=target_user_id, role="contributor")
    result = await add_member(project_id, req, ctx, db_session)
    assert result["role"] == "contributor"
    assert result["user_id"] == target_user_id


@pytest.mark.asyncio
async def test_add_member_legacy_role_name_member_aliased(db_session):
    """旧名 member 应自动 alias 到 contributor"""
    ctx, project_id, target_user_id = await _setup(db_session)

    req = AddMemberRequest(user_id=target_user_id, role="member")
    result = await add_member(project_id, req, ctx, db_session)
    assert result["role"] == "contributor"


@pytest.mark.asyncio
async def test_add_member_legacy_admin_aliased_to_maintainer(db_session):
    """旧名 admin 应映射到 maintainer（且 owner 调用者拥有权限）"""
    ctx, project_id, target_user_id = await _setup(db_session)

    req = AddMemberRequest(user_id=target_user_id, role="admin")
    result = await add_member(project_id, req, ctx, db_session)
    assert result["role"] == "maintainer"


@pytest.mark.asyncio
async def test_add_member_default_role_is_contributor(db_session):
    """AddMemberRequest 不传 role 时默认 contributor"""
    ctx, project_id, target_user_id = await _setup(db_session)

    req = AddMemberRequest(user_id=target_user_id)
    assert req.role == "contributor"
    result = await add_member(project_id, req, ctx, db_session)
    assert result["role"] == "contributor"


@pytest.mark.asyncio
async def test_add_member_owner_role_rejected(db_session):
    """不能直接邀请为 owner"""
    ctx, project_id, target_user_id = await _setup(db_session)

    req = AddMemberRequest(user_id=target_user_id, role="owner")
    with pytest.raises(HTTPException) as exc:
        await add_member(project_id, req, ctx, db_session)
    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_update_member_role_new_name_maintainer(db_session):
    """update 接受新名 maintainer"""
    ctx, project_id, target_user_id = await _setup(db_session)
    # 先加为 contributor
    req_add = AddMemberRequest(user_id=target_user_id, role="contributor")
    added = await add_member(project_id, req_add, ctx, db_session)

    req_upd = UpdateMemberRoleRequest(role="maintainer")
    result = await update_member_role(
        project_id, added["id"], req_upd, ctx, db_session
    )
    assert result["role"] == "maintainer"


@pytest.mark.asyncio
async def test_update_member_role_legacy_admin_aliased(db_session):
    """update 接受旧名 admin -> maintainer"""
    ctx, project_id, target_user_id = await _setup(db_session)
    req_add = AddMemberRequest(user_id=target_user_id, role="contributor")
    added = await add_member(project_id, req_add, ctx, db_session)

    req_upd = UpdateMemberRoleRequest(role="admin")
    result = await update_member_role(
        project_id, added["id"], req_upd, ctx, db_session
    )
    assert result["role"] == "maintainer"


@pytest.mark.asyncio
async def test_update_member_role_to_owner_rejected(db_session):
    """update 不允许改为 owner"""
    ctx, project_id, target_user_id = await _setup(db_session)
    req_add = AddMemberRequest(user_id=target_user_id, role="contributor")
    added = await add_member(project_id, req_add, ctx, db_session)

    req_upd = UpdateMemberRoleRequest(role="owner")
    with pytest.raises(HTTPException) as exc:
        await update_member_role(
            project_id, added["id"], req_upd, ctx, db_session
        )
    assert exc.value.status_code == 400
