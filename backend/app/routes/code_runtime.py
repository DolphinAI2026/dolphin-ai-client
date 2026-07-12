from __future__ import annotations

from typing import Annotated, Any, Optional
from urllib.parse import quote, unquote_plus, urlsplit

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.background import BackgroundTask
from starlette.responses import RedirectResponse, Response, StreamingResponse

from app.code_runtime.service import (
    code_runtime_proxy_prefix,
    create_code_application,
    create_proxy_cookie_token,
    ensure_code_application,
    ensure_application_access,
    list_code_applications,
    open_code_session,
    validate_embed_token,
    validate_proxy_cookie_token,
)
from app.code_runtime.auth import (
    control_plane_access_token,
    control_plane_refresh_token,
    control_plane_token_needs_refresh,
    refresh_control_plane_token,
    store_control_plane_credentials,
)
from app.config import settings
from app.database import get_db
from app.deps import AuthContext, get_auth_context
from app.models import Application, User
from app.models.ai_chat import AIChatSession, CodeRuntimeAgentSession, CodeRuntimeBinding

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
    seed_project_id: Optional[str] = None


def _session_to_dict(session: AIChatSession) -> dict:
    return {
        "id": session.id,
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
        settings.control_plane_binding_enabled
        or provider in {"control_plane", "coding"}
    )
    if not uses_dolphin_token:
        return request.headers.get("authorization"), None
    token = control_plane_access_token(ctx.user)
    if token and not control_plane_token_needs_refresh(token):
        return f"Bearer {token}", None

    user = (
        await db.execute(
            select(User)
            .where(User.id == ctx.user.id)
            .with_for_update()
        )
    ).scalar_one()
    token = control_plane_access_token(user)
    if token and not control_plane_token_needs_refresh(token):
        return f"Bearer {token}", None

    refresh_token = control_plane_refresh_token(user)
    if not refresh_token:
        raise HTTPException(
            status_code=403,
            detail="当前账号未绑定 Control Plane，或用户 Token 已失效，请重新登录",
        )
    refreshed = await refresh_control_plane_token(refresh_token)
    store_control_plane_credentials(
        user,
        refreshed.access_token,
        refreshed.refresh_token or refresh_token,
    )
    await db.commit()
    ctx.user.coding_access_token = user.coding_access_token
    ctx.user.coding_refresh_token = user.coding_refresh_token
    return f"Bearer {refreshed.access_token}", None


@router.get("/applications")
async def list_code_runtime_applications(
    request: Request,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
    keyword: Optional[str] = None,
    provision_status: Optional[str] = Query(default=None, alias="provisionStatus"),
    page: int = 1,
    page_size: int = Query(default=50, alias="pageSize"),
):
    authorization, auth_provider = await _control_plane_request_auth(request, ctx, db)
    return await list_code_applications(
        keyword=keyword,
        provision_status=provision_status,
        page=page,
        page_size=page_size,
        authorization_header=authorization,
        delegated_context=ctx,
        auth_provider=auth_provider,
    )


