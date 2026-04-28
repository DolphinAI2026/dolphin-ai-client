"""ApplicationMember 邀请 API 测试 — 函数级调用，绕过 HTTP 层。

覆盖：
- list 合并 creator + inherited (ProjectMember) + direct (ApplicationMember)
- invite 落库
- 重复 invite 报 400
- 仅 owner 可指派 maintainer（contributor 调用者尝试 -> 403）
"""
import pytest
from fastapi import HTTPException

from app.deps import AuthContext
from app.models import Application, Project, ProjectMember, User
from app.models.collaboration import ApplicationMember
from app.models.tenant import Tenant, UserTenant
from app.routes.application_members import (
    InviteAppMemberRequest,
    invite_application_member,
    list_application_members,
)
from app.routes.applications import _get_application_permissions
from app.permissions import Action


async def _make_user(db, username: str) -> User:
    u = User(username=username, hashed_password="x")
    db.add(u)
    await db.flush()
    return u


async def _seed(db_session):
    """建一个 tenant + 多个用户 + project + application

    返回 dict:
      tenant, owner (creator), pm_user (project member, contributor),
      direct_user (application member, contributor), outside_user (待邀请),
      project, application
    """
    tenant = Tenant(tenant_name="t1", tenant_code="t1")
    db_session.add(tenant)
    await db_session.flush()

    owner = await _make_user(db_session, "owner_u")
    pm_user = await _make_user(db_session, "pm_u")
    direct_user = await _make_user(db_session, "direct_u")
    outside_user = await _make_user(db_session, "outside_u")

    db_session.add_all([
        UserTenant(user_id=owner.id, tenant_id=tenant.id, status=1),
        UserTenant(user_id=pm_user.id, tenant_id=tenant.id, status=1),
        UserTenant(user_id=direct_user.id, tenant_id=tenant.id, status=1),
        UserTenant(user_id=outside_user.id, tenant_id=tenant.id, status=1),
    ])

    project = Project(name="p1", user_id=owner.id, tenant_id=tenant.id)
    db_session.add(project)
    await db_session.flush()

    db_session.add(ProjectMember(project_id=project.id, user_id=owner.id, role="owner"))
    db_session.add(ProjectMember(project_id=project.id, user_id=pm_user.id, role="contributor"))

    application = Application(
        user_id=owner.id,
        tenant_id=tenant.id,
        created_by=owner.id,
        project_id=project.id,
        app_name="App 1",
        app_code="app_1",
    )
    db_session.add(application)
    await db_session.flush()

    db_session.add(ApplicationMember(
        application_id=application.id,
        user_id=direct_user.id,
        role="contributor",
        invited_by=owner.id,
    ))
    await db_session.commit()

    return {
        "tenant": tenant,
        "owner": owner,
        "pm_user": pm_user,
        "direct_user": direct_user,
        "outside_user": outside_user,
        "project": project,
        "application": application,
    }


def _ctx_for(user: User, tenant_id: int) -> AuthContext:
    return AuthContext(
        user=user,
        tenant_id=tenant_id,
        tenant_role="tenant_admin",
        org_permissions={},
    )


@pytest.mark.asyncio
async def test_list_includes_creator_and_inherited_and_direct(db_session):
    """list 应合并 creator (owner) + inherited (pm_user) + direct (direct_user)"""
    s = await _seed(db_session)
    ctx = _ctx_for(s["owner"], s["tenant"].id)

    result = await list_application_members(s["application"].id, ctx, db_session)

    by_username = {m["username"]: m for m in result}
    assert "owner_u" in by_username
    assert "pm_u" in by_username
    assert "direct_u" in by_username

    # owner 走 ProjectMember(owner) 一路 → source=inherited（更优先于 creator，因 already in project）
    # 但 owner_u 既是 creator 也是 inherited owner — 实际看实现：
    # ProjectMember 先放进 dict（source=inherited, role=owner），
    # ApplicationMember 之后会覆盖（owner 没 application_member），
    # 最后 creator 检查 if app.created_by not in members — 已经在了，不会加 creator。
    # 所以 owner_u 的 source 是 inherited（OK，因为他 role=owner 同样满足 UI）。
    assert by_username["owner_u"]["role"] == "owner"
    assert by_username["pm_u"]["source"] == "inherited"
    assert by_username["pm_u"]["role"] == "contributor"
    assert by_username["direct_u"]["source"] == "direct"
    assert by_username["direct_u"]["role"] == "contributor"


