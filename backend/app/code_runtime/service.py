from __future__ import annotations

import os
import base64
import re
import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable, Literal
from urllib.parse import parse_qsl, quote, urlencode, urlsplit, urlunsplit
from uuid import NAMESPACE_URL, uuid4, uuid5

import httpx
from fastapi import HTTPException
from jose import JWTError, jwt
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.code_runtime.sandbox_auth import (
    RUNTIME_AUTH_ERROR_HEADER,
    bootstrap_runtime_session,
    encrypt_runtime_cookie,
    runtime_session_expiry_for_storage,
    split_entry_token,
)
from app.code_runtime.local_runtime import (
    LocalRuntimeClient,
    default_local_workspace_path,
    default_local_workspace_root,
    ensure_registered_local_workspace,
    local_workspace_path_text,
)
from app.code_runtime.execution_target import ExecutionTarget
from app.models import Application, RegisteredWorkspace
from app.models.ai_chat import (
    AIChatSession,
    CodeRuntimeAgentSession,
    CodeRuntimeBinding,
    CodeRuntimeBrowserSession,
)

WorkspaceOpen = Callable[[str, str | None], Awaitable[dict[str, Any]]]

_EMBED_TOKEN_TYPE = "code_runtime_embed"
_PROXY_COOKIE_TOKEN_TYPE = "code_runtime_proxy"
_EMBED_TOKEN_ISSUER = "ai-builder"
_DEFAULT_CONTROL_PLANE_URL = "http://127.0.0.1:8080"
_DEFAULT_SEED_PROJECT_ID = "1781233861147"
_LOCAL_APPLICATION_PREFIX = "local-"
_LEGACY_BROWSER_SESSION_ID = "legacy-browser-session"
_DESKTOP_RUNTIME_ENVIRONMENT_KEYS = (
    "DOLPHIN_LOCAL_RUNTIME_MANAGER_URL",
    "DOLPHIN_LOCAL_RUNTIME_MANAGER_TOKEN",
    "DOLPHIN_DESKTOP_DATA_DIR",
    "DOLPHIN_AGENT_RUNTIME_PATH",
)


async def _create_desktop_runtime_agent_session(
    runtime_base_url: str,
    entry_token: str,
) -> str:
    """Create one Runtime agent session without exposing the desktop entry token."""
    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(connect=5, read=30, write=10, pool=10)
        ) as client:
            response = await client.post(
                f"{runtime_base_url.rstrip('/')}/api/agent/sessions",
                headers={"Authorization": f"Bearer {entry_token}"},
            )
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail="本地 Runtime 无法创建 agent session") from exc

    if response.status_code != 200:
        raise HTTPException(status_code=502, detail="本地 Runtime 创建 agent session 失败")
    try:
        payload = response.json()
    except ValueError as exc:
        raise HTTPException(status_code=502, detail="本地 Runtime agent session 响应无效") from exc
    if not isinstance(payload, dict):
        raise HTTPException(status_code=502, detail="本地 Runtime agent session 响应无效")
    runtime_session_id = str(payload.get("runtimeSessionId") or "").strip()
    if not runtime_session_id:
        raise HTTPException(status_code=502, detail="本地 Runtime 未返回 agent session 标识")
    return runtime_session_id


async def _remember_runtime_agent_session(
    db: AsyncSession,
    *,
    session: AIChatSession,
    binding: CodeRuntimeBinding,
) -> None:
    runtime_session_id = str(binding.runtime_session_id or "").strip()
    if not runtime_session_id:
        return
    record = (
        await db.execute(
            select(CodeRuntimeAgentSession).where(
                CodeRuntimeAgentSession.session_id == session.id,
                CodeRuntimeAgentSession.runtime_session_id == runtime_session_id,
            )
        )
    ).scalar_one_or_none()
    if record is None:
        record = CodeRuntimeAgentSession(
            tenant_id=session.tenant_id,
            control_plane_tenant_id=session.control_plane_tenant_id,
            user_id=session.user_id,
            app_id=int(session.app_id) if session.app_id else None,
            session_id=session.id,
            external_application_id=binding.external_application_id,
            runtime_session_id=runtime_session_id,
        )
        db.add(record)

    record.tenant_id = session.tenant_id
    record.control_plane_tenant_id = session.control_plane_tenant_id
    record.user_id = session.user_id
    record.app_id = int(session.app_id) if session.app_id else None
    record.external_application_id = binding.external_application_id
    record.workspace_id = binding.workspace_id
    record.sandbox_instance_id = binding.sandbox_instance_id
    record.conversation_id = binding.conversation_id
    record.status = binding.status


def derive_runtime_base_url(builder_url: str) -> str:
    parsed = urlsplit(str(builder_url or "").strip())
    if not parsed.scheme or not parsed.netloc:
        raise ValueError("builder_url must be absolute")
    path = parsed.path.rstrip("/")
    marker = "/builder"
    if path.endswith(marker):
        base_path = path[: -len(marker)]
    elif marker + "/" in path:
        base_path = path.split(marker + "/", 1)[0]
    else:
        base_path = path.rsplit("/", 1)[0]
    return urlunsplit((parsed.scheme, parsed.netloc, base_path.rstrip("/"), "", ""))


def _builder_suffix(builder_url: str) -> tuple[str, list[tuple[str, str]]]:
    parsed = urlsplit(str(builder_url or "").strip())
    path = parsed.path.rstrip("/") or "/builder"
    marker = "/builder"
    if marker in path:
        suffix = path[path.index(marker):]
    else:
        suffix = "/" + path.rsplit("/", 1)[-1]
    if suffix == marker:
        suffix += "/"
    return suffix or "/builder", parse_qsl(parsed.query, keep_blank_values=True)


CodeSessionRef = str | int

