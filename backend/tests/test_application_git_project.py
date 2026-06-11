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


def _ctx(user: User, tenant_id: int) -> AuthContext:
    return AuthContext(user=user, tenant_id=tenant_id, tenant_role="tenant_admin", org_permissions={})


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
