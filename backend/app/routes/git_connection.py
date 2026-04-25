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
from app.models.collaboration import GitConnection
from app.git.connection import encrypt_token
from app.project_access import require_project_access

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/projects", tags=["git-connection"])


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
