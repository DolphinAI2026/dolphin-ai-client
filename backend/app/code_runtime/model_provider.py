from __future__ import annotations

import hashlib
import json
import os
import tomllib
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app import runtime


MODEL_REQUIRED = "LOCAL_RUNTIME_MODEL_PROVIDER_REQUIRED"
PREPARATION_FAILED = "LOCAL_RUNTIME_PREPARATION_FAILED"


def _error(status_code: int, code: str, message: str) -> HTTPException:
    return HTTPException(status_code=status_code, detail=f"{code}: {message}")


def _text(value: object) -> str:
    return str(value or "").strip()


def _validated_model_config(model: Any) -> tuple[str, str, str, str]:
    model_name = _text(getattr(model, "model", None))
    base_url = _text(getattr(model, "base_url", None))
    token = _text(getattr(model, "api_key", None))
    provider = _text(getattr(model, "provider", None)).lower() or "openai"
    try:
        parsed = urlsplit(base_url)
    except ValueError as exc:
        raise _error(409, MODEL_REQUIRED, "Coding 模型配置无效") from exc
    if (
        not model_name
        or not token
        or parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
        or any(ord(character) < 32 for character in base_url)
    ):
        raise _error(409, MODEL_REQUIRED, "Coding 模型配置无效")
    return provider, base_url.rstrip("/"), token, model_name


def provider_identity(model: Any) -> tuple[str, str, str]:
    provider, base_url, token, _model_name = _validated_model_config(model)
    return provider, base_url, token


def host_codex_provider_document() -> tuple[dict[str, Any], tuple[str, str, str]] | None:
    if not runtime.is_desktop():
        return None
    if _text(os.getenv("DOLPHIN_CODE_HOST_CODEX_PROVIDER", "0")).lower() not in {
        "1",
        "true",
        "yes",
        "on",
    }:
        return None

    configured_home = _text(os.getenv("DOLPHIN_CODE_HOST_CODEX_HOME"))
    home = configured_home or _text(os.getenv("USERPROFILE")) or _text(os.getenv("HOME"))
    if not home:
        return None
    codex_home = Path(home) if configured_home else Path(home) / ".codex"
    try:
        config = tomllib.loads((codex_home / "config.toml").read_text(encoding="utf-8"))
        auth = json.loads((codex_home / "auth.json").read_text(encoding="utf-8"))
    except (OSError, ValueError, tomllib.TOMLDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(config, dict) or not isinstance(auth, dict):
        return None

    provider_name = _text(config.get("model_provider"))
    model_name = _text(config.get("model"))
    providers = config.get("model_providers")
    provider_config = providers.get(provider_name) if isinstance(providers, dict) else None
    if not provider_name or not model_name or not isinstance(provider_config, dict):
        return None
    env_key = _text(provider_config.get("env_key"))
    provider_view = type("HostCodexProvider", (), {
        "provider": "openai",
        "base_url": _text(provider_config.get("base_url")),
        "api_key": (_text(os.getenv(env_key)) if env_key else "") or _text(auth.get("OPENAI_API_KEY")),
        "model": model_name,
    })()
    try:
        identity = provider_identity(provider_view)
    except HTTPException:
        return None
    provider_id = "host." + hashlib.sha256("\x00".join(identity).encode()).hexdigest()[:20]
    return _document(provider_id, identity, model_name, [model_name]), identity


def _document(
    provider_id: str,
    identity: tuple[str, str, str],
    default_model: str,
    models: list[str],
) -> dict[str, Any]:
    return {
        "defaultProviderId": provider_id,
        "providers": [{
            "providerId": provider_id,
            "providerType": "openai-compatible",
            "runtimeProviderKind": identity[0],
            "apiBaseUrl": identity[1],
            "token": identity[2],
            "defaultModel": default_model,
            "models": [{"id": model, "displayName": model} for model in models],
        }],
    }


def _catalog_cache_path(cache_dir: Path, tenant_id: str) -> Path:
    digest = hashlib.sha256(tenant_id.encode()).hexdigest()[:20]
    return cache_dir / f"control-plane-{digest}.json"


def _catalog_provider(catalog: dict[str, Any]) -> tuple[str, str, list[str]]:
    providers = catalog.get("providers")
    default_id = _text(catalog.get("defaultProviderId"))
    if not isinstance(providers, list) or not default_id:
        raise ValueError("catalog providers are invalid")
    provider = next((item for item in providers if isinstance(item, dict) and _text(item.get("providerId")) == default_id), None)
    if not provider or not provider.get("credentialConfigured"):
        raise ValueError("catalog default provider is unavailable")
    default_model = _text(provider.get("defaultModel")) or _text(catalog.get("defaultModel"))
    models = [
        _text(item.get("id"))
        for item in provider.get("models", [])
        if isinstance(item, dict) and _text(item.get("id"))
    ]
    if not default_model or default_model not in models:
        raise ValueError("catalog default model is invalid")
    return default_id, default_model, models


async def _control_plane_catalog(
    *,
    control_plane_url: str,
    authorization: str,
    tenant_id: str,
    cache_dir: Path,
) -> dict[str, Any] | None:
    cache_path = _catalog_cache_path(cache_dir, tenant_id)
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(connect=5, read=15, write=10, pool=10)) as client:
            response = await client.get(
                f"{control_plane_url.rstrip('/')}/api/code/desktop-runtime-model-catalog",
                headers={"Authorization": authorization, "X-Tenant-Id": tenant_id},
            )
        if response.status_code >= 400:
            raise ValueError("catalog request failed")
        catalog = response.json()
        if not isinstance(catalog, dict):
            raise ValueError("catalog response is invalid")
        _catalog_provider(catalog)
        cache_dir.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(json.dumps(catalog, ensure_ascii=True), encoding="utf-8")
        return catalog
    except (httpx.HTTPError, OSError, ValueError, json.JSONDecodeError):
        try:
            cached = json.loads(cache_path.read_text(encoding="utf-8"))
            _catalog_provider(cached)
            return cached
        except (OSError, ValueError, json.JSONDecodeError):
            return None


