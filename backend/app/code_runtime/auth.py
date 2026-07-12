from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

import httpx
from fastapi import HTTPException
from jose import jwt as jose_jwt

from app.code_runtime.service import control_plane_base_url
from app.config import settings
from app.crypto import decrypt_password, encrypt_password


@dataclass
class ControlPlaneAuthResult:
    username: str
    display_name: str | None = None
    external_user_id: str | None = None
    roles: list[str] = field(default_factory=list)
    tenant_id: str | None = None
    tenant_name: str | None = None
    access_token: str = ""
    refresh_token: str | None = None


@dataclass
class ControlPlaneTokenResult:
    access_token: str
    refresh_token: str | None = None
    tenant_id: str | None = None


_ENCRYPTED_TOKEN_PREFIX = "enc:v1:"


def store_control_plane_credentials(
    user: Any,
    access_token: str,
    refresh_token: str | None = None,
) -> None:
    user.coding_base_url = control_plane_base_url()
    user.coding_access_token = _ENCRYPTED_TOKEN_PREFIX + encrypt_password(access_token)
    user.coding_refresh_token = (
        _ENCRYPTED_TOKEN_PREFIX + encrypt_password(refresh_token)
        if refresh_token
        else None
    )


def _stored_token(user: Any, field: str) -> str | None:
    value = str(getattr(user, field, "") or "").strip()
    if not value:
        return None
    if not value.startswith(_ENCRYPTED_TOKEN_PREFIX):
        return value
    try:
        return decrypt_password(value[len(_ENCRYPTED_TOKEN_PREFIX):])
    except Exception:
        return None


def control_plane_access_token(user: Any) -> str | None:
    return _stored_token(user, "coding_access_token")


def control_plane_refresh_token(user: Any) -> str | None:
    return _stored_token(user, "coding_refresh_token")


def control_plane_token_needs_refresh(token: str, *, skew_seconds: int = 60) -> bool:
    try:
        expires_at = int(jose_jwt.get_unverified_claims(token).get("exp") or 0)
    except Exception:
        return False
    return expires_at > 0 and expires_at <= int(time.time()) + skew_seconds


def _dolphin_workspace_base_url() -> str:
    return str(settings.dolphin_workspace_base_url or "").strip().rstrip("/")


def _response_payload(
    response: httpx.Response,
    *,
    fallback: str,
    failure_status: int,
) -> dict[str, Any]:
    try:
        payload = response.json()
    except Exception as exc:
        raise HTTPException(
            status_code=response.status_code if response.status_code >= 400 else failure_status,
            detail=f"{fallback}：上游返回非 JSON 数据",
        ) from exc
    if not isinstance(payload, dict):
        raise HTTPException(status_code=failure_status, detail=f"{fallback}：上游返回异常数据")
    if response.status_code >= 400:
        detail = payload.get("detail") or payload.get("message") or fallback
        raise HTTPException(status_code=response.status_code, detail=str(detail))
    return payload


async def fetch_dolphin_captcha() -> dict[str, str]:
    base_url = _dolphin_workspace_base_url()
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            payload = _response_payload(
                await client.get(f"{base_url}/api/auth/captcha"),
                fallback="Dolphin 验证码获取失败",
                failure_status=503,
            )
    except HTTPException:
        raise
    except httpx.RequestError as exc:
        raise HTTPException(status_code=503, detail="Dolphin 登录服务暂不可用") from exc

    captcha_id = str(payload.get("captcha_id") or "").strip()
    image_data = str(payload.get("image_data") or "").strip()
    if not captcha_id or not image_data:
        raise HTTPException(status_code=502, detail="Dolphin 验证码返回异常")
    return {"captcha_id": captcha_id, "image_data": image_data}


async def login_to_control_plane(
    username: str,
    password: str,
    captcha_id: str,
    captcha_code: str,
) -> ControlPlaneAuthResult:
    base_url = _dolphin_workspace_base_url()
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            token = _response_payload(
                await client.post(
                    f"{base_url}/api/auth/login",
                    json={
                        "username": username,
                        "password": password,
                        "captcha_id": captcha_id,
                        "captcha_code": captcha_code,
                    },
                ),
                fallback="Dolphin 登录失败",
                failure_status=401,
            )
            if token.get("requires_tenant_selection") and not token.get("access_token"):
                raise HTTPException(
                    status_code=409,
                    detail="当前 Dolphin 账号包含多个租户，请先在大平台设置默认租户后重试",
                )
            access_token = str(token.get("access_token") or "").strip()
            if not access_token:
                raise HTTPException(status_code=502, detail="Dolphin 登录未返回 access_token")
            current_user = _response_payload(
                await client.get(
                    f"{base_url}/api/auth/me",
                    headers={"Authorization": f"Bearer {access_token}"},
                ),
                fallback="Dolphin 当前用户读取失败",
                failure_status=401,
            )
    except HTTPException:
        raise
    except httpx.RequestError as exc:
        raise HTTPException(status_code=503, detail="Dolphin 登录服务暂不可用") from exc

    role = str(current_user.get("role") or "").strip()
    resolved_username = str(current_user.get("username") or username).strip() or username
    return ControlPlaneAuthResult(
        username=resolved_username,
        display_name=str(current_user.get("nickname") or resolved_username).strip(),
        external_user_id=str(current_user.get("id") or "").strip() or None,
        roles=[role] if role else [],
        tenant_id=str(current_user.get("tenant_id") or "").strip() or None,
        tenant_name=str(current_user.get("tenant_name") or "").strip() or None,
        access_token=access_token,
        refresh_token=str(token.get("refresh_token") or "").strip() or None,
    )


async def refresh_control_plane_token(refresh_token: str) -> ControlPlaneTokenResult:
    base_url = _dolphin_workspace_base_url()
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            payload = _response_payload(
                await client.post(
                    f"{base_url}/api/auth/refresh",
                    json={"refresh_token": refresh_token},
                ),
                fallback="Dolphin Token 刷新失败",
                failure_status=401,
            )
    except HTTPException:
        raise
    except httpx.RequestError as exc:
        raise HTTPException(status_code=503, detail="Dolphin Token 刷新暂不可用") from exc

    access_token = str(payload.get("access_token") or "").strip()
    if not access_token:
        raise HTTPException(status_code=502, detail="Dolphin Token 刷新未返回 access_token")
    return ControlPlaneTokenResult(
        access_token=access_token,
        refresh_token=str(payload.get("refresh_token") or "").strip() or None,
    )


async def exchange_apaas_token(
    apaas_token: str,
    apaas_tenant_id: str,
) -> ControlPlaneTokenResult:
    base_url = _dolphin_workspace_base_url()
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            payload = _response_payload(
                await client.post(
                    f"{base_url}/api/auth/apaas/exchange",
                    json={
                        "apaas_token": apaas_token,
                        "apaas_tenant_id": apaas_tenant_id,
                    },
                ),
                fallback="aPaaS 账号换取 Dolphin Token 失败",
                failure_status=401,
            )
    except HTTPException:
        raise
    except httpx.RequestError as exc:
        raise HTTPException(status_code=503, detail="Dolphin 账号绑定服务暂不可用") from exc

    access_token = str(payload.get("access_token") or "").strip()
    if not access_token:
        raise HTTPException(status_code=502, detail="Dolphin 账号绑定未返回 access_token")
    return ControlPlaneTokenResult(
        access_token=access_token,
        refresh_token=str(payload.get("refresh_token") or "").strip() or None,
        tenant_id=str(payload.get("tenant_id") or "").strip() or None,
    )