_CODE_SESSION_ROUTE_RE = re.compile(r"^s([0-9a-z]+)$")
_MAX_CODE_SESSION_ID = 2_147_483_647
_BASE36_DIGITS = "0123456789abcdefghijklmnopqrstuvwxyz"


def code_session_route_id(session_id: int) -> str:
    if isinstance(session_id, bool) or not isinstance(session_id, int):
        raise ValueError("session_id must be an integer")
    if session_id <= 0 or session_id > _MAX_CODE_SESSION_ID:
        raise ValueError("session_id is outside the supported range")

    value = session_id
    encoded = ""
    while value:
        value, remainder = divmod(value, 36)
        encoded = _BASE36_DIGITS[remainder] + encoded
    return f"s{encoded}"


def decode_code_session_route_id(route_id: str) -> int | None:
    normalized = str(route_id or "").strip()
    match = _CODE_SESSION_ROUTE_RE.fullmatch(normalized)
    if not match:
        return None
    value = int(match.group(1), 36)
    if value <= 0 or value > _MAX_CODE_SESSION_ID:
        return None
    return value if code_session_route_id(value) == normalized else None


def ensure_code_session_public_id(session: AIChatSession) -> str:
    public_id = str(getattr(session, "public_id", "") or "").strip()
    if not public_id:
        session_id = getattr(session, "id", None)
        public_id = str(
            uuid5(NAMESPACE_URL, f"ai-builder:code-session:{session_id}")
            if session_id is not None
            else uuid4()
        )
        session.public_id = public_id
    return public_id


async def resolve_code_session(db: AsyncSession, session_ref: CodeSessionRef) -> AIChatSession | None:
    normalized = str(session_ref or "").strip()
    if not normalized:
        return None
    route_session_id = decode_code_session_route_id(normalized)
    if normalized.startswith("s"):
        session = await db.get(AIChatSession, route_session_id) if route_session_id else None
    else:
        session = (
            await db.execute(
                select(AIChatSession).where(AIChatSession.public_id == normalized)
            )
        ).scalar_one_or_none()
        if session is None and normalized.isdigit():
            session = await db.get(AIChatSession, int(normalized))
    if session is not None:
        ensure_code_session_public_id(session)
    return session


def code_runtime_proxy_prefix(session_id: CodeSessionRef) -> str:
    return f"/api/code-runtime/{str(session_id).strip()}"


def build_embed_url(session_id: CodeSessionRef, builder_url: str, dolphin_token: str) -> str:
    raw_query_items = urlsplit(str(builder_url or "")).query.split("&")
    if any(item.partition("=")[0] == "token" for item in raw_query_items if item):
        clean_builder_url, _entry_token = split_entry_token(builder_url)
    else:
        clean_builder_url = builder_url
    suffix, query_items = _builder_suffix(clean_builder_url)
    query_items = [
        (key, value)
        for key, value in query_items
        if key != "hideHistory"
    ]
    for key in ("externalSessionRail", "hideHistory", "hideNewSession"):
        if not any(item_key == key for item_key, _value in query_items):
            query_items.append((key, "1"))
    query_items.append(("dolphin_token", dolphin_token))
    query = urlencode(query_items)
    fragment = urlsplit(clean_builder_url).fragment
    embedded_url = f"{code_runtime_proxy_prefix(session_id)}{suffix}{'?' + query if query else ''}"
    return f"{embedded_url}#{fragment}" if fragment else embedded_url


def strip_dolphin_token_from_url(url: str) -> str:
    parsed = urlsplit(url)
    query_items = [
        (key, value)
        for key, value in parse_qsl(parsed.query, keep_blank_values=True)
        if key != "dolphin_token"
    ]
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, urlencode(query_items), parsed.fragment))


def _create_runtime_token(
    *,
    token_type: str,
    session_id: CodeSessionRef,
    user_id: int,
    tenant_id: int,
    control_plane_tenant_id: str | None,
    browser_session_id: str | None,
    minutes: int,
) -> str:
    browser_session_id = _normalize_browser_session_id(browser_session_id)
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),
        "tid": int(tenant_id),
        "sid": str(session_id),
        "bsid": browser_session_id,
        "type": token_type,
        "iat": now,
        "exp": now + timedelta(minutes=minutes),
        "iss": _EMBED_TOKEN_ISSUER,
    }
    if control_plane_tenant_id:
        payload["cp_tid"] = str(control_plane_tenant_id)
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def _normalize_browser_session_id(browser_session_id: str | None) -> str:
    value = _LEGACY_BROWSER_SESSION_ID if browser_session_id is None else str(browser_session_id).strip()
    if not value or len(value) > 64:
        raise ValueError("browser_session_id must be non-empty and at most 64 characters")
    return value


def create_embed_token(
    *,
    session_id: CodeSessionRef,
    user_id: int,
    tenant_id: int,
    control_plane_tenant_id: str | None = None,
    browser_session_id: str | None = None,
    minutes: int = 10,
) -> str:
    return _create_runtime_token(
        token_type=_EMBED_TOKEN_TYPE,
        session_id=session_id,
        user_id=user_id,
        tenant_id=tenant_id,
        control_plane_tenant_id=control_plane_tenant_id,
        browser_session_id=browser_session_id,
        minutes=minutes,
    )


def create_proxy_cookie_token(
    *,
    session_id: CodeSessionRef,
    user_id: int,
    tenant_id: int,
    control_plane_tenant_id: str | None = None,
    browser_session_id: str | None = None,
    minutes: int = 12 * 60,
) -> str:
    return _create_runtime_token(
        token_type=_PROXY_COOKIE_TOKEN_TYPE,
        session_id=session_id,
        user_id=user_id,
        tenant_id=tenant_id,
        control_plane_tenant_id=control_plane_tenant_id,
        browser_session_id=browser_session_id,
        minutes=minutes,
    )


