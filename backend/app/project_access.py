from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Project


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
    """项目权限尚未设计，租户内项目不按成员角色限制操作。"""
    return True


def project_role_permissions(role: Optional[str]) -> dict[str, bool]:
    return {
        "can_view": True,
        "can_edit": True,
        "can_manage_project": True,
        "can_manage_platform": True,
        "can_manage_members": True,
        "can_manage_member_roles": True,
        "can_delete": True,
        "can_publish": True,
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

    return ProjectAccess(project=project, role="tenant")


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
    return access
