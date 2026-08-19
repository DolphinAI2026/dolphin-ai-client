from __future__ import annotations

import asyncio
import hashlib
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from http.cookies import SimpleCookie
from typing import Any, Callable
from urllib.parse import quote, unquote_plus, urlsplit, urlunsplit

import httpx
from fastapi import HTTPException
from jose import JWTError, jwt
from sqlalchemy import select

from app.config import settings
from app.code_runtime.sandbox_metrics import (
    SandboxAuthMetricsRegistry,
    sandbox_auth_metrics,
)
from app.crypto import decrypt_password, encrypt_password

RUNTIME_COOKIE_NAME = "apaas_sandbox_token"
_ENCRYPTED_COOKIE_PREFIX = "enc:v1:"
RUNTIME_AUTH_ERROR_HEADER = "X-APAAS-Sandbox-Auth-Error"
_LAUNCH_AUTH_ERRORS = {
    "sandbox_launch_token_expired",
    "sandbox_launch_token_invalid",
}
_SESSION_CAPACITY_ERROR = "sandbox_session_capacity_exceeded"
_PROXY_COOKIE_TOKEN_TYPE = "code_runtime_proxy"
logger = logging.getLogger(__name__)


def runtime_session_expiry_for_storage(value: datetime | None) -> datetime | None:
    if value is None or value.tzinfo is None:
        return value
    return value.astimezone(timezone.utc).replace(tzinfo=None)


@dataclass(frozen=True)
class RuntimeBootstrap:
    clean_builder_url: str
    runtime_base_url: str
    runtime_cookie: str = field(repr=False)
    runtime_cookie_hash: str
    expires_at: datetime | None


@dataclass(frozen=True)
class SandboxRenewalResult:
    generation: int
    joined: bool
    runtime_cookie: str = field(repr=False)
    runtime_cookie_hash: str
    expires_at: datetime | None


class SandboxRenewalFailure(Exception):
    _DETAILS = {
        "login_required": (401, True),
        "workspace_forbidden": (403, True),
        "sandbox_unavailable": (404, True),
        "workspace_temporarily_unavailable": (503, False),
    }

    def __init__(self, code: str, *, stage: str | None = None):
        if code not in self._DETAILS:
            raise ValueError(f"Unknown sandbox renewal failure: {code}")
        super().__init__(code)
        self.code = code
        self.stage = stage
        self.status_code, self.clear_cookies = self._DETAILS[code]


_renewal_locks: dict[tuple[int, str], asyncio.Lock] = {}


def _renewal_lock(binding_id: int, browser_session_id: str) -> asyncio.Lock:
    key = (int(binding_id), str(browser_session_id))
    lock = _renewal_locks.get(key)
    if lock is None:
        lock = asyncio.Lock()
        _renewal_locks[key] = lock
    return lock


def _renewal_failure(exc: BaseException) -> SandboxRenewalFailure:
    if isinstance(exc, SandboxRenewalFailure):
        return exc
    if isinstance(exc, HTTPException):
        if exc.status_code == 401:
            return SandboxRenewalFailure("login_required")
        if exc.status_code == 403:
            return SandboxRenewalFailure("workspace_forbidden")
        if exc.status_code in {404, 410}:
            return SandboxRenewalFailure("sandbox_unavailable")
    return SandboxRenewalFailure("workspace_temporarily_unavailable")


async def _workspace_open_with_refresh(
    authorization: str,
    *,
    authorization_provider: Callable[..., Any],
    workspace_open: Callable[[str], Any],
    forced_refresh_used: bool,
) -> tuple[dict[str, Any], str, bool]:
    try:
        opened = await asyncio.wait_for(workspace_open(authorization), timeout=60.0)
        return opened, authorization, forced_refresh_used
    except HTTPException as exc:
        if exc.status_code != 401:
            raise _renewal_failure(exc) from exc
    except (asyncio.TimeoutError, httpx.RequestError) as exc:
        raise SandboxRenewalFailure("workspace_temporarily_unavailable") from exc

    if forced_refresh_used:
        raise SandboxRenewalFailure("login_required")
    rejected_access_token = authorization.removeprefix("Bearer ").strip() or None
    try:
        refreshed_authorization = await authorization_provider(
            force_refresh=True,
            rejected_access_token=rejected_access_token,
        )
        opened = await asyncio.wait_for(
            workspace_open(refreshed_authorization),
            timeout=60.0,
        )
        return opened, refreshed_authorization, True
    except HTTPException as exc:
        raise _renewal_failure(exc) from exc
    except SandboxRenewalFailure:
        raise
    except (asyncio.TimeoutError, httpx.RequestError) as exc:
        raise SandboxRenewalFailure("workspace_temporarily_unavailable") from exc
    except Exception as exc:
        raise SandboxRenewalFailure("login_required") from exc


