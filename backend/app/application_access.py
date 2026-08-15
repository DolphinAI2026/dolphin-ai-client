from __future__ import annotations

from sqlalchemy import literal, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Application, Project, ProjectMember
from app.models.collaboration import ApplicationMember


PROJECT_TO_APPLICATION_ROLE = {
    "owner": "owner",
    "maintainer": "admin",
    "admin": "admin",
    "contributor": "collaborator",
    "viewer": "collaborator",
    "member": "collaborator",
}
ROLE_LEVELS = {"collaborator": 1, "admin": 2, "owner": 3}


def normalize_application_role(role: str | None) -> str | None:
    if role in ROLE_LEVELS:
        return role
    return PROJECT_TO_APPLICATION_ROLE.get(str(role or "").strip())


def application_visible_to_user_clause(user_id: int):
    direct_membership = select(ApplicationMember.id).where(
        ApplicationMember.application_id == Application.id,
        ApplicationMember.user_id == user_id,
    ).exists()
    inherited_membership = (
        select(ProjectMember.id)
        .join(Project, Project.id == ProjectMember.project_id)
        .where(
            Application.project_id.is_not(None),
            ProjectMember.project_id == Application.project_id,
            ProjectMember.user_id == user_id,
            Project.tenant_id == Application.tenant_id,
        )
        .exists()
    )
    return or_(
        Application.created_by == user_id,
        direct_membership,
        inherited_membership,
    )


async def resolve_effective_application_role(
    db: AsyncSession,
    app: Application,
    user_id: int,
) -> str | None:
    roles: list[str] = []
    if app.created_by == user_id:
        roles.append("owner")

    direct_role = select(ApplicationMember.role).where(
        ApplicationMember.application_id == app.id,
        ApplicationMember.user_id == user_id,
    ).scalar_subquery()
    inherited_role = literal(None)
    if app.project_id is not None:
        inherited_role = (
            select(ProjectMember.role)
            .join(Project, Project.id == ProjectMember.project_id)
            .where(
                ProjectMember.project_id == app.project_id,
                ProjectMember.user_id == user_id,
                Project.tenant_id == app.tenant_id,
            )
            .scalar_subquery()
        )
    direct, inherited = (await db.execute(
        select(direct_role, inherited_role)
    )).one()

    direct = normalize_application_role(direct)
    inherited = PROJECT_TO_APPLICATION_ROLE.get(str(inherited or "").strip())
    if direct:
        roles.append(direct)
    if inherited:
        roles.append(inherited)
    return max(roles, key=ROLE_LEVELS.__getitem__) if roles else None
