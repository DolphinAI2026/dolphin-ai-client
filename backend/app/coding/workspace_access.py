"""Shared workspace access checks for coding routes and agent tools."""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.coding.workspace import WorkspaceManager
from app.deps import AuthContext
from app.models import Application
from app.project_access import project_role_at_least, require_project_access


workspace_mgr = WorkspaceManager()


def _workspace_permissions(access_role: str) -> dict[str, bool]:
    return {
        "edit": project_role_at_least(access_role, "member"),
        "delete": project_role_at_least(access_role, "admin"),
        "publish": project_role_at_least(access_role, "admin"),
        "upload_to_platform": project_role_at_least(access_role, "admin"),
    }


def _decorate_workspace_access(meta: dict[str, Any], access_role: str) -> dict[str, Any]:
    return {
        **meta,
        "access_role": access_role,
        "permissions": _workspace_permissions(access_role),
    }


async def _ensure_workspace_access(
    ws_id: str,
    ctx: AuthContext,
    db: AsyncSession,
    *,
    minimum_project_role: str = "member",
) -> dict[str, Any]:
    try:
        meta = workspace_mgr.get_workspace_info(ws_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="工作区不存在")

    project_id = meta.get("project_id")
    if project_id:
        # project_id 字段被复用为「所属应用」(Application.id)。应用绑定不是协作项目,
        # 不能拿它查 Project 表(会 404 把工作区打不开)。归属=应用属本租户:
        # 创建者按 owner, 同租户其他成员按 member(admin 级操作仍只限创建者)。
        app_row = await db.execute(
            select(Application.id).where(
                Application.id == int(project_id),
                Application.tenant_id == ctx.tenant_id,
            )
        )
        if app_row.scalar_one_or_none() is not None:
            role = "owner" if meta.get("user_id") == ctx.user.id else "member"
            if minimum_project_role in ("admin", "owner") and role != "owner":
                raise HTTPException(status_code=403, detail="无权执行该操作")
            return _decorate_workspace_access(meta, role)
        access = await require_project_access(
            db,
            project_id=int(project_id),
            user_id=ctx.user.id,
            tenant_id=ctx.tenant_id,
            minimum_role=minimum_project_role,
        )
        return _decorate_workspace_access(meta, access.role)

    if meta.get("user_id") != ctx.user.id:
        raise HTTPException(status_code=403, detail="无权访问该工作区")

    return _decorate_workspace_access(meta, "owner")
