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


def _extract_apaas_app_version(app_detail: dict) -> str:
    for key in ("currentVersion", "appVersion", "version"):
        value = app_detail.get(key) if isinstance(app_detail, dict) else None
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""


def _bump_patch_version(version: str, fallback: str = "1.0.1") -> str:
    clean = str(version or "").strip().lstrip("vV")
    if not clean:
        return fallback
    try:
        parts = [int(part) for part in clean.split(".")]
        if not parts:
            return fallback
        parts[-1] += 1
        return ".".join(str(part) for part in parts)
    except Exception:
        return fallback


def _is_apaas_version_error(error: Exception | str) -> bool:
    text = str(error)
    return "版本" in text or "version" in text.lower()


async def _deploy_apaas_app_with_version_retry(
    client: APaaSClient,
    apaas_app_id: str,
    first_version: str,
    abstract: str,
) -> tuple[str, list[dict]]:
    events: list[dict] = []
    try:
        await client.deploy_app(apaas_app_id, first_version, abstract=abstract)
        return first_version, events
    except Exception as first_error:
        if not _is_apaas_version_error(first_error):
            raise

        remote_detail = await client.query_app_detail(apaas_app_id)
        remote_version = _extract_apaas_app_version(remote_detail)
        retry_base = remote_version or first_version
        retry_version = _bump_patch_version(retry_base)
        if retry_version == first_version:
            retry_version = _bump_patch_version(first_version)
        if retry_version == first_version:
            raise first_error

        events.append({
            "type": "publish",
            "status": "version_retry",
            "from": first_version,
            "to": retry_version,
            "remote_version": remote_version,
            "error": str(first_error)[:300],
        })
        await client.deploy_app(apaas_app_id, retry_version, abstract=abstract)
        return retry_version, events


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
        current_version = _extract_apaas_app_version(app_detail)
        next_version = _bump_patch_version(current_version) if current_version else "1.0.0"
        access_event = {"type": "app_access", "object_type": "ALL", "status": "skipped"}
        try:
            await client.save_app_access(str(app.apaas_app_id), object_type="ALL", object_ids=[])
            access_event["status"] = "success"
        except Exception as access_error:
            logger.warning("publish_application: app access save failed app_id=%s apaas_app_id=%s: %s", app_id, app.apaas_app_id, access_error)
            access_event = {"type": "app_access", "object_type": "ALL", "status": "failed", "error": str(access_error)}
        published_version, retry_events = await _deploy_apaas_app_with_version_retry(
            client, str(app.apaas_app_id), next_version, APP_DEPLOY_ABSTRACT
        )
        app.status = "completed"
        await db.commit()
        await complete_deploy_record(
            db, record, app, success=True, version_label=published_version,
            event_log=[
                access_event,
                *retry_events,
                {"type": "publish", "version": published_version, "status": "success"},
            ],
        )
        return {"ok": True, "version": published_version, "remote_status": "ENABLE", "deploy_record_id": record.id}
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
                    current_version = _extract_apaas_app_version(app_detail)
                    next_version = _bump_patch_version(current_version) if current_version else "1.0.0"
                    access_event = {"type": "app_access", "object_type": "ALL", "status": "skipped"}
                    try:
                        await client.save_app_access(str(app.apaas_app_id), object_type="ALL", object_ids=[])
                        access_event["status"] = "success"
                    except Exception as access_error:
                        logger.warning("publish_application retry: app access save failed app_id=%s apaas_app_id=%s: %s", app_id, app.apaas_app_id, access_error)
                        access_event = {"type": "app_access", "object_type": "ALL", "status": "failed", "error": str(access_error)}
                    published_version, retry_events = await _deploy_apaas_app_with_version_retry(
                        client, str(app.apaas_app_id), next_version, APP_DEPLOY_ABSTRACT
                    )
                    app.status = "completed"
                    await db.commit()
                    await complete_deploy_record(
                        db, record, app, success=True, version_label=published_version,
                        event_log=[
                            {"type": "publish", "status": "token_refresh"},
                            access_event,
                            *retry_events,
                            {"type": "publish", "version": published_version, "status": "success"},
                        ],
                    )
                    return {"ok": True, "version": published_version, "remote_status": "ENABLE", "deploy_record_id": record.id}
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


@router.post("/{application_id}/git-project/ensure")
async def ensure_application_git_project(
    application_id: int,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """确保老应用也有 Project，供 Project 级 Git/GitHub 连接复用。"""
    app = (await db.execute(
        select(Application).where(
            Application.id == application_id,
            Application.tenant_id == ctx.tenant_id,
        )
    )).scalar_one_or_none()
    if not app:
        raise HTTPException(404, "应用不存在")

    if app.project_id:
        await require_project_access(
            db,
            project_id=app.project_id,
            user_id=ctx.user.id,
            tenant_id=ctx.tenant_id,
            minimum_role="member",
        )
        return {"application_id": app.id, "project_id": app.project_id, "created": False}

    if app.user_id != ctx.user.id and app.created_by != ctx.user.id:
        raise HTTPException(403, "无权为该应用创建 Git 项目")

    project = Project(
        name=app.app_name or app.app_code or f"应用 {app.id}",
        description=f"应用「{app.app_name or app.app_code or app.id}」的 Git/GitHub 集成项目",
        user_id=ctx.user.id,
        tenant_id=ctx.tenant_id,
    )
    db.add(project)
    await db.flush()
    db.add(ProjectMember(project_id=project.id, user_id=ctx.user.id, role="owner"))
    app.project_id = project.id
    await db.commit()
    await db.refresh(app)
    return {"application_id": app.id, "project_id": app.project_id, "created": True}


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
