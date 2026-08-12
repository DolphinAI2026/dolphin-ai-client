"""Application 级成员管理 — 外部协作者（在 Project member 之外的额外邀请）

合并显示 inherited（来自 Project）+ direct（应用级邀请）+ creator（Application.created_by）
三类成员，UI 用 source 字段区分。
"""
from __future__ import annotations
from typing import Annotated, Literal, Optional
import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.deps import get_auth_context, AuthContext
from app.application_access import (
    PROJECT_TO_APPLICATION_ROLE,
    ROLE_LEVELS,
    normalize_application_role,
    resolve_effective_application_role,
)
from app.models import Application, Project, ProjectMember, User
from app.models.collaboration import ApplicationMember
from app.models.tenant import Role, UserTenant
from app.audit_log import (
    AuditActorContext,
    add_audit_log,
    record_audit_log_best_effort,
    snapshot_audit_actor,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/applications", tags=["application-members"])

class InviteAppMemberRequest(BaseModel):
    username: Optional[str] = None
    user_id: Optional[int] = None
    role: Literal["admin", "collaborator"] = "collaborator"


class UpdateAppMemberRoleRequest(BaseModel):
    role: Literal["admin", "collaborator"]


async def _record_member_error(
    db: AsyncSession,
    *,
    actor: AuditActorContext,
    application_id: int,
    event_type: str,
    target_id: object,
    error: Exception,
) -> None:
    try:
        await db.rollback()
        result = "denied" if isinstance(error, HTTPException) and error.status_code == 403 else "failure"
        failure_reason = error.detail if isinstance(error, HTTPException) else str(error)
        await record_audit_log_best_effort(
            actor=actor,
            application_id=application_id,
            event_type=event_type,
            target_type="application_member",
            target_id=target_id,
            result=result,
            failure_reason=str(failure_reason),
        )
    except Exception:
        logger.exception("member error audit failed", extra={"application_id": application_id})


async def _require_member_manager(db: AsyncSession, app: Application, ctx: AuthContext) -> None:
    if ctx.tenant_role in {"tenant_admin", "platform_admin"}:
        return
    role = await resolve_effective_application_role(db, app, ctx.user.id)
    if role not in {"owner", "admin"}:
        raise HTTPException(403, "需要应用所有者或管理员权限")


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


async def _require_application_access(
    db: AsyncSession,
    *,
    application_id: int,
    tenant_id: int,
) -> Application:
    return await _resolve_application_or_404(db, application_id, tenant_id)


def _merge_member(members: dict[int, dict], item: dict) -> None:
    """Merge duplicate membership sources and keep the highest effective app role."""
    user_id = int(item["user_id"])
    item["role"] = normalize_application_role(item.get("role")) or "collaborator"
    existing = members.get(user_id)
    if not existing or ROLE_LEVELS.get(item["role"], 0) > ROLE_LEVELS.get(existing.get("role"), 0):
        members[user_id] = item


async def _attach_tenant_user_meta(
    db: AsyncSession,
    *,
    members: dict[int, dict],
    tenant_id: int,
) -> None:
    if not members:
        return
    rows = (await db.execute(
        select(UserTenant, Role)
        .outerjoin(Role, Role.id == UserTenant.role_id)
        .where(
            UserTenant.tenant_id == tenant_id,
            UserTenant.user_id.in_(list(members.keys())),
        )
    )).all()
    meta_by_user_id = {
        membership.user_id: {
            "tenant_status": membership.status,
            "tenant_role_code": role.role_code if role else None,
            "tenant_role_name": role.role_name if role else None,
        }
        for membership, role in rows
    }
    for user_id, member in members.items():
        member.update(meta_by_user_id.get(user_id, {
            "tenant_status": None,
            "tenant_role_code": None,
            "tenant_role_name": None,
        }))


@router.get("/{application_id}/members")
async def list_application_members(
    application_id: int,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """列出应用的所有成员（合并 inherited + direct + creator）"""
    app = await _require_application_access(
        db,
        application_id=application_id,
        tenant_id=ctx.tenant_id,
    )
    await _require_member_manager(db, app, ctx)

    members: dict[int, dict] = {}

    if app.project_id:
        pm_rows = (await db.execute(
            select(ProjectMember, User)
            .join(Project, Project.id == ProjectMember.project_id)
            .join(User, ProjectMember.user_id == User.id)
            .where(
                ProjectMember.project_id == app.project_id,
                Project.tenant_id == app.tenant_id,
            )
        )).all()
        for pm, u in pm_rows:
            _merge_member(members, {
                "user_id": u.id,
                "username": u.username,
                "role": PROJECT_TO_APPLICATION_ROLE.get(pm.role, "collaborator"),
                "source": "inherited",
                "is_active": u.is_active,
                "created_at": pm.created_at.isoformat() if pm.created_at else None,
            })

    am_rows = (await db.execute(
        select(ApplicationMember, User)
        .join(User, ApplicationMember.user_id == User.id)
        .where(ApplicationMember.application_id == application_id)
    )).all()
    for am, u in am_rows:
        _merge_member(members, {
            "user_id": u.id,
            "username": u.username,
            "role": am.role,
            "source": "direct",
            "is_active": u.is_active,
            "created_at": am.created_at.isoformat() if am.created_at else None,
        })

    owner_user = (await db.execute(
        select(User).where(User.id == app.created_by)
    )).scalar_one_or_none()
    if owner_user:
        _merge_member(members, {
            "user_id": owner_user.id,
            "username": owner_user.username,
            "role": "owner",
            "source": "creator",
            "is_active": owner_user.is_active,
            "created_at": app.created_at.isoformat() if app.created_at else None,
        })

    await _attach_tenant_user_meta(db, members=members, tenant_id=ctx.tenant_id)
    return list(members.values())


@router.post("/{application_id}/members")
async def invite_application_member(
    application_id: int,
    req: InviteAppMemberRequest,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """直接添加当前组织用户为应用成员。"""
    actor = snapshot_audit_actor(ctx)
    target_ref = req.user_id or req.username or "unknown"
    try:
        return await _invite_application_member(application_id, req, ctx, db)
    except Exception as error:
        await _record_member_error(
            db,
            actor=actor,
            application_id=application_id,
            event_type="application_member.direct_add",
            target_id=target_ref,
            error=error,
        )
        raise


async def _invite_application_member(
    application_id: int,
    req: InviteAppMemberRequest,
    ctx: AuthContext,
    db: AsyncSession,
):
    app = await _require_application_access(
        db,
        application_id=application_id,
        tenant_id=ctx.tenant_id,
    )
    await _require_member_manager(db, app, ctx)

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

    requested = req.role
    if app.created_by == target.id:
        raise HTTPException(400, "创建者已拥有 owner 权限")

    inherited_role = None
    if app.project_id:
        inherited_member = (await db.execute(
            select(ProjectMember)
            .join(Project, Project.id == ProjectMember.project_id)
            .where(
                ProjectMember.project_id == app.project_id,
                ProjectMember.user_id == target.id,
                Project.tenant_id == app.tenant_id,
            )
        )).scalar_one_or_none()
        if inherited_member:
            inherited_role = PROJECT_TO_APPLICATION_ROLE.get(
                inherited_member.role, "collaborator",
            )

    existing = (await db.execute(
        select(ApplicationMember).where(
            ApplicationMember.application_id == application_id,
            ApplicationMember.user_id == target.id,
        )
    )).scalar_one_or_none()
    if existing:
        raise HTTPException(400, "该用户已是应用成员")
    if inherited_role and ROLE_LEVELS.get(requested, 0) <= ROLE_LEVELS.get(inherited_role, 0):
        raise HTTPException(400, "该用户已通过项目成员获得同等或更高权限")

    member = ApplicationMember(
        application_id=application_id,
        user_id=target.id,
        role=requested,
        invited_by=ctx.user.id,
    )
    db.add(member)
    await db.flush()
    add_audit_log(
        db, ctx=ctx, application_id=application_id,
        event_type="application_member.direct_add", target_type="application_member",
        target_id=target.id, result="success",
        after_value={"user_id": target.id, "role": requested},
    )
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
    actor = snapshot_audit_actor(ctx)
    try:
        return await _update_application_member_role(application_id, user_id, req, ctx, db)
    except Exception as error:
        await _record_member_error(
            db,
            actor=actor,
            application_id=application_id,
            event_type="application_member.role_changed",
            target_id=user_id,
            error=error,
        )
        raise


async def _update_application_member_role(
    application_id: int,
    user_id: int,
    req: UpdateAppMemberRoleRequest,
    ctx: AuthContext,
    db: AsyncSession,
):
    app = await _require_application_access(
        db,
        application_id=application_id,
        tenant_id=ctx.tenant_id,
    )
    await _require_member_manager(db, app, ctx)
    am = (await db.execute(
        select(ApplicationMember).where(
            ApplicationMember.application_id == application_id,
            ApplicationMember.user_id == user_id,
        )
    )).scalar_one_or_none()
    if not am:
        raise HTTPException(404, "应用直接成员不存在（如是 inherited 请到 Project 修改）")

    old_role = am.role
    new_role = req.role
    am.role = new_role
    await db.flush()
    add_audit_log(
        db, ctx=ctx, application_id=application_id,
        event_type="application_member.role_changed", target_type="application_member",
        target_id=user_id, result="success",
        before_value={"user_id": user_id, "role": old_role},
        after_value={"user_id": user_id, "role": new_role},
    )
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
    actor = snapshot_audit_actor(ctx)
    try:
        return await _remove_application_member(application_id, user_id, ctx, db)
    except Exception as error:
        await _record_member_error(
            db,
            actor=actor,
            application_id=application_id,
            event_type="application_member.removed",
            target_id=user_id,
            error=error,
        )
        raise


async def _remove_application_member(
    application_id: int,
    user_id: int,
    ctx: AuthContext,
    db: AsyncSession,
):
    app = await _require_application_access(
        db,
        application_id=application_id,
        tenant_id=ctx.tenant_id,
    )
    await _require_member_manager(db, app, ctx)
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
    before_value = {"user_id": user_id, "role": am.role}
    await db.delete(am)
    await db.flush()
    add_audit_log(
        db, ctx=ctx, application_id=application_id,
        event_type="application_member.removed", target_type="application_member",
        target_id=user_id, result="success", before_value=before_value,
    )
    await db.commit()
    return {"status": "ok"}