@pytest.mark.asyncio
async def test_list_creator_source_when_no_project(db_session):
    """如果 application 没 project_id，且 creator 不在 ApplicationMember 中，
    creator 应作为 source=creator 出现"""
    tenant = Tenant(tenant_name="t1", tenant_code="t1")
    db_session.add(tenant)
    await db_session.flush()

    owner = await _make_user(db_session, "lone_owner")
    db_session.add(UserTenant(user_id=owner.id, tenant_id=tenant.id, status=1))

    application = Application(
        user_id=owner.id,
        tenant_id=tenant.id,
        created_by=owner.id,
        project_id=None,
        app_name="Lone",
        app_code="lone",
    )
    db_session.add(application)
    await db_session.commit()

    ctx = _ctx_for(owner, tenant.id)
    result = await list_application_members(application.id, ctx, db_session)
    assert len(result) == 1
    assert result[0]["username"] == "lone_owner"
    assert result[0]["source"] == "creator"
    assert result[0]["role"] == "owner"


@pytest.mark.asyncio
async def test_invite_creates_application_member(db_session):
    """owner 邀请 outside_user 为 contributor → 落库"""
    s = await _seed(db_session)
    ctx = _ctx_for(s["owner"], s["tenant"].id)

    req = InviteAppMemberRequest(user_id=s["outside_user"].id, role="contributor")
    result = await invite_application_member(s["application"].id, req, ctx, db_session)

    assert result["user_id"] == s["outside_user"].id
    assert result["role"] == "contributor"
    assert result["source"] == "direct"
    assert result["username"] == "outside_u"


@pytest.mark.asyncio
async def test_invite_duplicate_returns_400(db_session):
    """第二次邀请同一个已存在的 ApplicationMember → 400"""
    s = await _seed(db_session)
    ctx = _ctx_for(s["owner"], s["tenant"].id)

    req = InviteAppMemberRequest(user_id=s["direct_user"].id, role="contributor")
    with pytest.raises(HTTPException) as exc:
        await invite_application_member(s["application"].id, req, ctx, db_session)
    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_direct_application_member_gets_application_permissions(db_session):
    """直接邀请的应用成员应能进入应用列表/详情权限计算。"""
    s = await _seed(db_session)
    ctx = AuthContext(
        user=s["direct_user"],
        tenant_id=s["tenant"].id,
        tenant_role="member",
        org_permissions={"application:view": True, "application:edit": True},
    )

    perms = await _get_application_permissions(ctx, db_session, s["application"])

    assert perms is not None
    assert perms[Action.VIEW] is True
    assert perms[Action.EDIT] is True
    assert perms["publish"] is False
    assert perms["can_manage_members"] is False
    assert perms["access_role"] == "contributor"


@pytest.mark.asyncio
async def test_only_owner_can_invite_maintainer(db_session):
    """contributor 调用者尝试邀请 maintainer → 403"""
    s = await _seed(db_session)
    # pm_user 是 ProjectMember(contributor)，不能邀请 maintainer，且 contributor 也没 maintainer 权限
    # 这里用一个 maintainer 级 caller 测试：先 promote pm_user 到 maintainer，再尝试邀请 maintainer
    pm = (await db_session.execute(
        __import__("sqlalchemy").select(ProjectMember).where(
            ProjectMember.user_id == s["pm_user"].id,
            ProjectMember.project_id == s["project"].id,
        )
    )).scalar_one()
    pm.role = "maintainer"
    await db_session.commit()

    ctx = AuthContext(
        user=s["pm_user"],
        tenant_id=s["tenant"].id,
        tenant_role="member",
        org_permissions={"application:view": True, "application:edit": True},
    )
    req = InviteAppMemberRequest(user_id=s["outside_user"].id, role="maintainer")
    with pytest.raises(HTTPException) as exc:
        await invite_application_member(s["application"].id, req, ctx, db_session)
    assert exc.value.status_code == 403
