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
from app.models import User, Application, DocumentVersion, ChangePlan, ApiCallLog, PlatformEnv, Conversation, ConfigSnapshot, Tenant, APaaSUserCredential
from app.auth import get_current_user
from app.schemas import ApplicationCreate, ApplicationPageResponse, ApplicationResponse, MergedAppResponse
from app.deps import get_auth_context, AuthContext, resolve_effective_tenant_id
from app.permissions import check_resource_permission, Action
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

from ._helpers import *  # noqa: F401,F403
from . import _helpers  # noqa: F401

router = APIRouter()
logger = logging.getLogger(__name__)

_APPLICATION_TYPES = {"low-code", "ai-code"}


def _normalize_application_type(value: str | None) -> str | None:
    normalized = str(value or "").strip()
    if not normalized or normalized == "all":
        return None
    if normalized not in _APPLICATION_TYPES:
        raise HTTPException(status_code=400, detail="app_type 必须是 low-code 或 ai-code")
    return normalized

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
    tenant_id = await resolve_effective_tenant_id(db, ctx)
    if not tenant_id:
        return ""
    result = await db.execute(
        select(Tenant.apaas_tenant_id_str).where(Tenant.id == tenant_id)
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
    effective_tenant_id = await resolve_effective_tenant_id(db, ctx)
    bound_tenant_id = await _resolve_current_apaas_tenant_id(db, ctx)

    env_result = await db.execute(
        select(PlatformEnv)
        .where(PlatformEnv.tenant_id == effective_tenant_id)
        .where(PlatformEnv.status == "connected")
        .order_by(desc(PlatformEnv.is_default), desc(PlatformEnv.updated_at), desc(PlatformEnv.id))
        .limit(1)
    )
    env = env_result.scalar_one_or_none()
    if env and (env.token or "").strip():
        return (
            (env.base_url or settings.apaas_base_url or "").rstrip("/"),
            (env.platform_tenant_id or bound_tenant_id or "").strip(),
            (env.token or "").strip(),
            f"platform_env:{env.id}",
        )

    cred_result = await db.execute(
        select(APaaSUserCredential)
        .where(APaaSUserCredential.user_id == ctx.user.id)
        .where(APaaSUserCredential.local_tenant_id == effective_tenant_id)
        .where(APaaSUserCredential.status == "connected")
        .order_by(desc(APaaSUserCredential.last_login_at), desc(APaaSUserCredential.updated_at), desc(APaaSUserCredential.id))
        .limit(1)
    )
    cred = cred_result.scalar_one_or_none()
    if cred and (cred.token or "").strip():
        return (
            (cred.base_url or settings.apaas_base_url or "").rstrip("/"),
            (cred.apaas_tenant_id or bound_tenant_id or "").strip(),
            (cred.token or "").strip(),
            f"user_credential:{cred.id}",
        )

    return (
        (ctx.user.apaas_base_url or settings.apaas_base_url or "").rstrip("/"),
        (bound_tenant_id or ctx.apaas_tenant_id or ctx.user.apaas_tenant_id or "").strip(),
        (ctx.user.apaas_token or "").strip(),
        "user_legacy",
    )


async def _list_remote_apps_for_current_builder_tenant(
    db: AsyncSession,
    ctx: AuthContext,
) -> tuple[list, str | None, str | None]:
    """List remote low-code apps through the current local tenant binding."""
    effective_tenant_id = await resolve_effective_tenant_id(db, ctx)
    env = await _resolve_platform_env_for_tenant(db, effective_tenant_id)
    if env:
        # Do not use the user's legacy token as a cross-tenant fallback. The
        # selected PlatformEnv owns the aPaaS tenant context for this request.
        token = (env.token or "").strip()
        if not token and not (env.username and env.password_enc):
            return [], env.base_url, env.platform_tenant_id
        client = APaaSClient(base_url=env.base_url, tenant_id=env.platform_tenant_id, token=token)
        try:
            if not token and env.username and env.password_enc:
                login_result = await client.login(env.username, decrypt_password(env.password_enc))
                env.token = (login_result.get("token") or "").strip()
                env.status = "connected"
                await db.commit()
                client = APaaSClient(base_url=env.base_url, tenant_id=env.platform_tenant_id, token=env.token)
            return await client.query_app_list(), env.base_url, env.platform_tenant_id
        except Exception:
            if env.username and env.password_enc:
                try:
                    login_result = await client.login(env.username, decrypt_password(env.password_enc))
                    env.token = (login_result.get("token") or "").strip()
                    env.status = "connected"
                    await db.commit()
                    client = APaaSClient(base_url=env.base_url, tenant_id=env.platform_tenant_id, token=env.token)
                    return await client.query_app_list(), env.base_url, env.platform_tenant_id
                except Exception as relogin_error:
                    raise relogin_error
            raise

    base_url, tenant_id, token, _source = await _resolve_apaas_call_context(db, ctx)
    if not base_url or not tenant_id or not token:
        return [], base_url or None, tenant_id or None
    client = APaaSClient(base_url=base_url, tenant_id=tenant_id, token=token)
    return await client.query_app_list(), base_url, tenant_id


def _apply_application_list_filters(stmt, ctx: AuthContext, team_scope: str | None, source_filter: str | None, stage: str | None = None):
    stmt = stmt.where(Application.tenant_id == ctx.tenant_id)
    if team_scope and team_scope.isdigit():
        stmt = stmt.where(Application.team_id == int(team_scope))

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
    return {
        Action.VIEW: True,
        Action.EDIT: True,
        Action.DELETE: True,
        Action.CLONE: True,
        "publish": True,
        "can_manage_members": True,
        "can_manage_member_roles": True,
        "access_role": "tenant",
    }


async def _require_application_permission(
    ctx: AuthContext,
    db: AsyncSession,
    app: Application,
    action: str,
) -> dict[str, bool]:
    return await _get_application_permissions(ctx, db, app)




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
    # 先用租户约束取轻量候选，再在 Python 里做归一化相似匹配。
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


async def list_applications(
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
    team_scope: Optional[str] = Query(None),
    include_remote: bool = Query(True),
    source_filter: Optional[str] = Query(None),  # local / remote / linked
    include_config: bool = Query(True),  # False → 省掉沉重的 config_preview blob（计数仍保留）
    app_type: Optional[str] = Query(None),  # low-code / ai-code / all
):
    """获取应用列表（本地 + 得帆云平台合并）"""
    effective_tenant_id = await resolve_effective_tenant_id(db, ctx)
    requested_app_type = _normalize_application_type(app_type)
    # 1. 查本地应用
    query = select(Application).where(Application.tenant_id == effective_tenant_id)
    if requested_app_type:
        query = query.where(Application.app_type == requested_app_type)
    if team_scope and team_scope.isdigit():
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
            select(PlatformEnv).where(PlatformEnv.tenant_id == effective_tenant_id)
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
    if include_remote and requested_app_type != "ai-code" and source_filter != "local":
        try:
            remote_apps, remote_base_url, remote_tenant_id = await _list_remote_apps_for_current_builder_tenant(db, ctx)
            env_base_url = remote_base_url or env_base_url
            env_tenant_id = remote_tenant_id or env_tenant_id
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
    if include_remote and requested_app_type != "ai-code" and source_filter != "local":
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

    app_type = _normalize_application_type(data.app_type) or "low-code"
    source_workspace_id = (data.source_workspace_id or "").strip() or None
    if app_type != "ai-code":
        source_workspace_id = None

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
        app_type=app_type,
        source_workspace_id=source_workspace_id,
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
    env_id: Optional[int] = None
    apaas_app_id: str


async def _resolve_import_apaas_context(
    db: AsyncSession,
    ctx: AuthContext,
    requested_env_id: int | None,
) -> tuple[PlatformEnv | None, str, str, str, str]:
    """Resolve the aPaaS context used by platform-app import.

    Import used to hard-require ``requested_env_id`` to be a PlatformEnv row in
    the current Builder tenant. The app list path already supports tenant/user
    aPaaS bindings, so a stale env id from the UI should not block import when
    the current tenant still has a valid default env or user credential.
    """
    effective_tenant_id = await resolve_effective_tenant_id(db, ctx)
    env = await _resolve_platform_env_for_tenant(db, effective_tenant_id, requested_env_id)
    if env:
        token = (env.token or "").strip()
        if token or (env.username and env.password_enc):
            return env, env.base_url, env.platform_tenant_id, token, f"platform_env:{env.id}"
        raise HTTPException(status_code=400, detail="当前平台环境 token 不可用，请在环境管理中重新登录")

    base_url, tenant_id, token, source = await _resolve_apaas_call_context(db, ctx)
    if not base_url or not tenant_id or not token:
        raise HTTPException(status_code=400, detail="当前用户平台 token 不可用，请重新登录")

    source_env = None
    if source.startswith("platform_env:"):
        try:
            source_env_id = int(source.split(":", 1)[1])
            source_env = (
                await db.execute(
                    select(PlatformEnv).where(
                        PlatformEnv.id == source_env_id,
                        PlatformEnv.tenant_id == effective_tenant_id,
                    )
                )
            ).scalar_one_or_none()
        except Exception:
            source_env = None
    elif env and str(env.platform_tenant_id or "").strip() == str(tenant_id or "").strip():
        source_env = env

    return source_env, base_url, tenant_id, token, source


async def _query_import_app_detail_with_fallbacks(
    db: AsyncSession,
    ctx: AuthContext,
    env: PlatformEnv | None,
    base_url: str,
    platform_tenant_id: str,
    token: str,
    credential_source: str,
    app_id: str,
) -> tuple[dict, str, APaaSClient]:
    """Query an app using the current binding, then other valid user tokens.

    A tenant environment token can expire independently of the user's current
    aPaaS session.  The list dialog and import action are separate requests, so
    the dialog may still render while the cached environment token has become
    unusable.  Do not replace a shared tenant token with a user credential;
    only use the latter as a request-local fallback.
    """
    candidates: list[tuple[str, str, str, str]] = [
        (base_url, platform_tenant_id, token, credential_source),
    ]

    env_relogin_attempted = False
    if env and env.username and env.password_enc and not token:
        env_relogin_attempted = True
        try:
            password = decrypt_password(env.password_enc)
            login_client = APaaSClient(
                base_url=env.base_url,
                tenant_id=env.platform_tenant_id,
            )
            login_result = await login_client.login(env.username, password)
            refreshed = (login_result.get("token") or "").strip()
            if refreshed:
                env.token = refreshed
                env.status = "connected"
                await db.commit()
                candidates.insert(
                    0,
                    (
                        env.base_url,
                        env.platform_tenant_id,
                        refreshed,
                        f"platform_env:{env.id}",
                    ),
                )
        except Exception:
            logger.info("import platform app: environment re-login failed", exc_info=True)

    effective_tenant_id = await resolve_effective_tenant_id(db, ctx)
    credential_result = await db.execute(
        select(APaaSUserCredential)
        .where(
            APaaSUserCredential.user_id == ctx.user.id,
            APaaSUserCredential.local_tenant_id == effective_tenant_id,
            APaaSUserCredential.status == "connected",
        )
        .order_by(
            desc(APaaSUserCredential.last_login_at),
            desc(APaaSUserCredential.updated_at),
            desc(APaaSUserCredential.id),
        )
        .limit(1)
    )
    credential = credential_result.scalar_one_or_none()
    if credential:
        credential_token = (credential.token or "").strip()
        credential_tenant_id = (credential.apaas_tenant_id or platform_tenant_id).strip()
        if credential_token and credential_tenant_id == platform_tenant_id:
            candidates.append(
                (
                    (credential.base_url or base_url).rstrip("/"),
                    credential_tenant_id,
                    credential_token,
                    f"user_credential:{credential.id}",
                )
            )
        if not credential_token and credential.password_enc:
            try:
                password = decrypt_password(credential.password_enc)
                login_client = APaaSClient(
                    base_url=(credential.base_url or base_url).rstrip("/"),
                    tenant_id=credential_tenant_id,
                )
                login_result = await login_client.login(credential.account, password)
                refreshed = (login_result.get("token") or "").strip()
                if refreshed:
                    credential.token = refreshed
                    credential.status = "connected"
                    await db.commit()
                    candidates.insert(
                        0,
                        (
                            (credential.base_url or base_url).rstrip("/"),
                            credential_tenant_id,
                            refreshed,
                            f"user_credential:{credential.id}",
                        ),
                    )
            except Exception:
                logger.info("import platform app: user credential re-login failed", exc_info=True)

    legacy_token = (getattr(ctx.user, "apaas_token", "") or "").strip()
    # User.apaas_token is a legacy, mutable field and may belong to another
    # aPaaS tenant. It is only safe when no tenant environment is selected.
    if not env and legacy_token and legacy_token != token:
        candidates.append(
            (
                (getattr(ctx.user, "apaas_base_url", "") or base_url).rstrip("/"),
                (getattr(ctx.user, "apaas_tenant_id", "") or platform_tenant_id).strip(),
                legacy_token,
                "user_legacy",
            )
        )

    seen: set[tuple[str, str, str]] = set()
    last_error: Exception | None = None
    for candidate_base_url, candidate_tenant_id, candidate_token, source in candidates:
        key = (candidate_base_url, candidate_tenant_id, candidate_token)
        if not candidate_token or key in seen:
            continue
        seen.add(key)
        try:
            client = APaaSClient(
                base_url=candidate_base_url,
                tenant_id=candidate_tenant_id,
                token=candidate_token,
            )
            detail = await client.query_app_detail(app_id)
            return detail, source, client
        except Exception as exc:
            last_error = exc
            if env and env.username and env.password_enc and not env_relogin_attempted:
                env_relogin_attempted = True
                try:
                    password = decrypt_password(env.password_enc)
                    login_client = APaaSClient(
                        base_url=env.base_url,
                        tenant_id=env.platform_tenant_id,
                    )
                    login_result = await login_client.login(env.username, password)
                    refreshed = (login_result.get("token") or "").strip()
                    if refreshed:
                        env.token = refreshed
                        env.status = "connected"
                        await db.commit()
                        candidates.append(
                            (
                                env.base_url,
                                env.platform_tenant_id,
                                refreshed,
                                f"platform_env:{env.id}",
                            )
                        )
                except Exception:
                    logger.info("import platform app: deferred environment re-login failed", exc_info=True)

    if last_error:
        raise last_error
    raise RuntimeError("no usable aPaaS token")


@router.post("/import-from-platform", response_model=ApplicationResponse)
async def import_from_platform(
    body: ImportFromPlatformRequest,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """从平台导入已有应用：拉取结构 → 生成 config_preview + markdown 需求文档"""
    from app.platform_sync import sync_from_platform_full
    from app.services.config_to_spec import config_to_markdown

    effective_tenant_id = await resolve_effective_tenant_id(db, ctx)

    # 1. 获取当前租户可用的 aPaaS 调用上下文。env_id 只作为优先项，避免新绑定链路
    # 已能列应用，但导入仍卡在旧 PlatformEnv.id 强校验上。
    env, base_url, platform_tenant_id, token, credential_source = await _resolve_import_apaas_context(
        db,
        ctx,
        body.env_id,
    )
    resolved_env_id = env.id if env else None

    # 2. 检查是否已导入
    existing = await db.execute(
        select(Application).where(
            Application.tenant_id == effective_tenant_id,
            Application.apaas_app_id == body.apaas_app_id,
        )
    )
    existing_app = existing.scalar_one_or_none()

    # 3. 获取应用信息；失败时在候选凭据之间回退。
    try:
        app_detail, credential_source, client = await _query_import_app_detail_with_fallbacks(
            db,
            ctx,
            env,
            base_url,
            platform_tenant_id,
            token,
            credential_source,
            body.apaas_app_id,
        )
    except Exception as exc:
        detail = (
            "平台 token 已过期，请在环境管理中重新登录后再导入"
            if is_apaas_token_error(str(exc))
            else "查询平台应用详情失败，请稍后重试"
        )
        logger.warning(
            "平台应用导入详情查询失败 app_id=%s env_id=%s source=%s error=%s",
            body.apaas_app_id,
            resolved_env_id,
            credential_source,
            exc,
            exc_info=True,
        )
        raise HTTPException(status_code=400, detail=detail) from exc

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
        existing_app.platform_env_id = resolved_env_id
        existing_app.current_doc_version = new_version
        existing_app.status = "completed"

        await db.commit()
        await db.refresh(existing_app)

        logger.info(
            "应用重新导入成功: %s (apaas_id=%s, version=%s, env_id=%s, credential_source=%s)",
            app_name,
            body.apaas_app_id,
            new_version,
            resolved_env_id,
            credential_source,
        )
        return _enrich(existing_app)

    # 7. 创建本地 Application 记录
    config_str = _dump_preview_config(config)
    new_app = Application(
        user_id=ctx.user.id,
        tenant_id=effective_tenant_id,
        created_by=ctx.user.id,
        app_name=app_name,
        app_code=resolved_app_code,
        description=app_desc,
        config_preview=config_str,
        requirement_doc=markdown_spec,
        apaas_app_id=body.apaas_app_id,
        platform_env_id=resolved_env_id,
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

    logger.info(
        "应用导入成功: %s (apaas_id=%s, env_id=%s, credential_source=%s)",
        app_name,
        body.apaas_app_id,
        resolved_env_id,
        credential_source,
    )
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
