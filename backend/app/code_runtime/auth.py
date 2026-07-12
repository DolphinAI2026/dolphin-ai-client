from __future__ import annotations

import base64
import hashlib
import os
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

import httpx
from fastapi import HTTPException
from jose import jwt as jose_jwt
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding

from app.config import settings
from app.code_runtime.service import control_plane_base_url
from app.crypto import decrypt_password, encrypt_password


@dataclass
class ControlPlaneAuthResult:
    username: str
    display_name: str | None = None
    external_user_id: str | None = None
    roles: list[str] = field(default_factory=list)
    access_token: str = ""
    refresh_token: str | None = None


@dataclass
class ControlPlaneFederationResult:
    status: str
    access_token: str | None = None
    refresh_token: str | None = None
    binding_challenge: str | None = None
    control_plane_user_id: str | None = None
    trace_id: str | None = None


@dataclass
class ControlPlaneTokenResult:
    access_token: str
    refresh_token: str | None = None


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


def normalize_spki_public_key_body(public_key: str) -> str:
    return (
        str(public_key or "")
        .replace("-----BEGIN PUBLIC KEY-----", "")
        .replace("-----END PUBLIC KEY-----", "")
        .replace("\r", "")
        .replace("\n", "")
        .replace("\t", "")
        .replace(" ", "")
        .strip()
    )


def _base64_url_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _random_base64_url(byte_count: int) -> str:
    return _base64_url_encode(os.urandom(byte_count))


def _create_pkce_pair() -> dict[str, str]:
    code_verifier = _random_base64_url(48)
    code_challenge = _base64_url_encode(hashlib.sha256(code_verifier.encode()).digest())
    return {
        "codeVerifier": code_verifier,
        "codeChallenge": code_challenge,
        "codeChallengeMethod": "S256",
        "state": _random_base64_url(24),
        "clientSessionId": _random_base64_url(24),
    }


def _parse_scopes(raw: str) -> list[str]:
    import re

    return [item for item in (part.strip() for part in re.split(r"[,\s]+", raw or "")) if item]


def _coding_auth_scopes() -> list[str]:
    return _parse_scopes(settings.dolphin_code_auth_scopes or "profile,admin:control-plane")


def _envelope_message(payload: object, fallback: str) -> str:
    if isinstance(payload, dict):
        for key in ("message", "msg", "error", "detail"):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return fallback


def _unwrap_envelope(response: httpx.Response, *, failure_status: int = 400) -> dict[str, Any]:
    try:
        payload = response.json()
    except Exception as exc:
        raise HTTPException(
            status_code=response.status_code if response.status_code >= 400 else failure_status,
            detail="Control Plane 认证链路返回非 JSON 数据",
        ) from exc

    status_code = response.status_code if response.status_code >= 400 else failure_status
    if not isinstance(payload, dict):
        raise HTTPException(status_code=status_code, detail="Control Plane 认证链路返回异常数据")

    code = str(payload.get("code") or "").upper()
    if response.status_code >= 400 or code not in ("OK", "SUCCESS"):
        raise HTTPException(
            status_code=status_code,
            detail=_envelope_message(payload, "Control Plane 认证失败"),
        )

    data = payload.get("data")
    return data if isinstance(data, dict) else {}


def _encrypt_login_password(password: str, public_key: str) -> str:
    key_body = normalize_spki_public_key_body(public_key)
    public_key_obj = serialization.load_der_public_key(base64.b64decode(key_body))
    encrypted = public_key_obj.encrypt(
        str(password or "").encode("utf-8"),
        padding.OAEP(
            mgf=padding.MGF1(algorithm=hashes.SHA256()),
            algorithm=hashes.SHA256(),
            label=None,
        ),
    )
    return _base64_url_encode(encrypted)


def _require_text(payload: dict[str, Any], key: str, stage: str) -> str:
    value = str(payload.get(key) or "").strip()
    if not value:
        raise HTTPException(status_code=502, detail=f"Control Plane 认证链路缺少 {stage}.{key}")
    return value


def _token_values(payload: dict[str, Any] | None) -> tuple[str | None, str | None]:
    token = payload if isinstance(payload, dict) else {}
    access_token = str(token.get("accessToken") or "").strip() or None
    refresh_token = str(token.get("refreshToken") or "").strip() or None
    return access_token, refresh_token


def _binding_user_id(payload: dict[str, Any]) -> str | None:
    binding = payload.get("binding")
    if not isinstance(binding, dict):
        return None
    return str(binding.get("controlPlaneUserId") or "").strip() or None


