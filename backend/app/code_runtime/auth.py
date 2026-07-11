from __future__ import annotations

import base64
import hashlib
import os
from dataclasses import dataclass, field
from typing import Any

import httpx
from fastapi import HTTPException
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding

from app.config import settings
from app.code_runtime.service import control_plane_base_url


@dataclass
class CodingAuthResult:
    username: str
    display_name: str | None = None
    external_user_id: str | None = None
    roles: list[str] = field(default_factory=list)
    access_token: str = ""
    refresh_token: str | None = None


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


def _coding_auth_client_id() -> str:
    return (settings.dolphin_code_auth_client_id or "").strip() or "control-plane-console"


def _coding_auth_redirect_uri() -> str:
    return (settings.dolphin_code_auth_redirect_uri or "").strip() or "http://localhost/auth/callback"


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
            detail="Coding 登录链路返回非 JSON 数据",
        ) from exc

    status_code = response.status_code if response.status_code >= 400 else failure_status
    if not isinstance(payload, dict):
        raise HTTPException(status_code=status_code, detail="Coding 登录链路返回异常数据")

    code = str(payload.get("code") or "").upper()
    if response.status_code >= 400 or code not in ("OK", "SUCCESS"):
        raise HTTPException(
            status_code=status_code,
            detail=_envelope_message(payload, "Coding 登录失败"),
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
        raise HTTPException(status_code=502, detail=f"Coding 登录链路缺少 {stage}.{key}")
    return value


async def login_to_coding_control_plane(
    username: str,
    password: str,
    base_url: str | None = None,
) -> CodingAuthResult:
    resolved_base_url = (
        str(base_url).strip().rstrip("/")
        if base_url is not None
        else control_plane_base_url()
    )
    client_id = _coding_auth_client_id()
    redirect_uri = _coding_auth_redirect_uri()
    scopes = _coding_auth_scopes()
    pkce = _create_pkce_pair()

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            login_key = _unwrap_envelope(
                await client.get(f"{resolved_base_url}/api/auth/login-key"),
                failure_status=503,
            )
            authorization = _unwrap_envelope(
                await client.post(
                    f"{resolved_base_url}/api/auth/authorize",
                    json={
                        "responseType": "code",
                        "clientId": client_id,
                        "redirectUri": redirect_uri,
                        "scopes": scopes,
                        "state": pkce["state"],
                        "codeChallenge": pkce["codeChallenge"],
                        "codeChallengeMethod": pkce["codeChallengeMethod"],
                    },
                ),
                failure_status=401,
            )
            if authorization.get("state") != pkce["state"]:
                raise HTTPException(status_code=502, detail="Coding 登录 state 校验失败")

            public_key = _require_text(login_key, "publicKey", "login-key")
            login_result = _unwrap_envelope(
                await client.post(
                    f"{resolved_base_url}/api/auth/login",
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
                raise HTTPException(status_code=502, detail="Coding 登录 state 校验失败")

            token = _unwrap_envelope(
                await client.post(
                    f"{resolved_base_url}/api/auth/token",
                    json={
                        "grantType": "authorization_code",
                        "code": _require_text(login_result, "code", "login"),
                        "clientId": client_id,
                        "redirectUri": redirect_uri,
                        "codeVerifier": pkce["codeVerifier"],
                    },
                ),
                failure_status=401,
            )
            access_token = _require_text(token, "accessToken", "token")
            current_user = _unwrap_envelope(
                await client.get(
                    f"{resolved_base_url}/api/auth/me",
                    headers={"Authorization": f"Bearer {access_token}"},
                ),
                failure_status=401,
            )
    except HTTPException:
        raise
    except httpx.RequestError as exc:
        raise HTTPException(status_code=503, detail="Coding 登录链路暂不可用，请稍后重试") from exc

    roles = current_user.get("roles")
    role_values = [str(role) for role in roles] if isinstance(roles, list) else []
    resolved_username = str(current_user.get("username") or username).strip() or username
    return CodingAuthResult(
        username=resolved_username,
        display_name=str(current_user.get("displayName") or "").strip() or None,
        external_user_id=str(current_user.get("userId") or "").strip() or None,
        roles=role_values,
        access_token=access_token,
        refresh_token=str(token.get("refreshToken") or "").strip() or None,
    )
