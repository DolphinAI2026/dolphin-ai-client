"""Git 连接管理（Phase C v1：PAT 直连；Phase D Task 7：OAuth 完整流）"""
from __future__ import annotations
from typing import Annotated
import logging
import os
from urllib.parse import urlencode

import httpx
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


# ─────────────────────────────────────────────────────────────────
# Phase D Task 5 — Workspace → repo sync 端点
# ─────────────────────────────────────────────────────────────────


@app_router.post("/{application_id}/workspaces/{workspace_id}/sync-to-repo")
async def sync_workspace_to_repo_endpoint(
    application_id: int,
    workspace_id: str,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """把 workspace 推到 repo 的 workspaces/<id>/ 子目录（v1 单向）。

    需 project contributor+。
    """
    from app.git.workspace_sync import push_workspace_to_repo

    app_obj = (await db.execute(
        select(Application).where(
            Application.id == application_id,
            Application.tenant_id == ctx.tenant_id,
        )
    )).scalar_one_or_none()
    if not app_obj:
        raise HTTPException(404, "应用不存在")
    if app_obj.project_id is None:
        raise HTTPException(400, "应用未关联 project")

    await require_project_access(
        db, project_id=app_obj.project_id, user_id=ctx.user.id, tenant_id=ctx.tenant_id,
        minimum_role="contributor",
    )

    try:
        return await push_workspace_to_repo(
            db, application=app_obj, workspace_id=workspace_id,
        )
    except RuntimeError as e:
        raise HTTPException(400, str(e))


# ─────────────────────────────────────────────────────────────────
# Phase D Task 7 — OAuth 完整流（GitHub + GitLab）
# ─────────────────────────────────────────────────────────────────


GITHUB_AUTHORIZE_URL = "https://github.com/login/oauth/authorize"
GITHUB_TOKEN_URL = "https://github.com/login/oauth/access_token"
GITHUB_DEFAULT_SCOPE = "repo,read:org"
GITLAB_DEFAULT_SCOPE = "api read_repository write_repository"


def _builder_base_url() -> str:
    """前端可达的 Builder URL（OAuth callback redirect_uri 拼装用）。"""
    return os.environ.get("BUILDER_PUBLIC_URL", "http://localhost:5173").rstrip("/")


def _redirect_uri(provider: str) -> str:
    return f"{_builder_base_url()}/git/callback/{provider}"


@router.get("/{project_id}/git-oauth/start")
async def git_oauth_start(
    project_id: int,
    provider: str,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
    host: str | None = None,
):
    """返回 OAuth authorize URL，让前端跳转。

    state v1 简化为 project_id（生产应加 nonce 防 CSRF — backlog）。
    """
    await require_project_access(
        db, project_id=project_id, user_id=ctx.user.id, tenant_id=ctx.tenant_id,
        minimum_role="maintainer",
    )

    if provider not in ("github", "gitlab"):
        raise HTTPException(400, "provider 仅支持 github / gitlab")

    state = str(project_id)

    if provider == "github":
        client_id = os.environ.get("GITHUB_CLIENT_ID")
        if not client_id:
            raise HTTPException(500, "GITHUB_CLIENT_ID 未配置")
        params = {
            "client_id": client_id,
            "redirect_uri": _redirect_uri("github"),
            "scope": os.environ.get("GITHUB_OAUTH_SCOPE", GITHUB_DEFAULT_SCOPE),
            "state": state,
        }
        return {"authorize_url": f"{GITHUB_AUTHORIZE_URL}?{urlencode(params)}"}

    # gitlab
    client_id = os.environ.get("GITLAB_CLIENT_ID")
    if not client_id:
        raise HTTPException(500, "GITLAB_CLIENT_ID 未配置")
    gitlab_host = (host or os.environ.get("GITLAB_HOST") or "https://gitlab.com").rstrip("/")
    params = {
        "client_id": client_id,
        "redirect_uri": _redirect_uri("gitlab"),
        "response_type": "code",
        "scope": os.environ.get("GITLAB_OAUTH_SCOPE", GITLAB_DEFAULT_SCOPE),
        "state": state,
    }
    return {"authorize_url": f"{gitlab_host}/oauth/authorize?{urlencode(params)}"}


class OAuthCallbackRequest(BaseModel):
    provider: str           # 'github' | 'gitlab'
    code: str
    state: str
    group_id_or_org: str
    host: str | None = None  # gitlab self-hosted 可指定


@router.post("/{project_id}/git-oauth/callback")
async def git_oauth_callback(
    project_id: int,
    req: OAuthCallbackRequest,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """前端把 ?code=... 转交回来；用 code 换 access_token + upsert GitConnection。"""
    await require_project_access(
        db, project_id=project_id, user_id=ctx.user.id, tenant_id=ctx.tenant_id,
        minimum_role="maintainer",
    )

    if req.provider not in ("github", "gitlab"):
        raise HTTPException(400, "provider 仅支持 github / gitlab")

    # state v1 校验：必须等于 project_id（生产应做 nonce + signed token）
    if req.state != str(project_id):
        raise HTTPException(400, "state 不匹配（CSRF 防护）")

    if req.provider == "github":
        client_id = os.environ.get("GITHUB_CLIENT_ID")
        client_secret = os.environ.get("GITHUB_CLIENT_SECRET")
        if not client_id or not client_secret:
            raise HTTPException(500, "GITHUB_CLIENT_ID / GITHUB_CLIENT_SECRET 未配置")
        token_url = GITHUB_TOKEN_URL
        token_payload = {
            "client_id": client_id,
            "client_secret": client_secret,
            "code": req.code,
            "redirect_uri": _redirect_uri("github"),
        }
        host = "https://api.github.com"
    else:
        client_id = os.environ.get("GITLAB_CLIENT_ID")
        client_secret = os.environ.get("GITLAB_CLIENT_SECRET")
        if not client_id or not client_secret:
            raise HTTPException(500, "GITLAB_CLIENT_ID / GITLAB_CLIENT_SECRET 未配置")
        host = (req.host or os.environ.get("GITLAB_HOST") or "https://gitlab.com").rstrip("/")
        token_url = f"{host}/oauth/token"
        token_payload = {
            "client_id": client_id,
            "client_secret": client_secret,
            "code": req.code,
            "grant_type": "authorization_code",
            "redirect_uri": _redirect_uri("gitlab"),
        }

    async with httpx.AsyncClient(timeout=20.0) as client:
        resp = await client.post(
            token_url,
            data=token_payload,
            headers={"Accept": "application/json"},
        )
    if resp.status_code >= 400:
        logger.warning("OAuth token exchange failed: %s %s", resp.status_code, resp.text[:200])
        raise HTTPException(502, f"OAuth token 换取失败：{resp.status_code}")
    try:
        data = resp.json()
    except Exception:
        raise HTTPException(502, "OAuth token 响应非 JSON")

    access_token = data.get("access_token")
    if not access_token:
        err = data.get("error_description") or data.get("error") or "未知错误"
        raise HTTPException(502, f"OAuth 未返回 access_token：{err}")

    # upsert GitConnection
    existing = (await db.execute(
        select(GitConnection).where(GitConnection.project_id == project_id)
    )).scalar_one_or_none()
    if existing:
        existing.provider = req.provider
        existing.host = host
        existing.access_token_enc = encrypt_token(access_token)
        existing.group_id_or_org = req.group_id_or_org
        existing.status = "connected"
        await db.commit()
        await db.refresh(existing)
        conn = existing
    else:
        conn = GitConnection(
            project_id=project_id,
            provider=req.provider,
            host=host,
            access_token_enc=encrypt_token(access_token),
            group_id_or_org=req.group_id_or_org,
            status="connected",
        )
        db.add(conn)
        await db.commit()
        await db.refresh(conn)

    return _to_dict(conn)