async def _renew_browser_runtime_session(
    *,
    binding_id: int,
    browser_session_id: str,
    observed_generation: int,
    session_factory: Callable[[], Any],
    authorization_provider: Callable[..., Any],
    workspace_open: Callable[[str], Any],
    bootstrap: Callable[[str], Any],
) -> SandboxRenewalResult:
    from app.models.ai_chat import CodeRuntimeBinding, CodeRuntimeBrowserSession

    async with _renewal_lock(binding_id, browser_session_id):
        async with session_factory() as db:
            browser_session = (
                await db.execute(
                    select(CodeRuntimeBrowserSession)
                    .where(
                        CodeRuntimeBrowserSession.binding_id == int(binding_id),
                        CodeRuntimeBrowserSession.browser_session_id == str(browser_session_id),
                    )
                    .with_for_update()
                )
            ).scalar_one_or_none()
            binding = (
                await db.execute(
                    select(CodeRuntimeBinding)
                    .where(CodeRuntimeBinding.id == int(binding_id))
                )
            ).scalar_one_or_none()
            if browser_session is None or binding is None:
                raise SandboxRenewalFailure("sandbox_unavailable")

            current_generation = int(browser_session.generation or 0)
            if current_generation > int(observed_generation):
                try:
                    runtime_cookie = decrypt_runtime_cookie(
                        browser_session.runtime_session_cookie_enc
                    )
                except ValueError as exc:
                    raise SandboxRenewalFailure(
                        "workspace_temporarily_unavailable"
                    ) from exc
                return SandboxRenewalResult(
                    generation=current_generation,
                    joined=True,
                    runtime_cookie=runtime_cookie,
                    runtime_cookie_hash=browser_session.runtime_session_hash,
                    expires_at=browser_session.runtime_session_expires_at,
                )

            try:
                authorization = await authorization_provider(
                    force_refresh=False,
                    rejected_access_token=None,
                )
            except HTTPException as exc:
                raise _renewal_failure(exc) from exc
            except SandboxRenewalFailure:
                raise
            except Exception as exc:
                raise SandboxRenewalFailure("login_required") from exc

            opened: dict[str, Any] | None = None
            runtime_bootstrap: RuntimeBootstrap | None = None
            forced_refresh_used = False
            for bootstrap_attempt in range(2):
                opened, authorization, forced_refresh_used = (
                    await _workspace_open_with_refresh(
                        authorization,
                        authorization_provider=authorization_provider,
                        workspace_open=workspace_open,
                        forced_refresh_used=forced_refresh_used,
                    )
                )
                builder_url = str(
                    opened.get("specReviewUrl") or opened.get("builderUrl") or ""
                ).strip()
                if not builder_url:
                    raise SandboxRenewalFailure(
                        "workspace_temporarily_unavailable"
                    )
                try:
                    bootstrap_kwargs = (
                        {"runtime_base_url": opened.get("runtimeBaseUrl")}
                        if (
                            "runtimeBaseUrl" in opened
                            and not settings.dolphin_code_ignore_runtime_base_url
                        )
                        else {}
                    )
                    runtime_bootstrap = await asyncio.wait_for(
                        bootstrap(builder_url, **bootstrap_kwargs),
                        timeout=10.0,
                    )
                    break
                except SandboxRenewalFailure:
                    raise
                except HTTPException as exc:
                    auth_error = str(
                        (exc.headers or {}).get(RUNTIME_AUTH_ERROR_HEADER) or ""
                    ).strip()
                    if bootstrap_attempt == 0 and exc.status_code != 401:
                        continue
                    if auth_error in _LAUNCH_AUTH_ERRORS or exc.status_code == 401:
                        raise SandboxRenewalFailure(
                            "workspace_temporarily_unavailable",
                            stage="bootstrap",
                        ) from exc
                    failure = _renewal_failure(exc)
                    raise SandboxRenewalFailure(
                        failure.code,
                        stage="bootstrap",
                    ) from exc
                except Exception as exc:
                    failure = _renewal_failure(exc)
                    raise SandboxRenewalFailure(
                        failure.code,
                        stage="bootstrap",
                    ) from exc

            if opened is None or runtime_bootstrap is None:
                raise SandboxRenewalFailure("workspace_temporarily_unavailable")

            next_generation = max(
                current_generation,
                int(binding.auth_generation or 0),
            ) + 1
            encrypted_cookie = encrypt_runtime_cookie(runtime_bootstrap.runtime_cookie)
            browser_session.runtime_session_cookie_enc = encrypted_cookie
            browser_session.runtime_session_hash = runtime_bootstrap.runtime_cookie_hash
            browser_session.runtime_session_expires_at = runtime_session_expiry_for_storage(
                runtime_bootstrap.expires_at
            )
            browser_session.generation = next_generation
            binding.runtime_service_session_enc = encrypted_cookie
            binding.auth_generation = next_generation
            binding.builder_url = runtime_bootstrap.clean_builder_url
            binding.runtime_base_url = runtime_bootstrap.runtime_base_url
            binding.workspace_id = opened.get("workspaceId") or binding.workspace_id
            binding.sandbox_instance_id = (
                opened.get("sandboxInstanceId") or binding.sandbox_instance_id
            )
            binding.status = "ready"
            binding.last_error = None
            try:
                await db.commit()
            except Exception as exc:
                await db.rollback()
                raise SandboxRenewalFailure(
                    "workspace_temporarily_unavailable",
                    stage="commit",
                ) from exc

            return SandboxRenewalResult(
                generation=next_generation,
                joined=False,
                runtime_cookie=runtime_bootstrap.runtime_cookie,
                runtime_cookie_hash=runtime_bootstrap.runtime_cookie_hash,
                expires_at=runtime_bootstrap.expires_at,
            )


