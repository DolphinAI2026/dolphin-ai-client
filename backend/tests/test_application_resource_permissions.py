import pytest
from fastapi import HTTPException

from app.deps import AuthContext
from app.models import Application, Project, ProjectMember, User
from app.models.collaboration import ApplicationMember
from app.models.tenant import Tenant, UserTenant
from app.permissions import Action, batch_get_permissions, check_resource_permission


async def _user(db, tenant_id: int, username: str) -> User:
    user = User(username=username, hashed_password="x")
    db.add(user)
    await db.flush()
    db.add(UserTenant(user_id=user.id, tenant_id=tenant_id, status=1))
    return user


def _ctx(user: User, tenant_id: int, tenant_role: str = "member") -> AuthContext:
    return AuthContext(
        user=user,
        tenant_id=tenant_id,
        tenant_role=tenant_role,
        org_permissions={},
    )


async def _seed(db):
    tenant = Tenant(tenant_name="permissions", tenant_code="permissions")
    other_tenant = Tenant(tenant_name="other", tenant_code="permissions-other")
    db.add_all([tenant, other_tenant])
    await db.flush()

    owner = await _user(db, tenant.id, "permission-owner")
    direct_admin = await _user(db, tenant.id, "permission-admin")
    direct_collaborator = await _user(db, tenant.id, "permission-collaborator")
    inherited_admin = await _user(db, tenant.id, "permission-inherited-admin")
    inherited_collaborator = await _user(db, tenant.id, "permission-inherited-collaborator")
    highest_role = await _user(db, tenant.id, "permission-highest-role")
    outsider = await _user(db, tenant.id, "permission-outsider")

    project = Project(name="permissions-project", user_id=owner.id, tenant_id=tenant.id)
    other_project = Project(name="other-project", user_id=owner.id, tenant_id=other_tenant.id)
    db.add_all([project, other_project])
    await db.flush()
    db.add_all([
        ProjectMember(project_id=project.id, user_id=inherited_admin.id, role="maintainer"),
        ProjectMember(project_id=project.id, user_id=inherited_collaborator.id, role="contributor"),
        ProjectMember(project_id=project.id, user_id=highest_role.id, role="maintainer"),
        ProjectMember(project_id=other_project.id, user_id=outsider.id, role="owner"),
    ])

    app = Application(
        user_id=owner.id,
        tenant_id=tenant.id,
        created_by=owner.id,
        project_id=project.id,
        app_name="Permissions App",
        app_code="permissions-app",
    )
    cross_project_app = Application(
        user_id=owner.id,
        tenant_id=tenant.id,
        created_by=owner.id,
        project_id=other_project.id,
        app_name="Cross Project App",
        app_code="cross-project-app",
    )
    db.add_all([app, cross_project_app])
    await db.flush()
    db.add_all([
        ApplicationMember(
            application_id=app.id,
            user_id=direct_admin.id,
            role="admin",
            invited_by=owner.id,
        ),
        ApplicationMember(
            application_id=app.id,
            user_id=direct_collaborator.id,
            role="collaborator",
            invited_by=owner.id,
        ),
        ApplicationMember(
            application_id=app.id,
            user_id=highest_role.id,
            role="collaborator",
            invited_by=owner.id,
        ),
    ])
    await db.commit()
    return {
        "tenant": tenant,
        "owner": owner,
        "direct_admin": direct_admin,
        "direct_collaborator": direct_collaborator,
        "inherited_admin": inherited_admin,
        "inherited_collaborator": inherited_collaborator,
        "highest_role": highest_role,
        "outsider": outsider,
        "app": app,
        "cross_project_app": cross_project_app,
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("user_key", "action"),
    [
        ("owner", Action.VIEW),
        ("owner", Action.EDIT),
        ("owner", Action.DELETE),
        ("owner", Action.CLONE),
        ("direct_admin", Action.DELETE),
        ("inherited_admin", Action.DELETE),
        ("highest_role", Action.DELETE),
        ("direct_collaborator", Action.VIEW),
        ("direct_collaborator", Action.EDIT),
        ("direct_collaborator", Action.CLONE),
        ("inherited_collaborator", Action.EDIT),
    ],
)
async def test_application_effective_roles_allow_expected_actions(db_session, user_key, action):
    seed = await _seed(db_session)
    await check_resource_permission(
        _ctx(seed[user_key], seed["tenant"].id),
        db_session,
        seed["app"],
        "application",
        action,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("user_key", ["direct_collaborator", "inherited_collaborator"])
async def test_application_collaborators_cannot_delete(db_session, user_key):
    seed = await _seed(db_session)
    with pytest.raises(HTTPException) as denied:
        await check_resource_permission(
            _ctx(seed[user_key], seed["tenant"].id),
            db_session,
            seed["app"],
            "application",
            Action.DELETE,
        )
    assert denied.value.status_code == 403


@pytest.mark.asyncio
@pytest.mark.parametrize("action", [Action.VIEW, Action.EDIT, Action.DELETE, Action.CLONE])
async def test_application_outsider_is_denied_all_actions(db_session, action):
    seed = await _seed(db_session)
    with pytest.raises(HTTPException) as denied:
        await check_resource_permission(
            _ctx(seed["outsider"], seed["tenant"].id),
            db_session,
            seed["app"],
            "application",
            action,
        )
    assert denied.value.status_code == 403


@pytest.mark.asyncio
async def test_cross_tenant_project_membership_does_not_grant_application_permission(db_session):
    seed = await _seed(db_session)
    with pytest.raises(HTTPException) as denied:
        await check_resource_permission(
            _ctx(seed["outsider"], seed["tenant"].id),
            db_session,
            seed["cross_project_app"],
            "application",
            Action.VIEW,
        )
    assert denied.value.status_code == 403


@pytest.mark.asyncio
@pytest.mark.parametrize("tenant_role", ["tenant_admin", "platform_admin"])
async def test_application_tenant_admin_roles_bypass_member_lookup(db_session, tenant_role):
    seed = await _seed(db_session)
    await check_resource_permission(
        _ctx(seed["outsider"], seed["tenant"].id, tenant_role),
        db_session,
        seed["app"],
        "application",
        Action.DELETE,
    )


@pytest.mark.asyncio
async def test_application_permission_requires_database_session(db_session):
    seed = await _seed(db_session)
    with pytest.raises(ValueError, match="db is required"):
        await check_resource_permission(
            _ctx(seed["owner"], seed["tenant"].id),
            None,
            seed["app"],
            "application",
            Action.VIEW,
        )


@pytest.mark.asyncio
async def test_batch_application_permissions_match_effective_roles(db_session):
    seed = await _seed(db_session)
    expected_collaborator = {
        Action.VIEW: True,
        Action.EDIT: True,
        Action.DELETE: False,
        Action.CLONE: True,
    }
    expected_outsider = {
        Action.VIEW: False,
        Action.EDIT: False,
        Action.DELETE: False,
        Action.CLONE: False,
    }

    collaborator = await batch_get_permissions(
        _ctx(seed["direct_collaborator"], seed["tenant"].id),
        db_session,
        [seed["app"]],
        "application",
    )
    outsider = await batch_get_permissions(
        _ctx(seed["outsider"], seed["tenant"].id),
        db_session,
        [seed["app"], seed["cross_project_app"]],
        "application",
    )

    assert collaborator == [expected_collaborator]
    assert outsider == [expected_outsider, expected_outsider]
