from __future__ import annotations
import json
import logging
import re
from datetime import datetime
from typing import Annotated, List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File, Form
from pydantic import BaseModel
from sqlalchemy import select, desc, func as sa_func, delete, and_, not_, or_
from sqlalchemy.ext.asyncio import AsyncSession
from sse_starlette.sse import EventSourceResponse
from app.database import get_db
from app.models import User, Application, DocumentVersion, ChangePlan, ApiCallLog, PlatformEnv, Conversation, ConfigSnapshot, Project, ProjectMember
from app.models.collaboration import ApplicationMember
from app.auth import get_current_user
from app.schemas import ApplicationCreate, ApplicationPageResponse, ApplicationResponse, MergedAppResponse
from app.deps import get_auth_context, AuthContext
from app.permissions import has_org_permission, check_resource_permission, batch_get_permissions, Action
from jose import JWTError, jwt
from app.config import settings, APP_DEPLOY_ABSTRACT
from app.apaas_client import APaaSClient
from app.llm_client import LLMClient
from app.crypto import decrypt_password
from app.json_utils import loads_if_str
from app.error_messages import (
    APAAS_LOGIN_FAILED,
    APAAS_TOKEN_EXPIRED_GENERIC,
    is_apaas_token_error,
)

from app.services.config_converter import convert_analysis_to_app_config
from app.project_access import get_project_access, normalize_project_role, project_role_at_least, require_project_access


# 共享 helper 从子模块 re-export（保持 `from app.routes.applications import _xxx` 的向后兼容）
from ._helpers import *  # noqa: F401,F403
from . import _helpers  # noqa: F401

router = APIRouter(prefix="/applications", tags=["应用"])
logger = logging.getLogger(__name__)


def _is_application_admin(ctx: AuthContext) -> bool:
    return ctx.tenant_role in ("platform_admin", "tenant_admin")


def _application_access_clause(ctx: AuthContext):
    if _is_application_admin(ctx):
        return None
    project_owner_ids = (
        select(Project.id)
        .where(Project.tenant_id == ctx.tenant_id, Project.user_id == ctx.user.id)
    )
    project_member_ids = (
        select(ProjectMember.project_id)
        .join(Project, Project.id == ProjectMember.project_id)
        .where(Project.tenant_id == ctx.tenant_id, ProjectMember.user_id == ctx.user.id)
    )
    direct_member_ids = (
        select(ApplicationMember.application_id)
        .where(ApplicationMember.user_id == ctx.user.id)
    )
    return or_(
        Application.created_by == ctx.user.id,
        Application.user_id == ctx.user.id,
        Application.project_id.in_(project_owner_ids),
        Application.project_id.in_(project_member_ids),
        Application.id.in_(direct_member_ids),
    )


def _application_stage_clause(stage: str | None):
    if not stage or stage == "all":
        return None
    deployed = or_(Application.status == "completed", Application.apaas_app_id.isnot(None))
    has_draft_config = and_(
        Application.config_preview.isnot(None),
        Application.config_preview != "",
        Application.config_preview != "{}",
        Application.config_preview != "null",
    )
    active = and_(
        not_(deployed),
        Application.status != "failed",
        or_(Application.status.in_(("generating", "updating")), has_draft_config),
    )
    if stage == "deployed":
        return deployed
    if stage == "active":
        return active
    if stage == "draft":
        return and_(not_(deployed), not_(active))
    return None


def _apply_application_list_filters(stmt, ctx: AuthContext, team_scope: str | None, source_filter: str | None, stage: str | None = None):
    stmt = stmt.where(Application.tenant_id == ctx.tenant_id)
    if team_scope == "personal":
        stmt = stmt.where(Application.created_by == ctx.user.id, Application.team_id.is_(None))
    elif team_scope and team_scope.isdigit():
        stmt = stmt.where(Application.team_id == int(team_scope))

    access_clause = _application_access_clause(ctx)
    if access_clause is not None:
        stmt = stmt.where(access_clause)

    if source_filter == "local":
        stmt = stmt.where(Application.apaas_app_id.is_(None))
    elif source_filter == "linked":
        stmt = stmt.where(Application.apaas_app_id.isnot(None))
    elif source_filter == "remote":
        stmt = stmt.where(Application.id == -1)

    stage_clause = _application_stage_clause(stage)
    if stage_clause is not None:
        stmt = stmt.where(stage_clause)
    return stmt


class GenerateAppIconResponse(BaseModel):
    ok: bool
    app_id: int
    icon_svg: str


async def _get_application_permissions(
    ctx: AuthContext,
    db: AsyncSession,
    app: Application,
) -> Optional[dict[str, bool]]:
    def role_permissions(role: str) -> dict[str, bool]:
        normalized = normalize_project_role(role)
        return {
            Action.VIEW: True,
            Action.EDIT: project_role_at_least(normalized, "contributor"),
            Action.DELETE: normalized == "owner",
            Action.CLONE: project_role_at_least(normalized, "contributor"),
            "publish": project_role_at_least(normalized, "maintainer"),
            "can_manage_members": project_role_at_least(normalized, "maintainer"),
            "can_manage_member_roles": normalized == "owner",
            "access_role": normalized,
        }

    if ctx.tenant_role in ("platform_admin", "tenant_admin"):
        return {
            **role_permissions("owner"),
            "access_role": "tenant_admin",
        }

    effective_role: Optional[str] = "owner" if (app.created_by == ctx.user.id or app.user_id == ctx.user.id) else None

    if app.project_id:
        access = await get_project_access(
            db,
            project_id=int(app.project_id),
            user_id=ctx.user.id,
            tenant_id=ctx.tenant_id,
        )
        if access:
            effective_role = max(
                [role for role in (effective_role, access.role) if role],
                key=lambda role: {"viewer": 1, "contributor": 2, "maintainer": 3, "owner": 4}.get(normalize_project_role(role), 0),
            )

    direct_member = (await db.execute(
        select(ApplicationMember).where(
            ApplicationMember.application_id == app.id,
            ApplicationMember.user_id == ctx.user.id,
        )
    )).scalar_one_or_none()
    if direct_member:
        effective_role = max(
            [role for role in (effective_role, direct_member.role) if role],
            key=lambda role: {"viewer": 1, "contributor": 2, "maintainer": 3, "owner": 4}.get(normalize_project_role(role), 0),
        )

    if not effective_role:
        return None

    return role_permissions(effective_role)


async def _require_application_permission(
    ctx: AuthContext,
    db: AsyncSession,
    app: Application,
    action: str,
) -> dict[str, bool]:
    permissions = await _get_application_permissions(ctx, db, app)
    if not permissions:
        raise HTTPException(status_code=404, detail="应用不存在")
    if not permissions.get(action, False):
        raise HTTPException(status_code=403, detail="无权操作该应用")
    return permissions




class MatchByNameItem(BaseModel):
    id: int
    app_name: str
    app_code: str
    status: str
    apaas_app_id: Optional[str] = None
    updated_at: Optional[datetime] = None


@router.get("/match-by-name", response_model=List[MatchByNameItem])
async def match_applications_by_name(
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
    app_name_like: str = Query(..., min_length=1, max_length=120),
    limit: int = Query(5, ge=1, le=20),
):
    """按 app_name 模糊匹配本租户内当前用户可见的应用，用于 AI-Chat → Builder
    的"新建/更新到现有"选择对话框的候选拉取。

    匹配规则：
    - tenant 隔离 + 用户 access clause（owner / project member / app member / tenant_admin）
    - app_name 子串（ilike %X%），按 updated_at desc
    - 不查远程平台（轻量），只返必要字段
    """
    keyword = (app_name_like or "").strip()
    if not keyword:
        return []
    stmt = (
        select(Application)
        .where(Application.tenant_id == ctx.tenant_id)
        .where(Application.app_name.ilike(f"%{keyword}%"))
    )
    access_clause = _application_access_clause(ctx)
    if access_clause is not None:
        stmt = stmt.where(access_clause)
    stmt = stmt.order_by(desc(Application.updated_at)).limit(limit)
    rows = (await db.execute(stmt)).scalars().all()
    return [
        MatchByNameItem(
            id=app.id,
            app_name=app.app_name,
            app_code=app.app_code,
            status=app.status,
            apaas_app_id=app.apaas_app_id,
            updated_at=app.updated_at,
        )
        for app in rows
    ]


@router.get("", response_model=List[MergedAppResponse])
async def list_applications(
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
    team_scope: Optional[str] = Query(None),
    include_remote: bool = Query(True),
    source_filter: Optional[str] = Query(None),  # local / remote / linked
):
    """获取应用列表（本地 + 得帆云平台合并）"""
    # 1. 查本地应用
    query = select(Application).where(Application.tenant_id == ctx.tenant_id)
    if team_scope == "personal":
        query = query.where(Application.created_by == ctx.user.id, Application.team_id.is_(None))
    elif team_scope and team_scope.isdigit():
        query = query.where(Application.team_id == int(team_scope))
    query = query.order_by(desc(Application.updated_at))
    result = await db.execute(query)
    local_apps = result.scalars().all()

    # 1.5 获取所有环境信息（用于构建 URL 和显示环境名称）
    env_base_url = None
    env_tenant_id = None
    env_map: dict[int, dict] = {}  # env_id → {env_name, status}
    try:
        from app.models import PlatformEnv
        env_result = await db.execute(
            select(PlatformEnv).where(PlatformEnv.tenant_id == ctx.tenant_id)
        )
        all_envs = env_result.scalars().all()
        for env in all_envs:
            env_map[env.id] = {"env_name": env.env_name, "status": env.status}
            if env.is_default:
                env_base_url = env.base_url
                env_tenant_id = env.platform_tenant_id
    except Exception:
        pass

    # 2. 拉取远程应用（降级处理）
    remote_apps: list = []
    if include_remote and ctx.user.apaas_token and source_filter != "local":
        try:
            from app.apaas_client import APaaSClient
            client = APaaSClient(base_url=ctx.user.apaas_base_url, tenant_id=ctx.user.apaas_tenant_id, token=ctx.user.apaas_token)
            remote_apps = await client.query_app_list()
        except Exception as e:
            logger.warning(f"拉取得帆云应用列表失败（降级）: {e}")

    # 3. 合并
    remote_map = {}
    remote_code_map: dict[str, dict] = {}
    for r in remote_apps:
        rid = str(r.get("id", ""))
        if rid:
            remote_map[rid] = r
        rcode = str(r.get("appCode") or "").strip().lower()
        if rcode:
            remote_code_map.setdefault(rcode, r)

    # 2026-05-19 image #32: 用户 generate_app_from_doc 在 platform_env_X 上创建了应用，
    # 但本地 DB apaas_app_id 没写回（譬如调 MCP 中断 / 手工 SQL 重置）。
    # 这里按 platform_env_id 聚合 local apps，调 list_apaas_apps_in_env 拿真实
    # apaas_app_id，按 app_code 匹配回填。
    env_code_to_apaas: dict[int, dict[str, dict]] = {}  # {env_id: {code_lower: remote_app}}
    if include_remote and source_filter != "local":
        try:
            from app.coding.apaas_tools import APAAS_TOOL_EXECUTORS_PLATFORM
            list_exec = APAAS_TOOL_EXECUTORS_PLATFORM.get("list_apaas_apps")
            envs_to_fetch = {
                a.platform_env_id for a in local_apps
                if a.platform_env_id and not a.apaas_app_id and a.app_code
            }
            for eid in envs_to_fetch:
                if list_exec is None:
                    break
                try:
                    raw = await list_exec({}, eid, db)
                    parsed = json.loads(raw) if isinstance(raw, str) else raw
                    if parsed.get("ok") and isinstance(parsed.get("apps"), list):
                        code_map: dict[str, dict] = {}
                        for ra in parsed["apps"]:
                            code = str(ra.get("app_code") or "").strip().lower()
                            if code:
                                code_map.setdefault(code, ra)
                        env_code_to_apaas[eid] = code_map
                except Exception as e:
                    logger.warning(f"backfill: list_apaas_apps for env={eid} failed: {e}")
        except Exception as e:
            logger.warning(f"backfill: prep failed (non-fatal): {e}")

    merged: list[MergedAppResponse] = []
    matched_remote_ids: set[str] = set()
    # 2026-05-19: 用 app_code 回填 apaas_app_id — local DB 缺 apaas_app_id 但平台
    # 上其实已有同 appCode 的应用时（譬如本地手动 SQL 重置或 generate_app_from_doc
    # 写库失败但平台已创建成功），自动把本地 row 接上去显示成"已部署"。
    backfilled_ids: list[int] = []

    for app in local_apps:
        perms = await _get_application_permissions(ctx, db, app)
        if not perms or not perms.get(Action.VIEW, False):
            continue
        # 查找应用关联的环境信息
        app_env = env_map.get(app.platform_env_id) if app.platform_env_id else None
        app_env_name = app_env["env_name"] if app_env else None
        app_env_status = app_env["status"] if app_env else None

        # app_code 回填逻辑：缺 apaas_app_id 但平台有匹配 appCode 时，
        # 把 remote.id 写回 local DB + 当成 linked 处理。优先查 platform_env 的 apps，
        # 再 fallback 用户 home apaas 的 query_app_list。
        if not app.apaas_app_id and app.app_code:
            code_key = str(app.app_code).strip().lower()
            matched_apaas_id: str | None = None
            # 1) 查 app 自己的 platform_env_id
            if app.platform_env_id and app.platform_env_id in env_code_to_apaas:
                ra = env_code_to_apaas[app.platform_env_id].get(code_key)
                if ra:
                    matched_apaas_id = str(ra.get("apaas_app_id") or "")
            # 2) fallback：user home apaas list
            if not matched_apaas_id:
                matched_remote = remote_code_map.get(code_key)
                if matched_remote:
                    matched_apaas_id = str(matched_remote.get("id", ""))
            if matched_apaas_id:
                app.apaas_app_id = matched_apaas_id
                # 同时把 status 升到 completed（应用确实在平台上了）
                if not app.status or app.status == "draft":
                    app.status = "completed"
                backfilled_ids.append(app.id)

        if app.apaas_app_id:
            if app.apaas_app_id in remote_map:
                matched_remote_ids.add(app.apaas_app_id)
            if source_filter and source_filter != "linked":
                continue
            merged.append(
                _build_linked(
                    app,
                    remote_map.get(app.apaas_app_id, {}),
                    perms,
                    env_base_url,
                    env_tenant_id,
                    app_env_name,
                    app_env_status,
                )
            )
        else:
            if source_filter and source_filter != "local":
                continue
            merged.append(_build_local(app, perms, app_env_name, app_env_status))

    # 持久化 backfilled apaas_app_id（一次 commit，避免循环里 N 次 round-trip）
    if backfilled_ids:
        try:
            await db.commit()
            logger.info(f"backfilled apaas_app_id for app ids: {backfilled_ids}")
        except Exception as e:
            await db.rollback()
            logger.warning(f"backfill apaas_app_id commit failed (non-fatal): {e}")

    # 未匹配的远程应用
    if source_filter != "local":
        for rid, remote in remote_map.items():
            if rid not in matched_remote_ids:
                if source_filter and source_filter != "remote":
                    continue
                merged.append(_build_remote(remote, env_base_url, env_tenant_id))

    return merged


