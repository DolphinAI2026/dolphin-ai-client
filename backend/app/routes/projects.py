"""
Project API 路由 — 项目管理 + 平台环境配置
"""
from __future__ import annotations

import json
import logging
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import Project
from app.deps import get_auth_context, AuthContext
from app.apaas_client import APaaSClient
from app.coding.workspace import WorkspaceManager, WORKSPACE_ROOT

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/projects", tags=["projects"])


# ============================================================
# 请求/响应模型
# ============================================================

class CreateProjectRequest(BaseModel):
    name: str
    description: Optional[str] = None


class UpdateProjectRequest(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    platform_url: Optional[str] = None
    platform_tenant_id: Optional[str] = None
    platform_token: Optional[str] = None
    platform_username: Optional[str] = None
    platform_app_id: Optional[str] = None
    platform_app_name: Optional[str] = None


class ProjectConnectRequest(BaseModel):
    username: str
    password: str
    base_url: str
    tenant_id: str


# ============================================================
# 辅助函数
# ============================================================

def _project_to_dict(p: Project) -> dict:
    return {
        "id": p.id,
        "name": p.name,
        "description": p.description,
        "platform_url": p.platform_url,
        "platform_tenant_id": p.platform_tenant_id,
        "platform_username": p.platform_username,
        "platform_app_id": p.platform_app_id,
        "platform_app_name": p.platform_app_name,
        "platform_connected": bool(p.platform_token),
        "created_at": p.created_at.isoformat() if p.created_at else None,
        "updated_at": p.updated_at.isoformat() if p.updated_at else None,
    }


async def _get_project_or_404(
    project_id: int,
    user_id: int,
    db: AsyncSession,
) -> Project:
    result = await db.execute(
        select(Project).where(Project.id == project_id, Project.user_id == user_id)
    )
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    return project


# ============================================================
# CRUD 接口
# ============================================================

@router.get("")
async def list_projects(
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """列出当前用户的所有项目"""
    result = await db.execute(
        select(Project)
        .where(Project.user_id == ctx.user.id, Project.tenant_id == ctx.tenant_id)
        .order_by(Project.updated_at.desc())
    )
    projects = result.scalars().all()
    return [_project_to_dict(p) for p in projects]


@router.post("")
async def create_project(
    req: CreateProjectRequest,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """创建新项目"""
    project = Project(
        name=req.name,
        description=req.description,
        user_id=ctx.user.id,
        tenant_id=ctx.tenant_id,
    )
    db.add(project)
    await db.commit()
    await db.refresh(project)
    return _project_to_dict(project)


@router.get("/{project_id}")
async def get_project(
    project_id: int,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """获取项目详情"""
    project = await _get_project_or_404(project_id, ctx.user.id, db)
    return _project_to_dict(project)


@router.put("/{project_id}")
async def update_project(
    project_id: int,
    req: UpdateProjectRequest,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """更新项目（包括平台配置）"""
    project = await _get_project_or_404(project_id, ctx.user.id, db)

    for field in ["name", "description", "platform_url", "platform_tenant_id",
                  "platform_token", "platform_username", "platform_app_id", "platform_app_name"]:
        value = getattr(req, field, None)
        if value is not None:
            setattr(project, field, value)

    await db.commit()
    await db.refresh(project)
    return _project_to_dict(project)


@router.delete("/{project_id}")
async def delete_project(
    project_id: int,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """删除项目"""
    project = await _get_project_or_404(project_id, ctx.user.id, db)
    await db.delete(project)
    await db.commit()
    return {"status": "ok"}


# ============================================================
# 平台连接
# ============================================================

@router.post("/{project_id}/connect")
async def connect_project_platform(
    project_id: int,
    req: ProjectConnectRequest,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """为项目连接/登录得帆云平台"""
    project = await _get_project_or_404(project_id, ctx.user.id, db)

    client = APaaSClient(base_url=req.base_url, tenant_id=req.tenant_id)
    try:
        result = await client.login(req.username, req.password)
        token = result.get("token", "")

        project.platform_url = req.base_url
        project.platform_tenant_id = req.tenant_id
        project.platform_token = token
        project.platform_username = req.username

        await db.commit()
        await db.refresh(project)
        return _project_to_dict(project)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"平台登录失败: {e}")


# ============================================================
# 项目下的工作区
# ============================================================

@router.get("/{project_id}/workspaces")
async def list_project_workspaces(
    project_id: int,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """列出项目下的所有工作区"""
    # Verify project ownership
    await _get_project_or_404(project_id, ctx.user.id, db)

    ws_mgr = WorkspaceManager()
    all_workspaces = ws_mgr.list_user_workspaces(ctx.user.id)

    # Filter workspaces belonging to this project
    project_workspaces = []
    for ws in all_workspaces:
        if ws.get("project_id") == project_id:
            project_workspaces.append(ws)

    return project_workspaces