@router.post("/applications")
async def create_code_runtime_application(
    body: CreateCodeApplicationRequest,
    request: Request,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    authorization, auth_provider = await _control_plane_request_auth(request, ctx, db)
    return await create_code_application(
        app_name=body.app_name,
        app_code=body.app_code,
        seed_project_id=body.seed_project_id,
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
                AIChatSession.tenant_id == ctx.tenant_id,
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


@router.post("/sessions/{session_id}/open")
async def open_code_runtime_session(
    session_id: int,
    request: Request,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    authorization, auth_provider = await _control_plane_request_auth(request, ctx, db)
    result = await open_code_session(
        db=db,
        session_id=session_id,
        ctx=ctx,
        authorization_header=authorization,
        auth_provider=auth_provider,
    )
    await db.commit()
    return result


async def _runtime_json_request(
    binding: CodeRuntimeBinding,
    method: str,
    path: str,
    *,
    json_body: Any = None,
) -> Any:
    target = f"{binding.runtime_base_url.rstrip('/')}/{path.lstrip('/')}"
    headers = {"accept": "application/json"}
    if json_body is not None:
        headers["content-type"] = "application/json"
    try:
        async with httpx.AsyncClient(follow_redirects=False, timeout=60.0) as client:
            response = await client.request(method, target, headers=headers, json=json_body)
    except httpx.RequestError as exc:
        raise HTTPException(status_code=503, detail="Code runtime 暂时不可用") from exc
    if response.status_code >= 400:
        raise HTTPException(status_code=response.status_code, detail=response.text[:500] or "Code runtime request failed")
    if not response.content:
        return {}
    try:
        return response.json()
    except ValueError as exc:
        raise HTTPException(status_code=502, detail="Code runtime 返回了无效 JSON") from exc


def _runtime_session_has_visible_title(session: dict[str, Any]) -> bool:
    return bool(str(session.get("title") or "").strip() or str(session.get("summary") or "").strip())


def _runtime_session_placeholder(binding: CodeRuntimeBinding, runtime_session_id: str) -> dict[str, Any]:
    timestamp = binding.updated_at.isoformat() if binding.updated_at else None
    return {
        "runtimeSessionId": runtime_session_id,
        "title": "未命名会话",
        "state": "running",
        "createdAt": timestamp,
        "updatedAt": timestamp,
        "lastActiveAt": timestamp,
        "current": True,
        "deletedAt": None,
        "capabilityStale": False,
        "codexSessionResumable": True,
    }


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
    return _runtime_session_placeholder(binding, runtime_session_id)


async def _authorized_code_runtime_binding(
    db: AsyncSession,
    session_id: int,
    ctx: AuthContext,
) -> tuple[AIChatSession, CodeRuntimeBinding]:
    row = (
        await db.execute(
            select(AIChatSession, CodeRuntimeBinding)
            .join(CodeRuntimeBinding, CodeRuntimeBinding.session_id == AIChatSession.id)
            .where(
                AIChatSession.id == int(session_id),
                AIChatSession.tenant_id == ctx.tenant_id,
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


async def _remember_runtime_agent_session(
    db: AsyncSession,
    session: AIChatSession,
    binding: CodeRuntimeBinding,
    runtime_session_id: str,
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
        existing = CodeRuntimeAgentSession(
            tenant_id=session.tenant_id,
            user_id=session.user_id,
            app_id=int(session.app_id) if session.app_id else None,
            session_id=session.id,
            external_application_id=binding.external_application_id,
            runtime_session_id=runtime_id,
        )
        db.add(existing)
    existing.tenant_id = session.tenant_id
    existing.user_id = session.user_id
    existing.app_id = int(session.app_id) if session.app_id else None
    existing.external_application_id = binding.external_application_id
    existing.workspace_id = binding.workspace_id
    existing.sandbox_instance_id = binding.sandbox_instance_id


def _path_requires_runtime_current_alignment(path: str) -> bool:
    normalized = "/" + str(path or "").lstrip("/")
    return normalized == "/api/agent/sessions/current" or normalized.startswith("/api/agent/sessions/current/")


async def _ensure_runtime_current_session(binding: CodeRuntimeBinding, path: str) -> None:
    runtime_session_id = str(binding.runtime_session_id or "").strip()
    if not runtime_session_id or not _path_requires_runtime_current_alignment(path):
        return
    encoded_id = quote(runtime_session_id, safe="")
    await _runtime_json_request(binding, "POST", f"/api/agent/sessions/{encoded_id}/activate")


@router.get("/rail/history")
async def list_code_runtime_rail_history(
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    rows = (
        await db.execute(
            select(AIChatSession, CodeRuntimeBinding)
            .outerjoin(CodeRuntimeBinding, CodeRuntimeBinding.session_id == AIChatSession.id)
            .outerjoin(Application, Application.id == AIChatSession.app_id)
            .where(
                AIChatSession.tenant_id == ctx.tenant_id,
                AIChatSession.user_id == ctx.user.id,
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
            )
            .order_by(AIChatSession.updated_at.desc(), CodeRuntimeBinding.updated_at.desc(), AIChatSession.id.desc())
        )
    ).all()

    apps: list[dict[str, Any]] = []
    emitted_external_ids: set[str] = set()
    for session, binding in rows:
        external_id = str(
            (binding.external_application_id if binding else None)
            or session.external_application_id
            or ""
        ).strip()
        dedupe_key = external_id or f"session:{session.id}"
        if dedupe_key in emitted_external_ids:
            continue
        emitted_external_ids.add(dedupe_key)

        app: dict[str, Any] = {
            "shell_session_id": session.id,
            "external_application_id": external_id,
            "app_name": session.external_app_name or session.title,
            "app_code": session.external_app_code,
            "runtime_session_id": binding.runtime_session_id if binding else None,
            "sessions": [],
        }
        if not binding:
            apps.append(app)
            continue
        try:
            payload = await _runtime_json_request(binding, "GET", "/api/agent/sessions")
            sessions = payload.get("sessions") if isinstance(payload, dict) else []
            normalized_sessions = sessions if isinstance(sessions, list) else []
            scoped_ids = await _scoped_runtime_session_ids(db, session.id)
            if scoped_ids:
                normalized_sessions = [
                    item for item in normalized_sessions
                    if isinstance(item, dict) and str(item.get("runtimeSessionId") or "").strip() in scoped_ids
                ]
            else:
                other_scoped_ids = await _runtime_session_ids_scoped_to_other_shells(db, session.id)
                if other_scoped_ids:
                    normalized_sessions = [
                        item for item in normalized_sessions
                        if (
                            isinstance(item, dict)
                            and str(item.get("runtimeSessionId") or "").strip() not in other_scoped_ids
                        )
                    ]
            app["sessions"] = normalized_sessions
        except HTTPException as exc:
            app["error"] = exc.detail
        current_runtime_id = str(binding.runtime_session_id or "").strip()
        if current_runtime_id:
            normalized_sessions = [item for item in app["sessions"] if isinstance(item, dict)]
            current_found = False
            for item in normalized_sessions:
                if str(item.get("runtimeSessionId") or "").strip() == current_runtime_id:
                    item["current"] = True
                    current_found = True
                    break
            if not current_found:
                normalized_sessions.insert(0, await _current_runtime_session_item(binding, current_runtime_id))
            app["sessions"] = normalized_sessions
        apps.append(app)

    return {"apps": apps}


@router.post("/sessions/{session_id}/agent-sessions")
async def create_code_runtime_agent_session(
    session_id: int,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    session, binding = await _authorized_code_runtime_binding(db, session_id, ctx)
    payload = await _runtime_json_request(binding, "POST", "/api/agent/sessions", json_body={})
    runtime_session_id = str(
        (payload or {}).get("runtimeSessionId")
        or (payload or {}).get("runtime_session_id")
        or (payload or {}).get("id")
        or ""
    ).strip()
    if not runtime_session_id:
        raise HTTPException(status_code=502, detail="Code runtime 未返回新会话 ID")
    binding.runtime_session_id = runtime_session_id
    await _remember_runtime_agent_session(db, session, binding, runtime_session_id)
    await db.commit()
    return {
        "shell_session_id": int(session_id),
        "runtime_session_id": runtime_session_id,
        "session": payload,
    }


@router.post("/sessions/{session_id}/agent-sessions/{runtime_session_id}/activate")
async def activate_code_runtime_agent_session(
    session_id: int,
    runtime_session_id: str,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    session, binding = await _authorized_code_runtime_binding(db, session_id, ctx)
    encoded_id = quote(str(runtime_session_id), safe="")
    payload = await _runtime_json_request(binding, "POST", f"/api/agent/sessions/{encoded_id}/activate")
    activated_id = str((payload or {}).get("runtimeSessionId") or runtime_session_id)
    binding.runtime_session_id = activated_id
    await _remember_runtime_agent_session(db, session, binding, activated_id)
    await db.commit()
    return {
        "shell_session_id": int(session_id),
        "runtime_session_id": activated_id,
        "session": payload,
    }


@router.delete("/sessions/{session_id}/agent-sessions/{runtime_session_id}")
async def delete_code_runtime_agent_session(
    session_id: int,
    runtime_session_id: str,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    _session, binding = await _authorized_code_runtime_binding(db, session_id, ctx)
    encoded_id = quote(str(runtime_session_id), safe="")
    payload = await _runtime_json_request(binding, "DELETE", f"/api/agent/sessions/{encoded_id}")
    scoped = (
        await db.execute(
            select(CodeRuntimeAgentSession).where(
                CodeRuntimeAgentSession.session_id == int(session_id),
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


def _embed_cookie_name(session_id: int) -> str:
    return f"dolphin_code_runtime_{int(session_id)}"


def _runtime_cookie_header(cookie_header: str, session_id: int) -> str:
    proxy_cookie_name = _embed_cookie_name(session_id)
    forwarded: list[str] = []
    for part in str(cookie_header or "").split(";"):
        item = part.strip()
        if not item or "=" not in item:
            continue
        name, _value = item.split("=", 1)
        if name.strip() == proxy_cookie_name:
            continue
        forwarded.append(item)
    return "; ".join(forwarded)


def _copyable_request_headers(request: Request, session_id: int) -> dict[str, str]:
    excluded = {"host", "connection", "content-length", "cookie"}
    copied = {
        key: value
        for key, value in request.headers.items()
        if key.lower() not in excluded
    }
    cookie_header = _runtime_cookie_header(request.headers.get("cookie", ""), session_id)
    if cookie_header:
        copied["cookie"] = cookie_header
    return copied


def _rewrite_location_header(value: str, binding: CodeRuntimeBinding, session_id: int) -> str:
    if not value:
        return value
    proxy_prefix = code_runtime_proxy_prefix(session_id)
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
    prefix = str(forwarded_prefix or "").split(",", 1)[0].strip().rstrip("/")
    target_path = "/" + str(path or "").lstrip("/")
    if prefix.startswith("/") and prefix != "/" and not target_path.startswith(prefix + "/"):
        target_path = prefix + target_path
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
) -> dict[str, str]:
    excluded = {
        "connection",
        "content-encoding",
        "content-length",
        "transfer-encoding",
    }
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
                copied[key] = _rewrite_location_header(value, binding, session_id)
    return copied


def _rewrite_set_cookie_path(value: str, session_id: int) -> str:
    parts = [part.strip() for part in value.split(";")]
    rewritten: list[str] = []
    saw_path = False
    for part in parts:
        if part.lower().startswith("path="):
            rewritten.append(f"Path={code_runtime_proxy_prefix(session_id)}")
            saw_path = True
        else:
            rewritten.append(part)
    if not saw_path:
        rewritten.append(f"Path={code_runtime_proxy_prefix(session_id)}")
    return "; ".join(rewritten)


_EXTERNAL_SESSION_RAIL_INJECTION = r"""
<style id="dolphin-code-external-session-rail-style">
html.dolphin-code-external-session-rail button[aria-label="\5386\53f2\4f1a\8bdd"],
html.dolphin-code-external-session-rail button[aria-label="\65b0\5efa\4f1a\8bdd"],
html.dolphin-code-external-session-rail [title="\5386\53f2\4f1a\8bdd"],
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
    "button[aria-label=\"\u5386\u53f2\u4f1a\u8bdd\"]",
    "button[aria-label=\"\u65b0\u5efa\u4f1a\u8bdd\"]",
    "[title=\"\u5386\u53f2\u4f1a\u8bdd\"]",
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


def _inject_shell_config(html: bytes, session_id: int, origin: str) -> bytes:
    shell_config = (
        "{"
        f"externalBasePath:{code_runtime_proxy_prefix(session_id)!r},"
        f"webConsoleOrigin:{origin!r},"
        "externalSessionRail:true,"
        "hideHistory:true,"
        "hideNewSession:true"
        "}"
    )
    injection = _EXTERNAL_SESSION_RAIL_INJECTION.replace("__SHELL_CONFIG__", shell_config).encode("utf-8")
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


def _rewrite_runtime_dev_asset_paths(content: bytes, session_id: int) -> bytes:
    prefix = code_runtime_proxy_prefix(session_id).encode("utf-8")
    rewritten = content
    for root in (b"@vite/", b"@react-refresh", b"src/", b"node_modules/", b"@id/", b"@fs/"):
        rewritten = rewritten.replace(b'"/' + root, b'"' + prefix + b"/" + root)
        rewritten = rewritten.replace(b"'/" + root, b"'" + prefix + b"/" + root)
        rewritten = rewritten.replace(b"url(/" + root, b"url(" + prefix + b"/" + root)
    return rewritten


_DEV_ASSET_PREFIXES = ("src/", "@vite/", "@react-refresh", "node_modules/", "@id/", "@fs/")


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


async def _authorize_proxy_request(request: Request, session_id: int) -> Response | None:
    query_token = request.query_params.get("dolphin_token", "").strip()
    cookie_token = request.cookies.get(_embed_cookie_name(session_id), "").strip()
    if query_token:
        payload = validate_embed_token(query_token, session_id=session_id)
        proxy_token = create_proxy_cookie_token(
            session_id=session_id,
            user_id=int(payload["sub"]),
            tenant_id=int(payload["tid"]),
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
            path=code_runtime_proxy_prefix(session_id),
        )
        return redirect
    if cookie_token:
        validate_proxy_cookie_token(cookie_token, session_id=session_id)
        return None
    raise HTTPException(status_code=401, detail="Code runtime token required")


def _target_url(binding: CodeRuntimeBinding, path: str, request: Request) -> str:
    qs = _query_string_without_key(_request_raw_query_string(request), "dolphin_token")
    rooted = "/" + path.lstrip("/")
    return f"{binding.runtime_base_url.rstrip('/')}{rooted}{'?' + qs if qs else ''}"


@proxy_router.api_route("/{session_id}/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"])
async def proxy_code_runtime(
    session_id: int,
    path: str,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    auth_response = await _authorize_proxy_request(request, session_id)
    if auth_response is not None:
        return auth_response

    binding = (
        await db.execute(select(CodeRuntimeBinding).where(CodeRuntimeBinding.session_id == int(session_id)))
    ).scalar_one_or_none()
    if not binding:
        raise HTTPException(status_code=404, detail="Code runtime binding not found")

    await _ensure_runtime_current_session(binding, path)
    target = _target_url(binding, path, request)
    body = b"" if request.method in {"GET", "HEAD"} else await request.body()
    headers = _copyable_request_headers(request, session_id)

    # Builder HTML 要注入 shell 配置，让 d-ai-code 的 runtimePath() 走 Dolphin 代理前缀。
    if request.method == "GET" and path.rstrip("/") in {"builder", "builder/index.html"}:
        async with httpx.AsyncClient(follow_redirects=False, timeout=60.0) as client:
            upstream = await client.request(request.method, target, headers=headers, content=body)
        content_type = upstream.headers.get("content-type", "")
        content = upstream.content
        if "text/html" in content_type:
            content = _inject_shell_config(
                content,
                session_id,
                _browser_origin_from_headers(request.headers, str(request.base_url).rstrip("/")),
            )
            content = _rewrite_runtime_dev_asset_paths(content, session_id)
        response = Response(
            content=content,
            status_code=upstream.status_code,
            headers=_copyable_response_headers(upstream.headers, binding, session_id),
            media_type=content_type.split(";", 1)[0] if content_type else None,
        )
        for value in upstream.headers.get_list("set-cookie"):
            response.headers.append("set-cookie", _rewrite_set_cookie_path(value, session_id))
        return response

    if request.method == "GET" and _should_buffer_dev_asset_path(path):
        async with httpx.AsyncClient(follow_redirects=False, timeout=60.0) as client:
            upstream = await client.request(request.method, target, headers=headers, content=body)
        content_type = upstream.headers.get("content-type", "")
        content = upstream.content
        if _should_rewrite_buffered_response(path, content_type):
            content = _rewrite_runtime_dev_asset_paths(content, session_id)
        response = Response(
            content=content,
            status_code=upstream.status_code,
            headers=_copyable_response_headers(upstream.headers, binding, session_id),
            media_type=content_type.split(";", 1)[0] if content_type else None,
        )
        for value in upstream.headers.get_list("set-cookie"):
            response.headers.append("set-cookie", _rewrite_set_cookie_path(value, session_id))
        return response

    client = httpx.AsyncClient(follow_redirects=False, timeout=None)
    upstream_request = client.build_request(request.method, target, headers=headers, content=body)
    upstream = await client.send(upstream_request, stream=True)
    response = StreamingResponse(
        upstream.aiter_raw(),
        status_code=upstream.status_code,
        headers=_copyable_response_headers(upstream.headers, binding, session_id),
        background=BackgroundTask(_close_upstream, upstream, client),
    )
    for value in upstream.headers.get_list("set-cookie"):
        response.headers.append("set-cookie", _rewrite_set_cookie_path(value, session_id))
    return response


async def _close_upstream(upstream: httpx.Response, client: httpx.AsyncClient) -> None:
    await upstream.aclose()
    await client.aclose()