def _validate_runtime_token(
    token: str,
    *,
    session_id: CodeSessionRef,
    token_type: str,
    browser_session_id: str | None = None,
    legacy_session_id: int | None = None,
) -> dict[str, Any]:
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret_key,
            algorithms=[settings.jwt_algorithm],
            options={"verify_aud": False},
        )
    except JWTError as exc:
        raise HTTPException(status_code=401, detail="Code runtime token invalid") from exc
    accepted_session_ids = {str(session_id)}
    if legacy_session_id is not None:
        accepted_session_ids.add(str(legacy_session_id))
    expected_browser_session_id = (
        _normalize_browser_session_id(browser_session_id)
        if browser_session_id is not None
        else None
    )
    if (
        payload.get("type") != token_type
        or str(payload.get("sid") or "") not in accepted_session_ids
        or (
            expected_browser_session_id is not None
            and str(payload.get("bsid") or "") != expected_browser_session_id
        )
    ):
        raise HTTPException(status_code=401, detail="Code runtime token invalid")
    return payload


def validate_embed_token(
    token: str,
    *,
    session_id: CodeSessionRef,
    browser_session_id: str | None = None,
    legacy_session_id: int | None = None,
) -> dict[str, Any]:
    return _validate_runtime_token(
        token,
        session_id=session_id,
        token_type=_EMBED_TOKEN_TYPE,
        browser_session_id=browser_session_id,
        legacy_session_id=legacy_session_id,
    )


def validate_proxy_cookie_token(
    token: str,
    *,
    session_id: CodeSessionRef,
    browser_session_id: str | None = None,
    legacy_session_id: int | None = None,
) -> dict[str, Any]:
    return _validate_runtime_token(
        token,
        session_id=session_id,
        token_type=_PROXY_COOKIE_TOKEN_TYPE,
        browser_session_id=browser_session_id,
        legacy_session_id=legacy_session_id,
    )


async def ensure_application_access(db: AsyncSession, app_id: int, ctx: Any) -> Application:
    app = (
        await db.execute(
            select(Application).where(
                Application.id == int(app_id),
                Application.tenant_id == int(ctx.tenant_id),
            )
        )
    ).scalar_one_or_none()
    if not app:
        raise HTTPException(status_code=404, detail="应用不存在")
    return app


def ensure_code_application(app: Application) -> Application:
    if app.app_type != "ai-code":
        raise HTTPException(status_code=400, detail="该应用不是 Code 应用")
    return app


def external_application_id_for(app: Application) -> str:
    return str(app.apaas_app_id or app.id)


def control_plane_base_url() -> str:
    return (
        os.getenv("DOLPHIN_CODE_CONTROL_PLANE_URL", "").strip()
        or (settings.dolphin_code_control_plane_url or "").strip()
        or _DEFAULT_CONTROL_PLANE_URL
    ).rstrip("/")


def _workspace_open_override_url() -> str:
    return (
        os.getenv("DOLPHIN_CODE_WORKSPACE_OPEN_URL", "").strip()
        or (settings.dolphin_code_workspace_open_url or "").strip()
    ).rstrip("/")


def workspace_open_base_url() -> str:
    return _workspace_open_override_url() or control_plane_base_url()


def workspace_open_token() -> str:
    return (
        os.getenv("DOLPHIN_CODE_WORKSPACE_OPEN_TOKEN", "").strip()
        or (settings.dolphin_code_workspace_open_token or "").strip()
    )


def _validate_workspace_open_configuration() -> None:
    has_url = bool(_workspace_open_override_url())
    has_token = bool(workspace_open_token())
    if has_url != has_token:
        raise HTTPException(
            status_code=503,
            detail="Code workspace coordinator 配置不完整",
        )


def local_builder_url() -> str:
    return (
        os.getenv("DOLPHIN_CODE_BUILDER_URL", "").strip()
        or (settings.dolphin_code_builder_url or "").strip()
    )


def local_code_applications_enabled() -> bool:
    raw = os.getenv("DOLPHIN_CODE_LOCAL_CODE_APPLICATIONS", "").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def default_seed_project_id() -> str:
    return (
        os.getenv("DOLPHIN_CODE_DEFAULT_SEED_PROJECT_ID", "").strip()
        or (settings.dolphin_code_default_seed_project_id or "").strip()
        or _DEFAULT_SEED_PROJECT_ID
    )


def _desktop_runtime_environment_present() -> bool:
    return any(os.getenv(key, "").strip() for key in _DESKTOP_RUNTIME_ENVIRONMENT_KEYS)


def _builder_prefix_path(builder_url: str) -> str:
    parsed = urlsplit(str(builder_url or "").strip())
    path = parsed.path.rstrip("/") or "/builder"
    marker = "/builder"
    if marker in path:
        return path[: path.index(marker) + len(marker)] or marker
    return path


def _builder_tail_path(builder_url: str) -> str:
    parsed = urlsplit(str(builder_url or "").strip())
    if "/builder" not in parsed.path:
        return ""
    suffix, _query = _builder_suffix(builder_url)
    marker = "/builder"
    if suffix.startswith(marker):
        return suffix[len(marker):]
    return ""


def _rebase_builder_url_to_local(builder_url: str, configured_builder_url: str) -> str:
    source = str(builder_url or "").strip()
    local = str(configured_builder_url or "").strip()
    if not source or not local:
        return source

    source_parsed = urlsplit(source)
    local_parsed = urlsplit(local)
    if not source_parsed.scheme or not source_parsed.netloc:
        return source
    if not local_parsed.scheme or not local_parsed.netloc:
        return source
    if "/builder" not in source_parsed.path:
        return source

    path = _builder_prefix_path(local) + _builder_tail_path(source)
    query_items = parse_qsl(local_parsed.query, keep_blank_values=True)
    query_items.extend(parse_qsl(source_parsed.query, keep_blank_values=True))
    return urlunsplit(
        (
            local_parsed.scheme,
            local_parsed.netloc,
            path,
            urlencode(query_items),
            source_parsed.fragment,
        )
    )


