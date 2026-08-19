from __future__ import annotations

import asyncio
import gzip
import hashlib
import json
import re
import time
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from typing import Annotated, Any, Literal, Optional
from urllib.parse import parse_qsl, quote, unquote_plus, urlsplit

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy import and_, delete, func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from starlette.background import BackgroundTask
from starlette.requests import ClientDisconnect
from starlette.responses import RedirectResponse, Response, StreamingResponse

from app.code_runtime.service import (
    CodeSessionRef,
    _control_plane_headers,
    code_session_route_id,
    code_runtime_proxy_prefix,
    control_plane_base_url,
    create_code_application,
    create_proxy_cookie_token,
    default_local_code_application_workspace,
    default_workspace_open,
    ensure_code_session_public_id,
    ensure_code_application,
    ensure_application_access,
    is_local_code_application_id,
    list_code_applications,
    open_code_session,
    resolve_code_session,
    validate_embed_token,
    validate_local_model_proxy_token,
    validate_proxy_cookie_token,
)
from app.code_runtime.auth import (
    control_plane_access_token,
    control_plane_refresh_token,
    control_plane_token_needs_refresh,
    exchange_control_plane_session,
    fetch_remote_builder_rail_history,
    fetch_control_plane_identity,
    remote_builder_access_token,
    refresh_control_plane_token,
    store_control_plane_credentials,
    store_remote_builder_credentials,
)
from app.code_runtime.sandbox_auth import (
    RUNTIME_AUTH_ERROR_HEADER,
    RUNTIME_COOKIE_NAME,
    SandboxRenewalFailure,
    bootstrap_runtime_session,
    decrypt_runtime_cookie,
    renew_browser_runtime_session,
    validate_expired_proxy_cookie_token,
)
from app.code_runtime.sandbox_metrics import sandbox_auth_metrics
from app.code_runtime.execution_target import is_desktop_agent_runtime_target
from app.code_runtime.session_location import normalize_code_session_location_request
from app.data_source import DataDomain, DataExecution, DataAuthority, resolve_data_route
from app.code_runtime.local_runtime import (
    LocalRuntimeClient,
    rebind_registered_local_workspace,
)
from app.config import APP_VERSION, settings
from app import runtime
from app.database import AsyncSessionLocal, get_db
from app.deps import AuthContext, get_auth_context
from app.models import Application, User
from app.models.tenant import Tenant
from app.models.ai_chat import (
    AIChatSession,
    CodeRuntimeAgentSession,
    CodeRuntimeBinding,
    CodeRuntimeBrowserSession,
)

router = APIRouter(prefix="/code", tags=["code-runtime"])
proxy_router = APIRouter(prefix="/code-runtime", tags=["code-runtime-proxy"])


class CreateCodeSessionRequest(BaseModel):
    app_id: int
    title: Optional[str] = None
    selected_llm_config_id: Optional[int] = None


class CreateExternalCodeSessionRequest(BaseModel):
    external_application_id: str
    app_name: Optional[str] = None
    app_code: Optional[str] = None
    title: Optional[str] = None
    selected_llm_config_id: Optional[int] = None


class CreateCodeApplicationRequest(BaseModel):
    app_name: str
    app_code: str
    local_application: bool = False
    local_workspace_path: Optional[str] = None
    directory_mode: Literal["new_directory", "existing_directory"] = "new_directory"
    initialize_project: bool = False
    linked_remote_application_id: Optional[str] = None
    linked_remote_deployment_id: Optional[str] = None


class RebindLocalCodeWorkspaceRequest(BaseModel):
    local_workspace_path: str


@router.get("/applications/default-workspace")
async def default_code_application_workspace(app_code: str = Query(..., min_length=1)):
    return default_local_code_application_workspace(app_code)


@router.get("/internal/sandbox-auth-metrics", include_in_schema=False)
async def sandbox_auth_metrics_endpoint() -> Response:
    return Response(
        content=sandbox_auth_metrics.render(),
        media_type="text/plain; version=0.0.4",
    )


@router.get("/internal/sandbox-auth-state", include_in_schema=False)
async def sandbox_auth_state_endpoint() -> dict[str, str]:
    return {
        "writer_contract": "clean_builder_url_v1",
        "app_version": APP_VERSION,
    }


_control_plane_user_locks: dict[int, asyncio.Lock] = {}
_code_session_open_locks: dict[str, asyncio.Lock] = {}
_code_open_state: dict[tuple[int, int, str], tuple[str, str]] = {}


def _control_plane_user_lock(user_id: int) -> asyncio.Lock:
    lock = _control_plane_user_locks.get(int(user_id))
    if lock is None:
        lock = asyncio.Lock()
        _control_plane_user_locks[int(user_id)] = lock
    return lock


def _code_session_open_lock(session_ref: str) -> asyncio.Lock:
    key = str(session_ref).strip()
    lock = _code_session_open_locks.get(key)
    if lock is None:
        lock = asyncio.Lock()
        _code_session_open_locks[key] = lock
    return lock


def _code_open_phase_key(
    session: AIChatSession,
    ctx: AuthContext,
    session_ref: str,
) -> tuple[int, int, str]:
    session_identity = str(
        getattr(session, "public_id", None)
        or getattr(session, "id", None)
        or session_ref
    )
    tenant_id = int(getattr(session, "tenant_id", None) or ctx.tenant_id)
    user_id = int(getattr(session, "user_id", None) or ctx.user.id)
    return tenant_id, user_id, session_identity


def _control_plane_code_tenant_id(ctx: AuthContext) -> str | None:
    if str(getattr(ctx.user, "account_source", "") or "").strip().lower() != "control_plane":
        return None
    value = str(getattr(ctx, "control_plane_tenant_id", "") or "").strip()
    return value or None


def _code_session_scope(model: Any, ctx: AuthContext):
    control_plane_tenant_id = _control_plane_code_tenant_id(ctx)
    if control_plane_tenant_id:
        return model.control_plane_tenant_id == control_plane_tenant_id
    return model.tenant_id == ctx.tenant_id


def _can_view_tenant_code_history(ctx: AuthContext) -> bool:
    return bool(
        getattr(ctx.user, "is_platform_admin", False)
        or getattr(ctx, "tenant_role", "member") in {"platform_admin", "tenant_admin"}
    )


def _code_session_matches_context(session: AIChatSession, ctx: AuthContext) -> bool:
    control_plane_tenant_id = _control_plane_code_tenant_id(ctx)
    if control_plane_tenant_id:
        return session.control_plane_tenant_id == control_plane_tenant_id
    return session.tenant_id == ctx.tenant_id


async def _owned_local_code_session(
    db: AsyncSession,
    session_ref: str,
    ctx: AuthContext,
) -> AIChatSession:
    session = await resolve_code_session(db, session_ref)
    if (
        session is None
        or not _code_session_matches_context(session, ctx)
        or int(session.user_id) != int(ctx.user.id)
    ):
        raise HTTPException(status_code=404, detail="Code 会话不存在")
    if session.mode != "code":
        raise HTTPException(status_code=400, detail="该会话不是 Code 会话")
    if session.app_id or not is_local_code_application_id(
        session.external_application_id or ""
    ):
        raise HTTPException(status_code=400, detail="该会话不是本地 Code 应用")
    return session


async def _owned_code_session(
    db: AsyncSession,
    session_ref: str,
    ctx: AuthContext,
) -> AIChatSession:
    session = await resolve_code_session(db, session_ref)
    if (
        session is None
        or not _code_session_matches_context(session, ctx)
        or int(session.user_id) != int(ctx.user.id)
    ):
        raise HTTPException(status_code=404, detail="Code 会话不存在")
    if session.mode != "code":
        raise HTTPException(status_code=400, detail="该会话不是 Code 会话")
    return session


async def _reset_local_runtime_binding_state(
    db: AsyncSession,
    session: AIChatSession,
) -> None:
    await db.execute(
        update(CodeRuntimeBinding)
        .where(
            CodeRuntimeBinding.tenant_id == session.tenant_id,
            CodeRuntimeBinding.user_id == session.user_id,
            CodeRuntimeBinding.external_application_id
            == session.external_application_id,
        )
        .values(
            sandbox_instance_id=None,
            runtime_session_id=None,
            desktop_agent_runtime_token_enc=None,
            status="pending",
            last_error=None,
        )
    )
    await db.execute(
        delete(CodeRuntimeAgentSession).where(
            CodeRuntimeAgentSession.tenant_id == session.tenant_id,
            CodeRuntimeAgentSession.user_id == session.user_id,
            CodeRuntimeAgentSession.external_application_id
            == session.external_application_id,
        )
    )


def _resolved_code_sandbox_cache_config() -> dict[str, int | str]:
    profile = str(settings.dolphin_code_cache_profile or "normal").strip().lower()
    if profile not in {"normal", "performance"}:
        profile = "normal"
    if profile == "performance":
        browser_hot_frames = settings.dolphin_code_performance_browser_hot_frames
        server_warm_sandboxes = settings.dolphin_code_performance_server_warm_sandboxes_per_user
    else:
        browser_hot_frames = settings.dolphin_code_normal_browser_hot_frames
        server_warm_sandboxes = settings.dolphin_code_normal_server_warm_sandboxes_per_user
    return {
        "cache_profile": profile,
        "browser_hot_frames": min(10, max(1, int(browser_hot_frames))),
        "server_warm_sandboxes_per_user": min(50, max(1, int(server_warm_sandboxes))),
    }


async def _locked_control_plane_user_authorization(
    *,
    user_id: int,
    session_factory=AsyncSessionLocal,
    force_refresh: bool = False,
    rejected_access_token: str | None = None,
) -> str:
    async with _control_plane_user_lock(user_id):
        async with session_factory() as db:
            user = (
                await db.execute(
                    select(User).where(User.id == int(user_id)).with_for_update()
                )
            ).scalar_one_or_none()
            if user is None:
                raise SandboxRenewalFailure("login_required")

            access_token = control_plane_access_token(user)
            already_rotated = bool(
                force_refresh
                and rejected_access_token
                and access_token
                and access_token != rejected_access_token
            )
            if already_rotated or (
                access_token
                and not force_refresh
                and not control_plane_token_needs_refresh(access_token)
            ):
                return f"Bearer {access_token}"

            refresh_token = control_plane_refresh_token(user)
            if not refresh_token:
                raise SandboxRenewalFailure("login_required")
            try:
                refreshed = await refresh_control_plane_token(refresh_token)
            except Exception as exc:
                raise SandboxRenewalFailure("login_required") from exc
            store_control_plane_credentials(
                user,
                refreshed.access_token,
                refreshed.refresh_token or refresh_token,
            )
            try:
                await db.commit()
            except Exception as exc:
                await db.rollback()
                raise SandboxRenewalFailure(
                    "workspace_temporarily_unavailable"
                ) from exc
            return f"Bearer {refreshed.access_token}"


async def _resolve_control_plane_tenant_id(
    db: AsyncSession,
    ctx: AuthContext,
) -> str | None:
    current_tenant_id = str(
        getattr(ctx, "control_plane_tenant_id", "") or ""
    ).strip()
    if current_tenant_id:
        return current_tenant_id
    return None


def _session_to_dict(session: AIChatSession) -> dict:
    return {
        "id": session.id,
        "public_id": ensure_code_session_public_id(session),
        "route_id": code_session_route_id(session.id),
        "title": session.title,
        "status": session.status,
        "mode": session.mode,
        "app_id": session.app_id,
        "external_application_id": getattr(session, "external_application_id", None),
        "external_app_name": getattr(session, "external_app_name", None),
        "external_app_code": getattr(session, "external_app_code", None),
        "selected_llm_config_id": session.selected_llm_config_id,
        "workspace_dir": session.workspace_dir,
        "workspace_id": session.workspace_id,
        "created_at": session.created_at.isoformat() if session.created_at else None,
        "updated_at": session.updated_at.isoformat() if session.updated_at else None,
    }


async def _control_plane_request_auth(
    request: Request,
    ctx: AuthContext,
    db: AsyncSession,
) -> tuple[str | None, str | None]:
    provider = str(settings.auth_provider or "").strip().lower()
    uses_dolphin_token = (
        str(getattr(ctx.user, "account_source", "") or "").strip().lower()
        == "control_plane"
        or settings.control_plane_binding_enabled
        or provider in {"control_plane", "coding"}
    )
    if not uses_dolphin_token:
        return request.headers.get("authorization"), None
    ctx.control_plane_tenant_id = await _resolve_control_plane_tenant_id(db, ctx)
    token = control_plane_access_token(ctx.user)
    if token and not control_plane_token_needs_refresh(token):
        if runtime.is_desktop():
            try:
                identity = await fetch_control_plane_identity(token)
                ctx.control_plane_tenant_id = (
                    getattr(ctx, "control_plane_tenant_id", None) or identity.tenant_id
                )
                ctx.control_plane_tenant_name = getattr(
                    ctx,
                    "control_plane_tenant_name",
                    None,
                ) or identity.tenant_name
            except HTTPException:
                # Remote identity is authoritative.  A valid cached snapshot is
                # used only to keep an already-open local workspace available
                # while the Control Plane is temporarily unreachable.
                pass
        return f"Bearer {token}", None

    try:
        session_factory = (
            async_sessionmaker(
                db.bind,
                class_=AsyncSession,
                expire_on_commit=False,
            )
            if getattr(db, "bind", None) is not None
            else AsyncSessionLocal
        )
        authorization = await _locked_control_plane_user_authorization(
            user_id=int(ctx.user.id),
            session_factory=session_factory,
        )
    except SandboxRenewalFailure as exc:
        if exc.code == "login_required":
            raise HTTPException(
                status_code=403,
                detail="当前账号未绑定 Control Plane，或用户 Token 已失效，请重新登录",
            ) from exc
        raise HTTPException(status_code=exc.status_code, detail=exc.code) from exc
    fresh_access_token = authorization.removeprefix("Bearer ").strip()
    if fresh_access_token:
        store_control_plane_credentials(
            ctx.user,
            fresh_access_token,
            control_plane_refresh_token(ctx.user),
        )
    return authorization, None


async def _desktop_remote_builder_access_token(
    ctx: AuthContext,
    db: AsyncSession,
) -> str:
    """Return the cached remote Builder token, exchanging the CP token if needed."""
    token = remote_builder_access_token(ctx.user)
    if token and not control_plane_token_needs_refresh(token):
        return token

    control_plane_token = control_plane_access_token(ctx.user)
    tenant_id = await _resolve_control_plane_tenant_id(db, ctx)
    if not control_plane_token or not tenant_id:
        raise HTTPException(status_code=401, detail="远端登录已失效，请重新登录")
    token = await exchange_control_plane_session(control_plane_token, tenant_id)
    store_remote_builder_credentials(ctx.user, token)
    await db.commit()
    return token