async def login_to_control_plane(username: str, password: str) -> ControlPlaneAuthResult:
    base_url = control_plane_base_url()
    scopes = _coding_auth_scopes()
    pkce = _create_pkce_pair()

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            login_key = _unwrap_envelope(
                await client.get(f"{base_url}/api/builder-auth/oauth/login-key"),
                failure_status=503,
            )
            authorization = _unwrap_envelope(
                await client.post(
                    f"{base_url}/api/builder-auth/oauth/authorize",
                    json={
                        "responseType": "code",
                        "scopes": scopes,
                        "state": pkce["state"],
                        "codeChallenge": pkce["codeChallenge"],
                        "codeChallengeMethod": pkce["codeChallengeMethod"],
                    },
                ),
                failure_status=401,
            )
            if authorization.get("state") != pkce["state"]:
                raise HTTPException(status_code=502, detail="Control Plane 登录 state 校验失败")

            public_key = _require_text(login_key, "publicKey", "login-key")
            login_result = _unwrap_envelope(
                await client.post(
                    f"{base_url}/api/builder-auth/oauth/login",
                    json={
                        "authorizationRequestId": _require_text(
                            authorization,
                            "authorizationRequestId",
                            "authorize",
                        ),
                        "username": username,
                        "encryptedPassword": _encrypt_login_password(password, public_key),
                        "keyId": _require_text(login_key, "keyId", "login-key"),
                        "clientSessionId": pkce["clientSessionId"],
                    },
                    headers={"rsa-public-key": normalize_spki_public_key_body(public_key)},
                ),
                failure_status=401,
            )
            if login_result.get("state") != pkce["state"]:
                raise HTTPException(status_code=502, detail="Control Plane 登录 state 校验失败")

            token = _unwrap_envelope(
                await client.post(
                    f"{base_url}/api/builder-auth/oauth/token",
                    json={
                        "grantType": "authorization_code",
                        "code": _require_text(login_result, "code", "login"),
                        "codeVerifier": pkce["codeVerifier"],
                    },
                ),
                failure_status=401,
            )
            access_token = _require_text(token, "accessToken", "token")
            current_user = _unwrap_envelope(
                await client.get(
                    f"{base_url}/api/builder-auth/me",
                    headers={
                        "Authorization": f"Bearer {access_token}",
                        "X-Auth-Provider": "builder-control-plane",
                    },
                ),
                failure_status=401,
            )
    except HTTPException:
        raise
    except httpx.RequestError as exc:
        raise HTTPException(status_code=503, detail="Control Plane 登录链路暂不可用，请稍后重试") from exc

    roles = current_user.get("roles")
    role_values = [str(role) for role in roles] if isinstance(roles, list) else []
    resolved_username = str(current_user.get("username") or username).strip() or username
    return ControlPlaneAuthResult(
        username=resolved_username,
        display_name=str(current_user.get("displayName") or "").strip() or None,
        external_user_id=str(current_user.get("userId") or "").strip() or None,
        roles=role_values,
        access_token=access_token,
        refresh_token=str(token.get("refreshToken") or "").strip() or None,
    )


async def exchange_apaas_identity(
    subject_token: str,
    tenant_id: str,
) -> ControlPlaneFederationResult:
    base_url = control_plane_base_url()
    trace_id = str(uuid.uuid4())
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            data = _unwrap_envelope(
                await client.post(
                    f"{base_url}/api/builder-auth/federation/apaas/exchange",
                    json={
                        "subjectToken": subject_token,
                        "tenantId": tenant_id,
                    },
                    headers={"X-Trace-Id": trace_id},
                ),
                failure_status=401,
            )
    except HTTPException:
        raise
    except httpx.RequestError as exc:
        raise HTTPException(status_code=503, detail="Control Plane 账号绑定链路暂不可用") from exc

    access_token, refresh_token = _token_values(data.get("tokenResponse"))
    return ControlPlaneFederationResult(
        status=str(data.get("status") or "").strip(),
        access_token=access_token,
        refresh_token=refresh_token,
        binding_challenge=str(data.get("bindingChallenge") or "").strip() or None,
        control_plane_user_id=_binding_user_id(data),
        trace_id=str(data.get("traceId") or trace_id).strip(),
    )


async def bind_apaas_identity(
    binding_challenge: str,
    control_plane_proof_token: str,
    tenant_id: str,
    trace_id: str,
) -> ControlPlaneFederationResult:
    base_url = control_plane_base_url()
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            data = _unwrap_envelope(
                await client.post(
                    f"{base_url}/api/builder-auth/federation/apaas/bind",
                    json={
                        "bindingChallenge": binding_challenge,
                        "controlPlaneProofToken": control_plane_proof_token,
                        "tenantId": tenant_id,
                    },
                    headers={"X-Trace-Id": trace_id},
                ),
                failure_status=403,
            )
    except HTTPException:
        raise
    except httpx.RequestError as exc:
        raise HTTPException(status_code=503, detail="Control Plane 账号绑定链路暂不可用") from exc

    access_token, refresh_token = _token_values(data.get("tokenResponse"))
    return ControlPlaneFederationResult(
        status="TOKEN_ISSUED" if data.get("bound") else "BINDING_REQUIRED",
        access_token=access_token,
        refresh_token=refresh_token,
        control_plane_user_id=_binding_user_id(data),
        trace_id=str(data.get("traceId") or trace_id).strip(),
    )


async def refresh_control_plane_token(refresh_token: str) -> ControlPlaneTokenResult:
    base_url = control_plane_base_url()
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            data = _unwrap_envelope(
                await client.post(
                    f"{base_url}/api/builder-auth/oauth/refresh",
                    json={
                        "grantType": "refresh_token",
                        "refreshToken": refresh_token,
                    },
                ),
                failure_status=401,
            )
    except HTTPException:
        raise
    except httpx.RequestError as exc:
        raise HTTPException(status_code=503, detail="Control Plane Token 刷新暂不可用") from exc

    access_token = _require_text(data, "accessToken", "refresh")
    return ControlPlaneTokenResult(
        access_token=access_token,
        refresh_token=str(data.get("refreshToken") or "").strip() or None,
    )
