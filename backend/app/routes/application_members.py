"""Application 级成员管理 — 外部协作者（在 Project member 之外的额外邀请）

合并显示 inherited（来自 Project）+ direct（应用级邀请）+ creator（Application.created_by）
三类成员，UI 用 source 字段区分。
"""
from __future__ import annotations
from typing import Annotated, Optional
import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.deps import get_auth_context, AuthContext
from app.models import Application, Project, ProjectMember, User
from app.models.collaboration import ApplicationMember
from app.models.tenant import UserTenant
from app.project_access import normalize_project_role, project_role_at_least

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/applications", tags=["application-members"])


class InviteAppMemberRequest(BaseModel):
    username: Optional[str] = None
    user_id: Optional[int] = None
    role: str = "contributor"


class UpdateAppMemberRoleRequest(BaseModel):
    role: str


async def _resolve_application_or_404(
    db: AsyncSession, application_id: int, tenant_id: int
) -> Application:
    result = await db.execute(
        select(Application).where(
            Application.id == application_id,
            Application.tenant_id == tenant_id,
        )
    )
    app = result.scalar_one_or_none()
    if not app:
        raise HTTPException(404, "应用不存在")
    return app


async def _user_role_on_application(
    db: AsyncSession,
    *,
    application: Application,
    user_id: int,
) -> Optional[str]:
    """返回用户对 application 的 effective role（取 direct + inherited 的最高）。

    优先级：creator → direct (ApplicationMember) → inherited (ProjectMember)。
    """
    direct_role: Optional[str] = None
    inherited_role: Optional[str] = None

    am = (await db.execute(
        select(ApplicationMember).where(
            ApplicationMember.application_id == application.id,
            ApplicationMember.user_id == user_id,
        )
    )).scalar_one_or_none()
    if am:
        direct_role = normalize_project_role(am.role)

    if application.project_id:
        pm = (await db.execute(
            select(ProjectMember).where(
                ProjectMember.project_id == application.project_id,
                ProjectMember.user_id == user_id,
            )
        )).scalar_one_or_none()
        if pm:
            inherited_role = normalize_project_role(pm.role)

    if application.created_by == user_id:
        return "owner"

    candidates = [r for r in (direct_role, inherited_role) if r]
    if not candidates:
        return None
    return max(candidates, key=lambda r: {
        "viewer": 1, "contributor": 2, "maintainer": 3, "owner": 4
    }.get(r, 0))


async def _require_application_access(
    db: AsyncSession,
    *,
    application_id: int,
    user_id: int,
    tenant_id: int,
    minimum_role: str = "contributor",
) -> tuple[Application, str]:
    app = await _resolve_application_or_404(db, application_id, tenant_id)
    role = await _user_role_on_application(db, application=app, user_id=user_id)
    if not role:
        raise HTTPException(404, "应用不存在或无权访问")
    if not project_role_at_least(role, minimum_role):
        raise HTTPException(403, "无权访问该应用")
    return app, role


