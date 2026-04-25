"""
Project API 路由 — 项目管理 + 平台环境配置
"""
from __future__ import annotations

import json
import logging
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select, or_
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import Project, ProjectMember, User
from app.deps import get_auth_context, AuthContext
from app.apaas_client import APaaSClient
from app.coding.workspace import WorkspaceManager, WORKSPACE_ROOT
from app.error_messages import APAAS_TOKEN_EXPIRED_PROJECT, APAAS_TOKEN_REFRESH_FAILED
from app.models.tenant import UserTenant
from app.project_access import (
    ProjectAccess,
    get_project_access,
    project_role_at_least,
    project_role_permissions,
    require_project_access,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/projects", tags=["projects"])


async def ensure_platform_token(project: Project, db: AsyncSession) -> str:
    """确保项目的平台 token 有效。如果过期，自动用保存的凭证重新登录。"""
    import base64

    if not project.platform_url or not project.platform_tenant_id:
        raise HTTPException(400, "项目未配置平台环境")

    # 先试用现有 token
    if project.platform_token:
        try:
            client = APaaSClient(base_url=project.platform_url, tenant_id=project.platform_tenant_id, token=project.platform_token)
            await client.query_app_list()  # 简单验证 token 有效性
            return project.platform_token
        except Exception:
            logger.info(f"项目 {project.id} 的 token 已过期，尝试自动刷新")

    # Token 无效，用保存的凭证重新登录
    if not project.platform_username or not project.platform_password_enc:
        raise HTTPException(401, APAAS_TOKEN_EXPIRED_PROJECT)

    try:
        password = base64.b64decode(project.platform_password_enc).decode()
        client = APaaSClient(base_url=project.platform_url, tenant_id=project.platform_tenant_id)
        result = await client.login(project.platform_username, password)
        new_token = result.get("token", "")
        if not new_token:
            raise HTTPException(401, "自动刷新 token 失败，请重新连接平台")

        # 更新 token
        project.platform_token = new_token
        await db.commit()
        logger.info(f"项目 {project.id} token 自动刷新成功")
        return new_token
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"自动刷新 token 失败: {e}")
        raise HTTPException(401, APAAS_TOKEN_REFRESH_FAILED)


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
    platform_app_code: Optional[str] = None


class ProjectConnectRequest(BaseModel):
    username: str
    password: str
    base_url: str
    tenant_id: str


class AddMemberRequest(BaseModel):
    username: Optional[str] = None
    user_id: Optional[int] = None
    role: str = "member"


class UpdateMemberRoleRequest(BaseModel):
    role: str  # "admin" | "member"


# ============================================================
# 辅助函数
# ============================================================

def _project_to_dict(p: Project, *, current_role: Optional[str] = None) -> dict:
    payload = {
        "id": p.id,
        "name": p.name,
        "description": p.description,
        "platform_url": p.platform_url,
        "platform_tenant_id": p.platform_tenant_id,
        "platform_username": p.platform_username,
        "platform_app_id": p.platform_app_id,
        "platform_app_name": p.platform_app_name,
        "platform_app_code": p.platform_app_code,
        "platform_connected": bool(p.platform_token),
        "created_at": p.created_at.isoformat() if p.created_at else None,
        "updated_at": p.updated_at.isoformat() if p.updated_at else None,
    }
    if current_role:
        payload["current_role"] = current_role
        payload.update(project_role_permissions(current_role))
    return payload


# ============================================================
# CRUD 接口
# ============================================================

