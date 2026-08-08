"""Builder-owned integration with the standalone Builder AI Control Plane."""

from __future__ import annotations

import logging
import os
from typing import Any

import httpx
from fastapi import HTTPException

from app.config import settings

logger = logging.getLogger(__name__)

_SESSION_PATH = "/internal/builder-ai/auth/session"


def _management_base_url() -> str:
    return (
        os.getenv("BUILDER_AI_MANAGEMENT_URL", "").strip()
        or str(getattr(settings, "builder_ai_management_url", "") or "").strip()
    ).rstrip("/")


def _session_url(base_url: str) -> str:
    if base_url.endswith(_SESSION_PATH):
        return base_url
    return f"{base_url}{_SESSION_PATH}"


def _internal_headers() -> dict[str, str]:
    token_id = (
        os.getenv("BUILDER_AI_INTERNAL_CURRENT_TOKEN_ID", "").strip()
        or str(getattr(settings, "builder_ai_internal_current_token_id", "") or "").strip()
    )
    token = (
        os.getenv("BUILDER_AI_INTERNAL_CURRENT_TOKEN", "").strip()
        or str(getattr(settings, "builder_ai_internal_current_token", "") or "").strip()
    )
    if not token_id or not token:
        raise HTTPException(status_code=503, detail="Builder AI 管理服务未配置内部认证凭据")
    return {
        "Content-Type": "application/json",
        "X-Builder-Internal-Token-Id": token_id,
        "X-Builder-Internal-Token": token,
    }


async def exchange_web_console_session(
    *,
    user_id: str,
    username: str,
    apaas_access_token: str,
    apaas_tenant_id: str,
) -> dict[str, str] | None:
    """Exchange a validated aPaaS identity for a standalone console session."""
    base_url = _management_base_url()
    if not base_url:
        return None
    if not user_id or not username or not apaas_access_token or not apaas_tenant_id:
        raise HTTPException(status_code=502, detail="aPaaS 登录缺少 Builder AI 会话所需身份信息")

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(
                _session_url(base_url),
                headers=_internal_headers(),
                json={
                    "userId": str(user_id),
                    "username": str(username),
                    "apaasAccessToken": str(apaas_access_token),
                    "apaasTenantId": str(apaas_tenant_id),
                },
            )
    except httpx.RequestError as exc:
        logger.warning("standalone Builder AI session exchange unavailable: %s", type(exc).__name__)
        raise HTTPException(status_code=503, detail="Builder AI 管理服务暂不可用") from exc

    if response.status_code >= 400:
        detail = "Builder AI 管理服务拒绝创建会话"
        try:
            payload = response.json()
            if isinstance(payload, dict):
                detail = str(payload.get("message") or payload.get("detail") or detail)
        except ValueError:
            pass
        raise HTTPException(status_code=502, detail=detail)

    try:
        payload: Any = response.json()
    except ValueError as exc:
        raise HTTPException(status_code=502, detail="Builder AI 管理服务响应无效") from exc
    if not isinstance(payload, dict):
        raise HTTPException(status_code=502, detail="Builder AI 管理服务响应无效")

    session_token = str(payload.get("sessionToken") or payload.get("session_token") or "").strip()
    identity = payload.get("identity") if isinstance(payload.get("identity"), dict) else {}
    tenant_id = str(
        identity.get("apaasTenantId")
        or identity.get("tenantId")
        or apaas_tenant_id
        or ""
    ).strip()
    if not session_token or not tenant_id:
        raise HTTPException(status_code=502, detail="Builder AI 管理服务未返回有效会话")
    return {"access_token": session_token, "tenant_id": tenant_id}
