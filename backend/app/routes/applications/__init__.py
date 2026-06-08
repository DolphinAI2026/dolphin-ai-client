from __future__ import annotations
import json
import logging
import re
import time
from datetime import datetime
from difflib import SequenceMatcher
from typing import Annotated, List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File, Form
from pydantic import BaseModel, Field
from sqlalchemy import select, desc, func as sa_func, delete, and_, not_, or_
from sqlalchemy.ext.asyncio import AsyncSession
from sse_starlette.sse import EventSourceResponse
from app.database import get_db
from app.models import User, Application, DocumentVersion, ChangePlan, ApiCallLog, PlatformEnv, Conversation, ConfigSnapshot, Project, ProjectMember, Tenant, APaaSUserCredential
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
from app.tool_registry import tools_for_agent as _registry_tools_for_agent

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


async def _resolve_current_apaas_tenant_id(db: AsyncSession, ctx: AuthContext) -> str:
    """Return the aPaaS tenant bound to the currently selected AI Builder tenant."""
    if not ctx.tenant_id:
        return ""
    result = await db.execute(
        select(Tenant.apaas_tenant_id_str).where(Tenant.id == ctx.tenant_id)
    )
    return str(result.scalar_one_or_none() or "").strip()


async def _resolve_apaas_call_context(db: AsyncSession, ctx: AuthContext) -> tuple[str, str, str, str]:
    """Resolve base_url / tenant_id / token for the current local tenant.

    The legacy User.apaas_token is a single mutable token. Platform admins can
    switch across many aPaaS tenants, so using that field for a tenant-scoped
    app may send the right request with the wrong tenant token. Prefer the
    tenant platform environment token, then the per-local-tenant user
    credential, before falling back to the legacy field.
    """
    bound_tenant_id = await _resolve_current_apaas_tenant_id(db, ctx)

    env_result = await db.execute(
        select(PlatformEnv)
        .where(PlatformEnv.tenant_id == ctx.tenant_id)
        .where(PlatformEnv.status == "connected")
        .order_by(desc(PlatformEnv.is_default), desc(PlatformEnv.updated_at), desc(PlatformEnv.id))
        .limit(1)
    )
    env = env_result.scalar_one_or_none()
    if env and (env.token or "").strip():
        return (
            (settings.apaas_base_url or env.base_url or "").rstrip("/"),
            (env.platform_tenant_id or bound_tenant_id or "").strip(),
            (env.token or "").strip(),
            f"platform_env:{env.id}",
        )

    cred_result = await db.execute(
        select(APaaSUserCredential)
        .where(APaaSUserCredential.user_id == ctx.user.id)
        .where(APaaSUserCredential.local_tenant_id == ctx.tenant_id)
        .where(APaaSUserCredential.status == "connected")
        .order_by(desc(APaaSUserCredential.last_login_at), desc(APaaSUserCredential.updated_at), desc(APaaSUserCredential.id))
        .limit(1)
    )
    cred = cred_result.scalar_one_or_none()
    if cred and (cred.token or "").strip():
        return (
            (settings.apaas_base_url or cred.base_url or "").rstrip("/"),
            (cred.apaas_tenant_id or bound_tenant_id or "").strip(),
            (cred.token or "").strip(),
            f"user_credential:{cred.id}",
        )

    return (
        (settings.apaas_base_url or ctx.user.apaas_base_url or "").rstrip("/"),
        (bound_tenant_id or ctx.apaas_tenant_id or ctx.user.apaas_tenant_id or "").strip(),
        (ctx.user.apaas_token or "").strip(),
        "user_legacy",
    )


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
    match_reasons: List[str] = Field(default_factory=list)
    name_will_change: bool = False


_APP_NAME_MATCH_SUFFIXES = (
    "应用设计文档",
    "系统设计文档",
    "平台设计文档",
    "设计文档",
    "需求文档",
    "设计说明",
    "需求说明",
    "应用",
    "系统",
    "平台",
)


def _normalize_app_name_for_match(value: str) -> str:
    text = re.sub(r"[\s_\-—–《》「」『』（）()【】\\[\\]:：,，.。]+", "", str(value or "").lower())
    changed = True
    while changed and len(text) > 2:
        changed = False
        for suffix in _APP_NAME_MATCH_SUFFIXES:
            if text.endswith(suffix) and len(text) > len(suffix):
                text = text[: -len(suffix)]
                changed = True
                break
    return text


def _app_name_match_score(keyword: str, app_name: str) -> float:
    key = _normalize_app_name_for_match(keyword)
    name = _normalize_app_name_for_match(app_name)
    if not key or not name:
        return 0.0
    if key == name:
        return 100.0
    if key in name or name in key:
        shorter = min(len(key), len(name))
        longer = max(len(key), len(name))
        return 88.0 + (shorter / longer) * 10.0
    return SequenceMatcher(None, key, name).ratio() * 100.0


def _match_application_target(
    *,
    app: Application,
    app_name_like: str,
    app_code_like: str,
) -> tuple[float, list[str], bool]:
    reasons: list[str] = []
    score = 0.0

    requested_code = _normalize_app_code(app_code_like)
    existing_code = _normalize_app_code(app.app_code)
    if requested_code and existing_code == requested_code:
        reasons.append("code_exact")
        score = max(score, 120.0)

    name_score = _app_name_match_score(app_name_like, app.app_name) if app_name_like else 0.0
    if name_score >= 60.0:
        reasons.append("name_similar" if name_score < 100.0 else "name_exact")
        score = max(score, name_score)

    requested_name_raw = re.sub(r"\s+", "", str(app_name_like or "").strip().lower())
    existing_name_raw = re.sub(r"\s+", "", str(app.app_name or "").strip().lower())
    name_will_change = bool(
        requested_code
        and existing_code == requested_code
        and requested_name_raw
        and existing_name_raw
        and requested_name_raw != existing_name_raw
    )
    return score, reasons, name_will_change


@router.get("/match-by-name", response_model=List[MatchByNameItem])
async def match_applications_by_name(
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
    app_name_like: str = Query("", max_length=120),
    app_code_like: str = Query("", max_length=80),
    limit: int = Query(5, ge=1, le=20),
):
    """按 app_name / app_code 匹配本租户内当前用户可见的应用，用于 AI-Chat → Builder
    的"新建/更新到现有"选择对话框的候选拉取。

    匹配规则：
    - tenant 隔离 + 用户 access clause（owner / project member / app member / tenant_admin）
    - app_code 精确匹配优先；同编码但名称不同会标记 name_will_change
    - app_name 相似匹配：去掉"应用/系统/平台/设计文档"等通用后缀后，支持双向包含和相似度
    - 不查远程平台（轻量），只返必要字段
    """
    keyword = (app_name_like or "").strip()
    code_keyword = (app_code_like or "").strip()
    if not keyword and not code_keyword:
        return []
    stmt = (
        select(Application)
        .where(Application.tenant_id == ctx.tenant_id)
    )
    access_clause = _application_access_clause(ctx)
    if access_clause is not None:
        stmt = stmt.where(access_clause)
    # 先用租户/权限约束取轻量候选，再在 Python 里做归一化相似匹配。
    # 只用 SQL ILIKE 会漏掉「客户拜访管理应用」→「客户拜访管理」这类反向包含。
    stmt = stmt.order_by(desc(Application.updated_at)).limit(min(max(limit * 100, 500), 2000))
    rows = (await db.execute(stmt)).scalars().all()
    scored = []
    for app in rows:
        score, reasons, name_will_change = _match_application_target(
            app=app,
            app_name_like=keyword,
            app_code_like=code_keyword,
        )
        scored.append((score, reasons, name_will_change, app))
    scored = [
        item for item in scored
        if item[0] >= 60.0 and item[1]
    ]
    scored.sort(key=lambda item: (item[0], item[3].updated_at or datetime.min), reverse=True)
    return [
        MatchByNameItem(
            id=app.id,
            app_name=app.app_name,
            app_code=app.app_code,
            status=app.status,
            apaas_app_id=app.apaas_app_id,
            updated_at=app.updated_at,
            match_reasons=reasons,
            name_will_change=name_will_change,
        )
        for _, reasons, name_will_change, app in scored[:limit]
    ]


