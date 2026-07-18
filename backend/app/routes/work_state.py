"""WorkspaceShell 一站式聚合 BFF (Phase F)"""
from __future__ import annotations
from typing import Annotated, Optional
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.deps import get_auth_context, AuthContext
from app.models import Application, ProjectMember, User
from app.models.collaboration import (
    ChangeProposal, GitConnection, ApplicationMember,
)
from app.models.spec import Spec as SpecORM
from app.models.preference import UserPreference
from app.project_access import normalize_project_role

router = APIRouter(prefix="/applications", tags=["work-state"])


def _effective_mode(user_pref: str, app_default: Optional[str]) -> str:
    return app_default or user_pref or "simple"


@router.get("/{application_id}/work-state")
async def get_work_state(
    application_id: int,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    app = (await db.execute(
        select(Application).where(
            Application.id == application_id, Application.tenant_id == ctx.tenant_id
        )
    )).scalar_one_or_none()
    if not app:
        raise HTTPException(404, "应用不存在")

    # canonical Spec
    canonical = None
    if app.canonical_spec_id:
        crow = (await db.execute(select(SpecORM).where(SpecORM.id == app.canonical_spec_id))).scalar_one_or_none()
        if crow:
            canonical = {
                "id": crow.id, "version": crow.version, "kind": crow.kind,
                "commit_sha": crow.commit_sha, "updated_at": crow.updated_at.isoformat() if crow.updated_at else None,
            }

    # 当前用户 draft（未 promote 的草稿，按 created_by + application_id 查最新）
    current_draft = None
    drow = (await db.execute(
        select(SpecORM).where(
            SpecORM.application_id == app.id,
            SpecORM.kind == "draft",
            SpecORM.created_by == ctx.user.id,
        ).order_by(SpecORM.updated_at.desc()).limit(1)
    )).scalar_one_or_none()
    if drow:
        current_draft = {
            "id": drow.id, "version": drow.version,
            "completeness_confirmed": drow.completeness_confirmed,
            "completeness_total": drow.completeness_total,
            "updated_at": drow.updated_at.isoformat() if drow.updated_at else None,
        }

    # open / changes_requested / approved 提案
    open_props = (await db.execute(
        select(ChangeProposal).where(
            ChangeProposal.application_id == app.id,
            ChangeProposal.status.in_(["open", "changes_requested", "approved"]),
        ).order_by(ChangeProposal.created_at.desc())
    )).scalars().all()

    # applied 历史（最近 5）
    applied_props = (await db.execute(
        select(ChangeProposal).where(
            ChangeProposal.application_id == app.id,
            ChangeProposal.status == "applied",
        ).order_by(ChangeProposal.applied_at.desc()).limit(5)
    )).scalars().all()

    def _prop_dict(p: ChangeProposal) -> dict:
        return {
            "id": p.id, "title": p.title, "status": p.status,
            "created_by": p.created_by, "created_at": p.created_at.isoformat() if p.created_at else None,
            "applied_at": p.applied_at.isoformat() if p.applied_at else None,
            "git_pr_url": p.git_pr_url,
        }

    # git
    git_info = None
    if app.git_repo_url:
        gconn = (await db.execute(
            select(GitConnection).where(GitConnection.project_id == app.project_id)
        )).scalar_one_or_none() if app.project_id else None
        git_info = {
            "repo_url": app.git_repo_url,
            "provider": app.git_provider,
            "default_branch": app.git_default_branch,
            "connected": bool(gconn),
        }

    # members（合并 inherited + direct + creator）
    members: dict[int, dict] = {}
    if app.project_id:
        pm_rows = (await db.execute(
            select(ProjectMember, User).join(User, ProjectMember.user_id == User.id)
            .where(ProjectMember.project_id == app.project_id)
        )).all()
        for pm, u in pm_rows:
            members[u.id] = {"user_id": u.id, "username": u.username,
                             "role": normalize_project_role(pm.role), "source": "inherited"}
    am_rows = (await db.execute(
        select(ApplicationMember, User).join(User, ApplicationMember.user_id == User.id)
        .where(ApplicationMember.application_id == app.id)
    )).all()
    for am, u in am_rows:
        members[u.id] = {"user_id": u.id, "username": u.username,
                         "role": normalize_project_role(am.role), "source": "direct"}
    if app.created_by not in members:
        creator = (await db.execute(select(User).where(User.id == app.created_by))).scalar_one_or_none()
        if creator:
            members[creator.id] = {"user_id": creator.id, "username": creator.username,
                                   "role": "owner", "source": "creator"}

    # effective_mode
    pref = (await db.execute(
        select(UserPreference).where(UserPreference.user_id == ctx.user.id)
    )).scalar_one_or_none()
    user_mode = pref.default_mode if pref else "simple"
    effective = _effective_mode(user_mode, app.default_mode)

    return {
        "application": {
            "id": app.id, "app_name": app.app_name, "app_code": app.app_code,
            "status": app.status, "platform_url": app.platform_url,
            "apaas_app_id": app.apaas_app_id,
            "default_mode": app.default_mode,
        },
        "current_draft": current_draft,
        "canonical": canonical,
        "open_proposals": [_prop_dict(p) for p in open_props],
        "applied_history": [_prop_dict(p) for p in applied_props],
        "git": git_info,
        "members": list(members.values()),
        "effective_mode": effective,
        "user_role_on_app": "tenant",
        "user_pref_mode": user_mode,
    }
