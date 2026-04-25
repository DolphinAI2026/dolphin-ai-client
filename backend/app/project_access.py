from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Project, ProjectMember


PROJECT_ROLE_LEVELS = {
    "member": 1,
    "admin": 2,
    "owner": 3,
}


def normalize_project_role(role: Optional[str]) -> str:
    if role in PROJECT_ROLE_LEVELS:
        return role
    return "member"


def project_role_at_least(role: Optional[str], required: str) -> bool:
    actual = PROJECT_ROLE_LEVELS.get(normalize_project_role(role), 0)
    expected = PROJECT_ROLE_LEVELS.get(normalize_project_role(required), 0)
    return actual >= expected


def project_role_permissions(role: Optional[str]) -> dict[str, bool]:
    normalized = normalize_project_role(role)
    return {
        "can_view": True,
        "can_edit": project_role_at_least(normalized, "member"),
        "can_manage_project": project_role_at_least(normalized, "admin"),
        "can_manage_platform": project_role_at_least(normalized, "admin"),
        "can_manage_members": project_role_at_least(normalized, "admin"),
        "can_manage_member_roles": normalized == "owner",
        "can_delete": normalized == "owner",
        "can_publish": project_role_at_least(normalized, "admin"),
    }


@dataclass
class ProjectAccess:
    project: Project
    role: str

    @property
    def permissions(self) -> dict[str, bool]:
        return project_role_permissions(self.role)


async def get_project_access(
    db: AsyncSession,
    *,
    project_id: int,
    user_id: int,
    tenant_id: int,
) -> Optional[ProjectAccess]:
    result = await db.execute(
        select(Project).where(
            Project.id == project_id,
            Project.tenant_id == tenant_id,
        )
    )
    project = result.scalar_one_or_none()
    if not project:
        return None

    member_result = await db.execute(
        select(ProjectMember).where(
            ProjectMember.project_id == project_id,
            ProjectMember.user_id == user_id,
        )
    )
    member = member_result.scalar_one_or_none()
    if not member:
        if project.user_id == user_id:
            return ProjectAccess(project=project, role="owner")
        return None

    return ProjectAccess(
        project=project,
        role=normalize_project_role(member.role or "member"),
    )


async def require_project_access(
    db: AsyncSession,
    *,
    project_id: int,
    user_id: int,
    tenant_id: int,
    minimum_role: str = "member",
) -> ProjectAccess:
    access = await get_project_access(
        db,
        project_id=project_id,
        user_id=user_id,
        tenant_id=tenant_id,
    )
    if not access:
        raise HTTPException(status_code=404, detail="项目不存在")
    if not project_role_at_least(access.role, minimum_role):
        raise HTTPException(status_code=403, detail="无权访问该项目")
    return access