@router.get("")
async def list_projects(
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """列出当前用户的所有项目（包括作为成员参与的项目）"""
    # 查询用户参与的项目 ID 列表
    member_result = await db.execute(
        select(ProjectMember.project_id).where(ProjectMember.user_id == ctx.user.id)
    )
    member_project_ids = [row[0] for row in member_result.all()]
    role_result = await db.execute(
        select(ProjectMember.project_id, ProjectMember.role).where(ProjectMember.user_id == ctx.user.id)
    )
    role_map = {project_id: role for project_id, role in role_result.all()}

    result = await db.execute(
        select(Project)
        .where(
            Project.tenant_id == ctx.tenant_id,
            or_(
                Project.user_id == ctx.user.id,
                Project.id.in_(member_project_ids) if member_project_ids else False,
            ),
        )
        .order_by(Project.updated_at.desc())
    )
    projects = result.scalars().all()
    return [
        _project_to_dict(
            p,
            current_role=role_map.get(p.id) or ("owner" if p.user_id == ctx.user.id else "member"),
        )
        for p in projects
    ]


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
    await db.flush()  # 获取 project.id

    # 自动添加创建者为 owner
    owner_member = ProjectMember(
        project_id=project.id,
        user_id=ctx.user.id,
        role="owner",
    )
    db.add(owner_member)
    await db.commit()
    await db.refresh(project)
    return _project_to_dict(project, current_role="owner")


@router.get("/{project_id}")
async def get_project(
    project_id: int,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """获取项目详情"""
    access = await require_project_access(
        db,
        project_id=project_id,
        user_id=ctx.user.id,
        tenant_id=ctx.tenant_id,
    )
    return _project_to_dict(access.project, current_role=access.role)


@router.put("/{project_id}")
async def update_project(
    project_id: int,
    req: UpdateProjectRequest,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """更新项目（包括平台配置）"""
    access = await require_project_access(
        db,
        project_id=project_id,
        user_id=ctx.user.id,
        tenant_id=ctx.tenant_id,
        minimum_role="admin",
    )
    project = access.project

    for field in ["name", "description", "platform_url", "platform_tenant_id",
                  "platform_token", "platform_username", "platform_app_id", "platform_app_name",
                  "platform_app_code"]:
        value = getattr(req, field, None)
        if value is not None:
            setattr(project, field, value)

    await db.commit()
    await db.refresh(project)
    return _project_to_dict(project, current_role=access.role)


@router.delete("/{project_id}")
async def delete_project(
    project_id: int,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """删除项目（级联删除关联的成员记录）"""
    access = await require_project_access(
        db,
        project_id=project_id,
        user_id=ctx.user.id,
        tenant_id=ctx.tenant_id,
        minimum_role="owner",
    )
    project = access.project
    # 先用原始 SQL 删除关联的 project_members（避免 ORM flush 顺序问题）
    from sqlalchemy import text
    await db.execute(text("DELETE FROM project_members WHERE project_id = :pid"), {"pid": project_id})
    await db.execute(text("DELETE FROM projects WHERE id = :pid"), {"pid": project_id})
    await db.commit()
    return {"status": "ok"}


# ============================================================
# 平台连接
# ============================================================

@router.get("/{project_id}/platform-apps")
async def list_platform_apps(
    project_id: int,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """获取项目已连接平台的应用列表"""
    access = await require_project_access(
        db,
        project_id=project_id,
        user_id=ctx.user.id,
        tenant_id=ctx.tenant_id,
    )
    project = access.project

    if not project.platform_token:
        raise HTTPException(status_code=400, detail="项目尚未连接平台，请先登录")

    client = APaaSClient(
        base_url=project.platform_url,
        tenant_id=project.platform_tenant_id,
        token=project.platform_token,
    )
    try:
        apps = await client.query_app_list()
        # 返回简化列表
        return [
            {
                "app_id": str(app.get("id", "")),
                "app_name": app.get("appName", ""),
                "app_code": app.get("appCode", ""),
                "status": app.get("appStatus", ""),
            }
            for app in apps
        ]
    except Exception as e:
        logger.error(f"查询平台应用列表失败: {e}")
        raise HTTPException(status_code=400, detail=f"查询应用列表失败: {e}")


@router.post("/{project_id}/connect")
async def connect_project_platform(
    project_id: int,
    req: ProjectConnectRequest,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """为项目连接/登录得帆云平台"""
    access = await require_project_access(
        db,
        project_id=project_id,
        user_id=ctx.user.id,
        tenant_id=ctx.tenant_id,
        minimum_role="admin",
    )
    project = access.project

    client = APaaSClient(base_url=req.base_url, tenant_id=req.tenant_id)
    try:
        result = await client.login(req.username, req.password)
        token = result.get("token", "")
        user_info = result.get("user", {})

        # 更新 Project 表
        import base64
        project.platform_url = req.base_url
        project.platform_tenant_id = req.tenant_id
        project.platform_token = token
        project.platform_username = req.username
        project.platform_password_enc = base64.b64encode(req.password.encode()).decode()

        # 同步更新 User 表（generation_steps 等核心功能使用 User.apaas_token）
        user_result = await db.execute(select(User).where(User.id == ctx.user.id))
        user = user_result.scalar_one()
        user.apaas_token = token
        user.apaas_base_url = req.base_url
        user.apaas_tenant_id = req.tenant_id
        user.apaas_user_id = str(user_info.get("id", ""))

        await db.commit()
        await db.refresh(project)
        return _project_to_dict(project, current_role=access.role)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"平台登录失败: {e}")


# ============================================================
# 团队成员管理
# ============================================================

@router.get("/{project_id}/members")
async def list_members(
    project_id: int,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """列出项目所有成员"""
    await require_project_access(
        db,
        project_id=project_id,
        user_id=ctx.user.id,
        tenant_id=ctx.tenant_id,
    )
    result = await db.execute(
        select(ProjectMember, User)
        .join(User, ProjectMember.user_id == User.id)
        .where(ProjectMember.project_id == project_id)
        .order_by(ProjectMember.created_at)
    )
    rows = result.all()
    return [
        {
            "id": member.id,
            "user_id": member.user_id,
            "username": user.username,
            "role": member.role,
            "created_at": member.created_at.isoformat() if member.created_at else None,
        }
        for member, user in rows
    ]


@router.post("/{project_id}/members")
async def add_member(
    project_id: int,
    req: AddMemberRequest,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """添加项目成员（需要 owner 或 admin 权限）"""
    access = await require_project_access(
        db,
        project_id=project_id,
        user_id=ctx.user.id,
        tenant_id=ctx.tenant_id,
        minimum_role="admin",
    )

    # 查找目标用户
    if req.user_id:
        result = await db.execute(select(User).where(User.id == req.user_id))
    elif req.username:
        result = await db.execute(select(User).where(User.username == req.username))
    else:
        raise HTTPException(status_code=400, detail="请提供 username 或 user_id")

    target_user = result.scalar_one_or_none()
    if not target_user:
        raise HTTPException(status_code=404, detail="用户不存在")
    if not target_user.is_active:
        raise HTTPException(status_code=400, detail="目标用户已被禁用")

    membership_result = await db.execute(
        select(UserTenant).where(
            UserTenant.user_id == target_user.id,
            UserTenant.tenant_id == ctx.tenant_id,
            UserTenant.status == 1,
        )
    )
    if not membership_result.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="目标用户不是当前组织的有效成员")

    # 检查是否已是成员
    existing = await db.execute(
        select(ProjectMember).where(
            ProjectMember.project_id == project_id,
            ProjectMember.user_id == target_user.id,
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="该用户已是项目成员")

    role = req.role if req.role in ("admin", "member") else "member"
    if role == "admin" and access.role != "owner":
        raise HTTPException(status_code=403, detail="仅项目所有者可添加管理员")

    member = ProjectMember(
        project_id=project_id,
        user_id=target_user.id,
        role=role,
    )
    db.add(member)
    await db.commit()
    await db.refresh(member)
    return {
        "id": member.id,
        "user_id": member.user_id,
        "username": target_user.username,
        "role": member.role,
        "created_at": member.created_at.isoformat() if member.created_at else None,
    }


@router.delete("/{project_id}/members/{member_id}")
async def remove_member(
    project_id: int,
    member_id: int,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """移除项目成员（owner 不可被移除）"""
    access = await require_project_access(
        db,
        project_id=project_id,
        user_id=ctx.user.id,
        tenant_id=ctx.tenant_id,
        minimum_role="admin",
    )

    result = await db.execute(
        select(ProjectMember).where(
            ProjectMember.id == member_id,
            ProjectMember.project_id == project_id,
        )
    )
    member = result.scalar_one_or_none()
    if not member:
        raise HTTPException(status_code=404, detail="成员不存在")
    if member.role == "owner":
        raise HTTPException(status_code=400, detail="无法移除项目所有者")
    if member.user_id == ctx.user.id:
        raise HTTPException(status_code=400, detail="请勿通过项目设置移除自己")
    if member.role == "admin" and access.role != "owner":
        raise HTTPException(status_code=403, detail="仅项目所有者可移除管理员")

    await db.delete(member)
    await db.commit()
    return {"status": "ok"}


@router.put("/{project_id}/members/{member_id}")
async def update_member_role(
    project_id: int,
    member_id: int,
    req: UpdateMemberRoleRequest,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """更新成员角色（仅 owner 可操作）"""
    await require_project_access(
        db,
        project_id=project_id,
        user_id=ctx.user.id,
        tenant_id=ctx.tenant_id,
        minimum_role="owner",
    )

    result = await db.execute(
        select(ProjectMember).where(
            ProjectMember.id == member_id,
            ProjectMember.project_id == project_id,
        )
    )
    member = result.scalar_one_or_none()
    if not member:
        raise HTTPException(status_code=404, detail="成员不存在")
    if member.role == "owner":
        raise HTTPException(status_code=400, detail="无法修改所有者角色")

    if req.role not in ("admin", "member"):
        raise HTTPException(status_code=400, detail="角色只能是 admin 或 member")

    member.role = req.role
    await db.commit()
    await db.refresh(member)
    return {
        "id": member.id,
        "user_id": member.user_id,
        "role": member.role,
    }


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
    access = await require_project_access(
        db,
        project_id=project_id,
        user_id=ctx.user.id,
        tenant_id=ctx.tenant_id,
    )

    ws_mgr = WorkspaceManager()
    all_workspaces = ws_mgr.list_project_workspaces(project_id)
    permissions = {
        "edit": project_role_at_least(access.role, "member"),
        "delete": project_role_at_least(access.role, "admin"),
        "publish": project_role_at_least(access.role, "admin"),
        "upload_to_platform": project_role_at_least(access.role, "admin"),
    }
    return [
        {
            **ws,
            "access_role": access.role,
            "permissions": permissions,
        }
        for ws in all_workspaces
    ]