async def _local_provider(
    db: AsyncSession,
    tenant_id: int,
    selected_config_id: int | None,
) -> tuple[dict[str, Any], tuple[str, str, str]] | None:
    from app.crypto import decrypt_password
    from app.harness.llm_resolver import resolve_llm_config
    from app.routes.llm_configs import list_llm_configs_for_purpose

    selected = await resolve_llm_config(
        db, tenant_id, purpose="coding", selected_config_id=selected_config_id
    )
    if selected is None:
        return None
    identity = provider_identity(selected)
    compatible: set[str] = {_validated_model_config(selected)[3]}
    candidates = await list_llm_configs_for_purpose(db, tenant_id, "coding")
    if not candidates:
        candidates = await list_llm_configs_for_purpose(db, None, "coding")
    for candidate in candidates:
        try:
            candidate_view = type("CandidateModel", (), {
                "provider": candidate.provider,
                "base_url": candidate.base_url,
                "api_key": decrypt_password(candidate.api_key_enc),
                "model": candidate.model,
            })()
            if provider_identity(candidate_view) == identity:
                compatible.add(_validated_model_config(candidate_view)[3])
        except Exception:
            continue
    provider_id = "local." + hashlib.sha256("\x00".join(identity).encode()).hexdigest()[:20]
    return _document(provider_id, identity, _validated_model_config(selected)[3], sorted(compatible)), identity


async def provider_document(
    db: AsyncSession,
    ctx: Any,
    selected_config_id: int | None,
    *,
    control_plane_url: str | None = None,
    control_plane_authorization: str | None = None,
    control_plane_tenant_id: str | None = None,
    local_proxy_url: str | None = None,
    local_proxy_token: str | None = None,
    cache_dir: str | Path | None = None,
) -> tuple[dict[str, Any], tuple[str, str, str]]:
    if selected_config_id is not None:
        local = await _local_provider(db, int(ctx.tenant_id), selected_config_id)
        if local is not None:
            return local

    host = host_codex_provider_document()
    if host is not None:
        return host

    if all((control_plane_url, control_plane_authorization, control_plane_tenant_id, local_proxy_url, local_proxy_token, cache_dir)):
        catalog = await _control_plane_catalog(
            control_plane_url=_text(control_plane_url),
            authorization=_text(control_plane_authorization),
            tenant_id=_text(control_plane_tenant_id),
            cache_dir=Path(str(cache_dir)),
        )
        if catalog is not None:
            provider_id, default_model, models = _catalog_provider(catalog)
            identity = ("openai", _text(local_proxy_url).rstrip("/"), _text(local_proxy_token))
            return _document(provider_id, identity, default_model, models), identity

    local = await _local_provider(db, int(ctx.tenant_id), None)
    if local is not None:
        return local
    raise _error(409, MODEL_REQUIRED, "请先配置可用的 Coding 模型")


def provider_identity_from_document(document: dict[str, Any]) -> tuple[str, str, str]:
    providers = document.get("providers")
    if not isinstance(providers, list) or len(providers) != 1 or not isinstance(providers[0], dict):
        raise ValueError("invalid runtime model provider document")
    provider = providers[0]
    view = type("PersistedModel", (), {
        "provider": provider.get("runtimeProviderKind"),
        "base_url": provider.get("apiBaseUrl"),
        "api_key": provider.get("token"),
        "model": provider.get("defaultModel"),
    })()
    return provider_identity(view)


def provider_catalog_identity(document: dict[str, Any]) -> str:
    providers = document.get("providers")
    if not isinstance(providers, list):
        raise ValueError("invalid runtime model provider document")
    catalog = {
        "defaultProviderId": _text(document.get("defaultProviderId")),
        "providers": [
            {
                "providerId": _text(provider.get("providerId")),
                "defaultModel": _text(provider.get("defaultModel")),
                "models": sorted(
                    _text(model.get("id"))
                    for model in provider.get("models", [])
                    if isinstance(model, dict) and _text(model.get("id"))
                ),
            }
            for provider in providers
            if isinstance(provider, dict)
        ],
    }
    if not catalog["defaultProviderId"] or not catalog["providers"]:
        raise ValueError("invalid runtime model provider catalog")
    encoded = json.dumps(catalog, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()