def _rebase_workspace_open_builder_urls(opened: dict[str, Any]) -> dict[str, Any]:
    configured_builder_url = local_builder_url()
    if not configured_builder_url:
        return opened

    rewritten = dict(opened)
    for key in ("specReviewUrl", "chatUrl", "builderUrl"):
        if rewritten.get(key):
            rewritten[key] = _rebase_builder_url_to_local(str(rewritten[key]), configured_builder_url)
    return rewritten


def _control_plane_headers(
    authorization_header: str | None = None,
    *,
    include_content_type: bool = False,
    delegated_context: Any | None = None,
    shell_session_id: int | None = None,
    auth_provider: str | None = None,
) -> dict[str, str]:
    headers: dict[str, str] = {}
    if include_content_type:
        headers["Content-Type"] = "application/json"
    incoming = str(authorization_header or "").strip()
    has_user_bearer = incoming.lower().startswith("bearer ")
    if has_user_bearer:
        headers["Authorization"] = incoming
    else:
        token = (
            os.getenv("DOLPHIN_CODE_CONTROL_PLANE_TOKEN", "").strip()
            or (settings.dolphin_code_control_plane_token or "").strip()
        )
        if token:
            headers["Authorization"] = f"Bearer {token}"
    workspace_tenant_id = _header_text(
        getattr(delegated_context, "control_plane_tenant_id", None)
    ) or _header_text(
        getattr(getattr(delegated_context, "user", None), "coding_tenant_id", None)
    ) or _header_text(
        getattr(delegated_context, "apaas_tenant_id", None)
    )
    if workspace_tenant_id:
        headers["X-Tenant-Id"] = workspace_tenant_id
    delegation_secret = (
        os.getenv("DOLPHIN_CODE_CONTROL_PLANE_DELEGATION_SECRET", "").strip()
        or (settings.dolphin_code_control_plane_delegation_secret or "").strip()
    )
    if not has_user_bearer and delegation_secret and delegated_context is not None:
        headers["X-AI-Builder-Delegation-Secret"] = delegation_secret
    if not has_user_bearer:
        headers.update(_delegated_identity_headers(delegated_context, shell_session_id=shell_session_id))
    return headers


def _workspace_open_headers(
    authorization_header: str | None = None,
    *,
    delegated_context: Any | None = None,
    shell_session_id: int | None = None,
    auth_provider: str | None = None,
) -> dict[str, str]:
    token = workspace_open_token()
    if token:
        return {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
        }
    return _control_plane_headers(
        authorization_header,
        include_content_type=True,
        delegated_context=delegated_context,
        shell_session_id=shell_session_id,
        auth_provider=auth_provider,
    )


def _header_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _header_b64(value: Any) -> str | None:
    text = _header_text(value)
    if not text:
        return None
    return base64.urlsafe_b64encode(text.encode("utf-8")).decode("ascii")


def _delegated_git_username(username: Any, local_user_id: Any) -> str | None:
    value = _header_text(username)
    if not value:
        return None
    if value.lower() not in {"admin", "root"}:
        return value
    suffix = re.sub(r"[^a-zA-Z0-9_-]+", "-", str(local_user_id or "user")).strip("-") or "user"
    return f"ai-builder-{value.lower()}-{suffix}"


def _delegated_identity_headers(
    ctx: Any | None,
    *,
    shell_session_id: int | None = None,
) -> dict[str, str]:
    if ctx is None:
        return {}

    user = getattr(ctx, "user", None)
    local_user_id = _header_text(getattr(user, "id", None))
    local_tenant_id = _header_text(getattr(ctx, "tenant_id", None))
    delegated_user_id = _header_text(getattr(ctx, "apaas_user_id", None)) or local_user_id
    delegated_tenant_id = _header_text(getattr(ctx, "apaas_tenant_id", None)) or local_tenant_id
    username = _delegated_git_username(getattr(user, "username", None), local_user_id)
    display_name_b64 = _header_b64(getattr(user, "display_name", None))

    headers: dict[str, str] = {}
    if delegated_user_id:
        headers["X-AI-Builder-Delegated-User-Id"] = delegated_user_id
    if delegated_tenant_id:
        headers["X-AI-Builder-Delegated-Tenant-Id"] = delegated_tenant_id
    if local_user_id:
        headers["X-AI-Builder-Local-User-Id"] = local_user_id
    if local_tenant_id:
        headers["X-AI-Builder-Local-Tenant-Id"] = local_tenant_id
    if username:
        headers["X-AI-Builder-Delegated-Username"] = username
    if display_name_b64:
        headers["X-AI-Builder-Delegated-Display-Name-B64"] = display_name_b64
    if shell_session_id is not None:
        headers["X-AI-Builder-Shell-Session-Id"] = str(int(shell_session_id))
    return headers


def _control_plane_error_detail(response: httpx.Response) -> str:
    text = (response.text or "").strip()
    if response.status_code in (401, 403):
        return text[:500] or "Code Control Plane 认证失败，请配置 DOLPHIN_CODE_CONTROL_PLANE_TOKEN 或使用统一登录认证"
    return text[:500] or "Code Control Plane request failed"


