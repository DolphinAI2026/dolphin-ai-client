from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Project, ProjectMember


PROJECT_ROLE_LEVELS = {
    "viewer": 1,
    "contributor": 2,
    "maintainer": 3,
    "owner": 4,
}

# 旧名称到新名称的映射（向后兼容，DB 已通过 migration 改了，但 API 入参可能还是旧名称）
LEGACY_ROLE_ALIASES = {
    "member": "contributor",
    "admin": "maintainer",
}


def normalize_project_role(role: Optional[str]) -> str:
    if role in LEGACY_ROLE_ALIASES:
        return LEGACY_ROLE_ALIASES[role]
    if role in PROJECT_ROLE_LEVELS:
        return role
    return "viewer"


def project_role_at_least(role: Optional[str], required: str) -> bool:
    actual = PROJECT_ROLE_LEVELS.get(normalize_project_role(role), 0)
    expected = PROJECT_ROLE_LEVELS.get(normalize_project_role(required), 0)
    return actual >= expected


def project_role_permissions(role: Optional[str]) -> dict[str, bool]:
    normalized = normalize_project_role(role)
    return {
        "can_view": True,  # viewer 起就能看
        "can_edit": project_role_at_least(normalized, "contributor"),
        "can_manage_project": project_role_at_least(normalized, "maintainer"),
        "can_manage_platform": project_role_at_least(normalized, "maintainer"),
        "can_manage_members": project_role_at_least(normalized, "maintainer"),
        "can_manage_member_roles": normalized == "owner",
        "can_delete": normalized == "owner",
        "can_publish": project_role_at_least(normalized, "maintainer"),
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
        role=normalize_project_role(member.role or "contributor"),
    )


async def require_project_access(
    db: AsyncSession,
    *,
    project_id: int,
    user_id: int,
    tenant_id: int,
    minimum_role: str = "contributor",
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