@router.get("/page", response_model=ApplicationPageResponse)
async def list_applications_page(
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
    team_scope: Annotated[Optional[str], Query()] = None,
    source_filter: Annotated[Optional[str], Query()] = None,  # local / linked
    stage: Annotated[Optional[str], Query()] = "all",  # all / active / deployed / draft
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
):
    """分页获取 Builder 本地应用列表。

    这个端点只分页 Builder 侧已接入/已生成的应用；未绑定的远程平台应用仍走旧列表接口。
    """

    async def count_stage(stage_value: str | None) -> int:
        stmt = _apply_application_list_filters(
            select(sa_func.count(Application.id)).select_from(Application),
            ctx,
            team_scope,
            source_filter,
            stage_value,
        )
        return int((await db.execute(stmt)).scalar() or 0)

    counts = {
        "all": await count_stage("all"),
        "active": await count_stage("active"),
        "deployed": await count_stage("deployed"),
        "draft": await count_stage("draft"),
    }
    stage_key = stage if stage in counts else "all"
    total = counts[stage_key]
    total_pages = max(1, (total + page_size - 1) // page_size)
    safe_page = min(page, total_pages)

    query = _apply_application_list_filters(
        select(Application),
        ctx,
        team_scope,
        source_filter,
        stage_key,
    )
    query = query.order_by(desc(Application.updated_at)).offset((safe_page - 1) * page_size).limit(page_size)
    result = await db.execute(query)
    local_apps = result.scalars().all()

    env_base_url = None
    env_tenant_id = None
    env_map: dict[int, dict] = {}
    try:
        env_result = await db.execute(
            select(PlatformEnv).where(PlatformEnv.tenant_id == ctx.tenant_id)
        )
        all_envs = env_result.scalars().all()
        for env in all_envs:
            env_map[env.id] = {"env_name": env.env_name, "status": env.status}
            if env.is_default:
                env_base_url = env.base_url
                env_tenant_id = env.platform_tenant_id
    except Exception:
        pass

    items: list[MergedAppResponse] = []
    for app in local_apps:
        perms = await _get_application_permissions(ctx, db, app)
        if not perms or not perms.get(Action.VIEW, False):
            continue
        app_env = env_map.get(app.platform_env_id) if app.platform_env_id else None
        app_env_name = app_env["env_name"] if app_env else None
        app_env_status = app_env["status"] if app_env else None
        if app.apaas_app_id:
            items.append(
                _build_linked(
                    app,
                    {},
                    perms,
                    env_base_url,
                    env_tenant_id,
                    app_env_name,
                    app_env_status,
                )
            )
        else:
            items.append(_build_local(app, perms, app_env_name, app_env_status))

    return {
        "items": items,
        "total": total,
        "page": safe_page,
        "page_size": page_size,
        "total_pages": total_pages,
        "counts": counts,
    }


@router.get("/{app_id}", response_model=ApplicationResponse)
async def get_application(
    app_id: int,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)]
):
    result = await db.execute(
        select(Application).where(
            Application.id == app_id,
            Application.tenant_id == ctx.tenant_id
        )
    )
    app = result.scalar_one_or_none()
    if not app:
        raise HTTPException(status_code=404, detail="应用不存在")

    # 检查查看权限
    permissions = await _require_application_permission(ctx, db, app, Action.VIEW)

    resp = _enrich(app)
    resp.permissions = {
        Action.EDIT: permissions.get(Action.EDIT, False),
        Action.DELETE: permissions.get(Action.DELETE, False),
        Action.CLONE: permissions.get(Action.CLONE, False),
        "publish": permissions.get("publish", False),
    }

    # 构建平台直达链接
    if app.apaas_app_id:
        env_base_url = env_tenant_id = None
        if app.platform_env_id:
            env_result = await db.execute(select(PlatformEnv).where(PlatformEnv.id == app.platform_env_id))
            env = env_result.scalar_one_or_none()
            if env:
                env_base_url, env_tenant_id = env.base_url, env.platform_tenant_id
        if not env_base_url:
            # 回退到默认环境
            default_env_result = await db.execute(
                select(PlatformEnv).where(PlatformEnv.tenant_id == ctx.tenant_id, PlatformEnv.is_default == True)
            )
            default_env = default_env_result.scalar_one_or_none()
            if default_env:
                env_base_url, env_tenant_id = default_env.base_url, default_env.platform_tenant_id
        resp.apaas_url = _build_apaas_url(str(app.apaas_app_id), env_base_url, env_tenant_id)

    return resp


@router.get("/{app_id}/spec-markdown")
async def get_application_spec_as_markdown(
    app_id: int,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """返回应用当前 SPEC（config_preview）反向渲染的标准 markdown 设计文档。

    给 dolphin agent / 其他 MCP 调用方用：直接把当前应用结构作为 6 章节 md
    返回，agent 可以基于它增量改字段而不用问用户'有哪些字段'。

    优先级：
    1) 最新 DocumentVersion.raw_content（如果有）
    2) 否则用 config_preview 反向渲染（标准 6 章节模板）
    3) 都没有 → 返回空 + 标志说明这是空白草稿
    """
    from sqlalchemy import desc as sa_desc
    from app.models import DocumentVersion
    from ._helpers import _render_doc_content_from_config

    result = await db.execute(
        select(Application).where(
            Application.id == app_id,
            Application.tenant_id == ctx.tenant_id,
        )
    )
    app = result.scalar_one_or_none()
    if not app:
        raise HTTPException(status_code=404, detail="应用不存在")
    await check_resource_permission(ctx, db, app, "application", Action.VIEW)

    # 1) 拉最新 doc version
    doc_result = await db.execute(
        select(DocumentVersion)
        .where(DocumentVersion.application_id == app_id)
        .order_by(sa_desc(DocumentVersion.version))
        .limit(1)
    )
    latest_doc = doc_result.scalar_one_or_none()
    if latest_doc and latest_doc.raw_content and latest_doc.raw_content.strip():
        return {
            "ok": True,
            "app_id": app_id,
            "app_name": app.app_name,
            "app_code": app.app_code,
            "source": "doc_version",
            "version": latest_doc.version,
            "markdown": latest_doc.raw_content,
        }

    # 2) 反向渲染 config_preview
    cfg = app.config_preview
    if cfg:
        if isinstance(cfg, str):
            try:
                import json as _json
                cfg = _json.loads(cfg)
            except Exception:
                cfg = None
        if cfg:
            md = _render_doc_content_from_config(app.app_name or "", app.app_code or "", cfg)
            if md and md.strip():
                return {
                    "ok": True,
                    "app_id": app_id,
                    "app_name": app.app_name,
                    "app_code": app.app_code,
                    "source": "config_preview_rendered",
                    "version": None,
                    "markdown": md,
                }

    # 3) 空白草稿
    return {
        "ok": True,
        "app_id": app_id,
        "app_name": app.app_name,
        "app_code": app.app_code,
        "source": "empty",
        "version": None,
        "markdown": "",
        "note": "应用当前为空白草稿，无设计文档也无现有 SPEC 配置。",
    }


@router.post("", response_model=ApplicationResponse)
async def create_application(
    data: ApplicationCreate,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)]
):
    granted_permissions = sorted(
        code for code, allowed in (ctx.org_permissions or {}).items() if allowed
    )
    logger.info(
        "create_application request user_id=%s tenant_id=%s tenant_role=%s conversation_id=%s app_code=%s platform_env_id=%s granted_permissions=%s",
        ctx.user.id,
        ctx.tenant_id,
        ctx.tenant_role,
        data.conversation_id,
        data.app_code,
        data.platform_env_id,
        granted_permissions,
    )

    # 检查创建权限
    if not has_org_permission(ctx.org_permissions, "application", Action.CREATE):
        logger.warning(
            "create_application forbidden user_id=%s tenant_id=%s tenant_role=%s missing_permission=%s granted_permissions=%s",
            ctx.user.id,
            ctx.tenant_id,
            ctx.tenant_role,
            "application:create",
            granted_permissions,
        )
        raise HTTPException(status_code=403, detail="你的角色没有创建应用的权限")

    if data.project_id:
        await require_project_access(
            db,
            project_id=data.project_id,
            user_id=ctx.user.id,
            tenant_id=ctx.tenant_id,
            minimum_role="member",
        )

    # 租户应用数配额
    from app.tenant_quota import assert_tenant_quota
    await assert_tenant_quota(db, ctx.tenant_id, "applications")

    if data.canonical_spec_id:
        from app.builder_spec.persistence import load_spec
        spec = await load_spec(db, data.canonical_spec_id, tenant_id=ctx.tenant_id)
        if spec is None:
            raise HTTPException(status_code=404, detail="关联的 SPEC 不存在")

    app_code = _normalize_app_code(data.app_code)
    if not app_code and isinstance(data.config_preview, dict):
        preview_data = data.config_preview.get("data", data.config_preview)
        if isinstance(preview_data, dict):
            app_code = _normalize_app_code(preview_data.get("appCode") or preview_data.get("app_code"))
    app_code = app_code or _coerce_app_code(data.app_name)
    if not app_code:
        raise HTTPException(status_code=400, detail=APP_CODE_RULE_TEXT)

    config_preview = data.config_preview
    if isinstance(config_preview, dict):
        preview_data = config_preview.get("data", config_preview)
        if isinstance(preview_data, dict):
            preview_data["appCode"] = app_code
            preview_data["app_code"] = app_code

    config_str = _dump_preview_config(config_preview) if config_preview else None
    app = Application(
        user_id=ctx.user.id,
        tenant_id=ctx.tenant_id,
        created_by=ctx.user.id,
        team_id=None,  # 默认个人应用，后续可以转移到团队
        project_id=data.project_id,
        conversation_id=data.conversation_id,
        app_name=data.app_name,
        app_code=app_code,
        description=data.description,
        platform_env_id=data.platform_env_id,
        config_preview=config_str,
        canonical_spec_id=data.canonical_spec_id,
        status="draft"
    )
    db.add(app)
    await db.commit()
    await db.refresh(app)

    logger.info(
        "create_application success app_id=%s user_id=%s tenant_id=%s app_code=%s",
        app.id,
        ctx.user.id,
        ctx.tenant_id,
        app.app_code,
    )

    # 把对话中已创建的 DocumentVersion 关联到新 Application
    if data.conversation_id:
        try:
            from sqlalchemy import update as sa_update
            result = await db.execute(
                select(DocumentVersion).where(
                    DocumentVersion.conversation_id == data.conversation_id,
                    DocumentVersion.application_id.is_(None)
                )
            )
            conv_versions = result.scalars().all()
            if conv_versions:
                max_ver = await _bind_pending_doc_versions_to_app(db, app, conv_versions)
                app.current_doc_version = max_ver
                await db.commit()
                await db.refresh(app)
                logger.info(f"Linked {len(conv_versions)} DocumentVersion(s) to app {app.id}")
            else:
                # 兼容旧流程：对话里没有挂起版本时，也只允许从 canonical config 创建版本，
                # 绝不再把上传原文直接回灌到 DocumentVersion.raw_content。
                from app.models import Message

                doc_filename = f"{data.app_name or 'design-doc'}.md"
                msg_result = await db.execute(
                    select(Message).where(
                        Message.conversation_id == data.conversation_id,
                        Message.role == "system",
                        Message.content.like('%doc_raw%')
                    ).order_by(Message.id.desc()).limit(1)
                )
                doc_msg = msg_result.scalar_one_or_none()
                if doc_msg and doc_msg.content:
                    try:
                        raw = doc_msg.content
                        if '```doc_raw' in raw:
                            json_str = raw.split('```doc_raw\n', 1)[1].rsplit('\n```', 1)[0]
                        else:
                            json_str = raw
                        doc_data = json.loads(json_str)
                        doc_filename = doc_data.get("filename", doc_filename) or doc_filename
                    except (json.JSONDecodeError, IndexError, ValueError):
                        pass

                if config_preview:
                    await _sync_canonical_config_to_current_doc_version(
                        db,
                        app,
                        config_preview,
                        filename=doc_filename,
                        create_if_missing=True,
                    )
                    await db.commit()
                    await db.refresh(app)
                    logger.info("Fallback: created canonical DocumentVersion V1 for app %s", app.id)
        except Exception as e:
            logger.warning(f"Failed to link/create DocumentVersion: {e}")

    if config_preview:
        await _sync_canonical_config_to_current_doc_version(
            db,
            app,
            config_preview,
            create_if_missing=not bool(app.current_doc_version),
        )
        app.config_preview = _dump_preview_config(config_preview)
        await db.commit()
        await db.refresh(app)

    resp = _enrich(app)
    resp.permissions = {Action.EDIT: True, Action.DELETE: True, Action.CLONE: True, "publish": True}
    return resp