@router.get("/{application_id}/members")
async def list_application_members(
    application_id: int,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """列出应用的所有成员（合并 inherited + direct + creator）"""
    app, _role = await _require_application_access(
        db,
        application_id=application_id,
        user_id=ctx.user.id,
        tenant_id=ctx.tenant_id,
    )

    members: dict[int, dict] = {}

    if app.project_id:
        pm_rows = (await db.execute(
            select(ProjectMember, User)
            .join(User, ProjectMember.user_id == User.id)
            .where(ProjectMember.project_id == app.project_id)
        )).all()
        for pm, u in pm_rows:
            members[u.id] = {
                "user_id": u.id,
                "username": u.username,
                "role": normalize_project_role(pm.role),
                "source": "inherited",
                "created_at": pm.created_at.isoformat() if pm.created_at else None,
            }

    am_rows = (await db.execute(
        select(ApplicationMember, User)
        .join(User, ApplicationMember.user_id == User.id)
        .where(ApplicationMember.application_id == application_id)
    )).all()
    for am, u in am_rows:
        members[u.id] = {
            "user_id": u.id,
            "username": u.username,
            "role": normalize_project_role(am.role),
            "source": "direct",
            "created_at": am.created_at.isoformat() if am.created_at else None,
        }

    if app.created_by not in members:
        owner_user = (await db.execute(
            select(User).where(User.id == app.created_by)
        )).scalar_one_or_none()
        if owner_user:
            members[owner_user.id] = {
                "user_id": owner_user.id,
                "username": owner_user.username,
                "role": "owner",
                "source": "creator",
                "created_at": app.created_at.isoformat() if app.created_at else None,
            }

    return list(members.values())


@router.post("/{application_id}/members")
async def invite_application_member(
    application_id: int,
    req: InviteAppMemberRequest,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """邀请用户加入应用（外部协作者）"""
    app, role = await _require_application_access(
        db,
        application_id=application_id,
        user_id=ctx.user.id,
        tenant_id=ctx.tenant_id,
        minimum_role="maintainer",
    )

    if req.user_id:
        target = (await db.execute(select(User).where(User.id == req.user_id))).scalar_one_or_none()
    elif req.username:
        target = (await db.execute(select(User).where(User.username == req.username))).scalar_one_or_none()
    else:
        raise HTTPException(400, "请提供 username 或 user_id")
    if not target:
        raise HTTPException(404, "用户不存在")
    if not target.is_active:
        raise HTTPException(400, "目标用户已被禁用")

    ut = (await db.execute(
        select(UserTenant).where(
            UserTenant.user_id == target.id,
            UserTenant.tenant_id == ctx.tenant_id,
            UserTenant.status == 1,
        )
    )).scalar_one_or_none()
    if not ut:
        raise HTTPException(400, "目标用户不是当前组织的有效成员")

    requested = normalize_project_role(req.role)
    if requested == "owner":
        raise HTTPException(400, "不能直接邀请为 owner（只有创建者持有）")
    if requested == "maintainer" and role != "owner":
        raise HTTPException(403, "仅应用 owner 可添加 maintainer")

    existing = (await db.execute(
        select(ApplicationMember).where(
            ApplicationMember.application_id == application_id,
            ApplicationMember.user_id == target.id,
        )
    )).scalar_one_or_none()
    if existing:
        raise HTTPException(400, "该用户已是应用成员")

    member = ApplicationMember(
        application_id=application_id,
        user_id=target.id,
        role=requested,
        invited_by=ctx.user.id,
    )
    db.add(member)
    await db.commit()
    await db.refresh(member)

    return {
        "id": member.id,
        "user_id": member.user_id,
        "username": target.username,
        "role": member.role,
        "source": "direct",
        "created_at": member.created_at.isoformat() if member.created_at else None,
    }


@router.patch("/{application_id}/members/{user_id}")
async def update_application_member_role(
    application_id: int,
    user_id: int,
    req: UpdateAppMemberRoleRequest,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """改 application 直接成员的 role（不影响 inherited）"""
    _app, role = await _require_application_access(
        db,
        application_id=application_id,
        user_id=ctx.user.id,
        tenant_id=ctx.tenant_id,
        minimum_role="owner",
    )
    am = (await db.execute(
        select(ApplicationMember).where(
            ApplicationMember.application_id == application_id,
            ApplicationMember.user_id == user_id,
        )
    )).scalar_one_or_none()
    if not am:
        raise HTTPException(404, "应用直接成员不存在（如是 inherited 请到 Project 修改）")

    new_role = normalize_project_role(req.role)
    if new_role == "owner":
        raise HTTPException(400, "不能改成 owner")
    if new_role not in ("maintainer", "contributor", "viewer"):
        raise HTTPException(400, "角色只能是 maintainer/contributor/viewer")

    am.role = new_role
    await db.commit()
    await db.refresh(am)
    return {"id": am.id, "user_id": am.user_id, "role": am.role}


@router.delete("/{application_id}/members/{user_id}")
async def remove_application_member(
    application_id: int,
    user_id: int,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """移除 application 直接成员"""
    _app, role = await _require_application_access(
        db,
        application_id=application_id,
        user_id=ctx.user.id,
        tenant_id=ctx.tenant_id,
        minimum_role="maintainer",
    )
    am = (await db.execute(
        select(ApplicationMember).where(
            ApplicationMember.application_id == application_id,
            ApplicationMember.user_id == user_id,
        )
    )).scalar_one_or_none()
    if not am:
        raise HTTPException(404, "应用直接成员不存在")
    if user_id == ctx.user.id:
        raise HTTPException(400, "请勿通过应用设置移除自己")
    if normalize_project_role(am.role) == "maintainer" and role != "owner":
        raise HTTPException(403, "仅 owner 可移除 maintainer")

    await db.delete(am)
    await db.commit()
    return {"status": "ok"}