async def renew_browser_runtime_session(
    *,
    binding_id: int,
    browser_session_id: str,
    observed_generation: int,
    session_factory: Callable[[], Any],
    authorization_provider: Callable[..., Any],
    workspace_open: Callable[[str], Any],
    bootstrap: Callable[[str], Any],
    metrics: SandboxAuthMetricsRegistry = sandbox_auth_metrics,
    reason: str = "sandbox_session_expired",
) -> SandboxRenewalResult:
    started = time.monotonic()
    try:
        result = await _renew_browser_runtime_session(
            binding_id=binding_id,
            browser_session_id=browser_session_id,
            observed_generation=observed_generation,
            session_factory=session_factory,
            authorization_provider=authorization_provider,
            workspace_open=workspace_open,
            bootstrap=bootstrap,
        )
    except SandboxRenewalFailure as exc:
        metrics.record_renew("failure", exc.code, time.monotonic() - started)
        metrics.record_hard_failure(exc.code)
        if exc.stage:
            metrics.record_orphan(exc.stage)
        raise
    if result.joined:
        metrics.record_singleflight_join()
        reason = "joined"
    metrics.record_renew("success", reason, time.monotonic() - started)
    return result


def validate_expired_proxy_cookie_token(
    token: str,
    *,
    session_id: str | int,
    legacy_session_id: int | None = None,
) -> dict:
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret_key,
            algorithms=[settings.jwt_algorithm],
            options={"verify_aud": False, "verify_exp": False},
        )
    except JWTError as exc:
        raise HTTPException(status_code=401, detail="Code runtime token invalid") from exc
    accepted_session_ids = {str(session_id)}
    if legacy_session_id is not None:
        accepted_session_ids.add(str(legacy_session_id))
    browser_session_id = str(payload.get("bsid") or "").strip()
    try:
        expired = float(payload.get("exp")) <= datetime.now(timezone.utc).timestamp()
    except (TypeError, ValueError):
        expired = False
    if (
        payload.get("type") != _PROXY_COOKIE_TOKEN_TYPE
        or str(payload.get("sid") or "") not in accepted_session_ids
        or not browser_session_id
        or len(browser_session_id) > 64
        or not expired
    ):
        raise HTTPException(status_code=401, detail="Code runtime token invalid")
    return payload