class AutoCreateRequest(BaseModel):
    """前端首次生成配置时自动创建应用"""
    app_name: str
    config_preview: dict
    conversation_id: Optional[int] = None
    project_id: Optional[int] = None
    platform_env_id: Optional[int] = None  # 2026-05-06: 让 MCP / agent 在创建时绑定环境


class AutoCreateResponse(BaseModel):
    app_id: int
    app_name: str
    app_code: str
    is_new: bool  # True=新建, False=已存在
    platform_env_id: Optional[int] = None
    platform_env_name: Optional[str] = None


@router.post("/auto-create", response_model=AutoCreateResponse)
async def auto_create_application(
    data: AutoCreateRequest,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)]
):
    """首次生成配置时自动创建 Application。

    如果 conversation_id 已有关联应用，返回已有应用（不重复创建）。
    否则创建新的 draft 应用。
    """
    # 如果有 conversation_id，检查是否已有关联应用
    if data.conversation_id:
        result = await db.execute(
            select(Application).where(
                Application.conversation_id == data.conversation_id,
                Application.tenant_id == ctx.tenant_id,
            ).order_by(Application.id.desc()).limit(1)
        )
        existing = result.scalar_one_or_none()
        if existing:
            # 更新配置，并把本次对话里尚未绑定的最新文档版本挂到当前应用
            preview_data = data.config_preview.get("data", data.config_preview) if isinstance(data.config_preview, dict) else {}
            existing_code = (
                _normalize_app_code(existing.app_code)
                or _normalize_app_code(preview_data.get("appCode") if isinstance(preview_data, dict) else "")
                or _coerce_app_code(data.app_name)
            )
            if isinstance(preview_data, dict):
                preview_data["appCode"] = existing_code
                preview_data["app_code"] = existing_code
            existing.app_code = existing_code
            existing.config_preview = _dump_preview_config(data.config_preview)
            existing.app_name = data.app_name
            try:
                doc_ver_result = await db.execute(
                    select(DocumentVersion).where(
                        DocumentVersion.conversation_id == data.conversation_id,
                        DocumentVersion.application_id.is_(None),
                    ).order_by(DocumentVersion.version.desc())
                )
                pending_versions = doc_ver_result.scalars().all()
                if pending_versions:
                    latest_version = await _bind_pending_doc_versions_to_app(db, existing, pending_versions)
                    existing.current_doc_version = latest_version or existing.current_doc_version
            except Exception as e:
                logger.warning(f"auto-create(existing): link DocumentVersions failed: {e}")
            await _sync_canonical_config_to_current_doc_version(
                db,
                existing,
                data.config_preview,
                create_if_missing=not bool(existing.current_doc_version),
            )
            await db.commit()
            existing_env_name = None
            if existing.platform_env_id:
                env_q = await db.execute(
                    select(PlatformEnv).where(PlatformEnv.id == existing.platform_env_id)
                )
                env_obj = env_q.scalar_one_or_none()
                if env_obj:
                    existing_env_name = env_obj.env_name
            return AutoCreateResponse(
                app_id=existing.id,
                app_name=existing.app_name,
                app_code=existing.app_code,
                is_new=False,
                platform_env_id=existing.platform_env_id,
                platform_env_name=existing_env_name,
            )

    if data.project_id:
        await require_project_access(
            db,
            project_id=data.project_id,
            user_id=ctx.user.id,
            tenant_id=ctx.tenant_id,
            minimum_role="member",
        )

    # 租户应用数配额（auto-create 走到这里说明确认要新建）
    from app.tenant_quota import assert_tenant_quota
    await assert_tenant_quota(db, ctx.tenant_id, "applications")

    # 生成 app_code：优先使用解析文档中的 appCode
    import hashlib
    preview_data = data.config_preview.get("data", data.config_preview) if isinstance(data.config_preview, dict) else {}
    ascii_code = _normalize_app_code(preview_data.get("appCode") if isinstance(preview_data, dict) else "")
    if not ascii_code:
        ascii_code = _normalize_app_code(data.app_name)
    if not ascii_code:
        ascii_code = f"app-{hashlib.md5(data.app_name.encode()).hexdigest()[:6]}"
    if isinstance(preview_data, dict):
        preview_data["appCode"] = ascii_code
        preview_data["app_code"] = ascii_code

    config_str = _dump_preview_config(data.config_preview)

    # 2026-05-06: 决定 platform_env_id
    # 优先级：1) 请求里显式传的 → 2) 租户默认 env → 3) 任一 connected env → None（不绑）
    resolved_env_id: Optional[int] = None
    if data.platform_env_id:
        env_check = await db.execute(
            select(PlatformEnv).where(
                PlatformEnv.id == data.platform_env_id,
                PlatformEnv.tenant_id == ctx.tenant_id,
            )
        )
        if env_check.scalar_one_or_none():
            resolved_env_id = data.platform_env_id
        else:
            logger.warning(
                "auto-create: 请求 platform_env_id=%s 不存在或不属于 tenant=%s，降级 fallback",
                data.platform_env_id, ctx.tenant_id,
            )
    if not resolved_env_id:
        env_default = await db.execute(
            select(PlatformEnv).where(
                PlatformEnv.tenant_id == ctx.tenant_id,
                PlatformEnv.is_default == True,
            )
        )
        env_obj = env_default.scalar_one_or_none()
        if env_obj:
            resolved_env_id = env_obj.id

    # 🛡️ 2026-05-15 防 retry storm：dolphin agent 通过 MCP 工具
    # generate_app_from_doc 调本 endpoint 时不传 conversation_id（工具源码 v2
    # mcp_server.py:1978 create_body 没该字段），撞失败后 dolphin omnigate 自动
    # retry → 每次都进 INSERT 新行 — 实测一次 4 分钟内 13 行 dcs-service 失败
    # 占位。这里按 (tenant_id, app_code) 在 5 分钟窗口内复用最近一条 failed/draft
    # apaas_app_id 为空的占位行。conversation_id 模式不受影响（上面已 return）。
    if not data.conversation_id:
        from datetime import datetime, timedelta
        dedup_cutoff = datetime.utcnow() - timedelta(minutes=5)
        recent = await db.execute(
            select(Application).where(
                Application.tenant_id == ctx.tenant_id,
                Application.app_code == ascii_code,
                Application.status.in_(("draft", "failed")),
                Application.apaas_app_id.is_(None),
                Application.created_at > dedup_cutoff,
            ).order_by(Application.id.desc()).limit(1)
        )
        existing_failed = recent.scalar_one_or_none()
        if existing_failed:
            existing_failed.app_name = data.app_name
            existing_failed.config_preview = config_str
            if resolved_env_id:
                existing_failed.platform_env_id = resolved_env_id
            existing_failed.status = "draft"  # 重置让上游继续走部署链路
            await db.commit()
            logger.info(
                "auto-create dedup: reusing app_id=%s (app_code=%s, prior_status=%s, "
                "created_at=%s) — anti retry-storm 2026-05-15",
                existing_failed.id, ascii_code,
                existing_failed.status, existing_failed.created_at,
            )
            new_env_name_d = None
            if resolved_env_id:
                env_q_d = await db.execute(
                    select(PlatformEnv).where(PlatformEnv.id == resolved_env_id)
                )
                env_obj_d = env_q_d.scalar_one_or_none()
                if env_obj_d:
                    new_env_name_d = env_obj_d.env_name
            return AutoCreateResponse(
                app_id=existing_failed.id,
                app_name=existing_failed.app_name,
                app_code=existing_failed.app_code,
                is_new=False,
                platform_env_id=resolved_env_id,
                platform_env_name=new_env_name_d,
            )

    app = Application(
        user_id=ctx.user.id,
        tenant_id=ctx.tenant_id,
        created_by=ctx.user.id,
        project_id=data.project_id,
        conversation_id=data.conversation_id,
        app_name=data.app_name,
        app_code=ascii_code,
        config_preview=config_str,
        platform_env_id=resolved_env_id,
        status="draft",
    )
    db.add(app)
    await db.commit()
    await db.refresh(app)

    # 关联已有的 DocumentVersion
    if data.conversation_id:
        try:
            result = await db.execute(
                select(DocumentVersion).where(
                    DocumentVersion.conversation_id == data.conversation_id,
                    DocumentVersion.application_id.is_(None),
                )
            )
            linked_versions = result.scalars().all()
            max_ver = await _bind_pending_doc_versions_to_app(db, app, linked_versions)
            if max_ver:
                app.current_doc_version = max_ver
            await _sync_canonical_config_to_current_doc_version(
                db,
                app,
                data.config_preview,
                create_if_missing=not bool(max_ver),
            )
            await db.commit()
        except Exception as e:
            logger.warning(f"auto-create: link DocumentVersions failed: {e}")

    logger.info(f"auto-create: app_id={app.id}, app_name={app.app_name}, env_id={resolved_env_id}")
    new_env_name = None
    if resolved_env_id:
        env_q = await db.execute(select(PlatformEnv).where(PlatformEnv.id == resolved_env_id))
        env_obj = env_q.scalar_one_or_none()
        if env_obj:
            new_env_name = env_obj.env_name
    return AutoCreateResponse(
        app_id=app.id,
        app_name=app.app_name,
        app_code=app.app_code,
        is_new=True,
        platform_env_id=resolved_env_id,
        platform_env_name=new_env_name,
    )


# ============================================================
# 从平台导入已有应用
# ============================================================

class ImportFromPlatformRequest(BaseModel):
    env_id: int
    apaas_app_id: str


@router.post("/import-from-platform", response_model=ApplicationResponse)
async def import_from_platform(
    body: ImportFromPlatformRequest,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """从平台导入已有应用：拉取结构 → 生成 config_preview + markdown 需求文档"""
    from app.platform_sync import sync_from_platform_full
    from app.services.config_to_spec import config_to_markdown

    # 1. 获取环境
    env_result = await db.execute(
        select(PlatformEnv).where(
            PlatformEnv.id == body.env_id,
            PlatformEnv.tenant_id == ctx.tenant_id,
        )
    )
    env = env_result.scalar_one_or_none()
    if not env:
        raise HTTPException(status_code=404, detail="环境不存在")
    token = env.token or getattr(ctx.user, "apaas_token", None)
    if not token:
        raise HTTPException(status_code=400, detail="当前用户平台 token 不可用，请重新登录")

    # 2. 检查是否已导入
    existing = await db.execute(
        select(Application).where(
            Application.tenant_id == ctx.tenant_id,
            Application.apaas_app_id == body.apaas_app_id,
        )
    )
    existing_app = existing.scalar_one_or_none()

    # 3. 创建 client，获取应用信息
    client = APaaSClient(
        base_url=env.base_url,
        tenant_id=env.platform_tenant_id,
        token=token,
    )

    try:
        app_detail = await client.query_app_detail(body.apaas_app_id)
    except Exception:
        # token 可能过期，尝试刷新
        if env.username and env.password_enc:
            try:
                password = decrypt_password(env.password_enc)
                login_result = await client.login(env.username, password)
                env.token = login_result.get("token", "")
                env.status = "connected"
                await db.commit()
                client = APaaSClient(
                    base_url=env.base_url,
                    tenant_id=env.platform_tenant_id,
                    token=env.token,
                )
                app_detail = await client.query_app_detail(body.apaas_app_id)
            except Exception as e:
                raise HTTPException(status_code=400, detail=f"获取应用信息失败: {e}")
        else:
            raise HTTPException(status_code=400, detail="token 过期且无登录凭据")

    if not app_detail:
        raise HTTPException(status_code=404, detail="平台上未找到该应用")

    app_name = app_detail.get("appName", app_detail.get("name", "未命名"))
    app_code = app_detail.get("appCode", app_detail.get("code", ""))
    app_desc = app_detail.get("description", app_detail.get("appDescription", ""))

    # 4. 完整反向解析
    try:
        config = await sync_from_platform_full(client, body.apaas_app_id, app_name)
    except Exception as e:
        logger.error(f"反向解析失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"反向解析应用结构失败: {e}")

    config = dict(config or {})
    config["appName"] = app_name
    if app_code:
        config["appCode"] = app_code

    # 5. 生成 markdown 需求文档
    try:
        markdown_spec = config_to_markdown(config, app_description=app_desc)
    except Exception as e:
        logger.warning(f"生成 markdown 失败: {e}")
        markdown_spec = ""

    resolved_app_code = _normalize_app_code(app_code) or _normalize_app_code(config.get("appCode")) or _coerce_app_code(app_name)
    config["appCode"] = resolved_app_code
    config["app_code"] = resolved_app_code

    # 6. 已存在同平台应用：作为新版本重新导入
    if existing_app:
        await _require_application_permission(ctx, db, existing_app, Action.EDIT)
        import hashlib

        max_ver_result = await db.execute(
            select(sa_func.max(DocumentVersion.version)).where(
                DocumentVersion.application_id == existing_app.id
            )
        )
        max_ver = int(max_ver_result.scalar() or 0)
        new_version = max_ver + 1
        config_json = _dump_parsed_config(config)
        rendered_doc = _render_doc_content_from_config(
            app_name or existing_app.app_name or "",
            resolved_app_code or existing_app.app_code or "",
            config,
        )

        doc_ver = DocumentVersion(
            application_id=existing_app.id,
            conversation_id=existing_app.conversation_id,
            version=new_version,
            filename=f"{app_name or existing_app.app_name or '设计文档'}-V{new_version}.md",
            content_hash=hashlib.sha256(config_json.encode()).hexdigest(),
            raw_content=rendered_doc,
            parsed_config=config_json,
            parent_version=max_ver if max_ver > 0 else None,
            summary="从平台重新导入生成",
        )
        db.add(doc_ver)

        existing_app.app_name = app_name or existing_app.app_name
        existing_app.app_code = resolved_app_code or existing_app.app_code
        existing_app.description = app_desc
        existing_app.config_preview = _dump_preview_config(config)
        existing_app.requirement_doc = markdown_spec
        existing_app.platform_env_id = body.env_id
        existing_app.current_doc_version = new_version
        existing_app.status = "completed"

        await db.commit()
        await db.refresh(existing_app)

        logger.info(
            "应用重新导入成功: %s (apaas_id=%s, version=%s)",
            app_name,
            body.apaas_app_id,
            new_version,
        )
        return _enrich(existing_app)

    # 7. 创建本地 Application 记录
    from app.tenant_quota import assert_tenant_quota
    await assert_tenant_quota(db, ctx.tenant_id, "applications")
    config_str = _dump_preview_config(config)
    new_app = Application(
        user_id=ctx.user.id,
        tenant_id=ctx.tenant_id,
        created_by=ctx.user.id,
        app_name=app_name,
        app_code=resolved_app_code,
        description=app_desc,
        config_preview=config_str,
        requirement_doc=markdown_spec,
        apaas_app_id=body.apaas_app_id,
        platform_env_id=body.env_id,
        status="completed",
    )
    db.add(new_app)
    await db.flush()
    await _sync_canonical_config_to_current_doc_version(
        db,
        new_app,
        config,
        filename=f"{app_name or '设计文档'}-V1.md",
        summary="从平台导入自动生成",
        create_if_missing=True,
    )
    await db.commit()
    await db.refresh(new_app)

    logger.info(f"应用导入成功: {app_name} (apaas_id={body.apaas_app_id})")
    return _enrich(new_app)


@router.put("/{app_id}", response_model=ApplicationResponse)
async def update_application(
    app_id: int,
    data: ApplicationCreate,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)]
):
    """更新应用配置（继续完善后重新生成前调用）"""
    result = await db.execute(
        select(Application).where(
            Application.id == app_id,
            Application.tenant_id == ctx.tenant_id
        )
    )
    app = result.scalar_one_or_none()
    if not app:
        raise HTTPException(status_code=404, detail="应用不存在")

    await _require_application_permission(ctx, db, app, Action.EDIT)

    app.app_name = data.app_name
    app.description = data.description
    if hasattr(data, 'app_code') and data.app_code:
        normalized_app_code = _normalize_app_code(data.app_code)
        if not normalized_app_code:
            raise HTTPException(status_code=400, detail=APP_CODE_RULE_TEXT)
        app.app_code = normalized_app_code
    if hasattr(data, 'platform_env_id') and data.platform_env_id is not None:
        app.platform_env_id = data.platform_env_id
    if data.config_preview:
        preview_data = data.config_preview.get("data", data.config_preview) if isinstance(data.config_preview, dict) else {}
        if isinstance(preview_data, dict):
            preview_data["appCode"] = app.app_code
            preview_data["app_code"] = app.app_code
        app.config_preview = _dump_preview_config(data.config_preview)
        await _sync_canonical_config_to_current_doc_version(
            db,
            app,
            data.config_preview,
            create_if_missing=not bool(app.current_doc_version),
        )
    # 已上平台的应用再次修改时进入“更新中”，未完成的应用才回到草稿。
    if app.apaas_app_id or app.status in ("completed", "updating"):
        app.status = "updating"
    elif app.status == "failed":
        app.status = "draft"
    await db.commit()
    await db.refresh(app)
    return _enrich(app)