def _control_plane_error_code(response: httpx.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        return ""
    if not isinstance(payload, dict):
        return ""
    return str(payload.get("code") or payload.get("errorCode") or "").strip().upper()


def _is_loopback_builder_url(builder_url: str) -> bool:
    hostname = (urlsplit(str(builder_url or "").strip()).hostname or "").lower()
    return hostname in {"127.0.0.1", "localhost", "::1"}


def _local_application_data(*, app_name: str, app_code: str) -> dict[str, Any]:
    return {
        "applicationId": f"{_LOCAL_APPLICATION_PREFIX}{uuid4().hex}",
        "appCode": app_code,
        "appName": app_name,
        "description": None,
        "provisionStatus": "READY",
    }


def default_local_code_application_workspace(app_code: str) -> dict[str, str]:
    root = default_local_workspace_root().expanduser().resolve(strict=False)
    path = default_local_workspace_path(app_code).expanduser().resolve(strict=False)
    return {
        "workspace_root": local_workspace_path_text(root),
        "workspace_path": local_workspace_path_text(path),
    }


def is_local_code_application_id(application_id: str) -> bool:
    return str(application_id or "").strip().startswith(_LOCAL_APPLICATION_PREFIX)


def _status_to_local_status(status: str | None) -> str:
    normalized = str(status or "").strip().upper()
    if normalized in {"READY", "COMPLETED", "COMPLETE", "SUCCEEDED", "SUCCESS"}:
        return "completed"
    if normalized in {"FAILED", "FAILURE", "ERROR"}:
        return "failed"
    if normalized in {"PROVISIONING", "CREATING", "PENDING", "RUNNING", "STARTING"}:
        return "generating"
    return "draft"


def _normalize_code_application(item: dict[str, Any]) -> dict[str, Any]:
    external_id = str(item.get("applicationId") or item.get("id") or item.get("appId") or "").strip()
    app_code = str(item.get("appCode") or item.get("app_code") or external_id or "").strip()
    app_name = str(item.get("appName") or item.get("app_name") or app_code or external_id or "Code 应用").strip()
    status = str(item.get("provisionStatus") or item.get("status") or "").strip() or "UNKNOWN"
    return {
        "id": external_id,
        "external_application_id": external_id,
        "app_name": app_name,
        "app_code": app_code,
        "description": item.get("description"),
        "source": "d-ai-code",
        "app_type": "ai-code",
        "status": status,
        "local_status": _status_to_local_status(status),
        "remote_status": status,
        "models": 0,
        "forms": 0,
        "roles": 0,
        "dicts": 0,
        "repository": item.get("repository"),
        "owner": item.get("owner"),
        "created_at": item.get("createdAt") or item.get("created_at"),
        "updated_at": item.get("updatedAt") or item.get("updated_at"),
    }


async def list_code_applications(
    *,
    source: Literal["local", "remote"] = "remote",
    keyword: str | None = None,
    provision_status: str | None = None,
    page: int = 1,
    page_size: int = 50,
    authorization_header: str | None = None,
    delegated_context: Any | None = None,
    auth_provider: str | None = None,
    db: AsyncSession | None = None,
    ctx: Any | None = None,
) -> dict[str, Any]:
    if source == "local":
        if db is None or ctx is None:
            raise HTTPException(status_code=400, detail="本地应用列表缺少工作区上下文")
        rows = (
            await db.execute(
                select(RegisteredWorkspace)
                .where(
                    RegisteredWorkspace.tenant_id == int(ctx.tenant_id),
                    RegisteredWorkspace.user_id == int(ctx.user.id),
                    RegisteredWorkspace.apaas_app_id.like(f"{_LOCAL_APPLICATION_PREFIX}%"),
                )
                .order_by(RegisteredWorkspace.last_opened_at.desc(), RegisteredWorkspace.id.desc())
            )
        ).scalars().all()
        normalized_keyword = str(keyword or "").strip().lower()
        items: list[dict[str, Any]] = []
        for workspace in rows:
            application_id = str(workspace.apaas_app_id or "").strip()
            workspace_path = local_workspace_path_text(workspace.abs_path)
            app_code = Path(workspace_path).name
            app_name = str(workspace.display_name or app_code).strip() or app_code
            if normalized_keyword and normalized_keyword not in " ".join(
                (app_name, app_code, workspace_path)
            ).lower():
                continue
            created_at = workspace.created_at.isoformat() if workspace.created_at else None
            updated_at = workspace.last_opened_at.isoformat() if workspace.last_opened_at else created_at
            items.append({
                "id": application_id,
                "external_application_id": application_id,
                "app_name": app_name,
                "app_code": app_code,
                "description": None,
                "source": "desktop-local",
                "app_type": "ai-code",
                "status": "READY",
                "local_status": "completed",
                "remote_status": None,
                "models": 0,
                "forms": 0,
                "roles": 0,
                "dicts": 0,
                "local_workspace_path": workspace_path,
                "workspace_id": workspace.ws_id,
                "repository": None,
                "owner": None,
                "created_at": created_at,
                "updated_at": updated_at,
            })
        current_page = max(1, int(page or 1))
        current_page_size = max(1, int(page_size or 50))
        start = (current_page - 1) * current_page_size
        return {
            "items": items[start:start + current_page_size],
            "page": current_page,
            "pageSize": current_page_size,
            "total": len(items),
            "source": "desktop-local",
        }
    if local_code_applications_enabled():
        return {
            "items": [],
            "page": max(1, int(page or 1)),
            "pageSize": max(1, int(page_size or 50)),
            "total": 0,
            "source": "d-ai-code-local",
        }
    base_url = control_plane_base_url()
    params: dict[str, Any] = {"page": max(1, int(page or 1)), "pageSize": max(1, int(page_size or 50))}
    if str(keyword or "").strip():
        params["keyword"] = str(keyword).strip()
    if str(provision_status or "").strip():
        params["provisionStatus"] = str(provision_status).strip()
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(connect=10, read=30, write=10, pool=10)) as client:
            response = await client.get(
                f"{base_url}/api/applications",
                headers=_control_plane_headers(
                    authorization_header,
                    delegated_context=delegated_context,
                    auth_provider=auth_provider,
                ),
                params=params,
            )
    except httpx.RequestError as exc:
        raise HTTPException(status_code=503, detail=f"无法连接 Code Control Plane: {base_url}") from exc
    if response.status_code >= 400:
        raise HTTPException(status_code=response.status_code, detail=_control_plane_error_detail(response))

    try:
        data = response.json()
    except ValueError as exc:
        raise HTTPException(
            status_code=502,
            detail="Code Control Plane 应用列表响应无效，请检查 DOLPHIN_CODE_CONTROL_PLANE_URL",
        ) from exc
    if not isinstance(data, dict):
        raise HTTPException(
            status_code=502,
            detail="Code Control Plane 应用列表响应无效，请检查 DOLPHIN_CODE_CONTROL_PLANE_URL",
        )

    items = data.get("items")
    if not isinstance(items, list):
        raise HTTPException(status_code=502, detail="Code Control Plane 应用列表数据无效")
    return {
        "items": [_normalize_code_application(item) for item in items if isinstance(item, dict)],
        "page": data.get("page", params["page"]),
        "pageSize": data.get("pageSize", params["pageSize"]),
        "total": data.get("total", len(items)),
        "source": "d-ai-code",
    }


