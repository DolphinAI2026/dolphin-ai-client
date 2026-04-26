"""Git 连接管理（Phase C v1：仅 PAT 直连，OAuth 完整流留 v2）"""
from __future__ import annotations
from typing import Annotated
import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.deps import get_auth_context, AuthContext
from app.models import Application
from app.models.collaboration import GitConnection
from app.git.connection import encrypt_token
from app.project_access import require_project_access

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/projects", tags=["git-connection"])
# application 级别的 git-init 走独立 router（路径前缀不同）
app_router = APIRouter(prefix="/applications", tags=["git-init"])


class ConnectGitPATRequest(BaseModel):
    provider: str           # 'gitlab' | 'github'
    host: str               # 'https://gitlab.com' or 'https://github.com'
    access_token: str       # PAT
    group_id_or_org: str    # GitLab group path or GitHub org name


@router.post("/{project_id}/git-connection")
async def connect_git_pat(
    project_id: int,
    req: ConnectGitPATRequest,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """直连 git 平台（PAT 模式）。Phase C v1：仅此模式可用，OAuth 留 v2。"""
    await require_project_access(
        db, project_id=project_id, user_id=ctx.user.id, tenant_id=ctx.tenant_id,
        minimum_role="maintainer",
    )

    if req.provider not in ("gitlab", "github"):
        raise HTTPException(400, "provider 仅支持 gitlab / github")

    # 已有 connection 则覆盖更新
    existing = (await db.execute(
        select(GitConnection).where(GitConnection.project_id == project_id)
    )).scalar_one_or_none()
    if existing:
        existing.provider = req.provider
        existing.host = req.host
        existing.access_token_enc = encrypt_token(req.access_token)
        existing.group_id_or_org = req.group_id_or_org
        existing.status = "connected"
        await db.commit()
        await db.refresh(existing)
        conn = existing
    else:
        conn = GitConnection(
            project_id=project_id,
            provider=req.provider,
            host=req.host,
            access_token_enc=encrypt_token(req.access_token),
            group_id_or_org=req.group_id_or_org,
            status="connected",
        )
        db.add(conn)
        await db.commit()
        await db.refresh(conn)

    return _to_dict(conn)


@router.get("/{project_id}/git-connection")
async def get_git_connection(
    project_id: int,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    await require_project_access(
        db, project_id=project_id, user_id=ctx.user.id, tenant_id=ctx.tenant_id,
        minimum_role="contributor",
    )
    conn = (await db.execute(
        select(GitConnection).where(GitConnection.project_id == project_id)
    )).scalar_one_or_none()
    if not conn:
        return None
    return _to_dict(conn)


@router.delete("/{project_id}/git-connection")
async def delete_git_connection(
    project_id: int,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    await require_project_access(
        db, project_id=project_id, user_id=ctx.user.id, tenant_id=ctx.tenant_id,
        minimum_role="owner",
    )
    conn = (await db.execute(
        select(GitConnection).where(GitConnection.project_id == project_id)
    )).scalar_one_or_none()
    if not conn:
        raise HTTPException(404, "未连接 git")
    await db.delete(conn)
    await db.commit()
    return {"status": "ok"}


def _to_dict(conn: GitConnection) -> dict:
    return {
        "id": conn.id,
        "project_id": conn.project_id,
        "provider": conn.provider,
        "host": conn.host,
        "group_id_or_org": conn.group_id_or_org,
        "status": conn.status,
        # 不返回 access_token_enc — 安全
    }


@app_router.post("/{application_id}/git-init")
async def init_repo_endpoint(
    application_id: int,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """为 application 在 git 平台上初始化 repo + 推第一版 SPEC。

    要求：
    - application 存在且属于当前 tenant
    - application.project_id 必须存在（用来查 GitConnection）
    - 调用方至少是 project maintainer
    - 该 project 已配置 GitConnection（先调 POST /api/projects/{id}/git-connection）
    """
    from app.git.repo_init import init_repo_for_application

    app_obj = (await db.execute(
        select(Application).where(
            Application.id == application_id,
            Application.tenant_id == ctx.tenant_id,
        )
    )).scalar_one_or_none()
    if not app_obj:
        raise HTTPException(404, "应用不存在")

    if app_obj.project_id is None:
        raise HTTPException(400, "应用未关联 project，无法初始化 git repo")

    # role check：project maintainer+ 才能 init
    await require_project_access(
        db, project_id=app_obj.project_id, user_id=ctx.user.id, tenant_id=ctx.tenant_id,
        minimum_role="maintainer",
    )

    git_conn = (await db.execute(
        select(GitConnection).where(GitConnection.project_id == app_obj.project_id)
    )).scalar_one_or_none()
    if not git_conn:
        raise HTTPException(
            400,
            "项目尚未连接 git；请先调用 POST /api/projects/{project_id}/git-connection",
        )

    full_path = await init_repo_for_application(db, application=app_obj, git_connection=git_conn)
    return {
        "git_repo_url": app_obj.git_repo_url,
        "git_provider": app_obj.git_provider,
        "git_default_branch": app_obj.git_default_branch,
        "full_path": full_path,
    }


# ─────────────────────────────────────────────────────────────────
# Phase D Task 4 — Drift status / resolve endpoints
# ─────────────────────────────────────────────────────────────────


@app_router.get("/{application_id}/drift-status")
async def drift_status_endpoint(
    application_id: int,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """漂移检测：对比 git main HEAD 和 Builder canonical commit_sha。

    需 project viewer+（contributor 之上的最低读权限即可）。
    """
    from app.git.drift import check_drift

    app_obj = (await db.execute(
        select(Application).where(
            Application.id == application_id,
            Application.tenant_id == ctx.tenant_id,
        )
    )).scalar_one_or_none()
    if not app_obj:
        raise HTTPException(404, "应用不存在")

    if app_obj.project_id is not None:
        await require_project_access(
            db, project_id=app_obj.project_id, user_id=ctx.user.id, tenant_id=ctx.tenant_id,
            minimum_role="contributor",
        )

    return await check_drift(db, application=app_obj)


class ResolveDriftRequest(BaseModel):
    direction: str  # 'git_to_builder' | 'builder_to_git'


@app_router.post("/{application_id}/resolve-drift")
async def resolve_drift_endpoint(
    application_id: int,
    req: ResolveDriftRequest,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """记录漂移解决意图。需 project owner。"""
    from app.git.drift import resolve_drift

    app_obj = (await db.execute(
        select(Application).where(
            Application.id == application_id,
            Application.tenant_id == ctx.tenant_id,
        )
    )).scalar_one_or_none()
    if not app_obj:
        raise HTTPException(404, "应用不存在")
    if app_obj.project_id is None:
        raise HTTPException(400, "应用未关联 project，无法解决漂移")

    await require_project_access(
        db, project_id=app_obj.project_id, user_id=ctx.user.id, tenant_id=ctx.tenant_id,
        minimum_role="owner",
    )

    if req.direction not in ("git_to_builder", "builder_to_git"):
        raise HTTPException(400, "direction 必须是 git_to_builder 或 builder_to_git")

    return await resolve_drift(
        db, application=app_obj, direction=req.direction, resolved_by=ctx.user.id,
    )
