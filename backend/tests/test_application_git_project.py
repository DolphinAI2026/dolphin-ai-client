import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.deps import AuthContext
from app.models import Application, Project, ProjectMember, User
from app.models.tenant import Tenant, UserTenant
from app.routes.applications import ensure_application_git_project


async def _seed_owner_app(db_session, *, with_project: bool = False):
    tenant = Tenant(tenant_name="tenant", tenant_code="tenant")
    owner = User(username="git_app_owner", hashed_password="x")
    outsider = User(username="git_app_outsider", hashed_password="x")
    db_session.add_all([tenant, owner, outsider])
    await db_session.flush()
    db_session.add_all([
        UserTenant(user_id=owner.id, tenant_id=tenant.id, status=1),
        UserTenant(user_id=outsider.id, tenant_id=tenant.id, status=1),
    ])
    project = None
    if with_project:
        project = Project(name="Existing Project", user_id=owner.id, tenant_id=tenant.id)
        db_session.add(project)
        await db_session.flush()
        db_session.add(ProjectMember(project_id=project.id, user_id=owner.id, role="owner"))
    app = Application(
        user_id=owner.id,
        tenant_id=tenant.id,
        created_by=owner.id,
        project_id=project.id if project else None,
        app_name="Legacy App",
        app_code="legacy-app",
        status="completed",
    )
    db_session.add(app)
    await db_session.commit()
    return tenant, owner, outsider, app, project


def _ctx(user: User, tenant_id: int, tenant_role: str = "member") -> AuthContext:
    return AuthContext(user=user, tenant_id=tenant_id, tenant_role=tenant_role, org_permissions={})


@pytest.mark.asyncio
async def test_ensure_application_git_project_creates_project_for_legacy_app(db_session):
    tenant, owner, _, app, _ = await _seed_owner_app(db_session)

    result = await ensure_application_git_project(app.id, _ctx(owner, tenant.id), db_session)

    assert result["application_id"] == app.id
    assert result["created"] is True
    assert result["project_id"]

    project = (await db_session.execute(select(Project).where(Project.id == result["project_id"]))).scalar_one()
    member = (
        await db_session.execute(
            select(ProjectMember).where(
                ProjectMember.project_id == project.id,
                ProjectMember.user_id == owner.id,
            )
        )
    ).scalar_one()
    refreshed_app = (await db_session.execute(select(Application).where(Application.id == app.id))).scalar_one()

    assert project.name == "Legacy App"
    assert member.role == "owner"
    assert refreshed_app.project_id == project.id


@pytest.mark.asyncio
async def test_ensure_application_git_project_reuses_existing_project(db_session):
    tenant, owner, _, app, project = await _seed_owner_app(db_session, with_project=True)

    result = await ensure_application_git_project(app.id, _ctx(owner, tenant.id), db_session)

    assert result == {"application_id": app.id, "project_id": project.id, "created": False}
    projects = (await db_session.execute(select(Project))).scalars().all()
    assert len(projects) == 1


@pytest.mark.asyncio
async def test_ensure_application_git_project_rejects_non_owner_legacy_app(db_session):
    tenant, _, outsider, app, _ = await _seed_owner_app(db_session)

    with pytest.raises(HTTPException) as exc:
        await ensure_application_git_project(app.id, _ctx(outsider, tenant.id), db_session)

    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_ensure_application_git_project_checks_permission_before_reuse(db_session):
    tenant, _, outsider, app, _ = await _seed_owner_app(db_session, with_project=True)

    with pytest.raises(HTTPException) as exc:
        await ensure_application_git_project(app.id, _ctx(outsider, tenant.id), db_session)

    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_ensure_application_git_project_allows_non_owner_tenant_admin(db_session):
    tenant, owner, outsider, app, _ = await _seed_owner_app(db_session)

    result = await ensure_application_git_project(
        app.id,
        _ctx(outsider, tenant.id, "tenant_admin"),
        db_session,
    )

    assert result["application_id"] == app.id
    assert result["created"] is True
    project = await db_session.get(Project, result["project_id"])
    members = list((await db_session.scalars(
        select(ProjectMember).where(ProjectMember.project_id == project.id)
    )).all())
    assert project.user_id == owner.id
    assert [(member.user_id, member.role) for member in members] == [(owner.id, "owner")]

    with pytest.raises(HTTPException) as denied_after_admin_fallback_removed:
        await ensure_application_git_project(
            app.id,
            _ctx(outsider, tenant.id, "member"),
            db_session,
        )
    assert denied_after_admin_fallback_removed.value.status_code == 403


@pytest.mark.asyncio
@pytest.mark.parametrize("creator_state", ["missing", "other_tenant"])
async def test_ensure_application_git_project_rejects_invalid_tenant_creator(
    db_session,
    creator_state,
):
    tenant, _, outsider, app, _ = await _seed_owner_app(db_session)
    if creator_state == "missing":
        app.created_by = 999999
    else:
        other_tenant = Tenant(tenant_name="other", tenant_code="git-project-other")
        other_creator = User(username="other-tenant-creator", hashed_password="x")
        db_session.add_all([other_tenant, other_creator])
        await db_session.flush()
        db_session.add(UserTenant(
            user_id=other_creator.id,
            tenant_id=other_tenant.id,
            status=1,
        ))
        app.created_by = other_creator.id
    await db_session.commit()

    with pytest.raises(HTTPException) as invalid_creator:
        await ensure_application_git_project(
            app.id,
            _ctx(outsider, tenant.id, "tenant_admin"),
            db_session,
        )

    assert invalid_creator.value.status_code == 409
    await db_session.refresh(app)
    assert app.project_id is None