async def create_code_application(
    *,
    app_name: str,
    app_code: str,
    seed_project_id: str | None = None,
    local_application: bool = False,
    local_workspace_path: str | None = None,
    db: AsyncSession | None = None,
    ctx: Any | None = None,
    authorization_header: str | None = None,
    delegated_context: Any | None = None,
    auth_provider: str | None = None,
) -> dict[str, Any]:
    name = str(app_name or "").strip()
    code = str(app_code or "").strip()
    seed_id = str(seed_project_id or default_seed_project_id()).strip()
    if not name:
        raise HTTPException(status_code=400, detail="app_name 不能为空")
    if not code:
        raise HTTPException(status_code=400, detail="app_code 不能为空")
    if not seed_id:
        raise HTTPException(status_code=400, detail="seed_project_id 不能为空")

    if local_application or str(local_workspace_path or "").strip():
        if db is None or ctx is None:
            raise HTTPException(status_code=400, detail="本地应用创建缺少工作区上下文")
        data = _local_application_data(app_name=name, app_code=code)
        workspace = await ensure_registered_local_workspace(
            db,
            ctx,
            application_id=str(data["applicationId"]),
            display_name=name,
            workspace_path=local_workspace_path or default_local_workspace_path(code),
        )
        normalized = _normalize_code_application(data)
        normalized["source"] = "desktop-local"
        normalized["remote_status"] = None
        normalized["local_workspace_path"] = workspace.abs_path
        normalized["workspace_id"] = workspace.ws_id
        return normalized

    if local_code_applications_enabled():
        return _normalize_code_application(_local_application_data(app_name=name, app_code=code))

    base_url = control_plane_base_url()
    body = {
        "appCode": code,
        "appName": name,
        "seedProjectId": seed_id,
    }
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(connect=10, read=60, write=10, pool=10)) as client:
            response = await client.post(
                f"{base_url}/api/applications",
                headers=_control_plane_headers(
                    authorization_header,
                    include_content_type=True,
                    delegated_context=delegated_context,
                    auth_provider=auth_provider,
                ),
                json=body,
            )
    except httpx.RequestError as exc:
        raise HTTPException(status_code=503, detail=f"无法连接 Code Control Plane: {base_url}") from exc
    if response.status_code >= 400:
        builder_url = local_builder_url()
        if (
            response.status_code == 404
            and _control_plane_error_code(response) == "SEED_PROJECT_NOT_FOUND"
            and _is_loopback_builder_url(builder_url)
        ):
            return _normalize_code_application(_local_application_data(app_name=name, app_code=code))
        raise HTTPException(status_code=response.status_code, detail=_control_plane_error_detail(response))
    data = response.json()
    if not isinstance(data, dict):
        raise HTTPException(status_code=502, detail="Code Control Plane 返回了无效应用数据")
    return _normalize_code_application(data)


async def verify_control_plane_application_access(
    external_application_id: str,
    *,
    authorization_header: str | None = None,
    delegated_context: Any | None = None,
    auth_provider: str | None = None,
) -> None:
    application_id = str(external_application_id or "").strip()
    if not application_id:
        raise HTTPException(status_code=400, detail="external_application_id 不能为空")

    base_url = control_plane_base_url()
    target = f"{base_url}/api/applications/{quote(application_id, safe='')}"
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(connect=10, read=30, write=10, pool=10)) as client:
            response = await client.get(
                target,
                headers=_control_plane_headers(
                    authorization_header,
                    delegated_context=delegated_context,
                    auth_provider=auth_provider,
                ),
            )
    except httpx.RequestError as exc:
        raise HTTPException(status_code=503, detail=f"无法连接 Code Control Plane: {base_url}") from exc
    if response.status_code >= 400:
        raise HTTPException(
            status_code=response.status_code,
            detail=_control_plane_error_detail(response),
        )

    try:
        payload = response.json()
    except ValueError as exc:
        raise HTTPException(status_code=502, detail="Code Control Plane 返回了无效应用数据") from exc
    if not isinstance(payload, dict) or str(payload.get("applicationId") or "").strip() != application_id:
        raise HTTPException(status_code=502, detail="Code Control Plane 返回了无效应用数据")


def local_builder_workspace_open(external_application_id: str) -> dict[str, Any]:
    builder_url = local_builder_url()
    if not builder_url:
        raise HTTPException(status_code=503, detail=f"无法连接 Code Control Plane: {control_plane_base_url()}")
    return {
        "applicationId": external_application_id,
        "workspaceId": f"local-builder-{external_application_id}",
        "sandboxInstanceId": "local-builder",
        "conversationId": None,
        "specReviewUrl": builder_url,
    }