@router.patch("/{app_id}/code")
async def update_app_code(
    app_id: int,
    body: dict,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)]
):
    """更新应用编码（部署失败后修改）"""
    result = await db.execute(
        select(Application).where(Application.id == app_id, Application.tenant_id == ctx.tenant_id)
    )
    app = result.scalar_one_or_none()
    if not app:
        raise HTTPException(status_code=404, detail="应用不存在")
    await _require_application_permission(ctx, db, app, Action.EDIT)
    new_code = str(body.get("app_code") or "").strip()
    if not new_code:
        raise HTTPException(status_code=400, detail="app_code 不能为空")
    if not _is_valid_app_code(new_code):
        raise HTTPException(status_code=400, detail=APP_CODE_RULE_TEXT)
    app.app_code = new_code
    if app.config_preview:
        try:
            config = loads_if_str(app.config_preview)
            data = config.get("data", config)
            data["appCode"] = new_code
            data["app_code"] = new_code
            app.config_preview = _dump_preview_config(config)

            if app.current_doc_version:
                import hashlib
                from app.routes.generation_steps import _render_design_doc_markdown

                config_json = _dump_parsed_config(config)
                rendered_doc = _render_design_doc_markdown(app.app_name, new_code, data)
                version_result = await db.execute(
                    select(DocumentVersion).where(
                        DocumentVersion.application_id == app.id,
                        DocumentVersion.version == app.current_doc_version,
                    )
                )
                current_doc_ver = version_result.scalar_one_or_none()
                if current_doc_ver:
                    current_doc_ver.filename = f"{app.app_name or '设计文档'}-V{app.current_doc_version}.md"
                    current_doc_ver.content_hash = hashlib.sha256(config_json.encode()).hexdigest()
                    current_doc_ver.raw_content = rendered_doc
                    current_doc_ver.parsed_config = config_json
                    current_doc_ver.summary = f"初始版本（已完成应用编码修复：{new_code}）"
        except Exception as e:
            logger.warning(f"同步应用编码到文档版本失败: {e}")
    await db.commit()
    return {"ok": True, "app_code": new_code}


@router.post("/{app_id}/generate-icon", response_model=GenerateAppIconResponse)
async def generate_application_icon(
    app_id: int,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    result = await db.execute(
        select(Application).where(
            Application.id == app_id,
            Application.tenant_id == ctx.tenant_id,
        )
    )
    app = result.scalar_one_or_none()
    if not app:
        raise HTTPException(status_code=404, detail="应用不存在")

    await _require_application_permission(ctx, db, app, Action.EDIT)

    icon_svg = _fallback_generated_icon(app)
    app.icon_svg = icon_svg
    await db.commit()

    return GenerateAppIconResponse(ok=True, app_id=app.id, icon_svg=icon_svg)


@router.post("/{app_id}/publish")
async def publish_application(
    app_id: int,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)]
):
    """上线应用（发布到平台）。"""
    result = await db.execute(
        select(Application).where(Application.id == app_id, Application.tenant_id == ctx.tenant_id)
    )
    app = result.scalar_one_or_none()
    if not app:
        raise HTTPException(status_code=404, detail="应用不存在")
    if not app.apaas_app_id:
        raise HTTPException(status_code=400, detail="应用尚未部署，不能上线")

    permissions = await _require_application_permission(ctx, db, app, Action.EDIT)
    if not permissions.get("publish", False):
        raise HTTPException(status_code=403, detail="当前角色无权上线该应用")

    env = None
    if app.platform_env_id:
        env_result = await db.execute(select(PlatformEnv).where(PlatformEnv.id == app.platform_env_id))
        env = env_result.scalar_one_or_none()
    if not env:
        env_result = await db.execute(
            select(PlatformEnv).where(PlatformEnv.tenant_id == ctx.tenant_id, PlatformEnv.is_default == True)
        )
        env = env_result.scalar_one_or_none()
    if not env:
        env_result = await db.execute(
            select(PlatformEnv).where(
                PlatformEnv.tenant_id == ctx.tenant_id,
                PlatformEnv.status == "connected",
            ).limit(1)
        )
        env = env_result.scalar_one_or_none()
    if not env:
        raise HTTPException(status_code=400, detail="未找到可用的平台环境")

    token = env.token
    if not token and env.username and env.password_enc:
        try:
            password = decrypt_password(env.password_enc)
            login_client = APaaSClient(base_url=env.base_url, tenant_id=env.platform_tenant_id)
            login_result = await login_client.login(env.username, password)
            token = login_result.get("token", "")
            if token:
                env.token = token
                env.status = "connected"
                await db.commit()
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"平台登录失败: {e}")
    if not token:
        raise HTTPException(status_code=400, detail="平台 token 不可用，请先在环境管理中登录")

    try:
        client = APaaSClient(base_url=env.base_url, tenant_id=env.platform_tenant_id, token=token)
        app_detail = await client.query_app_detail(str(app.apaas_app_id))
        current_version = app_detail.get("appVersion", app_detail.get("version", ""))
        if current_version:
          parts = current_version.split(".")
          try:
              nums = [int(p) for p in parts]
              nums[-1] += 1
              next_version = ".".join(str(p) for p in nums)
          except Exception:
              next_version = "1.0.1"
        else:
          next_version = "1.0.0"
        await client.deploy_app(str(app.apaas_app_id), next_version, abstract=APP_DEPLOY_ABSTRACT)
        app.status = "completed"
        await db.commit()
        return {"ok": True, "version": next_version, "remote_status": "ENABLE"}
    except Exception as e:
        detail = str(e)
        if (is_apaas_token_error(detail) or "401" in detail) and env.username and env.password_enc:
            try:
                password = decrypt_password(env.password_enc)
                refresh_client = APaaSClient(base_url=env.base_url, tenant_id=env.platform_tenant_id)
                login_result = await refresh_client.login(env.username, password)
                token = login_result.get("token", "")
                if token:
                    env.token = token
                    env.status = "connected"
                    await db.commit()
                    client = APaaSClient(base_url=env.base_url, tenant_id=env.platform_tenant_id, token=token)
                    app_detail = await client.query_app_detail(str(app.apaas_app_id))
                    current_version = app_detail.get("appVersion", app_detail.get("version", ""))
                    if current_version:
                        parts = current_version.split(".")
                        try:
                            nums = [int(p) for p in parts]
                            nums[-1] += 1
                            next_version = ".".join(str(p) for p in nums)
                        except Exception:
                            next_version = "1.0.1"
                    else:
                        next_version = "1.0.0"
                    await client.deploy_app(str(app.apaas_app_id), next_version, abstract=APP_DEPLOY_ABSTRACT)
                    app.status = "completed"
                    await db.commit()
                    return {"ok": True, "version": next_version, "remote_status": "ENABLE"}
            except Exception as retry_error:
                raise HTTPException(status_code=401, detail=f"{APAAS_LOGIN_FAILED}：{retry_error}")
        raise HTTPException(status_code=400, detail=f"上线失败: {detail}")


class PlatformConfigUpdate(BaseModel):
    """更新应用的平台环境配置"""
    platform_url: Optional[str] = None
    platform_tenant_id: Optional[str] = None
    platform_username: Optional[str] = None
    platform_password_enc: Optional[str] = None


@router.patch("/{app_id}/platform-config")
async def update_platform_config(
    app_id: int,
    data: PlatformConfigUpdate,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """更新应用的平台环境配置"""
    result = await db.execute(
        select(Application).where(
            Application.id == app_id,
            Application.tenant_id == ctx.tenant_id,
        )
    )
    app = result.scalar_one_or_none()
    if not app:
        raise HTTPException(status_code=404, detail="应用不存在")

    await _require_application_permission(ctx, db, app, Action.EDIT)

    if data.platform_url is not None:
        app.platform_url = data.platform_url
    if data.platform_tenant_id is not None:
        app.platform_tenant_id = data.platform_tenant_id
    if data.platform_username is not None:
        app.platform_username = data.platform_username
    if data.platform_password_enc is not None:
        app.platform_password_enc = data.platform_password_enc

    await db.commit()
    return {"success": True, "message": "平台配置已更新"}


@router.delete("/{app_id}")
async def delete_application(
    app_id: int,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)]
):
    """删除本地应用记录及其关联数据"""
    try:
        result = await db.execute(
            select(Application).where(
                Application.id == app_id,
                Application.tenant_id == ctx.tenant_id
            )
        )
        app = result.scalar_one_or_none()
        if not app:
            raise HTTPException(status_code=404, detail="应用不存在")

        await _require_application_permission(ctx, db, app, Action.DELETE)

        if app.status in {"completed", "generating"} or app.apaas_app_id:
            raise HTTPException(status_code=400, detail="已构建或已同步到平台的应用不允许删除")

        # 先清理依赖当前 application_id 的关联数据，避免外键约束导致主记录删除失败。
        await db.execute(
            delete(DocumentVersion).where(DocumentVersion.application_id == app.id)
        )
        await db.execute(
            delete(ChangePlan).where(ChangePlan.application_id == app.id)
        )
        await db.execute(
            delete(ConfigSnapshot).where(ConfigSnapshot.application_id == app.id)
        )
        await db.execute(
            delete(ApiCallLog).where(ApiCallLog.application_id == app.id)
        )
        await db.execute(
            delete(Application).where(
                Application.id == app.id,
                Application.tenant_id == ctx.tenant_id,
            )
        )

        await db.commit()
        return {"ok": True}
    except HTTPException:
        await db.rollback()
        raise
    except Exception as exc:
        await db.rollback()
        logger.exception("delete application failed: app_id=%s tenant_id=%s", app_id, ctx.tenant_id)
        raise HTTPException(status_code=500, detail=f"删除失败: {exc}")