async def _fetch_desktop_remote_builder_rail_history(
    builder_access_token: str,
) -> dict[str, Any]:
    return await fetch_remote_builder_rail_history(builder_access_token)


async def _desktop_remote_rail_history(
    ctx: AuthContext,
    db: AsyncSession,
) -> dict[str, Any]:
    builder_access_token = await _desktop_remote_builder_access_token(ctx, db)
    try:
        remote_history = await _fetch_desktop_remote_builder_rail_history(
            builder_access_token
        )
    except HTTPException as exc:
        if exc.status_code != 401:
            raise
        # A remote Builder JWT has expired. The Control Plane credential remains
        # the upstream identity source and can mint one replacement session.
        control_plane_token = control_plane_access_token(ctx.user)
        tenant_id = await _resolve_control_plane_tenant_id(db, ctx)
        if not control_plane_token or not tenant_id:
            raise
        builder_access_token = await exchange_control_plane_session(
            control_plane_token,
            tenant_id,
        )
        store_remote_builder_credentials(ctx.user, builder_access_token)
        await db.commit()
        remote_history = await _fetch_desktop_remote_builder_rail_history(
            builder_access_token
        )

    remote_apps = remote_history.get("apps")
    if not isinstance(remote_apps, list):
        raise HTTPException(status_code=502, detail="远端 AI Builder 会话数据异常")

    shell_ids = [
        str(app.get("shell_session_id") or "").strip()
        for app in remote_apps
        if isinstance(app, dict) and str(app.get("shell_session_id") or "").strip()
    ]
    existing_by_public_id: dict[str, AIChatSession] = {}
    if shell_ids:
        existing = (
            await db.execute(
                select(AIChatSession).where(
                    AIChatSession.public_id.in_(shell_ids),
                    _code_session_scope(AIChatSession, ctx),
                    AIChatSession.user_id == ctx.user.id,
                )
            )
        ).scalars().all()
        existing_by_public_id = {
            str(session.public_id): session
            for session in existing
            if session.public_id
        }

    local_sessions: dict[str, AIChatSession] = {}
    for app in remote_apps:
        if not isinstance(app, dict):
            continue
        shell_id = str(app.get("shell_session_id") or "").strip()
        external_application_id = str(
            app.get("external_application_id") or ""
        ).strip()
        if not shell_id or not external_application_id:
            continue
        title = str(app.get("app_name") or app.get("app_code") or external_application_id)
        session = existing_by_public_id.get(shell_id)
        if session is None:
            session = AIChatSession(
                public_id=shell_id,
                tenant_id=ctx.tenant_id,
                control_plane_tenant_id=_control_plane_code_tenant_id(ctx),
                user_id=ctx.user.id,
                title=title,
                mode="code",
                status="active",
                external_application_id=external_application_id,
                external_app_name=str(app.get("app_name") or "").strip() or None,
                external_app_code=str(app.get("app_code") or "").strip() or None,
            )
            db.add(session)
            existing_by_public_id[shell_id] = session
        else:
            session.control_plane_tenant_id = _control_plane_code_tenant_id(ctx)
            session.title = title
            session.status = "active"
            session.external_application_id = external_application_id
            session.external_app_name = str(app.get("app_name") or "").strip() or None
            session.external_app_code = str(app.get("app_code") or "").strip() or None
        local_sessions[shell_id] = session
    await db.flush()

    local_session_ids = [session.id for session in local_sessions.values()]
    bindings_by_session_id: dict[int, CodeRuntimeBinding] = {}
    if local_session_ids:
        bindings = (
            await db.execute(
                select(CodeRuntimeBinding).where(
                    CodeRuntimeBinding.session_id.in_(local_session_ids)
                )
            )
        ).scalars().all()
        bindings_by_session_id = {
            int(binding.session_id): binding for binding in bindings
        }
    await db.commit()

    # The remote service owns which shells exist. Agent-session runtime state is
    # intentionally local because a desktop sandbox cannot resume a server-side
    # Codex runtime session.
    apps: list[dict[str, Any]] = []
    for app in remote_apps:
        if not isinstance(app, dict):
            continue
        shell_id = str(app.get("shell_session_id") or "").strip()
        session = local_sessions.get(shell_id)
        if not shell_id or session is None:
            continue
        binding = bindings_by_session_id.get(int(session.id))
        apps.append({
            "shell_session_id": shell_id,
            "external_application_id": session.external_application_id or "",
            "app_name": session.external_app_name or session.title,
            "app_code": session.external_app_code,
            "runtime_session_id": binding.runtime_session_id if binding else None,
            "sessions": [],
        })
    return {"apps": apps}


@router.get("/applications")
async def list_code_runtime_applications(
    request: Request,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
    source: Literal["local", "remote"] = "remote",
    keyword: Optional[str] = None,
    provision_status: Optional[str] = Query(default=None, alias="provisionStatus"),
    page: int = 1,
    page_size: int = Query(default=50, alias="pageSize"),
):
    started = time.monotonic()
    try:
        route = resolve_data_route(
            DataDomain.CODE,
            execution=DataExecution.LOCAL if source == "local" else DataExecution.REMOTE,
        )
        if route.authority is DataAuthority.DESKTOP_LOCAL:
            authorization, auth_provider = None, None
        else:
            authorization, auth_provider = await _control_plane_request_auth(request, ctx, db)
        result = await list_code_applications(
            source=source,
            keyword=keyword,
            provision_status=provision_status,
            page=page,
            page_size=page_size,
            authorization_header=authorization,
            delegated_context=ctx,
            auth_provider=auth_provider,
            db=db,
            ctx=ctx,
        )
    except Exception:
        sandbox_auth_metrics.record_builder_stage(
            "applications_shared_load",
            "failure",
            time.monotonic() - started,
        )
        raise
    sandbox_auth_metrics.record_builder_stage(
        "applications_shared_load",
        "success",
        time.monotonic() - started,
    )
    return result