@router.get("", response_model=List[MergedAppResponse])
async def list_applications(
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
    team_scope: Optional[str] = Query(None),
    include_remote: bool = Query(True),
    source_filter: Optional[str] = Query(None),  # local / remote / linked
    include_config: bool = Query(True),  # False → 省掉沉重的 config_preview blob（计数仍保留）
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

    # include_config=False：列表场景（侧栏 / 计数）不需要每个应用的完整 config_preview。
    # 计数字段(models/forms/roles/dicts)已由 _enrich 解析填好，这里只丢大 blob 本身。
    if not include_config:
        for m in merged:
            m.config_preview = None

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
        # 2026-06-01: 租户以「当前登录用户的 aPaaS 租户」为准 (ctx.user.apaas_tenant_id),
        # env 仅兜底 —— 避免用 app 绑定环境 / 默认环境里残留的别家租户拼出错租户深链。
        link_tenant_id = _resolve_current_apaas_tenant(ctx.user.apaas_tenant_id, env_tenant_id)
        resp.apaas_url = _build_apaas_url(str(app.apaas_app_id), env_base_url, link_tenant_id)

    return resp


@router.get("/{app_id}/spec-markdown")
async def get_application_spec_as_markdown(
    app_id: int,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """返回应用当前 SPEC（config_preview）反向渲染的标准 markdown 设计文档。

    给 外部 agent / 其他 MCP 调用方用：直接把当前应用结构作为 6 章节 md
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
    create_mode: Optional[str] = None  # reuse(默认)=同 app_code 复用; new=同名时自动加后缀新建


class AutoCreateResponse(BaseModel):
    app_id: int
    app_name: str
    app_code: str
    is_new: bool  # True=新建, False=已存在
    platform_env_id: Optional[int] = None
    platform_env_name: Optional[str] = None


def _extract_preview_data(config_preview) -> dict:
    """从 application.config_preview (str / dict) 取出 data 部分 (取不到返 {})。"""
    import json as _json
    raw = config_preview
    if isinstance(raw, str):
        try:
            raw = _json.loads(raw)
        except Exception:  # noqa: BLE001
            return {}
    if not isinstance(raw, dict):
        return {}
    d = raw.get("data", raw)
    return d if isinstance(d, dict) else {}


def _merge_preview_data(old: dict, new: dict) -> dict:
    """按 code 并集合并两份 preview.data 的列表资源 (模型/表单/角色/字典/权限)。

    2026-05-28 增量建应用用: 同一 app_code 重复 generate 时, 把新批次合并进已有应用,
    而不是覆盖/新建。new 覆盖同 code 的项 (取最新定义), old 独有的保留。appName/appCode
    等标量取 new。
    """
    if not isinstance(new, dict):
        return old if isinstance(old, dict) else {}
    if not isinstance(old, dict) or not old:
        return new
    merged = dict(new)

    def _key(item, keyfields):
        if not isinstance(item, dict):
            return None
        for kf in keyfields:
            v = item.get(kf)
            if v:
                return str(v).strip().lower()
        # 权限等无 code: 用 (表单 + 角色) 兜底
        fk = item.get("formCode") or item.get("formName") or item.get("form")
        rk = item.get("roleCode") or item.get("role")
        if fk or rk:
            return f"{fk}|{rk}".lower()
        return None

    for field, keyfields in (
        ("models", ("code", "modelCode")),
        ("forms", ("code", "formCode")),
        ("roles", ("code", "roleCode")),
        ("dicts", ("code", "dictCode")),
        ("permissions", ("code",)),
    ):
        old_list = old.get(field) if isinstance(old.get(field), list) else []
        new_list = new.get(field) if isinstance(new.get(field), list) else []
        by_key: dict = {}
        order: list = []
        for i, item in enumerate(list(old_list) + list(new_list)):
            k = _key(item, keyfields) or f"__pos_{field}_{i}"
            if k not in by_key:
                order.append(k)
            by_key[k] = item  # new 后写, 覆盖同 key 的 old
        merged[field] = [by_key[k] for k in order]
    return merged


async def _next_available_app_code(db: AsyncSession, tenant_id: int, base_code: str) -> str:
    """Return base_code or base_code-N when a local app already uses it."""
    normalized = _normalize_app_code(base_code) or "app"
    candidate = normalized
    suffix = 2
    while True:
        exists = (await db.execute(
            select(Application.id).where(
                Application.tenant_id == tenant_id,
                Application.app_code == candidate,
            ).limit(1)
        )).scalar_one_or_none()
        if not exists:
            return candidate
        candidate = f"{normalized}-{suffix}"
        suffix += 1


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
            resolved_existing_env = None
            if data.platform_env_id or not existing.platform_env_id:
                resolved_existing_env = await _resolve_platform_env_for_tenant(
                    db,
                    ctx.tenant_id,
                    data.platform_env_id,
                )
                if resolved_existing_env and (
                    not existing.platform_env_id
                    or not data.platform_env_id
                    or resolved_existing_env.id == data.platform_env_id
                ):
                    existing.platform_env_id = resolved_existing_env.id
            await db.commit()
            existing_env_name = None
            if resolved_existing_env and resolved_existing_env.id == existing.platform_env_id:
                existing_env_name = resolved_existing_env.env_name
            elif existing.platform_env_id:
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

    create_mode = (data.create_mode or "reuse").strip().lower()
    force_new = create_mode in {"new", "create_new", "force_new"}
    if force_new and not data.conversation_id:
        ascii_code = await _next_available_app_code(db, ctx.tenant_id, ascii_code)
        if isinstance(preview_data, dict):
            preview_data["appCode"] = ascii_code
            preview_data["app_code"] = ascii_code

    config_str = _dump_preview_config(data.config_preview)

    # 2026-05-06: 决定 platform_env_id
    # 优先级：1) 请求里显式传的 → 2) 租户默认 env → 3) 任一 connected env → 4) 任一 env
    resolved_env_id: Optional[int] = None
    resolved_env = await _resolve_platform_env_for_tenant(db, ctx.tenant_id, data.platform_env_id)
    if resolved_env:
        resolved_env_id = resolved_env.id

    # 🔑 2026-05-28 appCode = 应用身份: 同租户同 app_code 已存在 → 复用同一应用 + 增量合并,
    # 绝不建重复应用。修"大文档拆批 → 第二批同 appCode 撞'编码重复' → agent 加 -v1 →
    # 建出 inn-idm / inn-idm-v1 多个残缺应用乱套"(用户实测)。apaas appCode 本就唯一, 同 code
    # = 同一个应用 —— 不论状态/时间/有无 apaas_app_id 都复用 (保留 apaas_app_id 让 step
    # executor 增量补缺失模型/表单, 而不是新建)。也顺带覆盖了 2026-05-15 的 retry-storm 去重。
    # conversation_id 模式上面已 return, 不进这。
    if not data.conversation_id and not force_new:
        existing_q = await db.execute(
            select(Application).where(
                Application.tenant_id == ctx.tenant_id,
                Application.app_code == ascii_code,
            ).order_by(Application.id.desc()).limit(1)
        )
        existing_app = existing_q.scalar_one_or_none()
        if existing_app:
            # 增量合并 config (按 code 并集模型/表单/角色/字典/权限), 保留 apaas_app_id
            try:
                merged_data = _merge_preview_data(
                    _extract_preview_data(existing_app.config_preview), preview_data
                )
                existing_app.config_preview = _dump_preview_config({"type": "preview", "data": merged_data})
            except Exception as merge_exc:  # noqa: BLE001
                logger.warning("auto-create appCode 复用: 合并 config 失败, 退回用新 config: %s", merge_exc)
                existing_app.config_preview = config_str
            existing_app.app_name = data.app_name or existing_app.app_name
            if resolved_env_id:
                existing_app.platform_env_id = resolved_env_id
            existing_app.status = "draft"  # 复跑部署链路, step executor 增量补缺失模型/表单
            await db.commit()
            logger.info(
                "auto-create appCode 复用: app_id=%s app_code=%s (复用同一应用 + 增量合并, 不新建)",
                existing_app.id, ascii_code,
            )
            reuse_env_name = None
            if resolved_env_id:
                eq = await db.execute(select(PlatformEnv).where(PlatformEnv.id == resolved_env_id))
                eo = eq.scalar_one_or_none()
                if eo:
                    reuse_env_name = eo.env_name
            return AutoCreateResponse(
                app_id=existing_app.id,
                app_name=existing_app.app_name,
                app_code=existing_app.app_code,
                is_new=False,
                platform_env_id=resolved_env_id,
                platform_env_name=reuse_env_name,
            )

    # 租户应用数配额: 仅真正新建时校验 (上面 appCode 复用/conversation 复用都已 return,
    # 复用同一应用不应再撞配额 —— 否则"满配额租户改不了已有应用"反直觉)。
    from app.tenant_quota import assert_tenant_quota
    await assert_tenant_quota(db, ctx.tenant_id, "applications")

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
    # 生成未完成不能上线 —— deploy 起的后台生成(模型/表单/权限)可能还在跑(apaas_app_id
    # 在生成早期就写入, 不能当"已就绪"的依据)。此时 publish 会发出半成品版本(表单缺失)。
    # 硬门要求 status=completed 再发, 同时挡住 agent 提前宣布"已上线"和 UI 提前发布。
    if app.status in ("generating", "in_progress"):
        raise HTTPException(
            status_code=409,
            detail="应用还在生成中（模型/表单/权限尚未全部就绪），请等生成完成（status=completed）后再上线。可轮询 get_application / 步骤状态查进度。",
        )

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

    # 写一条 in_progress 部署记录（用于历史 + 回滚）
    from .deploy_history import create_deploy_record_pre, complete_deploy_record
    record = await create_deploy_record_pre(
        db, app, ctx.user, deploy_type="publish", version_label=None
    )

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
        await complete_deploy_record(
            db, record, app, success=True, version_label=next_version,
            event_log=[{"type": "publish", "version": next_version, "status": "success"}],
        )
        return {"ok": True, "version": next_version, "remote_status": "ENABLE", "deploy_record_id": record.id}
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
                    await complete_deploy_record(
                        db, record, app, success=True, version_label=next_version,
                        event_log=[
                            {"type": "publish", "status": "token_refresh"},
                            {"type": "publish", "version": next_version, "status": "success"},
                        ],
                    )
                    return {"ok": True, "version": next_version, "remote_status": "ENABLE", "deploy_record_id": record.id}
            except Exception as retry_error:
                await complete_deploy_record(
                    db, record, app, success=False,
                    error_message=f"{APAAS_LOGIN_FAILED}：{retry_error}",
                    event_log=[{"type": "publish", "status": "token_refresh_failed", "error": str(retry_error)}],
                )
                raise HTTPException(status_code=401, detail=f"{APAAS_LOGIN_FAILED}：{retry_error}")
        await complete_deploy_record(
            db, record, app, success=False,
            error_message=f"上线失败: {detail}",
            event_log=[{"type": "publish", "status": "failed", "error": detail}],
        )
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


# ── 2026-05-26 design-v4 I3: 应用 env 切换 ──
#
# 应用栏 "开发 / 生产" toggle 需要知道当前 tenant 有哪些 env, 哪个是
# 当前 (= application.platform_env_id 对应) 的 env. 这个 endpoint 列出来,
# 让前端 toggle 切换时拿到目标 env 的 url + id, 调 platform-proxy/entry
# 时透传 env_id 真切 iframe.
#
# env type 推断 (env_name 启发式 — current schema 没 type 字段):
#   含 prod / production / 生产           → 'prod'
#   含 trial / preview / sandbox / 预览    → 'preview'
#   其他                                   → 'dev'
def _infer_env_type(env_name: str) -> str:
    name_lower = (env_name or "").lower()
    if any(k in name_lower for k in ("prod", "production")) or "生产" in (env_name or ""):
        return "prod"
    if any(k in name_lower for k in ("trial", "preview", "sandbox")) or "预览" in (env_name or ""):
        return "preview"
    return "dev"


@router.get("/{app_id}/envs")
async def list_app_envs(
    app_id: int,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """列出当前应用可切换的平台环境.

    返回当前 tenant 全部 envs (PlatformEnv), 推断每个 env 的 type
    (dev / preview / prod), 标记 current=true 的是 application.platform_env_id
    对应的那个.

    前端应用栏 "开发 / 生产" toggle 用这个 endpoint:
      - 默认显示 type=dev 那个 (current env 一般是 dev)
      - 点 "生产" → 找 type=prod 的 env, 切 iframe URL 走那个 env_id
      - 没 type=prod env → toast "未配置生产环境"

    返:
      ok: True
      envs: [
        { id, env_name, alias?, base_url, type, current, status,
          has_token, can_iframe }
      ]
      current_env_id: int | None
      has_prod_env: bool
    """
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

    # 拉当前 tenant 所有 env
    env_rows = await db.execute(
        select(PlatformEnv)
        .where(PlatformEnv.tenant_id == ctx.tenant_id)
        .order_by(PlatformEnv.is_default.desc(), PlatformEnv.id.asc())
    )
    envs = env_rows.scalars().all()

    out_envs = []
    has_prod = False
    for env in envs:
        env_type = _infer_env_type(env.env_name)
        if env_type == "prod":
            has_prod = True
        is_current = bool(app.platform_env_id and env.id == app.platform_env_id)
        has_token = bool(env.token)
        out_envs.append({
            "id": env.id,
            "env_name": env.env_name,
            "alias": env.alias,
            "base_url": env.base_url,
            "type": env_type,
            "current": is_current,
            "status": env.status,
            "is_default": env.is_default,
            "has_token": has_token,
            "can_iframe": has_token and env.status == "connected",
        })

    return {
        "ok": True,
        "envs": out_envs,
        "current_env_id": app.platform_env_id,
        "has_prod_env": has_prod,
        "apaas_app_id": app.apaas_app_id,  # 前端判断是否能切 (没 apaas_app_id = 没部署)
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
# 2026-05-24 部署历史 + 回滚 (Agent C cherry-pick)
from . import deploy_history as _deploy_history  # noqa: E402
router.include_router(_deploy_history.router)
# 2026-05-26 PR6 (SPEC v2 §2 Section E0) — 扩展 section 子路由
# 4 endpoint: /dev-kits 轮询 + /extension-update-events SSE +
# /extension-update-notify 内部 hook + /republish 触发 aPaaS 重发
from . import extension as _extension  # noqa: E402
router.include_router(_extension.router)

# PR2b-followup (2026-05-26): SectionNav sub-tab 资源列表 — 7 个 GET endpoint
# 包 list_apaas_app_models / dicts / forms / lists / processes / business-events / roles
from . import section_content as _section_content  # noqa: E402
router.include_router(_section_content.router)

# K4 (2026-05-27): 应用日志 — 4 kind aggregator (deploy / operation / ai / error)
from . import logs_endpoint as _logs_endpoint  # noqa: E402
router.include_router(_logs_endpoint.router)

# U8 (2026-05-27): 设计 tab 内嵌 SPEC chat — 改 spec_sections 草稿 (跟 config-chat
# 区分: 草稿层, 不立即生效, 等用户"确认并生成"). MVP 用 rule-based mock LLM.
from . import spec_chat as _spec_chat  # noqa: E402
router.include_router(_spec_chat.router)
# V3 (2026-05-27): "确认并生成" modal — apply spec_sections 草稿到 apaas.
# /spec/apply-plan + /spec/apply (MVP dry-run, P5 接通 MCP 真调).
from . import spec_apply as _spec_apply  # noqa: E402
router.include_router(_spec_apply.router)

# Y (2026-05-27): SPEC 版本管理 + markdown 缓存.
# /spec/versions + /versions/{id} + /spec/markdown + /spec/export.md
from . import spec_versions as _spec_versions  # noqa: E402
router.include_router(_spec_versions.router)

# Y (2026-05-27): 业务事件 endpoint — SPEC 设计 tab 章九用.
# /business-events 包 list_apaas_business_events MCP.
from . import business_events as _business_events  # noqa: E402
router.include_router(_business_events.router)


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

    # 5. 🔑 2026-05-28 appCode = 应用身份: 同租户同 app_code 已存在 → 复用同一应用 + 增量合并 config,
    #    绝不建重复应用。修"大文档拆批 → 第二批同 appCode 撞'编码重复' → agent 加 -v1 →
    #    inn-idm / inn-idm-v1 多个残缺应用乱套"(用户实测)。apaas appCode 本就唯一, 同 code =
    #    同一个应用 —— 不论状态/时间/有无 apaas_app_id 都复用 (保留 apaas_app_id 让 generate
    #    pipeline 增量补缺失模型/表单, 而非新建)。顺带覆盖了原 retry-storm 去重 (5min 窗口)。
    config_str = _dump_preview_config(parsed)
    reused = (
        await db.execute(
            select(Application).where(
                Application.tenant_id == ctx.tenant_id,
                Application.app_code == ascii_code,
            ).order_by(Application.id.desc()).limit(1)
        )
    ).scalar_one_or_none()

    if reused:
        # 增量合并 config (按 code 并集模型/表单/角色/字典/权限), 保留 apaas_app_id
        try:
            merged_data = _merge_preview_data(
                _extract_preview_data(reused.config_preview), preview_data
            )
            reused.config_preview = _dump_preview_config({"type": "preview", "data": merged_data})
        except Exception as merge_exc:  # noqa: BLE001
            logger.warning(
                "deploy-from-artifact appCode 复用: 合并 config 失败, 退回新 config: %s", merge_exc
            )
            reused.config_preview = config_str
        reused.app_name = app_name or reused.app_name
        reused.requirement_doc = art.content
        if resolved_env_id:
            reused.platform_env_id = resolved_env_id
        reused.status = "generating"
        reused.ai_chat_session_id = sess.id
        await db.commit()
        await db.refresh(reused)
        app = reused
        logger.info(
            "deploy-from-artifact appCode 复用: app_id=%s app_code=%s (复用同一应用 + 增量合并, 不新建)",
            app.id, ascii_code,
        )
    else:
        # 6. 租户应用配额 (仅真正新建时校验; 复用同一应用不撞配额)
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


# PR2c (SPEC v2 §1.2): section-aware system prompt 软引导.
# 提取到模块级让单测可直接调 _build_section_hint, 避免触发整个 _config_chat_event_stream.
_CONFIG_CHAT_SECTION_HINTS: dict[str, str] = {
    "data": (
        "## 用户当前焦点：📊 数据 section\n"
        "用户当前在「数据」section 看模型 / 字段 / 字典. 优先围绕模型结构 / 字段属性 / 字典选项展开.\n"
        "工具优先级提示 (不锁): list_apaas_app_models / update_apaas_model_field / list_apaas_app_dicts / add_dict_option.\n"
        "若用户问跨 section 的事 (改菜单 / 改流程 / 改权限), 直接调对应工具 — 不要拦, 不要建议\"先切到 X section\". 仅在歧义时反问.\n\n"
    ),
    "ui": (
        "## 用户当前焦点：🎨 界面 section\n"
        "用户当前在「界面」section 看菜单 / 表单 / 列表. 优先围绕导航结构 / 表单组件 / 列表视图展开.\n"
        "工具优先级提示 (不锁): list_apaas_app_menus / add_apaas_menu / list_apaas_form_components / update_apaas_form_component.\n"
        "若用户问跨 section 的事 (改字段 / 改流程 / 改权限), 直接调对应工具 — 不要拦, 不要建议\"先切到 X section\". 仅在歧义时反问.\n\n"
    ),
    "logic": (
        "## 用户当前焦点：⚙️ 逻辑 section\n"
        "用户当前在「逻辑」section 看流程 / 业务事件 / 触发器. 优先围绕审批流 / 流程节点 / 业务事件钩子展开.\n"
        "工具优先级提示 (不锁): list_apaas_app_processes / set_apaas_app_process / list_apaas_business_events / create_business_event.\n"
        "若用户问跨 section 的事 (改字段 / 改菜单 / 改权限), 直接调对应工具 — 不要拦, 不要建议\"先切到 X section\". 仅在歧义时反问.\n\n"
    ),
    "permission": (
        "## 用户当前焦点：🔒 权限 section\n"
        "用户当前在「权限」section 看角色 / 菜单授权 / 字段授权. 优先围绕角色定义 / 菜单可见性 / 字段读写权限展开.\n"
        "工具优先级提示 (不锁): list_apaas_app_roles / create_apaas_app_roles / grant_app_access.\n"
        "若用户问跨 section 的事 (改字段 / 改菜单 / 改流程), 直接调对应工具 — 不要拦, 不要建议\"先切到 X section\". 仅在歧义时反问.\n\n"
    ),
    "extension": (
        "## 用户当前焦点：🧩 扩展 section\n"
        "用户当前在「扩展」section 看自开发组件 / 自开发整页 / 平台资源.\n"
        "⚠️ **Builder 不做自定义代码开发**：如果用户想写 Vue 组件 / 自开发整页 / 自定义后端接口 / npm build 等，\n"
        "请告诉用户：「自定义代码开发请用应用页右上角的「→ 自开发」入口，会带着当前应用进 AI Builder 做二次开发。」不要自己尝试建 workspace / 写代码 / 跑命令。\n"
        "若用户问改字段 / 改菜单 / 改流程 / 改权限, 直接调对应工具 — 不要拦. 仅在歧义时反问.\n\n"
    ),
}


def _build_section_hint(section: str | None) -> str:
    """根据用户当前 section 返软引导 prompt 片段.

    PR2c (SPEC v2 §1.2): 5 个白名单 section → 注入 focus hint;
    任何其他值 (含 None / 空串 / 大小写不一致 / 未知 section) → 返空串,
    跟旧行为兼容. 保守容错避免老前端 / agent 测试乱传字段.
    """
    if not section:
        return ""
    key = section.strip().lower()
    return _CONFIG_CHAT_SECTION_HINTS.get(key, "")


class ConfigChatReq(BaseModel):
    message: str  # 本轮用户自然语言诉求
    history: list[dict] = []  # 之前的对话 [{role: 'user'|'assistant', content: str}]
    # 2026-05-24: 用户可在 ConfigAssistantHeader 选模型。0/None = 走 _resolve_builder_llm_cfg
    # 默认 (跟原行为一致)。>0 时强制用该 LlmConfig.id 跑 agent (Claude/DeepSeek 等)。
    model_id: int | None = 0
    # 2026-05-24 加：session_id 用于会话持久化。0 / None / 不传 → 后端自动新建 session。
    # 后端在 'started' SSE 事件中回 session_id 给前端，前端 sticky 到 useConfigChat.sessionId。
    session_id: int | None = None
    # 2026-05-26 (PR2c SPEC v2 §1.2): SectionNav 当前 section 软引导 hint.
    # data/ui/logic/permission/extension 之一 → system_prompt 加 focus 提示;
    # 任何其他值 / None → 不注入 hint (跟老行为一致). **不做硬白名单切换** —
    # agent 看到的工具集全集不变, 只是优先讨论该 section 的事; 用户问跨 section
    # 操作时 agent 直接处理 (避免上下文丢).
    section: str | None = None


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


# 2026-05-19 起: 配置助手能用的 MCP 工具白名单。
# 2026-05-26 (SPEC v2 PR1): 改派生自 backend/tool_registry.yaml — 单一真相。
# 2026-05-26 (PR3 合 PR1): update_apaas_app_info 通过 yaml entry 加入 (agents:[config]).
#
# 历史原则 (写入 yaml 时的 agents=[config] 分类依据):
#   - "读取 apaas 真实状态" + "单字段/单菜单/单角色级精细修改" 全放
#   - 不放整模型 CRUD (避免一调就给用户结构性大改)
#   - 不放 deploy 类 (review 后另走链路)
#   - 不放 workspace 类 (这是部署后 panel, 不该碰本地 workspace)
#
# 加 / 改工具走 backend/tool_registry.yaml — 改对应 entry 的 agents 字段:
#   add `config`  → 进白名单
#   remove `config` → 出白名单
# 改完跑 `pytest backend/tests/test_tool_registry.py -v` 验证。
_CONFIG_CHAT_TOOL_WHITELIST: set[str] = set(_registry_tools_for_agent("config"))


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

        # ── 2026-05-24 会话持久化：resolve session_id（payload.session_id 复用 / 否则新建） ──
        # session 在 stream 一开始就建好，便于 user message 入库即可见，前端拉历史也对得上。
        # 失败兜底：任何一步抛异常都不阻断主流程，只 log，让 chat 流退化为旧的 in-memory 模式。
        from app.models.config_chat import ConfigChatMessage, ConfigChatSession
        config_session: ConfigChatSession | None = None
        try:
            requested_sid = payload.session_id or 0
            if requested_sid > 0:
                config_session = (await db.execute(
                    select(ConfigChatSession).where(
                        ConfigChatSession.id == requested_sid,
                        ConfigChatSession.tenant_id == ctx.tenant_id,
                        ConfigChatSession.user_id == ctx.user.id,
                        ConfigChatSession.app_id == app_id,
                    )
                )).scalar_one_or_none()
            if config_session is None:
                # 新建 — title 用 user prompt 截前 30 字（去 newlines 让标题成单行）
                _msg = (payload.message or "").replace("\n", " ").strip()
                _title = (_msg[:30] + ("…" if len(_msg) > 30 else "")) or "新对话"
                config_session = ConfigChatSession(
                    app_id=app_id,
                    tenant_id=ctx.tenant_id,
                    user_id=ctx.user.id,
                    title=_title,
                )
                db.add(config_session)
                await db.commit()
                await db.refresh(config_session)
            # 立刻落 user 消息（无论新老 session）
            db.add(ConfigChatMessage(
                session_id=config_session.id,
                role="user",
                content=payload.message or "",
            ))
            # bump session updated_at 让最近用过的 session 排前面
            config_session.updated_at = datetime.utcnow()
            await db.commit()
        except Exception as exc:
            log.warning("config_chat_stream: persist session/user-message failed: %r", exc)
            config_session = None  # 不阻断主流程

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
        # 2026-05-24: payload.model_id >0 时强制走指定 LlmConfig (用户在 Header 下拉切的);
        # 0/None 时走 conversation/tenant 默认 (跟老行为一致)。
        selected_config_id = (
            payload.model_id if payload.model_id and payload.model_id > 0 else None
        )
        try:
            cfg = await _resolve_builder_llm_cfg(
                db,
                ctx.tenant_id,
                conversation_id=app.conversation_id,
                selected_config_id=selected_config_id,
            )
        except Exception as exc:
            cfg = None
            log.warning("config_chat_stream: resolve_builder_llm_cfg failed: %r", exc)
        if not cfg:
            _fallback_reply = (
                f"已收到你的需求:「{payload.message}」。\n\n"
                "当前租户尚未配置可用的 LLM (环境管理 → 模型配置)，"
                "暂时无法自动生成变更草案。"
            )
            # 2026-05-24 落兜底 assistant 消息让历史完整
            if config_session is not None:
                try:
                    db.add(ConfigChatMessage(
                        session_id=config_session.id,
                        role="assistant",
                        content=_fallback_reply,
                    ))
                    config_session.updated_at = datetime.utcnow()
                    await db.commit()
                except Exception as exc:
                    log.warning("config_chat_stream: persist fallback assistant failed: %r", exc)
            yield _sse("done", {
                "reply": _fallback_reply,
                "change_plan": None,
                "requires_confirmation": False,
                "actions_summary": [],
                "tool_trace": [],
                "session_id": config_session.id if config_session else None,
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
            # 2026-05-24: 让前端日志显示实际跑的模型 (用户切了 model_id 后能验证生效)
            "model": cfg.get("model"),
            "provider": cfg.get("provider"),
            # 2026-05-24: 让前端 sticky session_id — 后续同 session 续聊只用这个值
            "session_id": config_session.id if config_session else None,
        })

        # SYSTEM prompt — 跟同步版完全一致, 加 PR2c 软 section hint.
        # PR2c (SPEC v2 §1.2): section hint 提取到模块级 _build_section_hint 让单测可直接验.
        env_id_hint = app.platform_env_id or "(未绑定 platform_env)"
        apaas_app_id_hint = app.apaas_app_id or "(未部署到 apaas)"
        section_hint = _build_section_hint(payload.section)
        system_prompt = (
            "你是 aPaaS 应用的「配置调整助手」（部署后的精细化配置编辑器）。\n\n"
            f"{section_hint}"
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
            "- 做了实际变更后（调了 update_*/create_*/delete_* 类工具且 ok=true），**在回复末尾**给 ```json 块带 summary + actions, **actions.type 必须是真工具名** (update_field / create_role / add_dict_option 等), 不要是 read/design 这种「建议型」占位\n"
            "- 只读问答（「列出当前菜单」）**不要给 json 块** — 给 json 但没真做事会让前端误以为有 ChangePlan 可应用, 这是反模式\n\n"
            "## 自定义代码开发 → 请走 AI Builder 二次开发\n\n"
            "如果用户提到「自开发页面 / 自定义 Vue 页 / 看板 / 大屏 / 自开发组件 / 写代码 / npm build / 后端自开发接口」等，\n"
            "**配置助手不直接处理这类请求**，请直接告知用户：\n"
            "「这类自定义代码开发请用应用页右上角的「→ 自开发」入口，会带着当前应用进 AI Builder 做二次开发。」\n"
            "不要尝试调用 create_dev_workspace / write_workspace_files / run_workspace_command / publish_dev_workspace 等 workspace 工具。\n\n"
            "## ⚠️ 浏览器操作铁律 — frame 级精确路由 (2026-05-25 升级)\n\n"
            "用户在 `localhost:5173/ai-builder/chat?app_id=N` ChatPage tab 里看着一个 iframe, iframe src 是\n"
            "`/api/platform-proxy/entry?...`, 会重定向到 `/platform/<tid>/admin/app-store/edit-app?appId=...`.\n\n"
            "**整个 tab 有两个关键 frame**:\n"
            "- **host frame** (顶层, URL 是 ChatPage 自己): ChatPage 的 Vue UI — 左侧对话 / 中间 hero / 右侧助手.\n"
            "  这是开发者 UI, 不是用户要改的应用配置.\n"
            "- **platform frame** (iframe, URL 含 `/platform/` 或 `/api/platform-proxy/entry`): 真正的 aPaaS 应用\n"
            "  配置页 — 应用编辑 / 菜单管理 / 流程设计 / 角色权限. **所有 \"调整应用 UI\" 操作目标都在这里**.\n\n"
            "### 正确操作流程\n"
            "1. `browser_snapshot` → 看返回的 `frames[]` 数组. 找 `role == \"platform\"` 的那个 frame, 拿 `tree`.\n"
            "   如果没有 role=\"platform\" 的 frame, 报错并停止 (见下「找不到 platform frame」铁律).\n"
            "2. 在 platform frame 的 `tree` 里找你要操作的元素 uid.\n"
            "3. `browser_click(uid=..., frame_role=\"platform\")` — **强烈推荐用 `frame_role` 而不是 `frame_id`**:\n"
            "   - `frame_role=\"platform\"`: extension 现场枚举找当前 platform iframe, 抗 iframe 重建 (ChatPage 的\n"
            "     Vue `:key` 会让 iframe 元素重新挂载, frame_id 跟着变; 用 role 寻址永远命中最新那个).\n"
            "   - frame_id 可以传作为 hint, 但失效时 extension 自动 fallback 到 role 解析, response 里\n"
            "     `self_healed: true` + `frame_id_was_stale: <旧 id>` 告诉你切了.\n"
            "4. `browser_type(uid=..., text=..., frame_role=\"platform\")` — 同理.\n"
            "5. `browser_wait_for_text(text=\"...\", frame_role=\"platform\", timeout_ms=5000)` — 等 platform 异步\n"
            "   渲染完再做下一步.\n"
            "6. `browser_press_key(key=\"Enter\", frame_role=\"platform\")` — 表单提交 / 弹窗关闭.\n\n"
            "### 铁律\n"
            "- ❌ **绝对不要 `browser_navigate(...)`**. ChatPage tab 是用户当前正在用的, navigate 替换整个 tab URL\n"
            "  → ChatPage 消失 → 后续 snapshot 找不到 iframe → 用户白等. 切菜单/页面靠 click platform frame 内部\n"
            "  的导航元素 (sidebar 菜单项 / breadcrumb / tab 标签), 让 iframe 自己跳, 不要碰父 tab.\n"
            "- ❌ **不传 frame_role 也不传 frame_id** = 默认 frame_id=0 = host frame = 点错地方.\n"
            "  操作 aPaaS 应用 UI 永远要 `frame_role=\"platform\"`.\n"
            "- ❌ **撞 `error_code: \"PLATFORM_FRAME_LOST\"`**: extension 重新枚举后也找不到 platform iframe.\n"
            "  说明 (a) 用户跳出 ChatPage 了, 或 (b) iframe 加载失败 (app 未部署 / 平台 token 过期 / proxy error).\n"
            "  立刻给用户报「未检测到 platform iframe」错, 绝对不要为了\"看起来 work\"去操作 host frame.\n"
            "- ❌ **撞 `Could not establish connection. Receiving end does not exist`**: 老 frame_id 过期 (iframe\n"
            "  被 Vue 重建了). 改用 `frame_role=\"platform\"` 立刻好 (extension 重新枚举找当前 platform). 这不是扩展\n"
            "  坏了, 是 frame_id 不耐用的本质 — 用 role 寻址一劳永逸.\n"
            "- ❌ 用旧 snapshot 的 uid: 每次 snapshot 都重置 uid 池. 操作前必 snapshot, 不要缓存 uid.\n\n"
            "### Frame 模型自检 (调用前心里过一遍)\n"
            "- 这一步是改用户的 aPaaS 应用 UI 吗? → 用 **platform** frame_id.\n"
            "- 这一步是看 ChatPage 自身状态吗? → 一般用不到; ChatPage 状态走 MCP API 类工具拿\n"
            "  (`get_apaas_app_overview` / `list_apaas_app_menus` 等), 不要靠 snapshot host frame.\n\n"
            "### 截图验收\n"
            "- 关键步骤 (改完字段 / 改完菜单) 调 `browser_screenshot` 让用户视觉确认. screenshot 是整个 tab 视口,\n"
            "  不分 frame — 用户能直接看到 iframe 内变化.\n\n"
            "### Fallback (chrome extension 未连)\n"
            "- snapshot 返 `source: \"cdm\"` 且 `frame_count: 1` → extension 没装, 走 chrome-devtools-mcp 的扁平视图,\n"
            "  看不到 iframe 内部 DOM. 此时告诉用户去装 apaas-builder-helper extension, 不要在 cdm 模式下硬操作\n"
            "  iframe 内元素 (会撞 ELEM_NOT_FOUND).\n\n"
            "### 撞 'No page selected' (cdm 兜底路径)\n"
            "- 如果 source=cdm 且报 No page selected: browser_list_pages 拿 tab 列表 → browser_select_page(pageId) 切\n"
            "  到 localhost:5173/ai-builder/chat 那个 tab → 再 snapshot. 仅 fallback 场景用.\n\n"
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
            "browser_click 序列），并标清前置 (需要先 navigate / login 到某页)。\n\n"

            "## ❌ 不要 demonstration 的场景 — 直接调专属 MCP\n"
            "下面这些操作 MCP 已封装好一键工具, 不要走 browser_start_recording / browser_click,\n"
            "也不要让用户『演示一下』 — 直接调对应 MCP 一把过, 比录制 + 重放快 100 倍 + 稳定:\n"
            "  - **⭐ 加新表单/功能** → `build_apaas_feature_from_spec(env_id, apaas_app_id,\n"
            "    feature_name, feature_code, fields=[...], process_stages=[...], parent_menu_id=...)`\n"
            "    用户说『加一个借书申请表单, 字段X/Y/Z, 走管理员审批』走这个 (见下『SPEC 驱动加新表单』).\n"
            "  - **创建/修改表单流程** → `set_apaas_app_process(env_id, apaas_app_id, menu_id,\n"
            "    process_name, process_code, stages=[...])` 或 `process_definition={nodes:[...],edges:[...]}`\n"
            "    示例: 借阅记录加管理员审核流程 → list_apaas_app_menus 拿 menu_id (form_id 不空那行)\n"
            "    → list_apaas_app_roles 拿 R_ADMIN 的 roleCode → set_apaas_app_process(menu_id=...,\n"
            "    process_name=\"借阅审批\", process_code=\"borrow_approval\",\n"
            "    stages=[{name:\"管理员审批\",approver_type:\"ROLE\",approver_code:\"R_ADMIN\"}])\n"
            "    条件分支/并行流程不要说工具不支持；传完整 process_definition：节点 type 可用 start/end/\n"
            "    assignee_approval/role_approval/condition(兼容 exclusive_gateway)/multi_branch/parallel_gateway/merge，edges 上用\n"
            "    condition 表达字段条件，例如 `vuln_category == 'info_disclosure'`。\n"
            "  - 加字段必填 → update_apaas_form_component (不是 browser_click)\n"
            "  - 加角色 → create_apaas_app_roles\n"
            "  - 加字典选项 → add_apaas_dict_option\n"
            "  - 加菜单 (关联已有表单) → create_apaas_form_menu / create_apaas_self_dev_menu\n"
            "  - 业务事件 → create_apaas_value_change_assignment_event / create_form_event_with_python_code\n"
            "  - 字段权限 → set_apaas_form_permissions\n"
            "**铁律**: 用户说『加新表单』/『加新功能』/『加流程』/『加审批』/『字段必填』/『加角色』等明确\n"
            "意图时, **先扫 MCP 工具列表找现成 wrapper, 找到就直接调**, 不要先 browser_snapshot 看页面,\n"
            "不要劝用户『演示一下』. 没现成 wrapper 才 fallback browser_* 或 demonstration.\n\n"

            "## ⭐ SPEC 驱动加新表单 (用户最高频场景)\n"
            "当用户说『加一个 XX 表单』/『加一个 XX 功能』/『新增 XX 模块』时, 走 2 阶段流程:\n\n"
            "**阶段 1: 生成 SPEC 给用户审核 (不调工具, 只回复)**\n"
            "  - 先调 list_apaas_app_models / list_apaas_app_roles 扫已有上下文 (避免编码冲突)\n"
            "  - 给用户出**简洁 SPEC** (markdown 即可, 不要塞一堆 XML 标签). 必含:\n"
            "    - 表单名 + feature_code (snake_case, 譬如 `borrow_apply`, 避开已有 modelCode). 表单名必须唯一且能说明用途, 不要只叫『表单/新增表单/测试表单』\n"
            "    - 字段表格: name / code / type / required / max_length / show_in_list / source\n"
            "    - source 必须写清数据来源: 固定枚举=字典选项; 业务对象=目标模型+显示字段; 人员/部门=系统用户/部门; 普通文本才留空\n"
            "    - (若用户提到审批) 流程节点: name / approver_type / approver_code\n"
            "    - 权限摘要: 哪些角色可新增/查看/编辑/删除/导出, 数据范围是本人/部门/全部\n"
            "  - 回复结尾问一句『按这个建吗？同意我就直接调工具一把建好』\n"
            "  - **此阶段不调 build_apaas_feature_from_spec, 也不调其他写工具**\n\n"
            "**阶段 2: 用户同意后执行 (一把调 build_apaas_feature_from_spec)**\n"
            "  - 用户回复『同意』/『建』/『可以』/『go』 → 立刻调 build_apaas_feature_from_spec\n"
            "  - feature_name = 表单中文名, feature_code = SPEC 里的 snake_case\n"
            "  - fields = SPEC 字段表格转 [{name, code, type, required, max_length, show_in_list}, ...]\n"
            "  - **业务对象选择字段** (客户/供应商/项目/产品/员工档案等) 不能用单行输入; 必须传 type='数据单选' 或 '数据选择' + ref:\n"
            "    {name:'客户', code:'customer_id', type:'数据单选', ref:{model:'customer_profile', field:'customer_name'}}\n"
            "    ref.model 必须来自 list_apaas_app_models 中已有模型或本次 SPEC 确认要新建的模型; 缺 ref 时不要执行创建, 先让用户补目标对象.\n"
            "  - **字典绑定字段** (type='下拉单选'/'下拉多选'/'单选框'/'复选框') 必须传 dict_options:\n"
            "    {name:'申请状态', code:'apply_status', type:'下拉单选', required:true,\n"
            "     dict_code:'borrow_apply_status', dict_name:'借书申请状态',\n"
            "     dict_options:[{name:'待提交',code:'draft'},{name:'待审批',code:'pending'},...]}\n"
            "    工具会自动建字典 + 字段组件绑定 (数据来源=数据字典, 不是输入值)\n"
            "  - 申请人/负责人/经办人/审批人用 type='人员选择'; 申请部门/归属部门用 type='部门选择'.\n"
            "  - process_stages = SPEC 里流程节点 (没流程就传 None / 不传)\n"
            "  - 工具会自动: 建字典 → 建模型 → 建表单 (含菜单) → 移分组 → 配流程\n"
            "  - 返成功后回复 ID 列表 + iframe + sidebar 自动刷新\n\n"
            "**为啥要 2 阶段**: 用户要审 SPEC + 改 SPEC, 不能 AI 拍脑袋直接建. 这是 super-agents-dev\n"
            "实证过的 AIAssistantService.formDesign 流程, 用户接受度最高.\n"
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
                _tc_start = time.monotonic()

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
                # 完整结果（放开 200 截断，供可展开工具卡的「输出」；截 4000 防超长/base64 爆）
                result_full = result_text[:4000] + ("..." if len(result_text) > 4000 else "")
                if image_data_url:
                    result_full = "(已截图，渲染在会话面板内)"
                trace_item = {
                    "tool_name": tool_name, "args": tc_args,
                    "ok": ok_flag, "summary": summary,
                    "result": result_full,
                    "duration_ms": int((time.monotonic() - _tc_start) * 1000),
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

        # 2026-05-24 落 assistant 消息 — 在 yield done 前先入库，保证前端拉历史时 reply
        # 跟当时 SSE 看到的一致。tool_trace_json 可能含 image_data_url，存 JSON 列即可（MySQL
        # JSON 类型最大 1GB，单图 ~30-50KB 没问题，多图也撑得住）。
        if config_session is not None:
            try:
                db.add(ConfigChatMessage(
                    session_id=config_session.id,
                    role="assistant",
                    content=reply,
                    tool_trace_json=tool_trace if tool_trace else None,
                    change_plan_json=change_plan,
                    actions_summary_json=actions_summary if actions_summary else None,
                ))
                config_session.updated_at = datetime.utcnow()
                await db.commit()
            except Exception as exc:
                log.warning("config_chat_stream: persist assistant message failed: %r", exc)

        yield _sse("done", {
            "reply": reply,
            "change_plan": change_plan,
            "requires_confirmation": bool(change_plan),
            "actions_summary": actions_summary,
            "tool_trace": tool_trace,
            # 2026-05-24: done 事件也带 session_id, 前端可以二次确认
            "session_id": config_session.id if config_session else None,
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


# ─────────────────────── Phase 3d · Browser viewport mini preview MJPEG 流 ───────────────────────
# 2026-05-21 用户反馈: agent 操作时用户不知道 agent 在看哪 / 干啥, 要切到其他 tab 看.
# 终极方案: ConfigAssistantPanel 内嵌 <img src=".../browser-stream"> 浏览器原生 MJPEG 解码,
# 显示 agent 操作的浏览器画面实时回放, 用户在配置助手原地看 agent.
#
# 数据流: ExtensionRouter.call("capture_frame_jpeg") 每 500ms 拿 frame → multipart/x-mixed-replace
# 浏览器收到自动播放. 单帧 ~30-50KB, 2fps = ~60-100KB/s 流量.
#
# 生命周期: stream 在 client 连接时启动, client 断开 (img tag unmount / page close) 时停.
# extension 没装时返 503.

async def _mjpeg_frame_generator(app_id: int, fps: float = 2.0):
    """每 1/fps 秒调 extension 拿一帧 jpeg, 包成 multipart frame yield."""
    import base64 as _b64
    from app.routes.browser_ext_ws import ext_router

    boundary = b"--apaas-frame"
    interval = 1.0 / max(fps, 0.5)
    last_send = 0.0
    placeholder_sent = False

    while True:
        now = asyncio.get_event_loop().time()
        sleep_for = max(0.0, interval - (now - last_send))
        if sleep_for > 0:
            await asyncio.sleep(sleep_for)
        last_send = asyncio.get_event_loop().time()

        if not ext_router.is_connected:
            if not placeholder_sent:
                # 一次性 placeholder 文字图片 (1×1 png) 通知 client 扩展未连
                empty_png = _b64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABAQMAAAAl21bKAAAAA1BMVEX///+nxBvIAAAAAXRSTlMAQObYZgAAAApJREFUCNdjYAAAAAIAAeIhvDMAAAAASUVORK5CYII=")
                yield boundary + b"\r\nContent-Type: image/png\r\nContent-Length: " + str(len(empty_png)).encode() + b"\r\n\r\n" + empty_png + b"\r\n"
                placeholder_sent = True
            continue

        try:
            result = await ext_router.call("capture_frame_jpeg", {"quality": 60}, timeout=5.0)
        except Exception:
            continue
        if not result.get("ok"):
            continue
        data_url = (result.get("result") or {}).get("image_data_url") or ""
        if not data_url.startswith("data:image/jpeg;base64,"):
            continue
        try:
            frame_bytes = _b64.b64decode(data_url[len("data:image/jpeg;base64,"):])
        except Exception:
            continue
        yield boundary + b"\r\nContent-Type: image/jpeg\r\nContent-Length: " + str(len(frame_bytes)).encode() + b"\r\n\r\n" + frame_bytes + b"\r\n"
        placeholder_sent = False


@router.get("/{app_id}/browser-stream")
async def browser_viewport_stream(
    app_id: int,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """MJPEG 流 endpoint — ConfigAssistantPanel <img src> 直接消费.

    Browser 原生支持 multipart/x-mixed-replace, 自动播放每帧 jpeg.
    扩展未连时返一帧 1×1 transparent png placeholder + 继续等扩展上线.
    """
    from fastapi.responses import StreamingResponse
    # 简单 auth check: 应用存在 + 用户能看
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

    return StreamingResponse(
        _mjpeg_frame_generator(app_id, fps=2.0),
        media_type="multipart/x-mixed-replace; boundary=apaas-frame",
        headers={
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Pragma": "no-cache",
            "X-Accel-Buffering": "no",  # nginx 不要 buffer
        },
    )


# ────────────────────── ChatPage 原生 AppMenuSidebar 用 ──────────────────────
# 2026-05-25: 不再走 ConfigChat agent (MCP loop), 直接给前端 sidebar 拉真实菜单.
# 走 platform list_apaas_app_menus, 返结构含 menu_id / menu_name / menu_type /
# form_id / icon / 父子嵌套 (isGroup + children).
# 前端 AppMenuSidebar.vue 渲染后点菜单 → 切 platform-proxy entry iframe 的 src
# 带上 menu_id/form_id/menu_type → 后端 _build_menu_redirect_path 算出对应表单
# 编辑器 URL.

@router.get("/{app_id}/apaas-menus")
async def get_application_apaas_menus(
    app_id: int,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """拉应用在 aPaaS 平台上的真实菜单列表 — ChatPage 原生 sidebar 用.

    返回:
      {
        ok: true,
        env_id: 11,
        apaas_app_id: "846351551214649344",
        menus: [{
          menu_id, menu_name, menu_type, form_id, form_code, icon, depth,
          is_group, parent_menu_id, children?: [...]  # 嵌套
        }, ...]
      }
    """
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

    if not app.apaas_app_id:
        return {"ok": False, "error_code": "APP_NOT_DEPLOYED",
                "message": "应用尚未部署到平台"}

    # 2026-05-25: 直接调 client.query_menus (manageAppMenu) 拿管理视图 — 含 GROUP
    # 跟 process workflow menus. mcp 的 list_apaas_app_menus 走 allAppMenu (runtime
    # 视图, 过滤了 GROUP) 不适合 sidebar 用.
    # 线上环境绑定来自 backend.env / Secret，不再依赖 applications.platform_env_id
    # 反查 platform_envs。旧 app 里残留的 platform_env_id 只作为诊断信息返回。
    try:
        base_url, tenant_id, token, credential_source = await _resolve_apaas_call_context(db, ctx)
        if not base_url or not tenant_id:
            return {
                "ok": False,
                "error_code": "APAAS_CONTEXT_MISSING",
                "message": "未获取到当前环境地址或当前租户绑定的 aPaaS 租户，无法拉取菜单",
                "env_id": app.platform_env_id,
                "tenant_id": ctx.tenant_id,
                "apaas_app_id": app.apaas_app_id,
            }
        if not token:
            return {
                "ok": False,
                "error_code": "CONFIG_ENV_TOKEN_MISSING",
                "message": "当前登录用户没有可用的 aPaaS token，请重新登录",
                "env_id": app.platform_env_id,
                "apaas_app_id": app.apaas_app_id,
            }
        logger.info(
            "应用 %s 按当前租户拉菜单 base_url=%s tenant_id=%s credential_source=%s stale_platform_env_id=%s",
            app.id, base_url, tenant_id, credential_source, app.platform_env_id,
        )
        client = APaaSClient(base_url=base_url, tenant_id=tenant_id, token=token)
        raw_menus_nested = await client.query_menus(app.apaas_app_id)
        if not raw_menus_nested:
            logger.info(
                "应用 %s manageAppMenu 返回空，fallback allAppMenu app_id=%s",
                app.id, app.apaas_app_id,
            )
            fallback = await client.query_all_app_menus(app.apaas_app_id)
            if isinstance(fallback, dict):
                raw_menus_nested = fallback.get("menus") or fallback.get("data") or fallback.get("items") or []
            elif isinstance(fallback, list):
                raw_menus_nested = fallback
        if not raw_menus_nested:
            logger.info(
                "应用 %s allAppMenu 仍为空，fallback queryAllFormMenu app_id=%s",
                app.id, app.apaas_app_id,
            )
            raw_menus_nested = await client.list_form_menus_for_event(app.apaas_app_id)
    except Exception as exc:
        return {
            "ok": False, "error_code": "APAAS_FETCH_FAILED",
            "message": f"拉取菜单失败: {exc}",
            "env_id": app.platform_env_id,
            "tenant_id": ctx.tenant_id,
            "apaas_tenant_id": tenant_id,
            "apaas_app_id": app.apaas_app_id,
        }

    # 平台返嵌套 (submenus 字段), 打平后给后续 normalize + tree-build 复用.
    def _flat_with_parent(nodes: list, parent_id: str = ""):
        out: list = []
        for n in nodes or []:
            if not isinstance(n, dict):
                continue
            # 注 platform 嵌套返结构里 submenus 已经是 dict 数组
            n_with_parent = {**n, "parentId": parent_id or n.get("parentId")}
            out.append(n_with_parent)
            kids = n.get("submenus") or n.get("children") or []
            cur_id = str(n.get("id") or n.get("menuId") or "")
            if kids and cur_id:
                out.extend(_flat_with_parent(kids, cur_id))
        return out

    menus_raw = _flat_with_parent(raw_menus_nested or [])

    # 兜底: 若空, 把 raw 当作单 list (老 API 返 array 不带 submenus 的情况)
    if not menus_raw and isinstance(raw_menus_nested, dict):
        menus_raw = raw_menus_nested.get("menus") or raw_menus_nested.get("data") or []

    def _normalize_menu(m: dict) -> dict:
        # 平台字段名可能是 camelCase / snake_case 混合, 都接住
        mtype = m.get("menu_type") or m.get("menuType") or ""
        return {
            "menu_id": str(m.get("menu_id") or m.get("menuId") or m.get("id") or ""),
            "menu_name": m.get("menu_name") or m.get("menuName") or m.get("name") or "",
            "menu_type": mtype,
            "menu_display": m.get("menu_display") or m.get("menuDisplay") or "",
            "form_id": str(m.get("form_id") or m.get("formId") or "") or None,
            "form_code": m.get("form_code") or m.get("formCode") or None,
            "icon": m.get("icon") or m.get("menu_icon") or m.get("menuIcon") or "",
            "depth": m.get("depth") or m.get("level") or 0,
            "path": m.get("path") or "",
            "parent_menu_id": str(m.get("parent_menu_id") or m.get("parentMenuId") or m.get("parentId") or m.get("pid") or "") or None,
            # menuType=GROUP 自动判为 group; 也兼容 is_group / isGroup 显式标记
            "is_group": bool(m.get("is_group") or m.get("isGroup")
                              or str(mtype).upper() == "GROUP"),
            "dashboard_id": str(m.get("dashboard_id") or m.get("dashboardId") or "") or None,
            "link_url": m.get("link_url") or m.get("linkUrl") or None,
            "sort_order": m.get("sort_order") or m.get("sortOrder")
                          or m.get("menuOrder") or 0,
        }

    # 2026-05-25: 过滤掉平台自动注入的系统菜单 (流程待办 / 我发起的 / 流程授权 etc)
    # 这些是 runtime 用户看的, 不是 AI Builder 配置目标. 用户/AI 不需要在 sidebar 看到.
    # 2026-06-05: 加 TASK_CENTER（异步任务管理）—— 平台自动注入的系统菜单, 不是配置目标。
    _SYSTEM_AUTO_MENU_TYPES = {
        "TODO", "TO_CHECK", "MY_SUBMIT", "MY_PARTICIPATE",
        "TODO_MANAGE", "PROC_AUTH", "PROC_FORWARD", "TASK_CENTER",
    }
    flat_all = [_normalize_menu(m) for m in menus_raw if isinstance(m, dict)]
    # 哪些分组在原始数据里本来有子菜单 —— 用于下面只剔「被系统过滤掏空」的分组,
    # 不误伤用户刚建、本来就空的分组。
    _parents_with_children = {m["parent_menu_id"] for m in flat_all if m.get("parent_menu_id")}
    flat = [m for m in flat_all if m["menu_type"].upper() not in _SYSTEM_AUTO_MENU_TYPES]

    # 嵌套 — 按 parent_menu_id 构 tree (无 parent 的放根)
    by_id: dict[str, dict] = {m["menu_id"]: {**m, "children": []} for m in flat if m["menu_id"]}
    roots: list[dict] = []
    for m in by_id.values():
        pid = m.get("parent_menu_id")
        if pid and pid in by_id:
            by_id[pid]["children"].append(m)
        else:
            roots.append(m)
    # 同层按 sort_order 排
    def _sort(items: list[dict]) -> None:
        items.sort(key=lambda x: (int(x.get("sort_order") or 0), x.get("menu_name") or ""))
        for it in items:
            if it.get("children"):
                _sort(it["children"])
    _sort(roots)

    # 剔掉「被系统菜单过滤掏空」的分组(如只装了 异步任务管理 的「系统管理」组)。
    # 只剔本来有子菜单、过滤后变空的分组; 用户新建的本来就空的分组保留(不在 _parents_with_children)。
    def _prune_emptied_groups(items: list[dict]) -> list[dict]:
        out: list[dict] = []
        for it in items:
            it["children"] = _prune_emptied_groups(it.get("children") or [])
            if it.get("is_group") and not it["children"] and it["menu_id"] in _parents_with_children:
                continue
            out.append(it)
        return out
    roots = _prune_emptied_groups(roots)

    return {
        "ok": True,
        "env_id": app.platform_env_id,
        "tenant_id": ctx.tenant_id,
        "apaas_tenant_id": tenant_id,
        "apaas_app_id": app.apaas_app_id,
        "menus": roots,
        "flat_count": len(flat),
    }


# 2026-05-25 续: ChatPage AppMenuSidebar 用户主动操作 menus 的 endpoint.
# Pinia store 调 backend, backend 复用 mcp_server 的 _call_apaas_platform_tool 走平台.

class _CreateMenuGroupReq(BaseModel):
    group_name: str
    menu_order: int = 0
    parent_id: str = ""


@router.post("/{app_id}/apaas-menu-group")
async def create_apaas_menu_group(
    app_id: int,
    payload: _CreateMenuGroupReq,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """sidebar 新建菜单分组 — 创建 menuType=GROUP 的菜单."""
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

    if not app.platform_env_id or not app.apaas_app_id:
        return {"ok": False, "error_code": "APP_NOT_DEPLOYED",
                "message": "应用未部署到平台"}

    name = payload.group_name.strip()
    if not name:
        return {"ok": False, "error_code": "INVALID_NAME", "message": "分组名必填"}

    # WRITE 类工具不在 _call_apaas_platform_tool 的 executor 字典里, 直接调 mcp tool fn
    from app.mcp_server import create_apaas_menu_group as _mcp_create_group  # type: ignore
    return await _mcp_create_group(
        env_id=app.platform_env_id,
        apaas_app_id=app.apaas_app_id,
        group_name=name,
        menu_order=payload.menu_order,
        parent_id=payload.parent_id,
    )


class _SetMenuParentReq(BaseModel):
    menu_id: str
    parent_id: str = ""  # "" = 移到根
    menu_order: int = 0


@router.post("/{app_id}/apaas-menu-set-parent")
async def set_apaas_menu_parent(
    app_id: int,
    payload: _SetMenuParentReq,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """sidebar 把菜单挂到分组下 / 移出回根级."""
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

    if not app.platform_env_id or not app.apaas_app_id:
        return {"ok": False, "error_code": "APP_NOT_DEPLOYED",
                "message": "应用未部署到平台"}
    if not payload.menu_id.strip():
        return {"ok": False, "error_code": "INVALID_PARAMS", "message": "menu_id 必填"}

    from app.mcp_server import set_apaas_menu_parent as _mcp_set_parent  # type: ignore
    return await _mcp_set_parent(
        env_id=app.platform_env_id,
        apaas_app_id=app.apaas_app_id,
        menu_id=payload.menu_id.strip(),
        parent_id=payload.parent_id,
        menu_order=payload.menu_order,
    )


class _DeleteMenuReq(BaseModel):
    menu_id: str
    menu_name: str = ""


@router.post("/{app_id}/apaas-menu-delete")
async def delete_apaas_menu(
    app_id: int,
    payload: _DeleteMenuReq,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """sidebar 删除菜单 — 普通菜单 / 表单菜单 / GROUP 分组 都用这个.

    平台 /xdap-app/menu/delete/menu 通用. 删表单菜单会联动删表单本身.
    删 GROUP 时前端应保证里面没子菜单 (否则平台行为是 cascade 还是 reject 没探过,
    前端 UI 拦一道安全).
    """
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

    if not app.platform_env_id or not app.apaas_app_id:
        return {"ok": False, "error_code": "APP_NOT_DEPLOYED",
                "message": "应用未部署到平台"}
    if not payload.menu_id.strip():
        return {"ok": False, "error_code": "INVALID_PARAMS", "message": "menu_id 必填"}

    from app.mcp_server import delete_apaas_app_menu as _mcp_delete_menu  # type: ignore
    return await _mcp_delete_menu(
        env_id=app.platform_env_id,
        apaas_app_id=app.apaas_app_id,
        menu_id=payload.menu_id.strip(),
        menu_name=payload.menu_name,
    )


# ───── 应用基本信息编辑（PR3, SPEC v2 §2 顶部 CTA）─────


class _UpdateApaasAppInfoReq(BaseModel):
    # 2026-05-26 (PR3 reviewer P1 #3): pydantic max_length 统一前后端校验.
    # app_name 上限跟前端 el-input maxlength=64 + saveAppInfo guard 对齐.
    # description 200 跟前端 textarea maxlength=200 对齐.
    # icon_svg 50KB 防超大 SVG 撑爆 payload (实际 svg 通常 <5KB).
    app_name: str = Field(default="", max_length=64)
    description: str = Field(default="", max_length=200)
    icon_svg: str = Field(default="", max_length=50_000)


@router.post("/{app_id}/update-apaas-info")
async def update_apaas_app_info_route(
    app_id: int,
    payload: _UpdateApaasAppInfoReq,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """改应用基本信息 (名称 / 描述 / 图标), 内部包装 `update_apaas_app_info` MCP 工具.

    ChatPage 顶部 breadcrumb 点应用名 → 弹小窗 → 保存调本接口. 跟 apaas-menu-delete
    一样的模式: 鉴权 + 应用存在性检查 + 透传到 mcp_server tool.

    保存成功后前端会刷新 builderAppDisplayName.
    """
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

    if not app.platform_env_id or not app.apaas_app_id:
        return {
            "ok": False, "error_code": "APP_NOT_DEPLOYED",
            "message": "应用未部署到平台，请先部署后再编辑应用信息",
        }

    has_any = any(v.strip() for v in (payload.app_name, payload.description, payload.icon_svg))
    if not has_any:
        return {
            "ok": False, "error_code": "INVALID_PARAMS",
            "message": "app_name / description / icon_svg 至少传一个非空字段",
        }

    from app.mcp_server import update_apaas_app_info as _mcp_update_app_info  # type: ignore
    mcp_result = await _mcp_update_app_info(
        env_id=app.platform_env_id,
        apaas_app_id=app.apaas_app_id,
        app_name=payload.app_name,
        description=payload.description,
        icon_svg=payload.icon_svg,
    )

    # 平台改名成功 → 同步回 backend Application.app_name + description (UI 即时刷新源头)
    # 2026-05-26 (PR3 reviewer P1 #2): commit 失败时不再 raise 500 — 平台已改好但本地
    # DB 没改, 应该告知客户端 partial_success 让 UI 提示\"已存到平台, 本地缓存稍后同步\"
    # 而不是误以为整体失败.
    if mcp_result.get("ok"):
        touched = False
        if payload.app_name.strip():
            app.app_name = payload.app_name.strip()
            touched = True
        if payload.description.strip():
            app.description = payload.description.strip()
            touched = True
        if payload.icon_svg.strip():
            app.icon_svg = payload.icon_svg.strip()
            touched = True
        if touched:
            try:
                await db.commit()
                await db.refresh(app)
                mcp_result["app_id"] = app.id
                mcp_result["synced_local_name"] = app.app_name
            except Exception as exc:
                logging.getLogger(__name__).warning(
                    "update_apaas_app_info_route DB commit 失败 (平台已改) app_id=%s: %r",
                    app_id, exc,
                )
                try:
                    await db.rollback()
                except Exception:
                    pass
                # 平台已改, 本地未同步 — UI 应显示"平台已更新, 下次刷新页面看到"提示
                mcp_result["partial_success"] = True
                mcp_result["db_sync_failed"] = True
                mcp_result["db_sync_error"] = str(exc)[:200]

    return mcp_result