async def default_workspace_open(
    external_application_id: str,
    handoff_id: str | None = None,
    *,
    authorization_header: str | None = None,
    delegated_context: Any | None = None,
    shell_session_id: int | None = None,
    auth_provider: str | None = None,
) -> dict[str, Any]:
    if is_local_code_application_id(external_application_id):
        return local_builder_workspace_open(external_application_id)

    _validate_workspace_open_configuration()
    if workspace_open_token():
        if not str(authorization_header or "").strip().lower().startswith("bearer "):
            raise HTTPException(
                status_code=401,
                detail="Code workspace 用户鉴权不可用",
            )
        await verify_control_plane_application_access(
            external_application_id,
            authorization_header=authorization_header,
            delegated_context=delegated_context,
            auth_provider=auth_provider,
        )
    base_url = workspace_open_base_url()
    body = {"handoffId": handoff_id} if handoff_id else None
    target = f"{base_url}/api/applications/{external_application_id}/workspace/open"
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(
            connect=10,
            read=settings.dolphin_code_workspace_open_timeout_seconds,
            write=10,
            pool=10,
        )) as client:
            response = await client.post(
                target,
                headers=_workspace_open_headers(
                    authorization_header,
                    delegated_context=delegated_context,
                    shell_session_id=shell_session_id,
                    auth_provider=auth_provider,
                ),
                json=body,
            )
    except httpx.RequestError as exc:
        if local_builder_url():
            return local_builder_workspace_open(external_application_id)
        raise HTTPException(status_code=503, detail=f"无法连接 Code Control Plane: {base_url}") from exc
    if response.status_code >= 400:
        if workspace_open_token() and response.status_code in {401, 403}:
            raise HTTPException(
                status_code=503,
                detail="Code workspace coordinator 鉴权失败",
            )
        raise HTTPException(status_code=response.status_code, detail=response.text[:500] or "Code workspace open failed")
    opened = response.json()
    if isinstance(opened, dict):
        return _rebase_workspace_open_builder_urls(opened)
    return opened