@router.get("/{app_id}")
async def get_application(
    app_id: int,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """获取单个应用详情（包含平台链接）"""
    result = await db.execute(
        select(Application).where(Application.id == app_id, Application.tenant_id == ctx.tenant_id)
    )
    app = result.scalar_one_or_none()
    if not app:
        raise HTTPException(status_code=404, detail="应用不存在")
    permissions = await _require_application_permission(ctx, db, app, Action.VIEW)

    # 获取关联的平台环境
    env_base_url = None
    env_tenant_id = None
    if app.platform_env_id:
        env_result = await db.execute(select(PlatformEnv).where(PlatformEnv.id == app.platform_env_id))
        env = env_result.scalar_one_or_none()
        if env:
            env_base_url = env.base_url
            env_tenant_id = env.platform_tenant_id

    apaas_url = None
    if app.apaas_app_id:
        apaas_url = _build_apaas_url(str(app.apaas_app_id), env_base_url, env_tenant_id)

    return {
        "id": app.id,
        "app_name": app.app_name,
        "app_code": app.app_code,
        "status": app.status,
        "apaas_app_id": app.apaas_app_id,
        "apaas_url": apaas_url,
        "platform_env_id": app.platform_env_id,
        "permissions": {
            Action.EDIT: permissions.get(Action.EDIT, False),
            Action.DELETE: permissions.get(Action.DELETE, False),
            Action.CLONE: permissions.get(Action.CLONE, False),
            "publish": permissions.get("publish", False),
        },
        "created_at": str(app.created_at) if app.created_at else None,
    }


# ── API 调用日志 ──

@router.get("/{app_id}/api-logs")
async def list_api_logs(
    app_id: int,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    step_key: Optional[str] = Query(None),
    success: Optional[bool] = Query(None),
):
    """查询应用的平台 API 调用日志（分页）"""
    # 验证应用归属
    result = await db.execute(
        select(Application).where(
            Application.id == app_id,
            Application.tenant_id == ctx.tenant_id,
        )
    )
    app = result.scalar_one_or_none()
    if not app:
        raise HTTPException(status_code=404, detail="应用不存在")

    await _require_application_permission(ctx, db, app, Action.VIEW)

    # 构建查询
    query = select(ApiCallLog).where(ApiCallLog.application_id == app_id)
    count_query = select(sa_func.count()).select_from(ApiCallLog).where(ApiCallLog.application_id == app_id)

    if step_key:
        query = query.where(ApiCallLog.step_key == step_key)
        count_query = count_query.where(ApiCallLog.step_key == step_key)
    if success is not None:
        query = query.where(ApiCallLog.success == success)
        count_query = count_query.where(ApiCallLog.success == success)

    # 总数
    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0

    # 分页查询
    query = query.order_by(desc(ApiCallLog.created_at)).offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(query)
    logs = result.scalars().all()

    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": [
            {
                "id": log.id,
                "step_key": log.step_key,
                "method": log.method,
                "url": log.url,
                "request_body": log.request_body,
                "response_status": log.response_status,
                "response_body": log.response_body,
                "success": log.success,
                "error_message": log.error_message,
                "elapsed_ms": log.elapsed_ms,
                "created_at": str(log.created_at) if log.created_at else None,
            }
            for log in logs
        ],
    }


# ── AnalysisResult → AppConfig 直接转换（无 LLM） ──────────────────────────


# 子模块路由挂载
# ---------------------------------------------------------------------------
from . import change_plans as _change_plans  # noqa: E402
router.include_router(_change_plans.router)
from . import generate as _generate  # noqa: E402
router.include_router(_generate.router)
from . import docs as _docs  # noqa: E402
router.include_router(_docs.router)
from . import preflight as _preflight  # noqa: E402
router.include_router(_preflight.router)


# ---------------------------------------------------------------------------
# Phase F：Application 默认模式 (simple|pro|None) 端点
# ---------------------------------------------------------------------------
class UpdateAppDefaultModeRequest(BaseModel):
    default_mode: Optional[str] = None  # None or 'simple' or 'pro'