@router.post("/applications")
async def create_code_runtime_application(
    body: CreateCodeApplicationRequest,
    request: Request,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    route = resolve_data_route(
        DataDomain.CODE,
        execution=(
            DataExecution.LOCAL
            if body.local_application or str(body.local_workspace_path or "").strip()
            else DataExecution.REMOTE
        ),
    )
    if route.authority is DataAuthority.DESKTOP_LOCAL:
        authorization, auth_provider = None, None
    else:
        authorization, auth_provider = await _control_plane_request_auth(request, ctx, db)
    return await create_code_application(
        app_name=body.app_name,
        app_code=body.app_code,
        local_application=body.local_application,
        local_workspace_path=body.local_workspace_path,
        directory_mode=body.directory_mode,
        initialize_project=body.initialize_project,
        linked_remote_application_id=body.linked_remote_application_id,
        linked_remote_deployment_id=body.linked_remote_deployment_id,
        db=db,
        ctx=ctx,
        authorization_header=authorization,
        delegated_context=ctx,
        auth_provider=auth_provider,
    )


@router.post("/sessions/from-app")
async def create_code_session_from_app(
    body: CreateCodeSessionRequest,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    app = ensure_code_application(await ensure_application_access(db, body.app_id, ctx))
    title = (body.title or "").strip() or f"{app.app_name} Code"
    session = AIChatSession(
        tenant_id=ctx.tenant_id,
        control_plane_tenant_id=_control_plane_code_tenant_id(ctx),
        user_id=ctx.user.id,
        app_id=app.id,
        title=title,
        mode="code",
        status="active",
        selected_llm_config_id=body.selected_llm_config_id if body.selected_llm_config_id else None,
    )
    db.add(session)
    await db.commit()
    await db.refresh(session)
    return _session_to_dict(session)


@router.post("/sessions/from-external-app")
async def create_code_session_from_external_app(
    body: CreateExternalCodeSessionRequest,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    external_id = str(body.external_application_id or "").strip()
    if not external_id:
        raise HTTPException(status_code=400, detail="external_application_id 不能为空")
    app_name = str(body.app_name or "").strip() or None
    app_code = str(body.app_code or "").strip() or None
    title = str(body.title or "").strip() or f"{app_name or app_code or external_id} Code"

    existing = (
        await db.execute(
            select(AIChatSession)
            .where(
                _code_session_scope(AIChatSession, ctx),
                AIChatSession.user_id == ctx.user.id,
                AIChatSession.mode == "code",
                AIChatSession.status != "archived",
                AIChatSession.external_application_id == external_id,
            )
            .order_by(AIChatSession.updated_at.desc(), AIChatSession.id.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if existing:
        changed = False
        if not getattr(existing, "public_id", None):
            ensure_code_session_public_id(existing)
            changed = True
        if app_name and existing.external_app_name != app_name:
            existing.external_app_name = app_name
            changed = True
        if app_code and existing.external_app_code != app_code:
            existing.external_app_code = app_code
            changed = True
        if body.title and existing.title != title:
            existing.title = title
            changed = True
        if body.selected_llm_config_id and existing.selected_llm_config_id != body.selected_llm_config_id:
            existing.selected_llm_config_id = body.selected_llm_config_id
            changed = True
        if changed:
            await db.commit()
            await db.refresh(existing)
        return _session_to_dict(existing)

    session = AIChatSession(
        tenant_id=ctx.tenant_id,
        control_plane_tenant_id=_control_plane_code_tenant_id(ctx),
        user_id=ctx.user.id,
        app_id=None,
        external_application_id=external_id,
        external_app_name=app_name,
        external_app_code=app_code,
        title=title,
        mode="code",
        status="active",
        selected_llm_config_id=body.selected_llm_config_id if body.selected_llm_config_id else None,
    )
    db.add(session)
    await db.commit()
    await db.refresh(session)
    return _session_to_dict(session)


@router.post("/sessions/{session_ref}/open")
async def open_code_runtime_session(
    session_ref: str,
    request: Request,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    session = await resolve_code_session(db, session_ref)
    lock_key = str(getattr(session, "id", None) or session_ref)
    async with _code_session_open_lock(lock_key):
        if session is None:
            session = await resolve_code_session(db, session_ref)
        if session is None:
            raise HTTPException(status_code=404, detail="Code 会话不存在")
        uses_local_builder = bool(
            not session.app_id
            and is_local_code_application_id(session.external_application_id or "")
        )
        phase_key = _code_open_phase_key(session, ctx, session_ref)
        _code_open_state[phase_key] = (
            "checking_project" if uses_local_builder else "provisioning",
            "opening",
        )
        # A local workspace never opens a remote Code runtime, but it can use
        # the logged-in Control Plane's Coding model catalog through the local
        # model proxy.  Keep the authorization for that catalog request rather
        # than falling back to an unrelated locally configured model.
        authorization, auth_provider = await _control_plane_request_auth(request, ctx, db)
        open_kwargs: dict[str, Any] = {}
        open_kwargs["on_local_phase"] = lambda phase: _code_open_state.__setitem__(
            phase_key,
            (phase, "opening"),
        )
        if not uses_local_builder:
            open_kwargs["on_phase"] = lambda phase: _code_open_state.__setitem__(
                phase_key,
                (phase, "opening"),
            )
        try:
            result = await open_code_session(
                db=db,
                session_id=session_ref,
                ctx=ctx,
                authorization_header=authorization,
                auth_provider=auth_provider,
                **open_kwargs,
            )
        finally:
            _code_open_state.pop(phase_key, None)
        try:
            await db.commit()
        except Exception as exc:
            await db.rollback()
            raise HTTPException(status_code=500, detail="Code runtime session open failed") from exc
        # Piggyback the resolved cache profile on the existing open call so the
        # browser does not add another request to the workspace critical path.
        return {
            **result,
            **_resolved_code_sandbox_cache_config(),
        }


def _local_model_proxy_token(request: Request) -> str:
    authorization = str(request.headers.get("authorization") or "").strip()
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise HTTPException(status_code=401, detail="本地模型代理鉴权失败")
    return token.strip()


async def _local_model_proxy_context(
    db: AsyncSession,
    *,
    external_application_id: str,
    token: str,
) -> tuple[AIChatSession, AuthContext]:
    sessions = (
        await db.execute(
            select(AIChatSession)
            .where(
                AIChatSession.mode == "code",
                AIChatSession.status != "archived",
                AIChatSession.external_application_id == external_application_id,
            )
            .order_by(AIChatSession.updated_at.desc(), AIChatSession.id.desc())
        )
    ).scalars().all()
    for session in sessions:
        if not validate_local_model_proxy_token(
            token,
            application_id=external_application_id,
            user_id=int(session.user_id),
            tenant_id=int(session.tenant_id),
            control_plane_tenant_id=session.control_plane_tenant_id,
        ):
            continue
        user = await db.get(User, int(session.user_id))
        if user is None:
            continue
        return session, AuthContext(
            user=user,
            tenant_id=int(session.tenant_id),
            tenant_role="member",
            org_permissions={},
            control_plane_tenant_id=session.control_plane_tenant_id,
        )
    raise HTTPException(status_code=401, detail="本地模型代理鉴权失败")


@router.api_route(
    "/model-proxy/{external_application_id}/v1/{model_path:path}",
    methods=["GET", "POST"],
)
async def proxy_desktop_runtime_model(
    external_application_id: str,
    model_path: str,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Forward a desktop Runtime request without exposing provider credentials."""
    path = str(model_path or "").strip("/")
    if (request.method == "GET" and path != "models") or (
        request.method == "POST" and path != "responses"
    ):
        raise HTTPException(status_code=404, detail="模型代理路径不存在")

    session, ctx = await _local_model_proxy_context(
        db,
        external_application_id=str(external_application_id or "").strip(),
        token=_local_model_proxy_token(request),
    )
    authorization, _auth_provider = await _control_plane_request_auth(
        type("LocalModelProxyRequest", (), {"headers": {}})(),
        ctx,
        db,
    )
    if not authorization:
        raise HTTPException(status_code=403, detail="线上模型服务未登录")

    try:
        body = b"" if request.method == "GET" else await request.body()
    except ClientDisconnect:
        return Response(status_code=499)
    headers = _control_plane_headers(
        authorization,
        delegated_context=ctx,
        shell_session_id=session.id,
    )
    if request.headers.get("content-type"):
        headers["Content-Type"] = request.headers["content-type"]
    if request.headers.get("accept"):
        headers["Accept"] = request.headers["accept"]
    target = f"{control_plane_base_url()}/api/code/model-gateway/v1/{path}"
    client = httpx.AsyncClient(
        timeout=httpx.Timeout(connect=10, read=None, write=30, pool=10)
    )
    try:
        upstream = await client.send(
            client.build_request(request.method, target, headers=headers, content=body),
            stream=True,
        )
    except httpx.RequestError as exc:
        await client.aclose()
        raise HTTPException(status_code=503, detail="线上模型服务暂时不可用") from exc

    response_headers: dict[str, str] = {"Cache-Control": "no-cache"}
    if content_type := upstream.headers.get("content-type"):
        response_headers["Content-Type"] = content_type
    if upstream.headers.get("x-accel-buffering"):
        response_headers["X-Accel-Buffering"] = upstream.headers["x-accel-buffering"]
    return StreamingResponse(
        upstream.aiter_raw(),
        status_code=upstream.status_code,
        headers=response_headers,
        background=BackgroundTask(_close_upstream, upstream, client),
    )


@router.get("/sessions/{session_ref}/open-status")
async def get_code_runtime_open_status(
    session_ref: str,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    session = await _owned_code_session(db, session_ref, ctx)
    in_flight = _code_open_state.get(_code_open_phase_key(session, ctx, session_ref))
    if in_flight:
        phase, runtime_state = in_flight
        return {
            "phase": phase,
            "runtime_state": runtime_state,
        }
    if session.app_id or not is_local_code_application_id(
        session.external_application_id or ""
    ):
        return {
            "phase": "opening_workbench",
            "runtime_state": "ready",
        }
    return await LocalRuntimeClient.from_environment().application_open_status(
        db,
        session,
        ctx,
    )


@router.post("/sessions/{session_ref}/local-runtime/restart")
async def restart_local_code_runtime(
    session_ref: str,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    session = await _owned_local_code_session(db, session_ref, ctx)
    _code_open_state.pop(_code_open_phase_key(session, ctx, session_ref), None)
    result = await LocalRuntimeClient.from_environment().restart_application(
        db,
        session,
        ctx,
    )
    await _reset_local_runtime_binding_state(db, session)
    await db.commit()
    return result


@router.patch("/sessions/{session_ref}/local-workspace")
async def rebind_local_code_workspace(
    session_ref: str,
    body: RebindLocalCodeWorkspaceRequest,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    session = await _owned_local_code_session(db, session_ref, ctx)
    _code_open_state.pop(_code_open_phase_key(session, ctx, session_ref), None)
    client = LocalRuntimeClient.from_environment()
    await client.restart_application(
        db,
        session,
        ctx,
        validate_workspace=False,
    )
    await _reset_local_runtime_binding_state(db, session)
    workspace = await rebind_registered_local_workspace(
        db,
        session,
        ctx,
        workspace_path=body.local_workspace_path,
    )
    await db.commit()
    return {
        "workspace_id": workspace.ws_id,
        "local_workspace_path": workspace.abs_path,
    }


def _desktop_runtime_authorization(binding: CodeRuntimeBinding) -> str:
    try:
        token = decrypt_runtime_cookie(binding.desktop_agent_runtime_token_enc or "")
    except ValueError as exc:
        raise HTTPException(status_code=503, detail="Desktop Code runtime token unavailable") from exc
    return f"Bearer {token}"


async def _runtime_json_request(
    binding: CodeRuntimeBinding,
    method: str,
    path: str,
    *,
    json_body: Any = None,
    timeout: float = 60.0,
) -> Any:
    target = f"{binding.runtime_base_url.rstrip('/')}/{path.lstrip('/')}"
    headers = {"accept": "application/json"}
    if is_desktop_agent_runtime_target(binding.execution_target):
        headers["authorization"] = _desktop_runtime_authorization(binding)
    elif binding.runtime_service_session_enc:
        try:
            runtime_cookie = decrypt_runtime_cookie(binding.runtime_service_session_enc)
        except ValueError as exc:
            raise HTTPException(status_code=503, detail="Code runtime session unavailable") from exc
        headers["cookie"] = f"apaas_sandbox_token={runtime_cookie}"
    if json_body is not None:
        headers["content-type"] = "application/json"
    try:
        async with httpx.AsyncClient(follow_redirects=False, timeout=timeout) as client:
            response = await client.request(method, target, headers=headers, json=json_body)
    except httpx.RequestError as exc:
        raise HTTPException(status_code=503, detail="Code runtime 暂时不可用") from exc
    if response.status_code >= 400:
        auth_error = str(response.headers.get(RUNTIME_AUTH_ERROR_HEADER) or "").strip()
        response_headers = {RUNTIME_AUTH_ERROR_HEADER: auth_error} if auth_error else None
        raise HTTPException(
            status_code=response.status_code,
            detail=response.text[:500] or "Code runtime request failed",
            headers=response_headers,
        )
    if not response.content:
        return {}
    try:
        return response.json()
    except ValueError as exc:
        raise HTTPException(status_code=502, detail="Code runtime 返回了无效 JSON") from exc


async def _refresh_runtime_binding(
    session: AIChatSession,
    binding: CodeRuntimeBinding,
    request: Request,
    ctx: AuthContext,
    db: AsyncSession,
) -> None:
    if is_desktop_agent_runtime_target(binding.execution_target):
        raise HTTPException(
            status_code=503,
            detail="Desktop Code runtime does not support Control Plane refresh",
        )
    uses_local_builder = bool(
        not session.app_id
        and is_local_code_application_id(session.external_application_id or "")
    )
    if uses_local_builder:
        authorization, auth_provider = None, None
    else:
        authorization, auth_provider = await _control_plane_request_auth(request, ctx, db)
    await open_code_session(
        db=db,
        session_id=session.id,
        ctx=ctx,
        authorization_header=authorization,
        auth_provider=auth_provider,
    )
    await db.commit()


async def _runtime_json_request_for_session(
    session: AIChatSession,
    binding: CodeRuntimeBinding,
    method: str,
    path: str,
    *,
    request: Request,
    ctx: AuthContext,
    db: AsyncSession,
    json_body: Any = None,
    timeout: float = 60.0,
) -> Any:
    try:
        return await _runtime_json_request(
            binding,
            method,
            path,
            json_body=json_body,
            timeout=timeout,
        )
    except HTTPException as exc:
        if is_desktop_agent_runtime_target(binding.execution_target):
            raise
        if not (
            exc.status_code == 401
            and (exc.headers or {}).get(RUNTIME_AUTH_ERROR_HEADER)
            in {"sandbox_session_expired", "sandbox_session_invalid"}
        ):
            raise
    await _refresh_runtime_binding(session, binding, request, ctx, db)
    return await _runtime_json_request(
        binding,
        method,
        path,
        json_body=json_body,
        timeout=timeout,
    )


def _runtime_session_has_visible_title(session: dict[str, Any]) -> bool:
    return bool(str(session.get("title") or "").strip() or str(session.get("summary") or "").strip())


def _runtime_session_placeholder(
    binding: CodeRuntimeBinding,
    runtime_session_id: str,
    fallback_title: str | None = None,
    *,
    include_sandbox: bool = False,
) -> dict[str, Any]:
    timestamp = binding.updated_at.isoformat() if binding.updated_at else None
    result = {
        "runtimeSessionId": runtime_session_id,
        "title": str(fallback_title or "").strip() or "未命名会话",
        "state": "running",
        "createdAt": timestamp,
        "updatedAt": timestamp,
        "lastActiveAt": timestamp,
        "current": True,
        "deletedAt": None,
        "capabilityStale": False,
        "codexSessionResumable": True,
    }
    if include_sandbox:
        result["sandboxInstanceId"] = binding.sandbox_instance_id
    return result


def _runtime_agent_snapshot_item(
    row: CodeRuntimeAgentSession,
    current_runtime_id: str,
    *,
    include_sandbox: bool = False,
) -> dict[str, Any]:
    created_at = row.runtime_created_at or row.created_at
    updated_at = row.runtime_updated_at or row.updated_at
    last_active_at = row.last_active_at or updated_at
    result = {
        "runtimeSessionId": row.runtime_session_id,
        "title": row.title or row.summary or "未命名会话",
        "summary": row.summary,
        "state": row.state or "waiting_input",
        "model": row.model,
        "createdAt": created_at.isoformat() if created_at else None,
        "updatedAt": updated_at.isoformat() if updated_at else None,
        "lastActiveAt": last_active_at.isoformat() if last_active_at else None,
        "current": row.runtime_session_id == current_runtime_id,
        "deletedAt": row.deleted_at.isoformat() if row.deleted_at else None,
        "capabilityStale": bool(row.capability_stale),
        "codexSessionResumable": bool(row.codex_session_resumable),
    }
    if include_sandbox:
        result["sandboxInstanceId"] = row.sandbox_instance_id
    return result


async def _runtime_session_detail_or_none(
    binding: CodeRuntimeBinding,
    runtime_session_id: str,
) -> dict[str, Any] | None:
    encoded_id = quote(str(runtime_session_id), safe="")
    try:
        payload = await _runtime_json_request(binding, "GET", f"/api/agent/sessions/{encoded_id}")
    except HTTPException:
        return None
    if not isinstance(payload, dict):
        return None
    payload_id = str(payload.get("runtimeSessionId") or "").strip()
    if payload_id and payload_id != runtime_session_id:
        return None
    return payload


async def _current_runtime_session_item(
    binding: CodeRuntimeBinding,
    runtime_session_id: str,
    fallback_title: str | None = None,
) -> dict[str, Any]:
    detail = await _runtime_session_detail_or_none(binding, runtime_session_id)
    if detail and _runtime_session_has_visible_title(detail):
        item = dict(detail)
        item["runtimeSessionId"] = runtime_session_id
        item["current"] = True
        item.setdefault("deletedAt", None)
        item.setdefault("capabilityStale", False)
        item.setdefault("codexSessionResumable", True)
        return item
    return _runtime_session_placeholder(binding, runtime_session_id, fallback_title)


async def _authorized_code_runtime_binding(
    db: AsyncSession,
    session_id: CodeSessionRef,
    ctx: AuthContext,
) -> tuple[AIChatSession, CodeRuntimeBinding]:
    session = await resolve_code_session(db, session_id)
    if (
        not session
        or not _code_session_matches_context(session, ctx)
        or session.user_id != ctx.user.id
        or session.mode != "code"
    ):
        raise HTTPException(status_code=404, detail="Code runtime binding not found")
    row = (
        await db.execute(
            select(AIChatSession, CodeRuntimeBinding)
            .join(CodeRuntimeBinding, CodeRuntimeBinding.session_id == AIChatSession.id)
            .where(
                AIChatSession.id == session.id,
                _code_session_scope(AIChatSession, ctx),
                AIChatSession.user_id == ctx.user.id,
                AIChatSession.mode == "code",
            )
        )
    ).one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="Code runtime binding not found")
    session, binding = row
    return session, binding


async def _scoped_runtime_session_ids(db: AsyncSession, session_id: int) -> set[str]:
    rows = (
        await db.execute(
            select(CodeRuntimeAgentSession.runtime_session_id).where(
                CodeRuntimeAgentSession.session_id == int(session_id)
            )
        )
    ).scalars().all()
    return {str(value or "").strip() for value in rows if str(value or "").strip()}


async def _runtime_session_ids_scoped_to_other_shells(db: AsyncSession, session_id: int) -> set[str]:
    rows = (
        await db.execute(
            select(CodeRuntimeAgentSession.runtime_session_id).where(
                CodeRuntimeAgentSession.session_id != int(session_id)
            )
        )
    ).scalars().all()
    return {str(value or "").strip() for value in rows if str(value or "").strip()}


def _filter_browser_runtime_sessions(
    sessions: list[Any],
    *,
    other_scoped_ids: set[str],
) -> list[dict[str, Any]]:
    return [
        item for item in sessions
        if (
            isinstance(item, dict)
            and str(item.get("runtimeSessionId") or "").strip()
            and str(item.get("runtimeSessionId") or "").strip() not in other_scoped_ids
        )
    ]


def _runtime_snapshot_text(value: Any, limit: int | None = None) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    return text[:limit] if limit else text


def _runtime_snapshot_time(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(timezone.utc)
    return parsed.replace(tzinfo=None)


def _apply_runtime_agent_session_snapshot(
    existing: CodeRuntimeAgentSession,
    snapshot: dict[str, Any] | None,
) -> None:
    runtime_updated_at, values = _runtime_agent_session_snapshot_values(snapshot)
    existing_runtime_version = (
        existing.runtime_updated_at or existing.last_active_at
    )
    if existing_runtime_version is not None and (
        runtime_updated_at is None
        or runtime_updated_at < existing_runtime_version
    ):
        return
    for field_name, value in values.items():
        setattr(existing, field_name, value)


def _runtime_agent_session_snapshot_values(
    snapshot: dict[str, Any] | None,
) -> tuple[datetime | None, dict[str, Any]]:
    payload = snapshot if isinstance(snapshot, dict) else {}
    runtime_updated_at = _runtime_snapshot_time(
        payload.get("updatedAt")
    ) or _runtime_snapshot_time(payload.get("lastActiveAt"))
    values: dict[str, Any] = {}
    text_fields = (
        ("title", "title", 300),
        ("summary", "summary", None),
        ("state", "state", 40),
        ("model", "model", 120),
    )
    for payload_key, field_name, limit in text_fields:
        value = _runtime_snapshot_text(payload.get(payload_key), limit)
        if value is not None:
            values[field_name] = value
    runtime_created_at = _runtime_snapshot_time(payload.get("createdAt"))
    if runtime_created_at is not None:
        values["runtime_created_at"] = runtime_created_at
    if runtime_updated_at is not None:
        values["runtime_updated_at"] = runtime_updated_at
    last_active_at = _runtime_snapshot_time(payload.get("lastActiveAt"))
    if last_active_at is not None:
        values["last_active_at"] = last_active_at
    if "deletedAt" in payload:
        values["deleted_at"] = _runtime_snapshot_time(payload.get("deletedAt"))
    if "capabilityStale" in payload:
        values["capability_stale"] = bool(payload["capabilityStale"])
    if "codexSessionResumable" in payload:
        values["codex_session_resumable"] = bool(payload["codexSessionResumable"])
    return runtime_updated_at, values


def _sync_runtime_agent_session_identity(
    existing: CodeRuntimeAgentSession,
    session: AIChatSession,
    binding: CodeRuntimeBinding,
) -> None:
    existing.control_plane_tenant_id = session.control_plane_tenant_id
    existing.tenant_id = session.tenant_id
    existing.user_id = session.user_id
    existing.app_id = int(session.app_id) if session.app_id else None
    existing.external_application_id = binding.external_application_id
    existing.workspace_id = binding.workspace_id
    existing.sandbox_instance_id = binding.sandbox_instance_id


async def _update_runtime_agent_session(
    db: AsyncSession,
    session: AIChatSession,
    binding: CodeRuntimeBinding,
    runtime_id: str,
    snapshot: dict[str, Any] | None,
) -> None:
    row_matches = (
        CodeRuntimeAgentSession.session_id == int(session.id),
        CodeRuntimeAgentSession.runtime_session_id == runtime_id,
    )
    await db.execute(
        update(CodeRuntimeAgentSession)
        .where(*row_matches)
        .values(
            control_plane_tenant_id=session.control_plane_tenant_id,
            tenant_id=session.tenant_id,
            user_id=session.user_id,
            app_id=int(session.app_id) if session.app_id else None,
            external_application_id=binding.external_application_id,
            workspace_id=binding.workspace_id,
            sandbox_instance_id=binding.sandbox_instance_id,
        )
        .execution_options(synchronize_session=False)
    )

    incoming_version, snapshot_values = _runtime_agent_session_snapshot_values(
        snapshot
    )
    if not snapshot_values:
        return
    existing_version = func.coalesce(
        CodeRuntimeAgentSession.runtime_updated_at,
        CodeRuntimeAgentSession.last_active_at,
    )
    version_condition = (
        existing_version.is_(None)
        if incoming_version is None
        else or_(
            existing_version.is_(None),
            existing_version <= incoming_version,
        )
    )
    await db.execute(
        update(CodeRuntimeAgentSession)
        .where(*row_matches, version_condition)
        .values(**snapshot_values)
        .execution_options(synchronize_session=False)
    )


async def _remember_runtime_agent_session(
    db: AsyncSession,
    session: AIChatSession,
    binding: CodeRuntimeBinding,
    runtime_session_id: str,
    snapshot: dict[str, Any] | None = None,
) -> None:
    runtime_id = str(runtime_session_id or "").strip()
    if not runtime_id:
        return
    existing = (
        await db.execute(
            select(CodeRuntimeAgentSession).where(
                CodeRuntimeAgentSession.session_id == int(session.id),
                CodeRuntimeAgentSession.runtime_session_id == runtime_id,
            )
        )
    ).scalar_one_or_none()
    if not existing:
        candidate = CodeRuntimeAgentSession(
            tenant_id=session.tenant_id,
            user_id=session.user_id,
            app_id=int(session.app_id) if session.app_id else None,
            session_id=session.id,
            external_application_id=binding.external_application_id,
            runtime_session_id=runtime_id,
        )
        try:
            async with db.begin_nested():
                db.add(candidate)
                _sync_runtime_agent_session_identity(candidate, session, binding)
                _apply_runtime_agent_session_snapshot(candidate, snapshot)
                await db.flush()
        except IntegrityError as exc:
            if candidate in db:
                db.expunge(candidate)
            existing = (
                await db.execute(
                    select(CodeRuntimeAgentSession).where(
                        CodeRuntimeAgentSession.session_id == int(session.id),
                        CodeRuntimeAgentSession.runtime_session_id == runtime_id,
                    )
                )
            ).scalar_one_or_none()
            if existing is None:
                raise exc
        else:
            return
    await _update_runtime_agent_session(
        db,
        session,
        binding,
        runtime_id,
        snapshot,
    )


def _path_requires_runtime_current_alignment(path: str) -> bool:
    normalized = "/" + str(path or "").lstrip("/")
    return normalized == "/api/agent/sessions/current" or normalized.startswith("/api/agent/sessions/current/")


async def _ensure_runtime_current_session(
    binding: CodeRuntimeBinding,
    path: str,
    *,
    request: Request | None = None,
    session_id: str | int | None = None,
) -> bool:
    runtime_session_id = str(binding.runtime_session_id or "").strip()
    if not runtime_session_id or not _path_requires_runtime_current_alignment(path):
        return False
    encoded_id = quote(runtime_session_id, safe="")
    target_path = f"/api/agent/sessions/{encoded_id}/activate"
    async def runtime_request(method: str, target: str) -> dict[str, Any]:
        if request is None:
            return await _runtime_json_request(binding, method, target)
        return await _browser_runtime_json_request(
            binding,
            method,
            target,
            request=request,
            session_id=session_id if session_id is not None else binding.session_id,
        )

    try:
        await runtime_request("POST", target_path)
    except HTTPException as exc:
        if exc.status_code != 404:
            raise
        current = await runtime_request("GET", "/api/agent/sessions/current")
        binding.runtime_session_id = str(
            (current or {}).get("runtimeSessionId") or ""
        ).strip() or None
        return True
    return False


@router.get("/rail/history")
async def list_code_runtime_rail_history(
    request: Request,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
    source: Literal["local", "remote", "all"] = "remote",
    scope: Literal["user", "tenant"] = "user",
):
    started = time.monotonic()
    tenant_history = scope == "tenant"
    if tenant_history and not _can_view_tenant_code_history(ctx):
        raise HTTPException(status_code=403, detail="仅租户管理员可查看租户级 Code 历史")
    if (
        source == "remote"
        and runtime.is_desktop()
        and ctx.user.account_source == "control_plane"
    ):
        try:
            result = await _desktop_remote_rail_history(ctx, db)
        except Exception:
            sandbox_auth_metrics.record_builder_stage(
                "rail_history_remote",
                "failure",
                time.monotonic() - started,
            )
            raise
        sandbox_auth_metrics.record_builder_stage(
            "rail_history_remote",
            "success",
            time.monotonic() - started,
        )
        return result

    try:
        external_application_id = func.coalesce(
            func.nullif(func.trim(CodeRuntimeBinding.external_application_id), ""),
            func.nullif(func.trim(AIChatSession.external_application_id), ""),
        )
        source_filters = []
        if source == "local":
            source_filters.append(external_application_id.like("local-%"))
        user_scope = [] if tenant_history else [AIChatSession.user_id == ctx.user.id]
        rows = (
            await db.execute(
                select(AIChatSession, CodeRuntimeBinding)
                .outerjoin(CodeRuntimeBinding, CodeRuntimeBinding.session_id == AIChatSession.id)
                .outerjoin(Application, Application.id == AIChatSession.app_id)
                .where(
                    _code_session_scope(AIChatSession, ctx),
                    *user_scope,
                    AIChatSession.mode == "code",
                    AIChatSession.status != "archived",
                    or_(AIChatSession.app_id.is_(None), Application.app_type == "ai-code"),
                    or_(
                        Application.app_type == "ai-code",
                        and_(
                            AIChatSession.external_application_id.isnot(None),
                            AIChatSession.external_application_id != "",
                        ),
                        and_(
                            CodeRuntimeBinding.external_application_id.isnot(None),
                            CodeRuntimeBinding.external_application_id != "",
                        ),
                    ),
                    *source_filters,
                )
                .order_by(AIChatSession.updated_at.desc(), CodeRuntimeBinding.updated_at.desc(), AIChatSession.id.desc())
            )
        ).all()

        shell_session_ids = [int(session.id) for session, _binding in rows]
        snapshot_rows = []
        if shell_session_ids:
            # Early remote Code sessions predate the agent-snapshot tenant
            # identity. Their rows belong to an already authorized shell but
            # would be hidden by the control-plane tenant scope below.
            control_plane_tenant_id = _control_plane_code_tenant_id(ctx)
            if control_plane_tenant_id:
                await db.execute(
                    update(CodeRuntimeAgentSession)
                    .where(
                        CodeRuntimeAgentSession.session_id.in_(shell_session_ids),
                        CodeRuntimeAgentSession.control_plane_tenant_id.is_(None),
                    )
                    .values(control_plane_tenant_id=control_plane_tenant_id)
                    .execution_options(synchronize_session=False)
                )
                await db.flush()
            snapshot_rows = (
                await db.execute(
                    select(CodeRuntimeAgentSession)
                    .where(
                        _code_session_scope(CodeRuntimeAgentSession, ctx),
                        *([] if tenant_history else [CodeRuntimeAgentSession.user_id == ctx.user.id]),
                        CodeRuntimeAgentSession.session_id.in_(shell_session_ids),
                        CodeRuntimeAgentSession.deleted_at.is_(None),
                    )
                    .order_by(
                        func.coalesce(
                            CodeRuntimeAgentSession.last_active_at,
                            CodeRuntimeAgentSession.runtime_updated_at,
                            CodeRuntimeAgentSession.updated_at,
                        ).desc(),
                        CodeRuntimeAgentSession.id.desc(),
                    )
                )
            ).scalars().all()
        snapshots_by_shell: dict[int, list[CodeRuntimeAgentSession]] = {}
        for snapshot in snapshot_rows:
            snapshots_by_shell.setdefault(int(snapshot.session_id), []).append(snapshot)

        user_ids = {int(session.user_id) for session, _binding in rows if session.user_id}
        user_names: dict[int, str] = {}
        if user_ids:
            user_rows = await db.execute(select(User.id, User.display_name, User.username).where(User.id.in_(user_ids)))
            user_names = {
                int(user_id): str(display_name or username or user_id)
                for user_id, display_name, username in user_rows.all()
            }

        apps: list[dict[str, Any]] = []
        for session, binding in rows:
            external_id = str(
                (binding.external_application_id if binding else None)
                or session.external_application_id
                or ""
            ).strip()
            # Rails must label a legacy local shell as local even when its
            # execution_location column predates the location contract.  The
            # binding can be the authoritative application id, so normalize
            # against the resolved id rather than only the session column.
            location = normalize_code_session_location_request(
                logical_application_id=session.logical_application_id,
                external_application_id=external_id,
                execution_location=session.execution_location,
                session_policy=None,
                session_purpose=session.session_purpose,
            )

            app: dict[str, Any] = {
                "shell_session_id": ensure_code_session_public_id(session),
                "external_application_id": external_id,
                "logical_application_id": location["logical_application_id"],
                "execution_location": location["execution_location"],
                "session_purpose": location["session_purpose"],
                "app_name": session.external_app_name or session.title,
                "app_code": session.external_app_code,
                "runtime_session_id": binding.runtime_session_id if binding else None,
                "sessions": [],
            }
            if tenant_history:
                app["user_id"] = int(session.user_id)
                app["user_name"] = user_names.get(int(session.user_id), str(session.user_id))
            if not binding:
                apps.append(app)
                continue
            current_runtime_id = str(
                binding.runtime_session_id or ""
            ).strip() if binding else ""
            app["sessions"] = [
                _runtime_agent_snapshot_item(
                    snapshot,
                    current_runtime_id,
                    include_sandbox=tenant_history,
                )
                for snapshot in snapshots_by_shell.get(int(session.id), [])
            ]
            if binding and current_runtime_id and not any(
                item["runtimeSessionId"] == current_runtime_id
                for item in app["sessions"]
            ):
                app["sessions"].insert(
                    0,
                    _runtime_session_placeholder(
                        binding,
                        current_runtime_id,
                        session.title,
                        include_sandbox=tenant_history,
                    ),
                )
            apps.append(app)
        result = {"apps": apps}
    except Exception:
        sandbox_auth_metrics.record_builder_stage(
            "rail_history_db",
            "failure",
            time.monotonic() - started,
        )
        raise
    sandbox_auth_metrics.record_builder_stage(
        "rail_history_db",
        "success",
        time.monotonic() - started,
    )
    return result


@router.post("/sessions/{session_id}/agent-sessions")
async def create_code_runtime_agent_session(
    session_id: str,
    request: Request,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    session, binding = await _authorized_code_runtime_binding(db, session_id, ctx)
    payload = await _runtime_json_request_for_session(
        session,
        binding,
        "POST",
        "/api/agent/sessions",
        request=request,
        ctx=ctx,
        db=db,
        json_body={},
    )
    runtime_session_id = str(
        (payload or {}).get("runtimeSessionId")
        or (payload or {}).get("runtime_session_id")
        or (payload or {}).get("id")
        or ""
    ).strip()
    if not runtime_session_id:
        raise HTTPException(status_code=502, detail="Code runtime 未返回新会话 ID")
    binding.runtime_session_id = runtime_session_id
    await _remember_runtime_agent_session(db, session, binding, runtime_session_id, payload)
    await db.commit()
    return {
        "shell_session_id": ensure_code_session_public_id(session),
        "runtime_session_id": runtime_session_id,
        "session": payload,
    }


@router.post("/sessions/{session_id}/agent-sessions/{runtime_session_id}/activate")
async def activate_code_runtime_agent_session(
    session_id: str,
    runtime_session_id: str,
    request: Request,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    session, binding = await _authorized_code_runtime_binding(db, session_id, ctx)
    encoded_id = quote(str(runtime_session_id), safe="")
    payload = await _runtime_json_request_for_session(
        session,
        binding,
        "POST",
        f"/api/agent/sessions/{encoded_id}/activate",
        request=request,
        ctx=ctx,
        db=db,
    )
    activated_id = str((payload or {}).get("runtimeSessionId") or runtime_session_id)
    binding.runtime_session_id = activated_id
    await _remember_runtime_agent_session(db, session, binding, activated_id, payload)
    await db.commit()
    return {
        "shell_session_id": ensure_code_session_public_id(session),
        "runtime_session_id": activated_id,
        "session": payload,
    }


@router.delete("/sessions/{session_id}/agent-sessions/{runtime_session_id}")
async def delete_code_runtime_agent_session(
    session_id: str,
    runtime_session_id: str,
    request: Request,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    session, binding = await _authorized_code_runtime_binding(db, session_id, ctx)
    encoded_id = quote(str(runtime_session_id), safe="")
    payload = await _runtime_json_request_for_session(
        session,
        binding,
        "DELETE",
        f"/api/agent/sessions/{encoded_id}",
        request=request,
        ctx=ctx,
        db=db,
    )
    scoped = (
        await db.execute(
            select(CodeRuntimeAgentSession).where(
                CodeRuntimeAgentSession.session_id == session.id,
                CodeRuntimeAgentSession.runtime_session_id == str(runtime_session_id),
            )
        )
    ).scalar_one_or_none()
    if scoped:
        await db.delete(scoped)
    current = payload.get("current") if isinstance(payload, dict) else None
    if isinstance(current, dict) and current.get("runtimeSessionId"):
        binding.runtime_session_id = str(current["runtimeSessionId"])
    elif binding.runtime_session_id == runtime_session_id:
        binding.runtime_session_id = None
    await db.commit()
    return payload if isinstance(payload, dict) else {"ok": True}


def _embed_cookie_name(session_id: CodeSessionRef) -> str:
    return f"dolphin_code_runtime_{str(session_id).strip()}"


def strip_proxy_and_runtime_cookies(cookie_header: str, session_id: CodeSessionRef) -> str:
    proxy_cookie_name = _embed_cookie_name(session_id)
    forwarded: list[str] = []
    for part in str(cookie_header or "").split(";"):
        item = part.strip()
        if not item or "=" not in item:
            continue
        name, _value = item.split("=", 1)
        if name.strip() in {proxy_cookie_name, RUNTIME_COOKIE_NAME}:
            continue
        forwarded.append(item)
    return "; ".join(forwarded)


def inject_runtime_cookie(headers: dict[str, str], runtime_cookie: str) -> None:
    cookie = str(runtime_cookie or "").strip()
    if not cookie:
        return
    existing = str(headers.get("cookie") or "").strip()
    item = f"{RUNTIME_COOKIE_NAME}={cookie}"
    headers["cookie"] = f"{existing}; {item}" if existing else item


def _copyable_request_headers(request: Request, session_id: CodeSessionRef) -> dict[str, str]:
    excluded = {"host", "connection", "content-length", "cookie"}
    copied = {
        key: value
        for key, value in request.headers.items()
        if key.lower() not in excluded
    }
    cookie_header = strip_proxy_and_runtime_cookies(
        request.headers.get("cookie", ""),
        session_id,
    )
    if cookie_header:
        copied["cookie"] = cookie_header
    return copied


def _cookie_header_has_value(cookie_header: str, cookie_name: str) -> bool:
    for part in str(cookie_header or "").split(";"):
        item = part.strip()
        if not item or "=" not in item:
            continue
        name, value = item.split("=", 1)
        if name.strip() == cookie_name and value.strip():
            return True
    return False


def _cookie_header_value(cookie_header: str, cookie_name: str) -> str:
    for part in str(cookie_header or "").split(";"):
        item = part.strip()
        if not item or "=" not in item:
            continue
        name, value = item.split("=", 1)
        if name.strip() == cookie_name:
            return value.strip()
    return ""


def _runtime_request_headers(
    request: Request,
    session_id: CodeSessionRef,
    binding: CodeRuntimeBinding,
    *,
    allow_query_token: bool = False,
    runtime_cookie: str | None = None,
) -> dict[str, str]:
    headers = _copyable_request_headers(request, session_id)
    headers.pop("authorization", None)
    if is_desktop_agent_runtime_target(binding.execution_target):
        headers["authorization"] = _desktop_runtime_authorization(binding)
    else:
        inject_runtime_cookie(headers, runtime_cookie or "")
    return headers


async def _browser_runtime_json_request(
    binding: CodeRuntimeBinding,
    method: str,
    path: str,
    *,
    request: Request,
    session_id: CodeSessionRef,
    json_body: Any = None,
    runtime_cookie: str | None = None,
) -> Any:
    target = f"{binding.runtime_base_url.rstrip('/')}/{path.lstrip('/')}"
    headers = _runtime_request_headers(
        request,
        session_id,
        binding,
        runtime_cookie=runtime_cookie,
    )
    headers["accept"] = "application/json"
    if json_body is not None:
        headers["content-type"] = "application/json"
    try:
        async with httpx.AsyncClient(follow_redirects=False, timeout=60.0) as client:
            response = await client.request(method, target, headers=headers, json=json_body)
    except httpx.RequestError as exc:
        raise HTTPException(status_code=503, detail="Code runtime 暂时不可用") from exc
    if response.status_code >= 400:
        auth_error = str(response.headers.get(RUNTIME_AUTH_ERROR_HEADER) or "").strip()
        response_headers = {RUNTIME_AUTH_ERROR_HEADER: auth_error} if auth_error else None
        raise HTTPException(
            status_code=response.status_code,
            detail=response.text[:500] or "Code runtime request failed",
            headers=response_headers,
        )
    if not response.content:
        return {}
    try:
        return response.json()
    except ValueError as exc:
        raise HTTPException(status_code=502, detail="Code runtime 返回了无效 JSON") from exc


@dataclass
class ProxyRecoveryBudget:
    recovery_used: bool = False


class BrowserRuntimeRequestFailure(HTTPException):
    def __init__(
        self,
        error: HTTPException,
        authorization: ProxyAuthorization,
        *,
        renewed: bool,
    ) -> None:
        super().__init__(
            status_code=error.status_code,
            detail=error.detail,
            headers=error.headers,
        )
        self.authorization = authorization
        self.renewed = renewed


async def _browser_runtime_json_request_for_session(
    session: AIChatSession,
    binding: CodeRuntimeBinding,
    authorization: ProxyAuthorization,
    method: str,
    path: str,
    *,
    request: Request,
    session_id: CodeSessionRef,
    db: AsyncSession,
    json_body: Any = None,
    recovery_budget: ProxyRecoveryBudget | None = None,
) -> tuple[Any, ProxyAuthorization]:
    budget = recovery_budget or ProxyRecoveryBudget()
    if is_desktop_agent_runtime_target(binding.execution_target):
        return (
            await _browser_runtime_json_request(
                binding,
                method,
                path,
                request=request,
                session_id=session_id,
                json_body=json_body,
            ),
            authorization,
        )
    try:
        payload = await _browser_runtime_json_request(
            binding,
            method,
            path,
            request=request,
            session_id=session_id,
            json_body=json_body,
            runtime_cookie=authorization.runtime_cookie,
        )
        return payload, authorization
    except HTTPException as exc:
        auth_error = (exc.headers or {}).get(RUNTIME_AUTH_ERROR_HEADER)
        if exc.status_code != 401 or auth_error not in {
            "sandbox_session_expired",
            "sandbox_session_invalid",
        }:
            raise
        if budget.recovery_used:
            raise BrowserRuntimeRequestFailure(
                exc,
                authorization,
                renewed=True,
            ) from exc
    budget.recovery_used = True
    renewed = await _renew_proxy_runtime_authorization(
        session,
        binding,
        authorization,
        db,
        reason=auth_error,
    )
    try:
        payload = await _browser_runtime_json_request(
            binding,
            method,
            path,
            request=request,
            session_id=session_id,
            json_body=json_body,
            runtime_cookie=renewed.runtime_cookie,
        )
    except HTTPException as exc:
        raise BrowserRuntimeRequestFailure(
            exc,
            renewed,
            renewed=True,
        ) from exc
    return payload, renewed


async def _ensure_browser_runtime_current_session(
    session: AIChatSession,
    binding: CodeRuntimeBinding,
    authorization: ProxyAuthorization,
    path: str,
    *,
    request: Request,
    session_id: CodeSessionRef,
    db: AsyncSession,
    recovery_budget: ProxyRecoveryBudget | None = None,
) -> tuple[bool, ProxyAuthorization]:
    budget = recovery_budget or ProxyRecoveryBudget()
    runtime_session_id = str(binding.runtime_session_id or "").strip()
    if not runtime_session_id or not _path_requires_runtime_current_alignment(path):
        return False, authorization
    encoded_id = quote(runtime_session_id, safe="")
    target_path = f"/api/agent/sessions/{encoded_id}/activate"
    fallback_required = False
    try:
        _, authorization = await _browser_runtime_json_request_for_session(
            session,
            binding,
            authorization,
            "POST",
            target_path,
            request=request,
            session_id=session_id,
            db=db,
            recovery_budget=budget,
        )
    except BrowserRuntimeRequestFailure as exc:
        authorization = exc.authorization
        if exc.status_code != 404:
            raise
        fallback_required = True
    except HTTPException as exc:
        if exc.status_code != 404:
            raise
        fallback_required = True
    if fallback_required:
        current, authorization = await _browser_runtime_json_request_for_session(
            session,
            binding,
            authorization,
            "GET",
            "/api/agent/sessions/current",
            request=request,
            session_id=session_id,
            db=db,
            recovery_budget=budget,
        )
        binding.runtime_session_id = str(
            (current or {}).get("runtimeSessionId") or ""
        ).strip() or None
        return True, authorization
    return False, authorization


def _path_with_forwarded_prefix(path: str, forwarded_prefix: str = "") -> str:
    prefix = str(forwarded_prefix or "").split(",", 1)[0].strip().rstrip("/")
    target_path = "/" + str(path or "").lstrip("/")
    if prefix.startswith("/") and prefix != "/" and not target_path.startswith(prefix + "/"):
        return prefix + target_path
    return target_path


def _public_proxy_prefix(session_id: CodeSessionRef, forwarded_prefix: str = "") -> str:
    return _path_with_forwarded_prefix(code_runtime_proxy_prefix(session_id), forwarded_prefix)


def _rewrite_location_header(
    value: str,
    binding: CodeRuntimeBinding,
    session_id: CodeSessionRef,
    forwarded_prefix: str = "",
) -> str:
    if not value:
        return value
    proxy_prefix = _public_proxy_prefix(session_id, forwarded_prefix)
    runtime_base = binding.runtime_base_url.rstrip("/")
    if value == runtime_base:
        return proxy_prefix
    if value.startswith(runtime_base + "/"):
        return proxy_prefix + value[len(runtime_base):]

    base_path = urlsplit(runtime_base).path.rstrip("/")
    if value.startswith("/") and base_path:
        if value == base_path:
            return proxy_prefix
        if value.startswith(base_path + "/"):
            return proxy_prefix + value[len(base_path):]
    if value.startswith("/"):
        return proxy_prefix + value
    return value


def _query_string_without_key(raw_query: bytes | str, key_to_remove: str) -> str:
    if isinstance(raw_query, bytes):
        query_text = raw_query.decode("latin-1")
    else:
        query_text = str(raw_query or "")
    if not query_text:
        return ""

    kept: list[str] = []
    for segment in query_text.split("&"):
        if not segment:
            continue
        raw_key = segment.split("=", 1)[0]
        try:
            key = unquote_plus(raw_key)
        except Exception:
            key = raw_key
        if key == key_to_remove:
            continue
        kept.append(segment)
    return "&".join(kept)


def _request_raw_query_string(request: Request) -> bytes:
    raw_query = request.scope.get("query_string", b"")
    if isinstance(raw_query, bytes):
        return raw_query
    return str(raw_query or "").encode("latin-1")


def _redirect_target_without_dolphin_token(
    path: str,
    raw_query: bytes | str,
    forwarded_prefix: str = "",
) -> str:
    target_path = _path_with_forwarded_prefix(path, forwarded_prefix)
    qs = _query_string_without_key(raw_query, "dolphin_token")
    return f"{target_path}{'?' + qs if qs else ''}"


def _content_disposition_ascii(value: str) -> str:
    parts = [part.strip() for part in str(value or "").split(";") if part.strip()]
    disposition = parts[0] if parts else "attachment"
    kept: list[str] = []
    filename = ""
    for part in parts[1:]:
        name, separator, raw = part.partition("=")
        normalized_name = name.strip().lower()
        if separator and normalized_name == "filename":
            filename = raw.strip().strip('"')
        elif separator and normalized_name == "filename*":
            kept.append(part)
        else:
            kept.append(part)
    if not filename:
        return value.encode("latin-1", "ignore").decode("latin-1")

    fallback = "download"
    if "." in filename:
        extension = filename.rsplit(".", 1)[1]
        if extension.isascii() and extension.replace("-", "").replace("_", "").isalnum():
            fallback = f"{fallback}.{extension}"
    kept.append(f'filename="{fallback}"')
    kept.append(f"filename*=UTF-8''{quote(filename, safe='')}")
    return "; ".join([disposition, *kept])


def _copyable_response_header_value(key: str, value: str) -> str | None:
    try:
        value.encode("latin-1")
        return value
    except UnicodeEncodeError:
        if key.lower() == "content-disposition":
            return _content_disposition_ascii(value)
        return None


def _copyable_response_headers(
    headers: httpx.Headers,
    binding: CodeRuntimeBinding | None = None,
    session_id: int | None = None,
    forwarded_prefix: str = "",
    *,
    preserve_content_encoding: bool = False,
) -> dict[str, str]:
    excluded = {
        "connection",
        "content-length",
        "transfer-encoding",
    }
    if not preserve_content_encoding:
        excluded.add("content-encoding")
    copied: dict[str, str] = {}
    for key, value in headers.items():
        lowered = key.lower()
        if lowered in excluded or lowered == "set-cookie":
            continue
        safe_value = _copyable_response_header_value(key, value)
        if safe_value is not None:
            copied[key] = safe_value
    if binding is not None and session_id is not None:
        for key, value in list(copied.items()):
            if key.lower() == "location":
                copied[key] = _rewrite_location_header(value, binding, session_id, forwarded_prefix)
    return copied


def _rewrite_set_cookie_path(value: str, session_id: CodeSessionRef, forwarded_prefix: str = "") -> str:
    proxy_prefix = _public_proxy_prefix(session_id, forwarded_prefix)
    parts = [part.strip() for part in value.split(";")]
    rewritten: list[str] = []
    saw_path = False
    for part in parts:
        if part.lower().startswith("path="):
            rewritten.append(f"Path={proxy_prefix}")
            saw_path = True
        else:
            rewritten.append(part)
    if not saw_path:
        rewritten.append(f"Path={proxy_prefix}")
    return "; ".join(rewritten)


_EXTERNAL_SESSION_RAIL_INJECTION = r"""
<style id="dolphin-code-external-session-rail-style">
html.dolphin-code-external-session-rail .builder-shell[data-external-session-rail="true"] .chat-session-actions button[aria-label="\5386\53f2\4f1a\8bdd"],
html.dolphin-code-external-session-rail .builder-shell[data-external-session-rail="true"] .chat-session-actions [title="\5386\53f2\4f1a\8bdd"] {
  display: inline-flex !important;
  visibility: visible !important;
  pointer-events: auto !important;
}
html.dolphin-code-external-session-rail .builder-shell[data-external-session-rail="true"] .chat-session-history-panel {
  display: flex !important;
}
html.dolphin-code-external-session-rail button[aria-label="\65b0\5efa\4f1a\8bdd"],
html.dolphin-code-external-session-rail [title="\65b0\5efa\4f1a\8bdd"] {
  display: none !important;
  visibility: hidden !important;
  pointer-events: none !important;
}
html.dolphin-code-external-session-rail .builder-shell[data-external-session-rail="true"] .workbench-panel-open-control {
  display: inline-flex !important;
  align-items: center !important;
  justify-content: center !important;
  top: 12px !important;
  right: 64px !important;
  width: 32px !important;
  height: 32px !important;
  padding: 0 !important;
  border: 1px solid #cbd5e1 !important;
  border-radius: 6px !important;
  background: var(--code-embed-panel) !important;
  color: #334155 !important;
  box-shadow: none !important;
  visibility: visible !important;
  pointer-events: auto !important;
}
html.dolphin-code-external-session-rail .builder-shell[data-external-session-rail="true"] .workbench-panel-open-control:hover,
html.dolphin-code-external-session-rail .builder-shell[data-external-session-rail="true"] .workbench-panel-open-control:focus-visible,
html.dolphin-code-external-session-rail .builder-shell[data-external-session-rail="true"] .workbench-panel-open-control:active {
  border-color: #cbd5e1 !important;
  background: var(--code-embed-panel) !important;
  color: #334155 !important;
}
html.dolphin-code-external-session-rail .builder-shell[data-external-session-rail="true"] .workbench-panel-tabbar {
  min-height: 40px !important;
  height: 40px !important;
  padding: 4px 10px !important;
  border-bottom: 1px solid var(--code-embed-border) !important;
  background: var(--code-embed-panel) !important;
  box-sizing: border-box !important;
}
html.dolphin-code-external-session-rail .builder-shell[data-external-session-rail="true"] .workbench-panel-fixed-actions {
  gap: 6px !important;
}
html.dolphin-code-external-session-rail .builder-shell[data-external-session-rail="true"] .workbench-panel-icon-button,
html.dolphin-code-external-session-rail .builder-shell[data-external-session-rail="true"] .workspace-file-viewer-toolbar-actions button {
  display: inline-flex !important;
  align-items: center !important;
  justify-content: center !important;
  width: 32px !important;
  height: 32px !important;
  padding: 0 !important;
  border: 1px solid #cbd5e1 !important;
  border-radius: 6px !important;
  background: var(--code-embed-panel) !important;
  color: #334155 !important;
  box-shadow: none !important;
}
html.dolphin-code-external-session-rail .builder-shell[data-external-session-rail="true"] .workbench-panel-icon-button:hover,
html.dolphin-code-external-session-rail .builder-shell[data-external-session-rail="true"] .workbench-panel-icon-button:focus-visible,
html.dolphin-code-external-session-rail .builder-shell[data-external-session-rail="true"] .workbench-panel-icon-button:active,
html.dolphin-code-external-session-rail .builder-shell[data-external-session-rail="true"] .workbench-panel-icon-button-active,
html.dolphin-code-external-session-rail .builder-shell[data-external-session-rail="true"] .workspace-file-viewer-toolbar-actions button:hover,
html.dolphin-code-external-session-rail .builder-shell[data-external-session-rail="true"] .workspace-file-viewer-toolbar-actions button:focus-visible,
html.dolphin-code-external-session-rail .builder-shell[data-external-session-rail="true"] .workspace-file-viewer-toolbar-actions button:active {
  border-color: #cbd5e1 !important;
  background: var(--code-embed-panel) !important;
  color: #334155 !important;
}
html.dolphin-code-external-session-rail .builder-shell[data-external-session-rail="true"] .workspace-file-viewer-toolbar {
  min-height: 40px !important;
  height: 40px !important;
  padding: 4px 10px !important;
  border-bottom: 1px solid var(--code-embed-border) !important;
  background: var(--code-embed-panel) !important;
  box-sizing: border-box !important;
}
html.dolphin-code-external-session-rail .builder-shell[data-external-session-rail="true"] .workspace-file-viewer-layout {
  grid-template-columns: minmax(0, 1fr) minmax(240px, 300px) !important;
}
html.dolphin-code-external-session-rail .builder-shell[data-external-session-rail="true"] .workspace-file-viewer-tree {
  border-left: 1px solid var(--code-embed-border) !important;
}
html.dolphin-code-external-session-rail .workbench-shell[data-layout-state="split"] .workbench-chat-rail:has(.chat-pane-history-open) {
  min-width: 240px !important;
  max-width: 76% !important;
}
</style>
<script id="dolphin-code-external-session-rail-script">
(function(){
  window.__APAAS_SHELL__=Object.assign({},window.__APAAS_SHELL__||{},__SHELL_CONFIG__);
  document.documentElement.classList.add("dolphin-code-external-session-rail");
  var selectors=[
    "button[aria-label=\"\u65b0\u5efa\u4f1a\u8bdd\"]",
    "[title=\"\u65b0\u5efa\u4f1a\u8bdd\"]"
  ];
  var scheduled=false;
  var scheduleFrame=window.requestAnimationFrame||function(fn){return window.setTimeout(fn,50);};
  function hideElement(el){
    if (!el.hasAttribute("hidden")) el.setAttribute("hidden","");
    if (el.getAttribute("aria-hidden")!=="true") el.setAttribute("aria-hidden","true");
    if (el.style && el.style.getPropertyValue("display")!=="none") {
      el.style.setProperty("display","none","important");
    }
  }
  function concealExternalRailControls(){
    document.documentElement.classList.add("dolphin-code-external-session-rail");
    selectors.forEach(function(selector){
      document.querySelectorAll(selector).forEach(function(el){
        hideElement(el);
      });
    });
  }
  function scheduleConcealExternalRailControls(){
    if (scheduled) return;
    scheduled=true;
    scheduleFrame(function(){
      scheduled=false;
      concealExternalRailControls();
    });
  }
  scheduleConcealExternalRailControls();
  new MutationObserver(scheduleConcealExternalRailControls).observe(document.documentElement,{
    subtree:true,
    childList:true,
    attributes:true,
    attributeFilter:["class"]
  });
})();
</script>
"""


def _inject_shell_config(
    html: bytes,
    session_id: CodeSessionRef,
    origin: str,
    forwarded_prefix: str = "",
) -> bytes:
    shell_config = json.dumps(
        {
            "externalBasePath": _public_proxy_prefix(session_id, forwarded_prefix),
            "webConsoleOrigin": origin,
            "externalSessionRail": True,
            "hideHistory": True,
            "hideNewSession": True,
        },
        ensure_ascii=True,
        separators=(",", ":"),
    )
    shell_config = (
        shell_config
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("&", "\\u0026")
    )
    injection = (
        '<script id="dolphin-code-shell-config">'
        "(function(){"
        "var config=__SHELL_CONFIG__;"
        "window.__DOLPHIN_CODE_SHELL__=Object.assign({},window.__DOLPHIN_CODE_SHELL__||{},config);"
        "window.__APAAS_SHELL__=Object.assign({},window.__APAAS_SHELL__||{},config);"
        # Some local Coding runtimes do not implement the optional shell
        # protocol.  Notify the outer shell once the proxied document has
        # loaded so a healthy Runtime cannot be mistaken for a failed one.
        "var notifyReady=function(){"
        "if(window.parent===window||!config.webConsoleOrigin)return;"
        "var frameKey=new URLSearchParams(window.location.search).get('frameKey');"
        "var message={type:'builder.ready'};"
        "if(frameKey){message.frameKey=frameKey;message.payload={frameKey:frameKey};}"
        "window.parent.postMessage(message,config.webConsoleOrigin);"
        "};"
        "if(document.readyState==='complete'){notifyReady();}"
        "else{window.addEventListener('load',notifyReady,{once:true});}"
        "})();"
        "</script>"
    ).replace("__SHELL_CONFIG__", shell_config).encode("utf-8")
    marker = b"</head>"
    if marker in html:
        return html.replace(marker, injection + marker, 1)
    return injection + html


def _origin_from_absolute_url(value: str) -> str:
    parsed = urlsplit(str(value or "").strip())
    if parsed.scheme and parsed.netloc:
        return f"{parsed.scheme}://{parsed.netloc}"
    return ""


def _browser_origin_from_headers(headers, fallback: str) -> str:
    for header_name in ("origin", "referer"):
        origin = _origin_from_absolute_url(headers.get(header_name, ""))
        if origin:
            return origin

    forwarded = headers.get("forwarded", "")
    if forwarded:
        pairs: dict[str, str] = {}
        for part in forwarded.split(",", 1)[0].split(";"):
            if "=" not in part:
                continue
            key, value = part.split("=", 1)
            pairs[key.strip().lower()] = value.strip().strip('"')
        if pairs.get("proto") and pairs.get("host"):
            return f"{pairs['proto']}://{pairs['host']}"

    forwarded_host = headers.get("x-forwarded-host", "").split(",", 1)[0].strip()
    if forwarded_host:
        fallback_scheme = urlsplit(str(fallback or "")).scheme or "http"
        forwarded_proto = headers.get("x-forwarded-proto", "").split(",", 1)[0].strip() or fallback_scheme
        return f"{forwarded_proto}://{forwarded_host}"

    return _origin_from_absolute_url(fallback) or str(fallback or "").rstrip("/")


def _rewrite_runtime_dev_asset_paths(
    content: bytes,
    session_id: CodeSessionRef,
    forwarded_prefix: str = "",
) -> bytes:
    prefix = _public_proxy_prefix(session_id, forwarded_prefix).encode("utf-8")
    rewritten = content
    for root in (b"@vite/", b"@react-refresh", b"src/", b"node_modules/", b"@id/", b"@fs/"):
        rewritten = rewritten.replace(b'"/' + root, b'"' + prefix + b"/" + root)
        rewritten = rewritten.replace(b"'/" + root, b"'" + prefix + b"/" + root)
        rewritten = rewritten.replace(b"url(/" + root, b"url(" + prefix + b"/" + root)
    return rewritten


_DEV_ASSET_PREFIXES = ("src/", "@vite/", "@react-refresh", "node_modules/", "@id/", "@fs/")
_BUILDER_ASSET_CACHE_KEY = b"runtime-proxy-v4"
_BUILDER_ASSET_REFERENCE = re.compile(
    rb"(?P<quote>[\"'])(?P<path>\./(?:assets/)?[^\"'?#\s]+\.(?:js|css))(?P=quote)"
)


def _cache_bust_builder_asset_references(content: bytes) -> bytes:
    """Invalidate legacy, incorrectly encoded Builder assets after a proxy repair."""

    def replace(match: re.Match[bytes]) -> bytes:
        return (
            match.group("quote")
            + match.group("path")
            + b"?dolphin_cache_key="
            + _BUILDER_ASSET_CACHE_KEY
            + match.group("quote")
        )

    return _BUILDER_ASSET_REFERENCE.sub(replace, content)


def _buffered_builder_asset_cache_control(*, is_builder_asset: bool) -> str:
    if is_builder_asset:
        # Asset URLs receive a proxy-owned cache key in the Builder document.
        # They are therefore immutable for that key while still allowing a
        # repair release to invalidate previously malformed responses.
        return "public, max-age=31536000, immutable"
    return "no-store"


def _should_buffer_dev_asset_path(path: str) -> bool:
    return path.lstrip("/").startswith(_DEV_ASSET_PREFIXES)


def _should_rewrite_buffered_response(path: str, content_type: str) -> bool:
    if not content_type:
        return _should_buffer_dev_asset_path(path)
    lowered = content_type.lower()
    if any(kind in lowered for kind in ("text/html", "javascript", "text/css")):
        return True
    # Vite can serve TypeScript/TSX modules as text/plain in some dev-server paths.
    return _should_buffer_dev_asset_path(path)


@dataclass(frozen=True)
class ProxyAuthorization:
    browser_session_id: str
    response: Response | None = None
    runtime_cookie: str | None = field(default=None, repr=False)
    runtime_cookie_hash: str | None = None
    observed_generation: int | None = None
    proxy_cookie_reissue_required: bool = False
    proxy_cookie_token: str | None = field(default=None, repr=False)


@dataclass(frozen=True)
class UpstreamAttempt:
    response: httpx.Response
    client: httpx.AsyncClient
    recoverable_auth_error: str | None


def _recoverable_runtime_auth_error(response: httpx.Response) -> str | None:
    if response.status_code != 401:
        return None
    auth_error = str(
        response.headers.get(RUNTIME_AUTH_ERROR_HEADER) or ""
    ).strip()
    if auth_error in {"sandbox_session_expired", "sandbox_session_invalid"}:
        return auth_error
    return None


def _observability_issue_list_fallback_response(
    *,
    method: str,
    path: str,
    request: Request,
    upstream: httpx.Response,
) -> Response | None:
    if method != "GET":
        return None
    if path.strip("/") != "api/builder/observability/issues":
        return None
    if upstream.status_code not in {403, 404}:
        return None

    payload = {
        "applicationId": request.query_params.get("applicationId", ""),
        "environmentId": request.query_params.get("environmentId", ""),
        "issues": [],
        "traceId": "",
    }
    return Response(
        content=json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
        status_code=200,
        media_type="application/json",
        headers={"cache-control": "no-store"},
    )


async def _send_upstream_once(
    *,
    method: str,
    target: str,
    headers: dict[str, str],
    body: bytes,
    timeout: float | None,
) -> UpstreamAttempt:
    client = httpx.AsyncClient(follow_redirects=False, timeout=timeout)
    request = client.build_request(method, target, headers=headers, content=body)
    try:
        response = await client.send(request, stream=True)
    except httpx.RequestError as exc:
        await client.aclose()
        raise HTTPException(status_code=503, detail="Code runtime 暂时不可用") from exc
    if response.is_stream_consumed:
        response = httpx.Response(
            response.status_code,
            headers=response.headers.raw,
            stream=httpx.ByteStream(response.content),
            request=request,
            extensions=response.extensions,
        )
    return UpstreamAttempt(
        response=response,
        client=client,
        recoverable_auth_error=_recoverable_runtime_auth_error(response),
    )


async def _close_upstream_attempt(attempt: UpstreamAttempt) -> None:
    await attempt.response.aclose()
    await attempt.client.aclose()


async def _renew_proxy_runtime_authorization(
    session: AIChatSession,
    binding: CodeRuntimeBinding,
    authorization: ProxyAuthorization,
    db: AsyncSession,
    *,
    reason: str,
) -> ProxyAuthorization:
    if is_desktop_agent_runtime_target(binding.execution_target):
        raise HTTPException(
            status_code=503,
            detail="Desktop Code runtime does not support Control Plane renewal",
        )

    async def authorization_provider(
        *,
        force_refresh: bool,
        rejected_access_token: str | None,
    ) -> str:
        return await _locked_control_plane_user_authorization(
            user_id=int(session.user_id),
            force_refresh=force_refresh,
            rejected_access_token=rejected_access_token,
        )

    async def workspace_open(current_authorization: str) -> dict[str, Any]:
        return await default_workspace_open(
            binding.external_application_id,
            authorization_header=current_authorization,
            delegated_context=session,
            shell_session_id=session.id,
        )

    result = await renew_browser_runtime_session(
        binding_id=binding.id,
        browser_session_id=authorization.browser_session_id,
        observed_generation=int(
            authorization.observed_generation
            if authorization.observed_generation is not None
            else binding.auth_generation
        ),
        session_factory=AsyncSessionLocal,
        authorization_provider=authorization_provider,
        workspace_open=workspace_open,
        bootstrap=bootstrap_runtime_session,
        reason=reason,
    )
    await db.refresh(binding)
    return replace(
        authorization,
        runtime_cookie=result.runtime_cookie,
        runtime_cookie_hash=result.runtime_cookie_hash,
        observed_generation=result.generation,
        proxy_cookie_reissue_required=True,
    )


async def _proxy_authorization_from_payload(
    payload: dict[str, Any],
    *,
    db: AsyncSession | None,
    binding: CodeRuntimeBinding | None,
    shell_session: AIChatSession | None = None,
    ctx: AuthContext | None = None,
) -> ProxyAuthorization:
    browser_session_id = str(payload.get("bsid") or "").strip()
    try:
        user_id = int(payload["sub"])
        tenant_id = int(payload["tid"])
    except (KeyError, TypeError, ValueError) as exc:
        raise HTTPException(status_code=401, detail="Code runtime token invalid") from exc
    if binding is None or db is None:
        return ProxyAuthorization(browser_session_id=browser_session_id)
    control_plane_tenant_id = str(payload.get("cp_tid") or "").strip() or None
    if (
        int(binding.user_id) != user_id
        or int(binding.tenant_id) != tenant_id
        or binding.control_plane_tenant_id != control_plane_tenant_id
        or (
            shell_session is not None
            and (
                int(binding.session_id) != int(shell_session.id)
                or int(shell_session.user_id) != user_id
                or int(shell_session.tenant_id) != tenant_id
                or shell_session.control_plane_tenant_id != control_plane_tenant_id
            )
        )
        or (
            ctx is not None
            and (
                int(ctx.user.id) != user_id
                or int(ctx.tenant_id) != tenant_id
                or _control_plane_code_tenant_id(ctx) != control_plane_tenant_id
            )
        )
    ):
        raise HTTPException(status_code=401, detail="Code runtime token invalid")
    if is_desktop_agent_runtime_target(binding.execution_target):
        _desktop_runtime_authorization(binding)
        return ProxyAuthorization(browser_session_id=browser_session_id)
    browser_session = (
        await db.execute(
            select(CodeRuntimeBrowserSession).where(
                CodeRuntimeBrowserSession.binding_id == binding.id,
                CodeRuntimeBrowserSession.browser_session_id == browser_session_id,
            )
        )
    ).scalar_one_or_none()
    if browser_session is None:
        if (
            is_local_code_application_id(binding.external_application_id)
            and not binding.runtime_service_session_enc
        ):
            return ProxyAuthorization(browser_session_id=browser_session_id)
        raise HTTPException(status_code=401, detail="Code runtime token invalid")
    try:
        runtime_cookie = decrypt_runtime_cookie(browser_session.runtime_session_cookie_enc)
    except ValueError as exc:
        raise HTTPException(status_code=503, detail="Code runtime session unavailable") from exc
    return ProxyAuthorization(
        browser_session_id=browser_session_id,
        runtime_cookie=runtime_cookie,
        runtime_cookie_hash=browser_session.runtime_session_hash,
        observed_generation=int(browser_session.generation),
    )

async def _authorize_proxy_request(
    request: Request,
    session_id: CodeSessionRef,
    *,
    legacy_session_id: int | None = None,
    db: AsyncSession | None = None,
    binding: CodeRuntimeBinding | None = None,
    shell_session: AIChatSession | None = None,
    ctx: AuthContext | None = None,
) -> ProxyAuthorization:
    query_token = request.query_params.get("dolphin_token", "").strip()
    cookie_token = request.cookies.get(_embed_cookie_name(session_id), "").strip()
    if query_token:
        # The public UUID is the token subject, while the browser may already
        # have navigated to the compact s<base36(id)> route.  Validate against
        # the stable public ID for this first hop, then issue a route-scoped
        # proxy cookie below.
        token_session_id = (
            ensure_code_session_public_id(shell_session)
            if shell_session is not None
            else session_id
        )
        payload = validate_embed_token(
            query_token,
            session_id=token_session_id,
            legacy_session_id=legacy_session_id,
        )
        authorized = await _proxy_authorization_from_payload(
            payload,
            db=db,
            binding=binding,
            shell_session=shell_session,
            ctx=ctx,
        )
        proxy_token = create_proxy_cookie_token(
            session_id=session_id,
            user_id=int(payload["sub"]),
            tenant_id=int(payload["tid"]),
            control_plane_tenant_id=str(payload.get("cp_tid") or "").strip() or None,
            browser_session_id=authorized.browser_session_id,
        )
        redirect = RedirectResponse(
            _redirect_target_without_dolphin_token(
                request.url.path,
                _request_raw_query_string(request),
                request.headers.get("x-forwarded-prefix", ""),
            ),
            status_code=307,
        )
        redirect.set_cookie(
            _embed_cookie_name(session_id),
            proxy_token,
            httponly=True,
            max_age=12 * 60 * 60,
            samesite="lax",
            path=_public_proxy_prefix(session_id, request.headers.get("x-forwarded-prefix", "")),
        )
        if authorized.runtime_cookie:
            _set_runtime_cookie(
                redirect,
                authorized.runtime_cookie,
                session_id,
                request.headers.get("x-forwarded-prefix", ""),
            )
        return ProxyAuthorization(
            browser_session_id=authorized.browser_session_id,
            response=redirect,
            runtime_cookie=authorized.runtime_cookie,
            runtime_cookie_hash=authorized.runtime_cookie_hash,
            observed_generation=authorized.observed_generation,
        )
    if cookie_token:
        try:
            payload = validate_proxy_cookie_token(
                cookie_token,
                session_id=session_id,
                legacy_session_id=legacy_session_id,
            )
            proxy_cookie_expired = False
        except HTTPException:
            payload = validate_expired_proxy_cookie_token(
                cookie_token,
                session_id=session_id,
                legacy_session_id=legacy_session_id,
            )
            proxy_cookie_expired = True
        authorized = await _proxy_authorization_from_payload(
            payload,
            db=db,
            binding=binding,
            shell_session=shell_session,
            ctx=ctx,
        )
        if proxy_cookie_expired:
            return replace(
                authorized,
                proxy_cookie_reissue_required=True,
                proxy_cookie_token=create_proxy_cookie_token(
                    session_id=session_id,
                    user_id=int(payload["sub"]),
                    tenant_id=int(payload["tid"]),
                    control_plane_tenant_id=str(payload.get("cp_tid") or "").strip() or None,
                    browser_session_id=authorized.browser_session_id,
                ),
            )
        return authorized
    raise HTTPException(status_code=401, detail="Code runtime token required")


async def _authorize_shell_request(
    request: Request,
    session_id: CodeSessionRef,
    *,
    db: AsyncSession | None = None,
    binding: CodeRuntimeBinding | None = None,
    legacy_session_id: int | None = None,
    ctx: AuthContext | None = None,
    shell_session: AIChatSession | None = None,
) -> ProxyAuthorization:
    authorization = str(request.headers.get("authorization") or "").strip()
    if authorization.lower().startswith("bearer "):
        cookies = getattr(request, "cookies", {})
        cookie_token = str(
            cookies.get(_embed_cookie_name(session_id), "")
            or _cookie_header_value(
                request.headers.get("cookie", ""),
                _embed_cookie_name(session_id),
            )
        ).strip()
        if not cookie_token:
            raise HTTPException(status_code=401, detail="Code runtime token required")
        try:
            payload = validate_proxy_cookie_token(
                cookie_token,
                session_id=session_id,
                legacy_session_id=legacy_session_id,
            )
            expired = False
        except HTTPException:
            payload = validate_expired_proxy_cookie_token(
                cookie_token,
                session_id=session_id,
                legacy_session_id=legacy_session_id,
            )
            expired = True
        authorized = await _proxy_authorization_from_payload(
            payload,
            db=db,
            binding=binding,
            shell_session=shell_session,
            ctx=ctx,
        )
        if not expired:
            return authorized
        return ProxyAuthorization(
            browser_session_id=authorized.browser_session_id,
            runtime_cookie=authorized.runtime_cookie,
            runtime_cookie_hash=authorized.runtime_cookie_hash,
            observed_generation=authorized.observed_generation,
            proxy_cookie_reissue_required=True,
        )
    return await _authorize_proxy_request(
        request,
        session_id,
        legacy_session_id=legacy_session_id,
        db=db,
        binding=binding,
        shell_session=shell_session,
        ctx=ctx,
    )


def _renew_authenticated_proxy_cookie(
    response: Response,
    request: Request,
    session_id: CodeSessionRef,
    ctx: AuthContext,
    browser_session_id: str,
) -> None:
    proxy_token = create_proxy_cookie_token(
        session_id=session_id,
        user_id=int(ctx.user.id),
        tenant_id=int(ctx.tenant_id),
        control_plane_tenant_id=_control_plane_code_tenant_id(ctx),
        browser_session_id=browser_session_id,
    )
    _set_proxy_cookie(
        response,
        proxy_token,
        session_id,
        request.headers.get("x-forwarded-prefix", ""),
    )


def _set_proxy_cookie(
    response: Response,
    proxy_token: str,
    session_id: CodeSessionRef,
    forwarded_prefix: str = "",
) -> None:
    response.set_cookie(
        _embed_cookie_name(session_id),
        proxy_token,
        httponly=True,
        max_age=12 * 60 * 60,
        samesite="lax",
        path=_public_proxy_prefix(session_id, forwarded_prefix),
    )


def _set_runtime_cookie(
    response: Response,
    runtime_cookie: str,
    session_id: CodeSessionRef,
    forwarded_prefix: str = "",
) -> None:
    response.set_cookie(
        RUNTIME_COOKIE_NAME,
        runtime_cookie,
        httponly=True,
        samesite="lax",
        path=_public_proxy_prefix(session_id, forwarded_prefix),
    )


def _sandbox_renewal_failure_response(
    failure: SandboxRenewalFailure,
    *,
    session_id: CodeSessionRef,
    forwarded_prefix: str = "",
) -> Response:
    response = Response(
        content=json.dumps(
            {"detail": failure.code},
            separators=(",", ":"),
        ),
        status_code=failure.status_code,
        media_type="application/json",
    )
    if not failure.clear_cookies:
        return response
    cookie_path = _public_proxy_prefix(session_id, forwarded_prefix)
    response.delete_cookie(
        _embed_cookie_name(session_id),
        path=cookie_path,
        httponly=True,
        samesite="lax",
    )
    response.delete_cookie(
        RUNTIME_COOKIE_NAME,
        path=cookie_path,
        httponly=True,
        samesite="lax",
    )
    return response


def _browser_runtime_request_failure_response(
    failure: BrowserRuntimeRequestFailure,
    *,
    session_id: CodeSessionRef,
    forwarded_prefix: str = "",
    cookie_reissue_required: bool = False,
) -> Response:
    response = Response(
        content=json.dumps(
            {"detail": failure.detail},
            ensure_ascii=False,
            separators=(",", ":"),
        ),
        status_code=failure.status_code,
        headers=failure.headers,
        media_type="application/json",
    )
    authorization = failure.authorization
    if (
        cookie_reissue_required
        or failure.renewed
        or authorization.proxy_cookie_reissue_required
    ) and authorization.runtime_cookie:
        _set_runtime_cookie(
            response,
            authorization.runtime_cookie,
            session_id,
            forwarded_prefix,
        )
    if authorization.proxy_cookie_token:
        _set_proxy_cookie(
            response,
            authorization.proxy_cookie_token,
            session_id,
            forwarded_prefix,
        )
    return response


async def _authorized_browser_shell(
    request: Request,
    response: Response,
    session_id: CodeSessionRef,
    ctx: AuthContext,
    db: AsyncSession,
) -> tuple[AIChatSession, CodeRuntimeBinding, ProxyAuthorization]:
    session, binding = await _authorized_code_runtime_binding(db, session_id, ctx)
    authorization = await _authorize_shell_request(
        request,
        session_id,
        db=db,
        binding=binding,
        legacy_session_id=session.id,
        ctx=ctx,
        shell_session=session,
    )
    if authorization.proxy_cookie_reissue_required:
        _renew_authenticated_proxy_cookie(
            response,
            request,
            session_id,
            ctx,
            authorization.browser_session_id,
        )
    return session, binding, authorization


@proxy_router.get("/{session_id}/shell/agent-sessions")
async def list_browser_authenticated_agent_sessions(
    session_id: str,
    request: Request,
    response: Response,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    session, binding, authorization = await _authorized_browser_shell(
        request, response, session_id, ctx, db
    )
    if authorization.response is not None:
        return authorization.response
    try:
        payload, authorization = await _browser_runtime_json_request_for_session(
            session,
            binding,
            authorization,
            "GET",
            "/api/agent/sessions",
            request=request,
            session_id=session_id,
            db=db,
        )
    except SandboxRenewalFailure as exc:
        return _sandbox_renewal_failure_response(
            exc,
            session_id=session_id,
            forwarded_prefix=request.headers.get("x-forwarded-prefix", ""),
        )
    if authorization.proxy_cookie_reissue_required and authorization.runtime_cookie:
        _set_runtime_cookie(
            response,
            authorization.runtime_cookie,
            session_id,
            request.headers.get("x-forwarded-prefix", ""),
        )
    sessions = payload.get("sessions") if isinstance(payload, dict) else []
    normalized_sessions = sessions if isinstance(sessions, list) else []
    other_scoped_ids = await _runtime_session_ids_scoped_to_other_shells(db, session.id)
    normalized_sessions = _filter_browser_runtime_sessions(
        normalized_sessions,
        other_scoped_ids=other_scoped_ids,
    )
    # Conversations created inside the embedded runtime do not pass through
    # the outer rail's create endpoint.  Persist every live item observed here
    # so a later rail refresh can retain all siblings even if the runtime only
    # exposes its current conversation after a reconnect.
    for item in normalized_sessions:
        await _remember_runtime_agent_session(
            db,
            session,
            binding,
            str(item.get("runtimeSessionId") or "").strip(),
            item,
        )
    if normalized_sessions:
        await db.commit()
    current_runtime_id = str(binding.runtime_session_id or "").strip()
    if current_runtime_id and not any(
        str(item.get("runtimeSessionId") or "").strip() == current_runtime_id
        for item in normalized_sessions
    ):
        normalized_sessions.insert(
            0,
            _runtime_session_placeholder(binding, current_runtime_id, session.title),
        )
    return {"sessions": normalized_sessions}


@proxy_router.post("/{session_id}/shell/agent-sessions")
async def create_browser_authenticated_agent_session(
    session_id: str,
    request: Request,
    response: Response,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    session, binding, authorization = await _authorized_browser_shell(
        request, response, session_id, ctx, db
    )
    if authorization.response is not None:
        return authorization.response
    try:
        payload, authorization = await _browser_runtime_json_request_for_session(
            session,
            binding,
            authorization,
            "POST",
            "/api/agent/sessions",
            request=request,
            session_id=session_id,
            db=db,
            json_body={},
        )
    except SandboxRenewalFailure as exc:
        return _sandbox_renewal_failure_response(
            exc,
            session_id=session_id,
            forwarded_prefix=request.headers.get("x-forwarded-prefix", ""),
        )
    if authorization.proxy_cookie_reissue_required and authorization.runtime_cookie:
        _set_runtime_cookie(
            response,
            authorization.runtime_cookie,
            session_id,
            request.headers.get("x-forwarded-prefix", ""),
        )
    runtime_session_id = str(
        (payload or {}).get("runtimeSessionId")
        or (payload or {}).get("runtime_session_id")
        or (payload or {}).get("id")
        or ""
    ).strip()
    if not runtime_session_id:
        raise HTTPException(status_code=502, detail="Code runtime 未返回新会话 ID")
    binding.runtime_session_id = runtime_session_id
    await _remember_runtime_agent_session(db, session, binding, runtime_session_id, payload)
    await db.commit()
    return {
        "shell_session_id": ensure_code_session_public_id(session),
        "runtime_session_id": runtime_session_id,
        "session": payload,
    }


@proxy_router.post("/{session_id}/shell/agent-sessions/{runtime_session_id}/activate")
async def activate_browser_authenticated_agent_session(
    session_id: str,
    runtime_session_id: str,
    request: Request,
    response: Response,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    session, binding, authorization = await _authorized_browser_shell(
        request, response, session_id, ctx, db
    )
    if authorization.response is not None:
        return authorization.response
    encoded_id = quote(str(runtime_session_id), safe="")
    try:
        payload, authorization = await _browser_runtime_json_request_for_session(
            session,
            binding,
            authorization,
            "POST",
            f"/api/agent/sessions/{encoded_id}/activate",
            request=request,
            session_id=session_id,
            db=db,
        )
    except SandboxRenewalFailure as exc:
        return _sandbox_renewal_failure_response(
            exc,
            session_id=session_id,
            forwarded_prefix=request.headers.get("x-forwarded-prefix", ""),
        )
    if authorization.proxy_cookie_reissue_required and authorization.runtime_cookie:
        _set_runtime_cookie(
            response,
            authorization.runtime_cookie,
            session_id,
            request.headers.get("x-forwarded-prefix", ""),
    )
    activated_id = str((payload or {}).get("runtimeSessionId") or runtime_session_id)
    binding.runtime_session_id = activated_id
    await _remember_runtime_agent_session(db, session, binding, activated_id, payload)
    await db.commit()
    return {
        "shell_session_id": ensure_code_session_public_id(session),
        "runtime_session_id": activated_id,
        "session": payload,
    }


@proxy_router.delete("/{session_id}/shell/agent-sessions/{runtime_session_id}")
async def delete_browser_authenticated_agent_session(
    session_id: str,
    runtime_session_id: str,
    request: Request,
    response: Response,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    session, binding, authorization = await _authorized_browser_shell(
        request, response, session_id, ctx, db
    )
    if authorization.response is not None:
        return authorization.response
    encoded_id = quote(str(runtime_session_id), safe="")
    try:
        payload, authorization = await _browser_runtime_json_request_for_session(
            session,
            binding,
            authorization,
            "DELETE",
            f"/api/agent/sessions/{encoded_id}",
            request=request,
            session_id=session_id,
            db=db,
        )
    except SandboxRenewalFailure as exc:
        return _sandbox_renewal_failure_response(
            exc,
            session_id=session_id,
            forwarded_prefix=request.headers.get("x-forwarded-prefix", ""),
        )
    if authorization.proxy_cookie_reissue_required and authorization.runtime_cookie:
        _set_runtime_cookie(
            response,
            authorization.runtime_cookie,
            session_id,
            request.headers.get("x-forwarded-prefix", ""),
        )
    scoped = (
        await db.execute(
            select(CodeRuntimeAgentSession).where(
                CodeRuntimeAgentSession.session_id == session.id,
                CodeRuntimeAgentSession.runtime_session_id == str(runtime_session_id),
            )
        )
    ).scalar_one_or_none()
    if scoped:
        await db.delete(scoped)
    current = payload.get("current") if isinstance(payload, dict) else None
    if isinstance(current, dict) and current.get("runtimeSessionId"):
        binding.runtime_session_id = str(current["runtimeSessionId"])
    elif binding.runtime_session_id == runtime_session_id:
        binding.runtime_session_id = None
    await db.commit()
    return payload if isinstance(payload, dict) else {"ok": True}


def _target_url(binding: CodeRuntimeBinding, path: str, request: Request) -> str:
    qs = _query_string_without_key(_request_raw_query_string(request), "dolphin_token")
    rooted = "/" + path.lstrip("/")
    return f"{binding.runtime_base_url.rstrip('/')}{rooted}{'?' + qs if qs else ''}"


def _decorate_runtime_response(
    response: Response,
    upstream: httpx.Response,
    *,
    session_id: CodeSessionRef,
    forwarded_prefix: str,
    runtime_cookie: str | None,
    cookie_reissue_required: bool,
    proxy_cookie_token: str | None,
) -> Response:
    for value in upstream.headers.get_list("set-cookie"):
        response.headers.append(
            "set-cookie",
            _rewrite_set_cookie_path(value, session_id, forwarded_prefix),
        )
    if cookie_reissue_required and runtime_cookie:
        _set_runtime_cookie(response, runtime_cookie, session_id, forwarded_prefix)
    if proxy_cookie_token:
        _set_proxy_cookie(
            response,
            proxy_cookie_token,
            session_id,
            forwarded_prefix,
        )
    return response


@proxy_router.api_route(
    "/{session_id}/{path:path}",
    methods=["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
)
async def proxy_code_runtime(
    session_id: str,
    path: str,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    forwarded_prefix = request.headers.get("x-forwarded-prefix", "")
    session = await resolve_code_session(db, session_id)
    if not session or session.mode != "code":
        raise HTTPException(status_code=404, detail="Code runtime binding not found")
    binding = (
        await db.execute(select(CodeRuntimeBinding).where(CodeRuntimeBinding.session_id == session.id))
    ).scalar_one_or_none()
    if not binding:
        raise HTTPException(status_code=404, detail="Code runtime binding not found")
    try:
        authorization = await _authorize_proxy_request(
            request,
            session_id,
            legacy_session_id=session.id,
            db=db,
            binding=binding,
            shell_session=session,
        )
    except SandboxRenewalFailure as exc:
        return _sandbox_renewal_failure_response(
            exc,
            session_id=session_id,
            forwarded_prefix=forwarded_prefix,
        )
    if authorization.response is not None:
        return authorization.response
    incoming_runtime_cookie = _cookie_header_value(
        request.headers.get("cookie", ""),
        RUNTIME_COOKIE_NAME,
    )
    cookie_reissue_required = bool(
        authorization.runtime_cookie_hash
        and hashlib.sha256(incoming_runtime_cookie.encode("utf-8")).hexdigest()
        != authorization.runtime_cookie_hash
    )
    recovery_budget = ProxyRecoveryBudget()

    try:
        binding_changed, authorization = await _ensure_browser_runtime_current_session(
            session,
            binding,
            authorization,
            path,
            request=request,
            session_id=session_id,
            db=db,
            recovery_budget=recovery_budget,
        )
    except BrowserRuntimeRequestFailure as exc:
        return _browser_runtime_request_failure_response(
            exc,
            session_id=session_id,
            forwarded_prefix=forwarded_prefix,
            cookie_reissue_required=cookie_reissue_required,
        )
    except SandboxRenewalFailure as exc:
        return _sandbox_renewal_failure_response(
            exc,
            session_id=session_id,
            forwarded_prefix=forwarded_prefix,
        )
    cookie_reissue_required |= authorization.proxy_cookie_reissue_required
    if binding_changed:
        await db.commit()
    target = _target_url(binding, path, request)
    try:
        body = b"" if request.method in {"GET", "HEAD"} else await request.body()
    except ClientDisconnect:
        # Hidden hot frames abort in-flight polling when shell visibility
        # changes. That is an expected client cancellation, not an ASGI error.
        return Response(status_code=499)
    is_builder_html = (
        request.method == "GET"
        and path.rstrip("/") in {"builder", "builder/index.html"}
    )
    is_buffered_dev_asset = (
        request.method == "GET"
        and _should_buffer_dev_asset_path(path)
    )
    is_builder_asset = request.method == "GET" and path.lstrip("/").startswith("builder/assets/")
    is_buffered_builder_asset = is_buffered_dev_asset or is_builder_asset
    headers = _runtime_request_headers(
        request,
        session_id,
        binding,
        allow_query_token=True,
        runtime_cookie=authorization.runtime_cookie,
    )
    if is_builder_html or is_builder_asset:
        # Builder HTML and production assets are sometimes routed through more
        # than one proxy. Fetching them uncompressed avoids mismatched nested
        # Content-Encoding headers that leave browsers parsing gzip bytes as JS.
        headers["accept-encoding"] = "identity"
    attempt = await _send_upstream_once(
        method=request.method,
        target=target,
        headers=headers,
        body=body,
        timeout=60.0 if is_builder_html or is_buffered_builder_asset else None,
    )
    if attempt.recoverable_auth_error and not is_desktop_agent_runtime_target(
        binding.execution_target
    ) and not recovery_budget.recovery_used:
        recoverable_auth_error = attempt.recoverable_auth_error
        await _close_upstream_attempt(attempt)
        recovery_budget.recovery_used = True
        try:
            authorization = await _renew_proxy_runtime_authorization(
                session,
                binding,
                authorization,
                db,
                reason=recoverable_auth_error,
            )
        except SandboxRenewalFailure as exc:
            sandbox_auth_metrics.record_replay(request.method, "failure")
            return _sandbox_renewal_failure_response(
                exc,
                session_id=session_id,
                forwarded_prefix=forwarded_prefix,
            )
        headers = _runtime_request_headers(
            request,
            session_id,
            binding,
            allow_query_token=True,
            runtime_cookie=authorization.runtime_cookie,
        )
        attempt = await _send_upstream_once(
            method=request.method,
            target=target,
            headers=headers,
            body=body,
            timeout=60.0 if is_builder_html or is_buffered_builder_asset else None,
        )
        sandbox_auth_metrics.record_replay(
            request.method,
            "failure" if attempt.response.status_code >= 400 else "success",
        )
        cookie_reissue_required = True

    upstream = attempt.response
    fallback_response = _observability_issue_list_fallback_response(
        method=request.method,
        path=path,
        request=request,
        upstream=upstream,
    )
    if fallback_response is not None:
        try:
            return _decorate_runtime_response(
                fallback_response,
                upstream,
                session_id=session_id,
                forwarded_prefix=forwarded_prefix,
                runtime_cookie=authorization.runtime_cookie,
                cookie_reissue_required=cookie_reissue_required,
                proxy_cookie_token=authorization.proxy_cookie_token,
            )
        finally:
            await _close_upstream_attempt(attempt)

    if is_builder_html or is_buffered_builder_asset:
        try:
            content_type = upstream.headers.get("content-type", "")
            content = await upstream.aread()
            if upstream.headers.get("content-encoding", "").lower() == "gzip":
                content = gzip.decompress(content)
            if is_builder_html and "text/html" in content_type:
                content = _inject_shell_config(
                    content,
                    session_id,
                    _browser_origin_from_headers(
                        request.headers,
                        str(request.base_url).rstrip("/"),
                    ),
                    forwarded_prefix,
                )
                content = _rewrite_runtime_dev_asset_paths(
                    content,
                    session_id,
                    forwarded_prefix,
                )
            elif is_buffered_builder_asset and _should_rewrite_buffered_response(
                path,
                content_type,
            ):
                content = _rewrite_runtime_dev_asset_paths(
                    content,
                    session_id,
                    forwarded_prefix,
                )
            if is_builder_html or (
                is_buffered_builder_asset
                and _should_rewrite_buffered_response(path, content_type)
            ):
                content = _cache_bust_builder_asset_references(content)
            response_headers = _copyable_response_headers(
                upstream.headers,
                binding,
                session_id,
                forwarded_prefix,
            )
            if is_buffered_builder_asset:
                response_headers["cache-control"] = _buffered_builder_asset_cache_control(
                    is_builder_asset=is_builder_asset,
                )
            response = Response(
                content=content,
                status_code=upstream.status_code,
                headers=response_headers,
                media_type=content_type.split(";", 1)[0] if content_type else None,
            )
            return _decorate_runtime_response(
                response,
                upstream,
                session_id=session_id,
                forwarded_prefix=forwarded_prefix,
                runtime_cookie=authorization.runtime_cookie,
                cookie_reissue_required=cookie_reissue_required,
                proxy_cookie_token=authorization.proxy_cookie_token,
            )
        finally:
            await _close_upstream_attempt(attempt)

    response = StreamingResponse(
        upstream.aiter_raw(),
        status_code=upstream.status_code,
        headers=_copyable_response_headers(
            upstream.headers,
            binding,
            session_id,
            forwarded_prefix,
            preserve_content_encoding=True,
        ),
        background=BackgroundTask(_close_upstream, upstream, attempt.client),
    )
    return _decorate_runtime_response(
        response,
        upstream,
        session_id=session_id,
        forwarded_prefix=forwarded_prefix,
        runtime_cookie=authorization.runtime_cookie,
        cookie_reissue_required=cookie_reissue_required,
        proxy_cookie_token=authorization.proxy_cookie_token,
    )


async def _close_upstream(upstream: httpx.Response, client: httpx.AsyncClient) -> None:
    await upstream.aclose()
    await client.aclose()