def split_entry_token(builder_url: str) -> tuple[str, str]:
    parsed = urlsplit(str(builder_url or "").strip())
    if not parsed.scheme or not parsed.netloc:
        raise ValueError("Runtime builder URL is invalid")

    entry_token: str | None = None
    for item in parsed.query.split("&") if parsed.query else []:
        key, separator, value = item.partition("=")
        if key == "token":
            if entry_token is None:
                entry_token = unquote_plus(value) if separator else ""
    if not entry_token:
        raise ValueError("Runtime entry token is missing")
    clean_url, _removed = remove_builder_entry_tokens(builder_url)
    return clean_url, entry_token


def remove_builder_entry_tokens(builder_url: str) -> tuple[str, int]:
    parsed = urlsplit(str(builder_url or ""))
    clean_items: list[str] = []
    removed = 0
    for item in parsed.query.split("&") if parsed.query else []:
        key, _separator, _value = item.partition("=")
        if key == "token":
            removed += 1
            continue
        clean_items.append(item)
    return (
        urlunsplit(
            (
                parsed.scheme,
                parsed.netloc,
                parsed.path,
                "&".join(clean_items),
                parsed.fragment,
            )
        ),
        removed,
    )


def encrypt_runtime_cookie(value: str) -> str:
    if not str(value or ""):
        raise ValueError("Runtime cookie is missing")
    return _ENCRYPTED_COOKIE_PREFIX + encrypt_password(value)


def decrypt_runtime_cookie(value: str) -> str:
    encrypted = str(value or "")
    if not encrypted.startswith(_ENCRYPTED_COOKIE_PREFIX):
        raise ValueError("Runtime cookie decrypt failed")
    try:
        decrypted = decrypt_password(encrypted[len(_ENCRYPTED_COOKIE_PREFIX):])
    except Exception as exc:
        raise ValueError("Runtime cookie decrypt failed") from exc
    if not decrypted:
        raise ValueError("Runtime cookie decrypt failed")
    return decrypted


def _derive_runtime_base_url(builder_url: str) -> str:
    parsed = urlsplit(builder_url)
    path = parsed.path.rstrip("/")
    marker = "/builder"
    if path.endswith(marker):
        base_path = path[: -len(marker)]
    elif marker + "/" in path:
        base_path = path.split(marker + "/", 1)[0]
    else:
        base_path = path.rsplit("/", 1)[0]
    return urlunsplit((parsed.scheme, parsed.netloc, base_path.rstrip("/"), "", ""))


def _validated_runtime_base_url(value: str | None) -> str | None:
    candidate = str(value or "").strip()
    if not candidate:
        return None
    try:
        parsed = urlsplit(candidate)
        if parsed.scheme not in {"http", "https"}:
            raise ValueError("unsupported scheme")
        if not parsed.hostname:
            raise ValueError("hostname is missing")
        if parsed.username is not None or parsed.password is not None:
            raise ValueError("userinfo is forbidden")
        if parsed.query or parsed.fragment:
            raise ValueError("query and fragment are forbidden")
        parsed.port
        hostname = str(parsed.hostname or "").rstrip(".").lower()
        # workspace/open runs in the Control Plane's cluster.  A value such as
        # `runtime.namespace.svc.cluster.local` is valid *inside* that cluster
        # but is not routable from the desktop client.  In that case use the
        # public Builder URL below to derive the runtime origin instead.
        if hostname == "cluster.local" or hostname.endswith((".svc", ".svc.cluster.local")):
            raise ValueError("cluster-internal hostname")
    except ValueError as exc:
        logger.warning("Ignoring invalid Control Plane runtimeBaseUrl: %s", exc)
        return None
    return urlunsplit(
        (
            parsed.scheme,
            parsed.netloc,
            parsed.path.rstrip("/"),
            "",
            "",
        )
    )