@router.get("/{application_id}/default-mode")
async def get_application_default_mode(
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
    return {"application_id": app.id, "default_mode": app.default_mode}


@router.patch("/{application_id}/default-mode")
async def patch_application_default_mode(
    application_id: int,
    req: UpdateAppDefaultModeRequest,
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
    if not app.project_id:
        raise HTTPException(400, "应用未关联 project，无法设置默认模式")
    await require_project_access(
        db, project_id=app.project_id, user_id=ctx.user.id, tenant_id=ctx.tenant_id,
        minimum_role="maintainer",
    )
    if req.default_mode not in (None, "simple", "pro"):
        raise HTTPException(400, "default_mode 仅支持 None / 'simple' / 'pro'")
    app.default_mode = req.default_mode
    await db.commit()
    return {"application_id": app.id, "default_mode": app.default_mode}


# ─────────────────────── App ↔ AI Chat session 绑定 ───────────────────────


@router.post("/{app_id}/chat-session/ensure")
async def ensure_app_chat_session(
    app_id: int,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """获取或创建 application 绑定的 ai_chat_session。

    首次调用：建一个 ai_chat_session（mode=chat），把应用最新 md 作为 artifact
    注入（filename=`{app_name}-设计文档.md`），让 AI 在对话里能直接 read/write 这份文档。
    回写 application.ai_chat_session_id；后续调用直接复用同一 session。
    """
    from app.models import DocumentVersion
    from app.models.ai_chat import AIChatArtifact, AIChatSession

    res = await db.execute(
        select(Application).where(
            Application.id == app_id, Application.tenant_id == ctx.tenant_id
        )
    )
    app = res.scalar_one_or_none()
    if not app:
        raise HTTPException(status_code=404, detail="应用不存在")
    await check_resource_permission(ctx, db, app, "application", Action.EDIT)

    # 已绑就直接返回
    if app.ai_chat_session_id:
        existing = (
            await db.execute(
                select(AIChatSession).where(AIChatSession.id == app.ai_chat_session_id)
            )
        ).scalar_one_or_none()
        if existing and existing.tenant_id == ctx.tenant_id:
            return {
                "session_id": existing.id,
                "title": existing.title,
                "is_new": False,
            }
        # session 被删了或属其他租户：清掉重新建
        app.ai_chat_session_id = None

    session = AIChatSession(
        tenant_id=ctx.tenant_id,
        user_id=ctx.user.id,
        title=f"调整应用：{app.app_name or app.app_code or app_id}",
        mode="chat",
        status="active",
    )
    db.add(session)
    await db.flush()

    # 注入应用最新 md 作为初始 artifact
    latest_doc = (
        await db.execute(
            select(DocumentVersion)
            .where(DocumentVersion.application_id == app.id)
            .order_by(DocumentVersion.version.desc())
            .limit(1)
        )
    ).scalar_one_or_none()

    initial_md = ""
    if latest_doc:
        try:
            from app.routes.applications._doc_helpers import _ensure_doc_version_rendered_content as _render_md
            initial_md = await _render_md(db, app, latest_doc)
        except Exception:
            initial_md = ""
    if not initial_md and app.config_preview:
        # fallback：从 config_preview 渲染 md
        try:
            from app.routes.applications._doc_helpers import _render_doc_content_from_config as _render_from_cfg
            initial_md = _render_from_cfg(loads_if_str(app.config_preview)) or ""
        except Exception:
            initial_md = ""

    artifact_filename = f"{app.app_name or app.app_code or 'app'}-设计文档.md"
    if initial_md.strip():
        db.add(
            AIChatArtifact(
                session_id=session.id,
                filename=artifact_filename,
                format="md",
                content=initial_md,
                version=1,
            )
        )

    app.ai_chat_session_id = session.id
    await db.commit()
    await db.refresh(session)

    return {
        "session_id": session.id,
        "title": session.title,
        "is_new": True,
        "artifact_filename": artifact_filename if initial_md.strip() else None,
    }


@router.post("/{app_id}/sync-from-chat-md")
async def sync_app_from_chat_md(
    app_id: int,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """从绑定的 ai_chat session 拉最新 md artifact，走 upload-doc-version 流程更新应用。

    返回 doc-version 创建结果（version_id / change_plan_id 等），前端拿到后跟原"上传新版 md"
    一样进入变更预览/审查界面。
    """
    from app.models.ai_chat import AIChatArtifact

    res = await db.execute(
        select(Application).where(
            Application.id == app_id, Application.tenant_id == ctx.tenant_id
        )
    )
    app = res.scalar_one_or_none()
    if not app:
        raise HTTPException(status_code=404, detail="应用不存在")
    await check_resource_permission(ctx, db, app, "application", Action.EDIT)

    if not app.ai_chat_session_id:
        raise HTTPException(status_code=400, detail="应用还未绑定 AI Chat 会话，请先在对话中产生设计文档")

    # 拉最新 md artifact（按 updated_at desc，filter md）
    art = (
        await db.execute(
            select(AIChatArtifact)
            .where(AIChatArtifact.session_id == app.ai_chat_session_id)
            .where(AIChatArtifact.format == "md")
            .order_by(AIChatArtifact.updated_at.desc(), AIChatArtifact.version.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if not art or not art.content.strip():
        raise HTTPException(
            status_code=400,
            detail="对话里还没有可应用的 md 设计文档；请先让 AI 用 write_artifact 产出 / 修改设计文档",
        )

    return {
        "ok": True,
        "artifact_filename": art.filename,
        "artifact_version": art.version,
        "content": art.content,
        # 前端拿到 content 后调既有的 upload-doc-version 接口（FormData 上传 md）走完整变更流
        "next_step": "POST /applications/{app_id}/upload-doc-version with file=this content",
    }


# ============================================================================
# Plan C (2026-05-19): Deploy from ai_chat artifact
#
# 流：AIChatPage 用户点 🚀 → DeployConfirmModal 弹起 → 用户确认 → 调本 endpoint
#  1. 校验 artifact 属于当前 tenant
#  2. parse_design_doc(artifact.content) → config_preview JSON
#  3. 创建 / 复用 Application 记录 (status='generating', requirement_doc=md)
#  4. 返回 task_id + app_id 供前端轮询
#
# 真 build pipeline (run_complete_generation) 复用既有 generate.py 的
# /api/applications/{app_id}/generate SSE 端点 — 前端拿到 app_id 后接 SSE 即可。
# 这里 deploy-from-artifact 只做"建库+预解析" + 返回 task_id 做轻量轮询。
# ============================================================================


class DeployFromArtifactReq(BaseModel):
    """触发部署 — 从 ai_chat_artifacts 拉 md 内容生成应用。"""
    artifact_id: int
    env: str = "test"  # dev / test / prod
    app_code: Optional[str] = None  # 可选覆盖（默认从 md 里解析）
    platform_env_id: Optional[int] = None  # 可选覆盖（默认走租户 default env）


class DeployTaskResp(BaseModel):
    task_id: str
    app_id: int
    sse_url: str  # SSE 进度流 (复用 /api/applications/{app_id}/generate)


class DeployStatusResp(BaseModel):
    done: bool
    phase: str  # draft / generating / completed / failed
    progress: int  # 0-100 (粗略估算)
    error: Optional[str] = None
    app_id: Optional[int] = None


def _parse_task_id(task_id: str) -> Optional[int]:
    """task_id 格式: deploy-art-{app_id}-{epoch}, 抽出 app_id"""
    try:
        parts = task_id.split("-")
        # ["deploy", "art", "{app_id}", "{epoch}"]
        if len(parts) >= 4 and parts[0] == "deploy" and parts[1] == "art":
            return int(parts[2])
    except Exception:
        pass
    return None


@router.post("/deploy-from-artifact", response_model=DeployTaskResp)
async def deploy_from_artifact(
    payload: DeployFromArtifactReq,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """从 ai_chat artifact (md 设计文档) 触发应用部署。

    返回 task_id 让前端轮询；app_id 让前端可立即跳转应用详情页 / 接 SSE。
    """
    from app.models.ai_chat import AIChatArtifact, AIChatSession
    from app.doc_parser import parse_design_doc

    # 1. 拉 artifact + 校验属于当前 tenant
    row = (await db.execute(
        select(AIChatArtifact, AIChatSession)
        .join(AIChatSession, AIChatArtifact.session_id == AIChatSession.id)
        .where(
            AIChatArtifact.id == payload.artifact_id,
            AIChatSession.tenant_id == ctx.tenant_id,
        )
    )).one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="artifact 不存在或不属于当前租户")
    art, sess = row
    if not art.content.strip():
        raise HTTPException(status_code=400, detail="artifact 内容为空")
    if art.format != "md":
        raise HTTPException(
            status_code=400,
            detail=f"artifact 格式必须是 md (当前: {art.format})",
        )

    # 2. parse md → config_preview
    try:
        parsed = parse_design_doc(art.content)
    except Exception as e:
        logger.error(f"parse_design_doc failed: {e}", exc_info=True)
        raise HTTPException(status_code=400, detail=f"md 解析失败: {e}")

    if not isinstance(parsed, dict) or "data" not in parsed:
        raise HTTPException(
            status_code=400,
            detail="md 解析未产出 preview data — 请检查文档是否符合标准 6 章节格式",
        )

    preview_data = parsed.get("data", {})
    if not isinstance(preview_data, dict):
        raise HTTPException(status_code=400, detail="md 解析结果格式异常")

    # 3. 推导 app_name / app_code
    app_name = (
        preview_data.get("appName")
        or preview_data.get("app_name")
        or art.filename.rsplit(".", 1)[0]  # 去 .md 后缀作为 fallback
        or "未命名应用"
    )
    ascii_code = (
        _normalize_app_code(payload.app_code)
        or _normalize_app_code(preview_data.get("appCode") or preview_data.get("app_code"))
        or _coerce_app_code(app_name)
    )
    if not ascii_code:
        import hashlib
        ascii_code = f"app-{hashlib.md5(app_name.encode()).hexdigest()[:6]}"
    preview_data["appCode"] = ascii_code
    preview_data["app_code"] = ascii_code

    # 4. 决定 platform_env_id（优先级：req > tenant default > any connected）
    resolved_env_id: Optional[int] = None
    if payload.platform_env_id:
        env_check = await db.execute(
            select(PlatformEnv).where(
                PlatformEnv.id == payload.platform_env_id,
                PlatformEnv.tenant_id == ctx.tenant_id,
            )
        )
        if env_check.scalar_one_or_none():
            resolved_env_id = payload.platform_env_id
    if not resolved_env_id:
        env_default = await db.execute(
            select(PlatformEnv).where(
                PlatformEnv.tenant_id == ctx.tenant_id,
                PlatformEnv.is_default == True,
            )
        )
        env_obj = env_default.scalar_one_or_none()
        if env_obj:
            resolved_env_id = env_obj.id
    if not resolved_env_id:
        env_conn = await db.execute(
            select(PlatformEnv).where(
                PlatformEnv.tenant_id == ctx.tenant_id,
                PlatformEnv.status == "connected",
            ).limit(1)
        )
        env_obj = env_conn.scalar_one_or_none()
        if env_obj:
            resolved_env_id = env_obj.id

    # 5. 复用同租户 + 同 app_code 的 draft / failed 占位行（防 retry storm）
    from datetime import datetime as _dt, timedelta
    dedup_cutoff = _dt.utcnow() - timedelta(minutes=5)
    config_str = _dump_preview_config(parsed)
    reused = (
        await db.execute(
            select(Application).where(
                Application.tenant_id == ctx.tenant_id,
                Application.app_code == ascii_code,
                Application.status.in_(("draft", "failed", "generating")),
                Application.apaas_app_id.is_(None),
                Application.created_at > dedup_cutoff,
            ).order_by(Application.id.desc()).limit(1)
        )
    ).scalar_one_or_none()

    if reused:
        reused.app_name = app_name
        reused.config_preview = config_str
        reused.requirement_doc = art.content
        if resolved_env_id:
            reused.platform_env_id = resolved_env_id
        reused.status = "generating"
        reused.ai_chat_session_id = sess.id
        await db.commit()
        await db.refresh(reused)
        app = reused
    else:
        # 6. 租户应用配额
        from app.tenant_quota import assert_tenant_quota
        await assert_tenant_quota(db, ctx.tenant_id, "applications")

        app = Application(
            user_id=ctx.user.id,
            tenant_id=ctx.tenant_id,
            created_by=ctx.user.id,
            app_name=app_name,
            app_code=ascii_code,
            config_preview=config_str,
            requirement_doc=art.content,
            platform_env_id=resolved_env_id,
            ai_chat_session_id=sess.id,
            status="generating",
        )
        db.add(app)
        await db.commit()
        await db.refresh(app)

    import time
    task_id = f"deploy-art-{app.id}-{int(time.time())}"

    logger.info(
        "deploy-from-artifact: artifact_id=%s tenant=%s → app_id=%s code=%s env=%s task=%s",
        art.id, ctx.tenant_id, app.id, ascii_code, payload.env, task_id,
    )

    # SSE URL 走既有 /applications/{app_id}/generate（real build pipeline）
    # 前端拿到这个 URL 后接 EventSource (要带 ?token=<jwt> query param)
    sse_url = f"/api/applications/{app.id}/generate"

    return DeployTaskResp(
        task_id=task_id,
        app_id=app.id,
        sse_url=sse_url,
    )


@router.get("/deploy-status/{task_id}", response_model=DeployStatusResp)
async def deploy_status(
    task_id: str,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """轮询部署状态 — 根据 task_id 抽 app_id 查 Application.status。

    progress 是基于 status 的粗略估算（draft=10 / generating=50 / completed=100 / failed=0），
    真细节进度走 SSE /api/applications/{app_id}/generate。
    """
    app_id = _parse_task_id(task_id)
    if not app_id:
        raise HTTPException(status_code=400, detail=f"task_id 格式错误: {task_id}")

    res = await db.execute(
        select(Application).where(
            Application.id == app_id,
            Application.tenant_id == ctx.tenant_id,
        )
    )
    app = res.scalar_one_or_none()
    if not app:
        raise HTTPException(status_code=404, detail="task 对应的应用不存在或不属于当前租户")

    status = app.status or "draft"
    progress_map = {
        "draft": 10,
        "generating": 50,
        "updating": 60,
        "completed": 100,
        "failed": 0,
    }
    progress = progress_map.get(status, 0)
    done = status in ("completed", "failed")
    error = None
    if status == "failed":
        # 老 generation flow 没记结构化错；从 ApiCallLog 抓最近一条失败的 error_message
        try:
            log_res = await db.execute(
                select(ApiCallLog).where(
                    ApiCallLog.application_id == app.id,
                    ApiCallLog.success == False,  # noqa: E712
                ).order_by(ApiCallLog.created_at.desc()).limit(1)
            )
            log = log_res.scalar_one_or_none()
            if log and log.error_message:
                error = log.error_message[:500]  # 截断防过长
        except Exception:
            pass
        if not error:
            error = "部署失败（查看应用详情页错误日志）"

    return DeployStatusResp(
        done=done,
        phase=status,
        progress=progress,
        error=error,
        app_id=app.id,
    )


# ============================================================================
# /chat?app_id=X 部署后配置助手 — 自然语言 → ChangePlan 草案
# ----------------------------------------------------------------------------
# 用户在 /chat?app_id=X 看着 apaas iframe（已部署应用），右侧 ConfigAssistantPanel
# 用自然语言描述想做的调整 (例: "把人员档案的电话改成必填")。本 endpoint:
#   1. 拉 app 当前 SPEC (requirement_doc / canonical_spec markdown)
#   2. 调 LLM 把用户意图 → 人话回复 + (可选) ChangePlan JSON
#   3. 返回 reply / change_plan / actions_summary
# 真正执行改动走 incremental_update 链路 (`/{app_id}/incremental/preview` +
# `/{app_id}/incremental/execute`)，本 endpoint 只生成草案，不直接改后端。
#
# 当前版本：先接 LLM，但 ChangePlan 解析为最小可用 (从 ```json``` 块抽 JSON)。
# TODO: 后续把 SpecAgent / incremental_update 的 diff 生成抽公共方法复用，
#       让 change_plan 字段直接对齐 incremental_update.SelectedChange schema。
# ============================================================================


class ConfigChatReq(BaseModel):
    message: str  # 本轮用户自然语言诉求
    history: list[dict] = []  # 之前的对话 [{role: 'user'|'assistant', content: str}]


class ConfigChatToolTrace(BaseModel):
    tool_name: str
    args: dict
    ok: bool
    summary: str  # 200 字以内的结果摘要 (给前端 chip 用)


class ConfigChatResp(BaseModel):
    reply: str  # AI 自然语言回复 (给用户看的解释)
    change_plan: dict | None = None  # 草拟的 ChangePlan 结构，None 表示未生成
    requires_confirmation: bool = False  # true 时前端要弹 diff 卡 + 确认按钮
    actions_summary: list[str] = []  # 人话变更点 ["人员档案: 电话 改为必填"]
    tool_trace: list[ConfigChatToolTrace] = []  # 本轮 agent loop 调过的工具痕迹


# 2026-05-19：配置助手能用的 MCP 工具白名单。
# 原则：「读取 apaas 真实状态」+「单字段/单菜单/单角色级精细修改」全放进来，
# 不放整模型 CRUD（避免一调就给用户结构性大改）/不放 deploy 类（review 后另走链路）/
# 不放 workspace 类（这是部署后 panel，不该碰本地 workspace）。
_CONFIG_CHAT_TOOL_WHITELIST: set[str] = {
    # —— 读取类 ——（agent 第一步几乎都要拉真实结构对齐用户问的"哪个模型/字段"）
    "list_apaas_apps_in_env",
    "get_apaas_app_overview",
    "list_apaas_app_models",
    "list_apaas_app_menus",
    "list_apaas_form_views",
    "list_apaas_form_components",
    "list_apaas_form_permissions",
    "list_apaas_app_dicts",
    "list_apaas_models_in_env",
    "list_apaas_app_roles",
    # —— 查重 / 防冲突 ——
    "check_app_code_conflict",
    # —— 模型字段层 —— (字段名 / 类型 / 长度；改 required 走表单组件层)
    "add_apaas_model_field",
    "update_apaas_model_field",
    "disable_apaas_model_field",
    # —— 表单组件层 —— (改 required / label / placeholder / readonly / hidden / 默认值，
    # 用户最常说的"把手机号改成必填"走这里)
    "update_apaas_form_component",
    # —— 字典 / 选项 ——
    "create_apaas_app_dict",
    "update_apaas_app_dict",
    "add_apaas_dict_option",
    "update_apaas_dict_option",
    # —— 角色 ——
    "create_apaas_app_roles",
    "update_apaas_app_role",
    "delete_apaas_app_role",
    # —— 浏览器控制 (POC, 见 docs/rfc-2026-05-19-browser-control-poc.md) ——
    # MCP API 够不到的操作 (加表单组件 / 拖拽 / 改流程拓扑等) 走这里:
    # AI 先 browser_snapshot 看页面结构，再 click/type 操作。
    # 要求用户 Chrome 已 --remote-debugging-port=9222；没开则工具调用降级失败。
    "browser_snapshot",
    "browser_click",
    "browser_type",
    "browser_navigate",
    "browser_screenshot",
    "browser_list_pages",
    "browser_select_page",
    # —— Skill 自学习（image #46） ——
    # 用户教过 AI 一类操作后，AI 用 save_config_skill 把流程总结成 steps_md。
    # 下次同类指令进来，system_prompt 自动注入相关 skills 让 AI 直接 follow。
    "save_config_skill",
    "list_config_skills",
    "get_config_skill",
    "delete_config_skill",
    # —— Demonstration recording ——
    # 用户说"我点一遍你看"：AI 调 start → 用户操作 → AI 调 stop 拿 event log →
    # 自己 summarize 成 steps_md → save_config_skill
    "browser_start_recording",
    "browser_stop_recording",
}


@router.post("/{app_id}/config-chat", response_model=ConfigChatResp)
async def config_chat(
    app_id: int,
    payload: ConfigChatReq,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """部署后配置助手 — 接入 MCP 工具 + 完整 SPEC 上下文。

    Agent loop（最多 5 轮）：
      LLM → tool_calls → mcp_bridge.call_tool → tool_result → 再 LLM …
    直到 LLM 返回纯文本（不带 tool_calls）或达到上限。
    """
    # 1. 加载 application + 校验租户
    result = await db.execute(
        select(Application).where(
            Application.id == app_id,
            Application.tenant_id == ctx.tenant_id,
        )
    )
    app = result.scalar_one_or_none()
    if not app:
        raise HTTPException(status_code=404, detail="应用不存在")
    await _require_application_permission(ctx, db, app, Action.VIEW)

    log = logging.getLogger(__name__)

    # 2. 加载完整 SPEC。优先级：canonical_spec.payload → config_preview JSON → requirement_doc
    # 之前只截 3000 字符 markdown，模型/字段 code 都被截掉了 → AI 看不见真实结构。
    spec_ctx_text = ""
    spec_source = "none"
    try:
        from app.models.spec import Spec as _Spec  # 局部 import 避顶层循环
        if app.canonical_spec_id:
            spec_row = (await db.execute(
                select(_Spec).where(_Spec.id == app.canonical_spec_id)
            )).scalar_one_or_none()
            if spec_row and spec_row.payload:
                spec_ctx_text = json.dumps(spec_row.payload, ensure_ascii=False)[:12000]
                spec_source = f"canonical_spec_id={spec_row.id}"
    except Exception as exc:  # noqa: BLE001
        log.warning("config_chat: load canonical spec failed: %r", exc)
    if not spec_ctx_text and app.config_preview:
        spec_ctx_text = app.config_preview[:12000]
        spec_source = "config_preview"
    if not spec_ctx_text and app.requirement_doc:
        spec_ctx_text = app.requirement_doc[:12000]
        spec_source = "requirement_doc"

    # 3. 拉租户 LLM 配置
    try:
        cfg = await _resolve_builder_llm_cfg(
            db, ctx.tenant_id, conversation_id=app.conversation_id
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("config_chat: resolve_builder_llm_cfg failed: %r", exc)
        cfg = None
    if not cfg:
        return ConfigChatResp(
            reply=(
                f"已收到你的需求:「{payload.message}」。\n\n"
                "当前租户尚未配置可用的 LLM (环境管理 → 模型配置)，"
                "暂时无法自动生成变更草案。配置完成后即可使用本助手。"
            ),
            change_plan=None,
            requires_confirmation=False,
            actions_summary=[],
        )

    # 4. 拉 MCP 工具（白名单过滤）
    tool_schemas: list[dict] = []
    try:
        from app.ai_chat import mcp_bridge as _bridge
        all_schemas = await _bridge.get_tool_schemas_openai()
        tool_schemas = [
            s for s in all_schemas
            if s.get("function", {}).get("name") in _CONFIG_CHAT_TOOL_WHITELIST
        ]
        log.info(
            "config_chat: loaded %d MCP tools (whitelist=%d)",
            len(tool_schemas), len(_CONFIG_CHAT_TOOL_WHITELIST),
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("config_chat: mcp_bridge load failed: %r", exc)
        tool_schemas = []

    # 5. 构造 SYSTEM prompt
    env_id_hint = app.platform_env_id or "(未绑定 platform_env)"
    apaas_app_id_hint = app.apaas_app_id or "(未部署到 apaas)"
    system_prompt = (
        "你是 aPaaS 应用的「配置调整助手」（部署后的精细化配置编辑器）。\n\n"
        "## 当前应用上下文\n"
        f"- app_name: {app.app_name}\n"
        f"- app_code: {app.app_code}\n"
        f"- apaas_app_id: {apaas_app_id_hint}   ← 调 apaas 类工具时用这个\n"
        f"- platform_env_id: {env_id_hint}      ← 调 apaas 类工具的 env_id 参数用这个\n\n"
        "## 完整 SPEC（结构化 JSON 或 markdown，可直接搜索模型/字段 code）\n"
        f"[source: {spec_source}]\n"
        "```\n"
        f"{spec_ctx_text or '(应用暂无 SPEC，请先用工具拉真实结构)'}\n"
        "```\n\n"
        "## 工作方式（Claude-in-Chrome 级 agent 自主性）\n\n"
        "### 默认主动多步执行 ⚡\n"
        "- 用户描述完需求（哪怕复杂），你**一气呵成做完**：plan → 拉真实状态 → 多个工具改 → 验证 → 总结\n"
        "- **不要每步问'要继续吗 / 是否执行'** — 用户在配置助手发指令就是让你直接干\n"
        "- 例外只有两种：(a) 需求本身有歧义 (b) 改动会影响多个候选目标且选项明确\n\n"
        "### 复杂任务先 plan 再 execute 📋\n"
        "- 任务涉及 3+ 步工具调用时，**先在 assistant content 给出执行计划**：\n"
        "  ```\n"
        "  我的计划：\n"
        "  1. 拉 ncr_models 看金额字段都叫啥\n"
        "  2. batch update_apaas_model_field 给 amount/cost/price 加 required=true\n"
        "  3. 拉 form_components 找用到这些字段的表单\n"
        "  4. update_apaas_form_component 加 max 校验 50000\n"
        "  5. list_apaas_form_components 验证改动落实\n"
        "  开始执行...\n"
        "  ```\n"
        "- 给完计划**立刻开始调工具**，不要等用户回 'OK'\n\n"
        "### 拉真实状态优先 🔍\n"
        "- 用户提'模型/字段/菜单/角色/字典'时**先调 list_* 类工具**拉 apaas 真实结构\n"
        "- **不要凭 SPEC 想象** — SPEC 跟 apaas 真实状态可能漂移\n\n"
        "### Verify-after-execute ✅\n"
        "- 调了 update_* / create_* / delete_* 后**必须再调对应 list_* 验证**：\n"
        "  - update_apaas_model_field → list_apaas_app_models\n"
        "  - update_apaas_form_component → list_apaas_form_components\n"
        "  - create_apaas_app_roles → list_apaas_app_roles\n"
        "  - add_apaas_dict_option → list_apaas_app_dicts\n"
        "- 验证失败立刻报告用户 + 给修复建议\n\n"
        "### 错误恢复 🔧\n"
        "- 工具返 `ok:false` 时先读 error_code + user_action_required，按类型自愈：\n"
        "  - `APAAS_TOKEN_EXPIRED_AND_REFRESH_FAILED` → 告诉用户去环境管理刷 token\n"
        "  - `APAAS_APP_CODE_CONFLICT` → 改 app_code 重试（agent 自己改）\n"
        "  - `APAAS_PROCESS_FIELD_CONFLICT` / `APAAS_FIELD_RESERVED` → 跳过该字段继续其他\n"
        "  - 业务逻辑错 → 调 list_* 看现状再决定怎么改\n\n"
        "### 缺信息才反问（高 bar）\n"
        "- 多个候选时列出来让用户选；缺细节给合理默认 + 说明；真有歧义才问\n\n"
        "### 返回格式\n"
        "- 做了实际变更后**回复末尾**给 ```json 块带 summary + actions：\n"
        "   {\n"
        '     \"summary\": [\"人员档案.手机号 → 必填\"],\n'
        '     \"actions\": [\n'
        '       {\"type\": \"update_field\", \"model\": \"...\", \"field\": \"...\", \"changes\": {\"required\": true}}\n'
        "     ]\n"
        "   }\n"
        "- 只读问答不需要 json 块"
    )

    messages: list[dict] = [{"role": "system", "content": system_prompt}]
    for turn in (payload.history or [])[-8:]:
        role = turn.get("role")
        content = turn.get("content")
        if role in ("user", "assistant") and isinstance(content, str):
            messages.append({"role": role, "content": content})
    messages.append({"role": "user", "content": payload.message})

    # 6. Agent loop — 2026-05-21 升到 25 轮支持"主动多步"复杂任务
    # （改 N 个字段 + verify 多次 → 一气呵成需要更多轮数）
    tool_trace: list[ConfigChatToolTrace] = []
    reply = ""
    MAX_TURNS = 25
    try:
        llm = LLMClient(
            api_key=cfg["api_key"],
            base_url=cfg["base_url"],
            model=cfg["model"],
        )
        from app.ai_chat import mcp_bridge as _bridge

        for turn_idx in range(MAX_TURNS):
            llm_resp = await llm.chat_completion(
                messages,
                max_tokens=cfg.get("max_tokens", 4096),
                temperature=0.3,
                tools=tool_schemas if tool_schemas else None,
                tool_choice="auto" if tool_schemas else None,
            )
            try:
                msg = llm_resp["choices"][0]["message"]
            except (KeyError, IndexError, TypeError):
                msg = {}
            content = (msg.get("content") or "").strip()
            tool_calls = msg.get("tool_calls") or []

            # 把 assistant 这轮塞回 messages（带 tool_calls，方便下一轮 LLM 看到它自己调过啥）
            messages.append({
                "role": "assistant",
                "content": content,
                "tool_calls": tool_calls if tool_calls else None,
            })

            # 没有工具调用 → 终止
            if not tool_calls:
                reply = content
                break

            # 有工具调用 → 逐个执行 + 喂回
            for tc in tool_calls:
                tc_id = tc.get("id") or ""
                fn = tc.get("function") or {}
                tool_name = fn.get("name") or ""
                try:
                    tc_args = json.loads(fn.get("arguments") or "{}")
                except Exception:
                    tc_args = {}

                if tool_name not in _CONFIG_CHAT_TOOL_WHITELIST:
                    # 严格白名单：LLM 调没暴露的工具直接拒
                    result_text = json.dumps({
                        "ok": False,
                        "error_code": "TOOL_NOT_ALLOWED",
                        "message": f"工具 {tool_name} 不在配置助手白名单内",
                    }, ensure_ascii=False)
                    ok_flag = False
                else:
                    try:
                        result_text = await _bridge.call_tool(
                            tool_name,
                            tc_args,
                            tenant_id=ctx.tenant_id,
                            user_id=ctx.user.id,
                        )
                        try:
                            parsed = json.loads(result_text)
                            ok_flag = bool(parsed.get("ok", True)) if isinstance(parsed, dict) else True
                        except Exception:
                            ok_flag = True
                    except Exception as exc:  # noqa: BLE001
                        result_text = json.dumps({
                            "ok": False,
                            "error_code": "BRIDGE_EXCEPTION",
                            "message": str(exc),
                        }, ensure_ascii=False)
                        ok_flag = False

                # trace 给前端展示
                summary = result_text[:200] + ("..." if len(result_text) > 200 else "")
                tool_trace.append(ConfigChatToolTrace(
                    tool_name=tool_name,
                    args=tc_args,
                    ok=ok_flag,
                    summary=summary,
                ))

                # 喂回 LLM（必须用 tool role + tool_call_id 对齐）
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc_id,
                    "content": result_text[:4000],  # 控制单条 tool_result 体积
                })
        else:
            # 跑完所有轮还没收敛 — 取最后一次 assistant content
            reply = reply or f"（已达到工具调用上限 {MAX_TURNS} 轮，任务可能未完成）"
    except Exception as exc:  # noqa: BLE001
        log.warning("config_chat agent loop failed: %r", exc)
        return ConfigChatResp(
            reply=(
                f"已收到你的需求:「{payload.message}」。\n\n"
                f"调用 LLM 或工具时出错: {exc!s}\n请稍后重试，或联系管理员检查模型配置。"
            ),
            change_plan=None,
            requires_confirmation=False,
            actions_summary=[],
            tool_trace=tool_trace,
        )

    if not reply.strip():
        reply = "我没完全理解你的诉求，可以再描述详细点吗？例如:「把『员工档案』模型的『手机号』字段改成必填」。"

    # 7. 从 reply 抽 ```json 块
    change_plan: dict | None = None
    actions_summary: list[str] = []
    m = re.search(r"```json\s*(.*?)\s*```", reply, flags=re.DOTALL)
    if m:
        try:
            parsed = json.loads(m.group(1))
            if isinstance(parsed, dict):
                change_plan = parsed
                summary = parsed.get("summary")
                if isinstance(summary, list):
                    actions_summary = [str(s) for s in summary if s]
        except (json.JSONDecodeError, ValueError):
            pass

    return ConfigChatResp(
        reply=reply,
        change_plan=change_plan,
        requires_confirmation=bool(change_plan),
        actions_summary=actions_summary,
        tool_trace=tool_trace,
    )


# ── SSE 流式版 ─────────────────────────────────────────────
# 2026-05-19 image #40 reaction: 同步 config-chat 跑 5 轮 agent loop 容易超过
# 60s axios 默认超时；改成 SSE 让用户实时看到 "正在调 list_apaas_app_models /
# 已拿到 7 个模型" 的进度，体验跟 ai-chat 一致。
async def _config_chat_event_stream(
    app_id: int,
    payload: ConfigChatReq,
    ctx: AuthContext,
    db: AsyncSession,
):
    """SSE generator — 复用同步版的 agent loop 主体，每个关键点 yield 一个 SSE event。

    事件类型：
      started      {app_id, spec_source, tools}
      turn_start   {turn, of}
      tool_call    {tool_name, args}
      tool_result  {tool_name, ok, summary}
      assistant    {content}   每轮 LLM 返回的纯文本（即将进下一轮 / 或最终）
      done         {reply, change_plan, requires_confirmation, actions_summary, tool_trace}
      error        {message}
    """
    log = logging.getLogger(__name__)

    def _sse(event: str, data: dict) -> dict:
        return {"event": event, "data": json.dumps(data, ensure_ascii=False)}

    try:
        # ── 复用同步版的 application + spec + cfg + tools 加载 ──
        result = await db.execute(
            select(Application).where(
                Application.id == app_id,
                Application.tenant_id == ctx.tenant_id,
            )
        )
        app = result.scalar_one_or_none()
        if not app:
            yield _sse("error", {"message": "应用不存在"})
            return
        await _require_application_permission(ctx, db, app, Action.VIEW)

        # SPEC
        spec_ctx_text = ""
        spec_source = "none"
        try:
            from app.models.spec import Spec as _Spec
            if app.canonical_spec_id:
                spec_row = (await db.execute(
                    select(_Spec).where(_Spec.id == app.canonical_spec_id)
                )).scalar_one_or_none()
                if spec_row and spec_row.payload:
                    spec_ctx_text = json.dumps(spec_row.payload, ensure_ascii=False)[:12000]
                    spec_source = f"canonical_spec_id={spec_row.id}"
        except Exception as exc:
            log.warning("config_chat_stream: load canonical spec failed: %r", exc)
        if not spec_ctx_text and app.config_preview:
            spec_ctx_text = app.config_preview[:12000]
            spec_source = "config_preview"
        if not spec_ctx_text and app.requirement_doc:
            spec_ctx_text = app.requirement_doc[:12000]
            spec_source = "requirement_doc"

        # LLM cfg
        try:
            cfg = await _resolve_builder_llm_cfg(
                db, ctx.tenant_id, conversation_id=app.conversation_id
            )
        except Exception as exc:
            cfg = None
            log.warning("config_chat_stream: resolve_builder_llm_cfg failed: %r", exc)
        if not cfg:
            yield _sse("done", {
                "reply": (
                    f"已收到你的需求:「{payload.message}」。\n\n"
                    "当前租户尚未配置可用的 LLM (环境管理 → 模型配置)，"
                    "暂时无法自动生成变更草案。"
                ),
                "change_plan": None,
                "requires_confirmation": False,
                "actions_summary": [],
                "tool_trace": [],
            })
            return

        # MCP tools
        tool_schemas: list[dict] = []
        try:
            from app.ai_chat import mcp_bridge as _bridge
            all_schemas = await _bridge.get_tool_schemas_openai()
            tool_schemas = [
                s for s in all_schemas
                if s.get("function", {}).get("name") in _CONFIG_CHAT_TOOL_WHITELIST
            ]
        except Exception as exc:
            log.warning("config_chat_stream: mcp_bridge load failed: %r", exc)

        # 拉本租户 + 本应用的已有 skills，注入 prompt 让 AI 自己挑用
        skill_hint = ""
        try:
            from app.models import ConfigAssistantSkill
            # `select` 和 `or_` 在文件顶层已 import — 这里再 from-import 会让 Python 把
            # `select` 整个函数视作 local var，函数开头那次 select(Application) 就撞
            # UnboundLocalError。直接用顶层 import 即可。
            skill_rows = (await db.execute(
                select(ConfigAssistantSkill)
                .where(
                    ConfigAssistantSkill.tenant_id == ctx.tenant_id,
                    or_(
                        ConfigAssistantSkill.app_id.is_(None),
                        ConfigAssistantSkill.app_id == app_id,
                    ),
                )
                .order_by(ConfigAssistantSkill.use_count.desc(), ConfigAssistantSkill.created_at.desc())
                .limit(20)
            )).scalars().all()
            if skill_rows:
                lines = [f"- 【skill_id={r.id}】「{r.name}」  关键词: {r.intent_keywords}" for r in skill_rows]
                skill_hint = "\n".join(lines)
        except Exception as exc:
            log.warning("config_chat_stream: load skills failed: %r", exc)

        yield _sse("started", {
            "app_id": app_id,
            "spec_source": spec_source,
            "tools": len(tool_schemas),
            "skills": len(skill_hint.split("\n")) if skill_hint else 0,
        })

        # SYSTEM prompt — 跟同步版完全一致
        env_id_hint = app.platform_env_id or "(未绑定 platform_env)"
        apaas_app_id_hint = app.apaas_app_id or "(未部署到 apaas)"
        system_prompt = (
            "你是 aPaaS 应用的「配置调整助手」（部署后的精细化配置编辑器）。\n\n"
            "## 当前应用上下文\n"
            f"- app_name: {app.app_name}\n"
            f"- app_code: {app.app_code}\n"
            f"- apaas_app_id: {apaas_app_id_hint}   ← 调 apaas 类工具时用这个\n"
            f"- platform_env_id: {env_id_hint}      ← 调 apaas 类工具的 env_id 参数用这个\n\n"
            "## 完整 SPEC\n"
            f"[source: {spec_source}]\n"
            "```\n"
            f"{spec_ctx_text or '(应用暂无 SPEC，请先用工具拉真实结构)'}\n"
            "```\n\n"
            "## 工作方式（Claude-in-Chrome 级 agent 自主性）\n\n"
            "### 默认主动多步执行 ⚡\n"
            "- 用户描述完需求（哪怕复杂），你**一气呵成做完**：plan → 拉真实状态 → 多个工具改 → 验证 → 总结\n"
            "- **不要每步问'要继续吗 / 是否执行'** — 用户在配置助手发指令就是让你直接干\n"
            "- 例外只有两种：(a) 需求本身有歧义 (b) 改动会影响多个候选目标且选项明确\n\n"
            "### 复杂任务先 plan 再 execute 📋\n"
            "- 任务涉及 3+ 步工具调用时，**先在 assistant content 给出执行计划**（不需写文件，直接说）：\n"
            "  ```\n"
            "  我的计划：\n"
            "  1. 拉 ncr_models 看金额字段都叫啥\n"
            "  2. batch update_apaas_model_field 给 amount/cost/price 加 required=true\n"
            "  3. 拉 form_components 找用到这些字段的表单\n"
            "  4. update_apaas_form_component 加 max 校验 50000\n"
            "  5. list_apaas_form_components 验证改动落实\n"
            "  开始执行...\n"
            "  ```\n"
            "- 给完计划**立刻开始调工具**，不要等用户回 'OK'\n\n"
            "### 拉真实状态优先 🔍\n"
            "- 用户提'模型/字段/菜单/角色/字典'时**先调 list_* 类工具**拉 apaas 真实结构\n"
            "- **不要凭 SPEC 想象** — SPEC 跟 apaas 真实状态可能漂移\n\n"
            "### Verify-after-execute ✅（重要！）\n"
            "- 调了 update_* / create_* / delete_* 这类改动工具后，**必须再调对应 list_* 验证结果**：\n"
            "  - update_apaas_model_field → list_apaas_app_models 看字段确实改了\n"
            "  - update_apaas_form_component → list_apaas_form_components 看组件确实改了\n"
            "  - create_apaas_app_roles → list_apaas_app_roles 看角色真创建了\n"
            "  - add_apaas_dict_option → list_apaas_app_dicts 看选项确实加了\n"
            "- 验证失败立刻报告用户 + 给修复建议，不要硬跑下一步\n\n"
            "### 错误恢复 🔧（不要直接报错给用户）\n"
            "- 工具返 `ok:false` 时**先读 error_code + user_action_required**，按类型自愈：\n"
            "  - `APAAS_TOKEN_EXPIRED_AND_REFRESH_FAILED` → 告诉用户去环境管理刷 token，停止后续\n"
            "  - `APAAS_APP_CODE_CONFLICT` → 改 app_code 重试（agent 自己改，不问用户）\n"
            "  - `APAAS_PROCESS_FIELD_CONFLICT` / `APAAS_FIELD_RESERVED` → 跳过该字段，继续其他\n"
            "  - 业务逻辑错（如 max < min）→ 调 list_* 看现状再决定怎么改\n\n"
            "### 缺信息才反问（高 bar）\n"
            "- 用户说'把电话改成必填'但多个模型都有'电话'字段时，列候选让用户选\n"
            "- 用户说'加个字段'但没说类型/长度时，给合理默认（如 string(64)）+ 在回复里说明默认值\n"
            "- 真有歧义才问，少而精\n\n"
            "### 返回格式\n"
            "- 做了实际变更后，**在回复末尾**给 ```json 块带 summary + actions\n"
            "- 只读问答（如'列出当前菜单'）不需要 json 块\n\n"
            "## 浏览器控制兜底 (apaas 平台 MCP API 够不到时)\n"
            "如果用户要做的事 (加表单组件 / 拖拽字段到表单 / 改流程拓扑 / 改菜单顺序等)\n"
            "MCP API 没暴露，**不要直接告诉用户'我做不到，请手动操作'** — 试试浏览器工具：\n"
            "  1. browser_navigate(url) — 跳到目标页面\n"
            "  2. browser_snapshot — 拿当前 tab 的 a11y tree (含元素 uid)\n"
            "  3. browser_click(uid) / browser_type(uid, text) — 操作元素\n"
            "  4. browser_screenshot — 截图（直接渲染在会话面板让用户看）\n\n"
            "**⚠️ uid 跨 snapshot 不稳定！**\n"
            "- 每次 browser_snapshot 会重置 uid prefix (1_*, 2_*, 3_*...)\n"
            "- 用旧 snapshot 的 uid 调 click/type 会失败或点错元素\n"
            "- **铁律**：每次 click/type 前都先重新 browser_snapshot 拿当前 uid\n"
            "- 点击后建议再 browser_snapshot 验证 'selected' 状态变了\n\n"
            "**⚠️ 撞 'No page selected' 错？** chrome-devtools-mcp 内部 active page 状态丢了。修法:\n"
            "  1. browser_list_pages 拿所有 tab 列表 (含 pageId + URL)\n"
            "  2. 找用户当前要操作的 tab（一般是 localhost:5173/ai-builder/... 那个）\n"
            "  3. browser_select_page(pageId) 切过去\n"
            "  4. 再 snapshot/click 就行了\n\n"
            "**操作完关键步骤建议 browser_screenshot 让用户视觉验收** —— Claude in Chrome\n"
            "风格，截图会在右侧助手面板直接渲染缩略图，用户能确认 AI 真做对了。\n\n"
            "前提：用户 Chrome 必须开 --remote-debugging-port=9222。\n"
            "失败 (BRIDGE_NOT_STARTED) 时降级到出步骤指引让用户手动点。\n\n"
            "## Skill 自学习（重要！）\n"
            "你有一套『自学习 skills』 — 用户教你一类操作后，**主动调 save_config_skill** "
            "把步骤总结成 markdown 存下来，下次同类指令进来你能直接 follow，不用从零摸索。\n\n"
            "**已加载的当前应用 skills**：\n"
            f"{skill_hint or '(暂无 — 这是这个应用第一次教你。完成关键操作后主动调 save_config_skill 沉淀)'}\n\n"
            "工作流：\n"
            "1. 用户给指令时，先扫上方 skills 列表 — 关键词匹配上就 get_config_skill(id) 拿完整 steps_md 复现\n"
            "2. 没匹配上则按常规拆解（snapshot → click → ...）执行\n"
            "3. **执行完关键复杂操作后**（譬如成功加了字段挂到表单 / 改了流程节点），主动问用户：\n"
            "   『要把这个流程存成 skill 吗？下次类似指令我能直接做。』用户同意就调 save_config_skill。\n"
            "4. 用户说『忘掉这个流程』/『以后不要这么干』时调 delete_config_skill\n"
            "5. steps_md 写明: 触发条件 + 前置 (要先 list 啥拿 id) + 具体工具调用序列 + 失败处理\n\n"
            "## 演示式学习 (重要！用户不会描述细节工具调用)\n"
            "当用户说『我点一遍给你看』/『我教你』/『看着我做』/『我演示一下』时:\n"
            "  1. 你调 browser_start_recording — 注入 click/input/change 监听到浏览器\n"
            "  2. 告诉用户『好了，请操作。完成后告诉我 \"好了\"』\n"
            "  3. 用户点点点（你不要插嘴 / 不要调任何工具，让他完整演示）\n"
            "  4. 用户说『好了 / 完成了 / 就这样』后，你调 browser_stop_recording 拿 events 数组\n"
            "  5. 你看 events 序列 (click/input 顺序 + target tag/text/role 信息)，结合\n"
            "     当前 page snapshot 推断对应的 element selector，**总结成步骤化的 steps_md**\n"
            "  6. 给用户复述: 『我看到你做了这些: 1. 点了xxx 2. 在xxx输入yyy 3. ...对吗?』\n"
            "  7. 用户确认后调 save_config_skill 存（intent_keywords 从用户首次描述里提取）\n"
            "演示式学习重点: 用户给的是动作序列，**你的工作是把动作翻译成 MCP / browser 工具\n"
            "调用序列**（譬如用户点『新增字段』按钮 → 你写成 browser_snapshot 找按钮 +\n"
            "browser_click 序列），并标清前置 (需要先 navigate / login 到某页)。\n"
        )

        messages: list[dict] = [{"role": "system", "content": system_prompt}]
        for turn in (payload.history or [])[-8:]:
            r = turn.get("role")
            c = turn.get("content")
            if r in ("user", "assistant") and isinstance(c, str):
                messages.append({"role": r, "content": c})
        messages.append({"role": "user", "content": payload.message})

        tool_trace: list[dict] = []
        reply = ""
        # 2026-05-21 升到 25 轮支持"主动多步"复杂任务
        MAX_TURNS = 25
        llm = LLMClient(
            api_key=cfg["api_key"],
            base_url=cfg["base_url"],
            model=cfg["model"],
        )
        from app.ai_chat import mcp_bridge as _bridge

        for turn_idx in range(MAX_TURNS):
            yield _sse("turn_start", {"turn": turn_idx + 1, "of": MAX_TURNS})

            llm_resp = await llm.chat_completion(
                messages,
                max_tokens=cfg.get("max_tokens", 4096),
                temperature=0.3,
                tools=tool_schemas if tool_schemas else None,
                tool_choice="auto" if tool_schemas else None,
            )
            try:
                msg = llm_resp["choices"][0]["message"]
            except (KeyError, IndexError, TypeError):
                msg = {}
            content = (msg.get("content") or "").strip()
            tool_calls = msg.get("tool_calls") or []

            # 把 assistant 这轮塞回 messages
            messages.append({
                "role": "assistant",
                "content": content,
                "tool_calls": tool_calls if tool_calls else None,
            })

            # 每轮 LLM 完成都 emit 一下当前 content（即使有 tool_calls，content 也可能有思考过程）
            if content:
                yield _sse("assistant", {"content": content, "has_tool_calls": bool(tool_calls)})

            if not tool_calls:
                reply = content
                break

            # 执行 tool calls — 每个 tool start/end emit
            for tc in tool_calls:
                tc_id = tc.get("id") or ""
                fn = tc.get("function") or {}
                tool_name = fn.get("name") or ""
                try:
                    tc_args = json.loads(fn.get("arguments") or "{}")
                except Exception:
                    tc_args = {}

                yield _sse("tool_call", {"tool_name": tool_name, "args": tc_args})

                if tool_name not in _CONFIG_CHAT_TOOL_WHITELIST:
                    result_text = json.dumps({
                        "ok": False, "error_code": "TOOL_NOT_ALLOWED",
                        "message": f"工具 {tool_name} 不在白名单内",
                    }, ensure_ascii=False)
                    ok_flag = False
                else:
                    try:
                        result_text = await _bridge.call_tool(
                            tool_name, tc_args,
                            tenant_id=ctx.tenant_id, user_id=ctx.user.id,
                        )
                        try:
                            parsed = json.loads(result_text)
                            ok_flag = bool(parsed.get("ok", True)) if isinstance(parsed, dict) else True
                        except Exception:
                            ok_flag = True
                    except Exception as exc:
                        result_text = json.dumps({
                            "ok": False, "error_code": "BRIDGE_EXCEPTION", "message": str(exc),
                        }, ensure_ascii=False)
                        ok_flag = False

                # 检测 image_data_url（browser_screenshot 返的）— 给前端单独 emit
                # 避免 result_text 全文（含 base64 几十 KB）反复出现在 trace_item
                # 同时 messages 喂回 LLM 时图像不当 prompt token (vision pipeline 留 Phase 2)
                image_data_url: str | None = None
                try:
                    _parsed_tr = json.loads(result_text)
                    if isinstance(_parsed_tr, dict) and _parsed_tr.get("image_data_url"):
                        image_data_url = _parsed_tr["image_data_url"]
                except Exception:
                    pass

                summary = result_text[:200] + ("..." if len(result_text) > 200 else "")
                trace_item = {
                    "tool_name": tool_name, "args": tc_args,
                    "ok": ok_flag, "summary": summary,
                }
                if image_data_url:
                    trace_item["image_data_url"] = image_data_url
                tool_trace.append(trace_item)
                yield _sse("tool_result", trace_item)

                # 喂回 LLM 的 tool content：图片用占位文字替代 base64，避免 token 爆炸
                feed_text = result_text[:4000]
                if image_data_url:
                    feed_text = json.dumps({
                        "ok": True, "image_captured": True,
                        "note": "已截图，渲染在会话面板内供用户查看；后续可继续 snapshot/click 操作",
                    }, ensure_ascii=False)
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc_id,
                    "content": feed_text,
                })
        else:
            reply = reply or f"（已达到工具调用上限 {MAX_TURNS} 轮，任务可能未完成）"

        if not reply.strip():
            reply = "我没完全理解你的诉求，可以再描述详细点吗？"

        # 抽 ```json 块
        change_plan: dict | None = None
        actions_summary: list[str] = []
        m = re.search(r"```json\s*(.*?)\s*```", reply, flags=re.DOTALL)
        if m:
            try:
                parsed = json.loads(m.group(1))
                if isinstance(parsed, dict):
                    change_plan = parsed
                    summary = parsed.get("summary")
                    if isinstance(summary, list):
                        actions_summary = [str(s) for s in summary if s]
            except (json.JSONDecodeError, ValueError):
                pass

        yield _sse("done", {
            "reply": reply,
            "change_plan": change_plan,
            "requires_confirmation": bool(change_plan),
            "actions_summary": actions_summary,
            "tool_trace": tool_trace,
        })
    except Exception as exc:
        log.exception("config_chat_stream failed")
        yield _sse("error", {"message": str(exc)})


@router.post("/{app_id}/config-chat-stream")
async def config_chat_stream(
    app_id: int,
    payload: ConfigChatReq,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """SSE 版本的配置助手 — 用户实时看到 tool 调用进度，不撞 60s 前端超时。"""
    from sse_starlette.sse import EventSourceResponse
    return EventSourceResponse(_config_chat_event_stream(app_id, payload, ctx, db))
