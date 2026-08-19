"""Single-entry discovery contract for the cross-platform desktop client."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.builder_auth.settings import get_public_builder_auth_settings
from app.config import settings
from app.database import get_db

router = APIRouter(tags=["desktop-bootstrap"])


def _base(request: Request) -> str:
    configured = str(getattr(settings, "desktop_public_base_url", "") or "").strip()
    return (configured or str(request.base_url)).rstrip("/")


def _product_url(request: Request, configured: str) -> str:
    return (configured or _base(request)).rstrip("/")


def _api_url(value: str, request: Request) -> str:
    return (value or _base(request)).rstrip("/")


def _web_url(api_url: str) -> str:
    """Turn the common aPaaS API suffix into a browser-facing service root."""
    for suffix in ("/backend", "/api"):
        if api_url.lower().endswith(suffix):
            return api_url[: -len(suffix)].rstrip("/")
    return api_url


@router.get("/.well-known/dolphin-desktop-bootstrap")
async def desktop_bootstrap(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    auth = await get_public_builder_auth_settings(db)
    provider = "apaas" if auth.default_login_provider == "apaas" else "control_plane"
    if provider == "apaas":
        api_url = _api_url(
            str(getattr(settings, "apaas_api_base", "") or getattr(settings, "apaas_base_url", "")).strip(),
            request,
        )
        login_url = _web_url(api_url)
        platform_type = "apaas_builder"
        platform_name = "aPaaS Builder"
    else:
        login_url = str(getattr(settings, "dolphin_workspace_base_url", "") or _base(request)).rstrip("/")
        api_url = login_url
        platform_type = "control_plane"
        platform_name = str(getattr(settings, "desktop_platform_name", "Dolphin AI") or "Dolphin AI")

    builder_enabled = bool(auth.products.builder.enabled)
    # The standalone aPaaS deployment has no Code Control Plane. Keep Code
    # disabled even when a stale database switch still contains the default.
    code_enabled = provider == "control_plane" and bool(auth.products.code.enabled)
    return {
        "schema_version": 1,
        "deployment_id": str(getattr(settings, "desktop_deployment_id", "ai-builder") or "ai-builder"),
        "platform": {"type": platform_type, "name": platform_name},
        "auth": {
            "provider": provider,
            "login_url": login_url,
            "api_base_url": api_url,
            "logout_url": f"{login_url}/api/auth/logout",
        },
        "products": {
            "builder": {"enabled": builder_enabled, "base_url": _product_url(request, getattr(settings, "desktop_builder_base_url", ""))},
            "code": {"enabled": code_enabled, "base_url": _product_url(request, getattr(settings, "desktop_code_base_url", ""))},
        },
        "remote_capabilities": {
            "models": True,
            "mcp": True,
            "skills": True,
            "knowledge_bases": True,
            # Non-sensitive capability declaration only. The Control Plane
            # keeps the GitLab administrator credential server-side and the
            # desktop sidecar receives an ephemeral user credential per Git
            # command after the user confirms the action.
            "system_git": code_enabled,
        },
        "local_ai": {
            "enabled": True,
            "allowed_kinds": ["model", "mcp", "skill", "knowledge_base"],
            "bridge_protocol_version": int(getattr(settings, "desktop_bridge_protocol_version", 1) or 1),
        },
    }