async def open_code_session(
    *,
    db: AsyncSession,
    session_id: CodeSessionRef,
    ctx: Any,
    workspace_open: WorkspaceOpen | None = None,
    embed_token_factory: Callable[..., str] = create_embed_token,
    handoff_id: str | None = None,
    authorization_header: str | None = None,
    auth_provider: str | None = None,
    browser_session_id: str | None = None,
    on_local_phase: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    session = await resolve_code_session(db, session_id)
    if session is not None:
        session = (
            await db.execute(
                select(AIChatSession)
                .where(AIChatSession.id == session.id)
                .with_for_update()
            )
        ).scalar_one_or_none()
    control_plane_tenant_id = str(getattr(ctx, "control_plane_tenant_id", "") or "").strip()
    is_control_plane_code = (
        str(getattr(getattr(ctx, "user", None), "account_source", "") or "").strip().lower()
        == "control_plane"
    )
    matches_tenant = (
        session is not None
        and (
            session.control_plane_tenant_id == control_plane_tenant_id
            if is_control_plane_code and control_plane_tenant_id
            else session.tenant_id == int(ctx.tenant_id)
        )
    )
    if not session or not matches_tenant or session.user_id != int(ctx.user.id):
        raise HTTPException(status_code=404, detail="Code 会话不存在")
    if session.mode != "code":
        raise HTTPException(status_code=400, detail="该会话不是 Code 会话")
    external_app_id = str(getattr(session, "external_application_id", "") or "").strip()
    if session.app_id:
        app = ensure_code_application(await ensure_application_access(db, session.app_id, ctx))
        external_app_id = external_application_id_for(app)
    if not external_app_id:
        raise HTTPException(status_code=400, detail="Code 会话未绑定应用")

    desktop_entry_token: str | None = None
    desktop_runtime = is_local_code_application_id(external_app_id)
    bootstrap = None

    async def workspace_open_once() -> dict[str, Any]:
        if workspace_open is not None:
            return await workspace_open(external_app_id, handoff_id)
        return await default_workspace_open(
            external_app_id,
            handoff_id,
            authorization_header=authorization_header,
            delegated_context=ctx,
            shell_session_id=session.id,
            auth_provider=auth_provider,
        )

    if desktop_runtime:
        local_runtime = LocalRuntimeClient.from_environment()
        if on_local_phase is None:
            opened, desktop_entry_token = await local_runtime.open_application_with_entry_token(
                db,
                session,
                ctx,
            )
        else:
            opened, desktop_entry_token = await local_runtime.open_application_with_entry_token(
                db,
                session,
                ctx,
                on_phase=on_local_phase,
            )
    else:
        opened = await workspace_open_once()
    builder_url = str(opened.get("specReviewUrl") or opened.get("builderUrl") or "").strip()
    if not builder_url:
        raise HTTPException(status_code=502, detail="Code Control Plane 未返回 builder URL")

    if desktop_runtime or is_local_code_application_id(external_app_id):
        clean_builder_url = builder_url
        runtime_base_url = derive_runtime_base_url(builder_url)
    else:
        for bootstrap_attempt in range(2):
            try:
                bootstrap = await bootstrap_runtime_session(builder_url)
                break
            except HTTPException as exc:
                auth_error = str(
                    (exc.headers or {}).get(RUNTIME_AUTH_ERROR_HEADER) or ""
                ).strip()
                if (
                    auth_error == "sandbox_launch_token_expired"
                    and bootstrap_attempt == 0
                ):
                    opened = await workspace_open_once()
                    builder_url = str(
                        opened.get("specReviewUrl") or opened.get("builderUrl") or ""
                    ).strip()
                    if not builder_url:
                        raise HTTPException(
                            status_code=502,
                            detail="Code Control Plane 未返回 builder URL",
                        )
                    continue
                raise
            except ValueError as exc:
                raise HTTPException(
                    status_code=502,
                    detail="Code Control Plane 未返回 runtime entry token",
                ) from exc
        if bootstrap is None:
            raise HTTPException(status_code=503, detail="Code runtime 暂时不可用")
        clean_builder_url = bootstrap.clean_builder_url
        runtime_base_url = bootstrap.runtime_base_url

    runtime_session_id = (
        opened.get("runtimeSessionId")
        or (opened.get("session") or {}).get("runtimeSessionId")
        or None
    )

    binding = (
        await db.execute(select(CodeRuntimeBinding).where(CodeRuntimeBinding.session_id == session.id))
    ).scalar_one_or_none()
    is_new_binding = binding is None
    if not binding:
        binding = CodeRuntimeBinding(
            tenant_id=session.tenant_id,
            control_plane_tenant_id=session.control_plane_tenant_id,
            user_id=session.user_id,
            app_id=int(session.app_id) if session.app_id else None,
            session_id=session.id,
            external_application_id=external_app_id,
            runtime_base_url=runtime_base_url,
            builder_url=clean_builder_url,
        )
        db.add(binding)

    previous_sandbox_instance_id = str(binding.sandbox_instance_id or "").strip()
    opened_sandbox_instance_id = str(opened.get("sandboxInstanceId") or "").strip()
    desktop_runtime_instance_changed = bool(
        desktop_runtime
        and previous_sandbox_instance_id
        and opened_sandbox_instance_id
        and previous_sandbox_instance_id != opened_sandbox_instance_id
    )

    binding.tenant_id = session.tenant_id
    binding.control_plane_tenant_id = session.control_plane_tenant_id
    binding.user_id = session.user_id
    binding.app_id = int(session.app_id) if session.app_id else None
    binding.external_application_id = external_app_id
    binding.runtime_base_url = runtime_base_url
    binding.builder_url = clean_builder_url
    binding.workspace_id = opened.get("workspaceId") or binding.workspace_id
    binding.sandbox_instance_id = opened_sandbox_instance_id or binding.sandbox_instance_id
    if desktop_runtime:
        if not desktop_entry_token:
            raise HTTPException(status_code=503, detail="本地 Runtime entry token 不可用")
        if desktop_runtime_instance_changed:
            await db.execute(
                delete(CodeRuntimeAgentSession).where(
                    CodeRuntimeAgentSession.session_id == session.id
                )
            )
        current_runtime_session_id = (
            ""
            if desktop_runtime_instance_changed
            else str(binding.runtime_session_id or "").strip()
        )
        runtime_session_id = (
            current_runtime_session_id
            if current_runtime_session_id
            else await _create_desktop_runtime_agent_session(
                runtime_base_url,
                desktop_entry_token,
            )
        )
        binding.runtime_session_id = runtime_session_id
    if runtime_session_id:
        current_runtime_session_id = str(binding.runtime_session_id or "").strip()
        current_is_scoped = False
        if current_runtime_session_id:
            current_is_scoped = (
                await db.execute(
                    select(CodeRuntimeAgentSession).where(
                        CodeRuntimeAgentSession.session_id == session.id,
                        CodeRuntimeAgentSession.runtime_session_id == current_runtime_session_id,
                    )
                )
            ).scalar_one_or_none() is not None
        if not current_is_scoped:
            binding.runtime_session_id = runtime_session_id
    binding.conversation_id = opened.get("conversationId") or binding.conversation_id
    binding.status = "ready"
    binding.last_error = None
    if desktop_runtime:
        binding.execution_target = ExecutionTarget.DESKTOP_AGENT_RUNTIME.value
        binding.desktop_agent_runtime_token_enc = encrypt_runtime_cookie(desktop_entry_token)
    await db.flush()
    if desktop_runtime:
        await _remember_runtime_agent_session(db, session=session, binding=binding)
        await db.flush()

    resolved_browser_session_id = None
    if bootstrap is not None:
        binding.runtime_service_session_enc = encrypt_runtime_cookie(bootstrap.runtime_cookie)
        binding.auth_generation = 1 if is_new_binding else int(binding.auth_generation or 0) + 1
        resolved_browser_session_id = (
            str(browser_session_id or "").strip() or secrets.token_urlsafe(32)
        )
        browser_session = (
            await db.execute(
                select(CodeRuntimeBrowserSession).where(
                    CodeRuntimeBrowserSession.binding_id == binding.id,
                    CodeRuntimeBrowserSession.browser_session_id
                    == resolved_browser_session_id,
                )
            )
        ).scalar_one_or_none()
        if browser_session is None:
            browser_session = CodeRuntimeBrowserSession(
                binding_id=binding.id,
                browser_session_id=resolved_browser_session_id,
                runtime_session_cookie_enc="",
                runtime_session_hash="",
                generation=binding.auth_generation,
            )
            db.add(browser_session)
        browser_session.runtime_session_cookie_enc = encrypt_runtime_cookie(
            bootstrap.runtime_cookie
        )
        browser_session.runtime_session_hash = bootstrap.runtime_cookie_hash
        browser_session.runtime_session_expires_at = runtime_session_expiry_for_storage(
            bootstrap.expires_at
        )
        browser_session.generation = binding.auth_generation
        await db.flush()

    public_id = ensure_code_session_public_id(session)
    route_id = code_session_route_id(session.id)
    token = embed_token_factory(
        session_id=public_id,
        user_id=session.user_id,
        tenant_id=session.tenant_id,
        control_plane_tenant_id=session.control_plane_tenant_id,
        browser_session_id=resolved_browser_session_id,
    )
    return {
        "session_id": public_id,
        "route_id": route_id,
        "app_id": session.app_id,
        "external_application_id": external_app_id,
        "workspace_id": binding.workspace_id,
        "sandbox_instance_id": binding.sandbox_instance_id,
        "runtime_session_id": binding.runtime_session_id,
        "external_base_path": code_runtime_proxy_prefix(route_id),
        "embed_url": build_embed_url(route_id, clean_builder_url, token),
    }
