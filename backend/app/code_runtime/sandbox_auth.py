from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from http.cookies import SimpleCookie
from typing import Callable
from urllib.parse import quote, unquote_plus, urlsplit, urlunsplit

import httpx
from fastapi import HTTPException

from app.crypto import decrypt_password, encrypt_password

RUNTIME_COOKIE_NAME = "apaas_sandbox_token"
_ENCRYPTED_COOKIE_PREFIX = "enc:v1:"
_RUNTIME_AUTH_ERROR_HEADER = "X-APAAS-Sandbox-Auth-Error"
_LAUNCH_AUTH_ERRORS = {
    "sandbox_launch_token_expired",
    "sandbox_launch_token_invalid",
}


@dataclass(frozen=True)
class RuntimeBootstrap:
    clean_builder_url: str
    runtime_base_url: str
    runtime_cookie: str = field(repr=False)
    runtime_cookie_hash: str
    expires_at: datetime | None


def split_entry_token(builder_url: str) -> tuple[str, str]:
    parsed = urlsplit(str(builder_url or "").strip())
    if not parsed.scheme or not parsed.netloc:
        raise ValueError("Runtime builder URL is invalid")

    entry_token: str | None = None
    clean_items: list[str] = []
    for item in parsed.query.split("&") if parsed.query else []:
        key, separator, value = item.partition("=")
        if key == "token":
            if entry_token is None:
                entry_token = unquote_plus(value) if separator else ""
            continue
        clean_items.append(item)
    if not entry_token:
        raise ValueError("Runtime entry token is missing")
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
        entry_token,
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
    client_factory: Callable[[], httpx.AsyncClient] | None = None,
) -> RuntimeBootstrap:
    clean_builder_url, entry_token = split_entry_token(builder_url)
    runtime_base_url = _derive_runtime_base_url(clean_builder_url)
    request_url = f"{runtime_base_url}/api/status?token={quote(entry_token, safe='')}"
    factory = client_factory or (lambda: httpx.AsyncClient(timeout=10.0))
    try:
        async with factory() as client:
            response = await client.get(request_url, timeout=10.0)
    except httpx.RequestError as exc:
        raise HTTPException(status_code=503, detail="Runtime bootstrap unavailable") from None

    if response.status_code == 401:
        auth_error = str(response.headers.get(_RUNTIME_AUTH_ERROR_HEADER) or "").strip()
        if auth_error in _LAUNCH_AUTH_ERRORS:
            raise HTTPException(
                status_code=401,
                detail=(
                    "Runtime launch authorization expired"
                    if auth_error.endswith("_expired")
                    else "Runtime launch authorization invalid"
                ),
                headers={_RUNTIME_AUTH_ERROR_HEADER: auth_error},
            )
    if response.status_code >= 400:
        raise HTTPException(status_code=response.status_code, detail="Runtime bootstrap failed")

    runtime_cookie, expires_at = _runtime_cookie(response)
    return RuntimeBootstrap(
        clean_builder_url=clean_builder_url,
        runtime_base_url=runtime_base_url,
        runtime_cookie=runtime_cookie,
        runtime_cookie_hash=hashlib.sha256(runtime_cookie.encode("utf-8")).hexdigest(),
        expires_at=expires_at,
    )