def _runtime_cookie(response: httpx.Response) -> tuple[str, datetime | None]:
    value = response.cookies.get(RUNTIME_COOKIE_NAME)
    expires_at: datetime | None = None
    for raw_header in response.headers.get_list("set-cookie"):
        parsed = SimpleCookie()
        parsed.load(raw_header)
        morsel = parsed.get(RUNTIME_COOKIE_NAME)
        if morsel is None:
            continue
        value = value or morsel.value
        max_age = morsel["max-age"]
        if max_age:
            try:
                expires_at = datetime.now(timezone.utc) + timedelta(seconds=max(0, int(max_age)))
            except ValueError:
                pass
        elif morsel["expires"]:
            try:
                parsed_expires = parsedate_to_datetime(morsel["expires"])
                expires_at = (
                    parsed_expires.replace(tzinfo=timezone.utc)
                    if parsed_expires.tzinfo is None
                    else parsed_expires.astimezone(timezone.utc)
                )
            except (TypeError, ValueError, IndexError):
                pass
        if value:
            break
    if not value:
        raise HTTPException(status_code=502, detail="Runtime bootstrap response missing session cookie")
    return value, expires_at


async def bootstrap_runtime_session(
    builder_url: str,
    *,
    runtime_base_url: str | None = None,
    client_factory: Callable[[], httpx.AsyncClient] | None = None,
) -> RuntimeBootstrap:
    try:
        clean_builder_url, entry_token = split_entry_token(builder_url)
    except ValueError:
        sandbox_auth_metrics.record_builder_url_cleanup("failure")
        raise
    sandbox_auth_metrics.record_builder_url_cleanup("success")
    resolved_runtime_base_url = (
        _validated_runtime_base_url(runtime_base_url)
        or _derive_runtime_base_url(clean_builder_url)
    )
    request_url = f"{resolved_runtime_base_url}/api/status?token={quote(entry_token, safe='')}"
    factory = client_factory or (lambda: httpx.AsyncClient(timeout=10.0))
    try:
        async with factory() as client:
            response = await client.get(request_url, timeout=10.0)
    except httpx.RequestError as exc:
        raise HTTPException(status_code=503, detail="Runtime bootstrap unavailable") from None

    auth_error = str(response.headers.get(RUNTIME_AUTH_ERROR_HEADER) or "").strip()
    if response.status_code >= 400 and auth_error == _SESSION_CAPACITY_ERROR:
        raise HTTPException(
            status_code=503,
            detail="Runtime sandbox session capacity exceeded",
            headers={RUNTIME_AUTH_ERROR_HEADER: auth_error},
        )
    if response.status_code == 401:
        if auth_error in _LAUNCH_AUTH_ERRORS:
            raise HTTPException(
                status_code=401,
                detail=(
                    "Runtime launch authorization expired"
                    if auth_error.endswith("_expired")
                    else "Runtime launch authorization invalid"
                ),
                headers={RUNTIME_AUTH_ERROR_HEADER: auth_error},
            )
    if response.status_code >= 400:
        parsed_runtime_url = urlsplit(resolved_runtime_base_url)
        logger.warning(
            "Runtime bootstrap rejected status=%s auth_error=%s runtime_host=%s",
            response.status_code,
            auth_error or "none",
            parsed_runtime_url.hostname or "unknown",
        )
        raise HTTPException(status_code=response.status_code, detail="Runtime bootstrap failed")

    runtime_cookie, expires_at = _runtime_cookie(response)
    return RuntimeBootstrap(
        clean_builder_url=clean_builder_url,
        runtime_base_url=resolved_runtime_base_url,
        runtime_cookie=runtime_cookie,
        runtime_cookie_hash=hashlib.sha256(runtime_cookie.encode("utf-8")).hexdigest(),
        expires_at=expires_at,
    )
