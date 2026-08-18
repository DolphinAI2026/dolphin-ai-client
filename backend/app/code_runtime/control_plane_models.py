"""Read-only model options served by the Control Plane LiteLLM gateway."""
from __future__ import annotations

import hashlib
from typing import Any

import httpx
from fastapi import HTTPException

from app.code_runtime.service import (
    _control_plane_error_detail,
    _control_plane_headers,
    control_plane_base_url,
)


async def list_control_plane_model_options(
    *,
    purpose: str,
    authorization_header: str,
    delegated_context: Any,
) -> list[dict[str, Any]]:
    """Read models that the same gateway used for execution can actually serve.

    The Full Workspace catalog is useful for management metadata but is not an
    execution contract: it may advertise aliases which have not reached
    LiteLLM yet.  Keep the picker tied to ``/models`` on the Control Plane
    gateway so a selectable model is also a callable one.
    """
    base_url = control_plane_base_url()
    headers = _control_plane_headers(
        authorization_header,
        delegated_context=delegated_context,
    )
    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(connect=10, read=30, write=10, pool=10)
        ) as client:
            response = await client.get(
                f"{base_url}/api/code/model-gateway/v1/models",
                headers=headers,
            )
            # ``/models`` is the execution authority.  The runtime catalog is
            # read only to retain the configured default when that alias is
            # present in LiteLLM; its failure must never hide usable models.
            try:
                runtime_catalog = await client.get(
                    f"{base_url}/api/code/desktop-runtime-model-catalog",
                    headers=headers,
                )
            except httpx.RequestError:
                runtime_catalog = None
    except httpx.RequestError as exc:
        raise HTTPException(status_code=503, detail=f"无法连接 Control Plane: {base_url}") from exc
    if response.status_code >= 400:
        raise HTTPException(
            status_code=response.status_code,
            detail=_control_plane_error_detail(response),
        )

    table = _model_table(response)
    if not isinstance(table, list):
        raise HTTPException(status_code=502, detail="LiteLLM 模型列表响应无效")

    default_model = _runtime_default_model(runtime_catalog)

    options: list[dict[str, Any]] = []
    for item in table:
        if not isinstance(item, dict):
            continue
        status = str(item.get("status") or "").strip().lower()
        if status in {"disabled", "disable", "inactive", "0", "false"}:
            continue
        model = str(
            item.get("id")
            or item.get("model")
            or item.get("model_name")
            or item.get("modelName")
            or item.get("modelCode")
            or item.get("model_code")
            or item.get("modelId")
            or item.get("model_id")
            or ""
        ).strip()
        if not model:
            continue
        # Keep the synthetic ID stable so an existing conversation's explicit
        # model choice still resolves after switching the catalog source.
        digest = hashlib.sha1(f"control_plane:{model}".encode()).hexdigest()
        option_id = -((int(digest[:8], 16) % 2_000_000_000) + 1)
        options.append({
            "id": option_id,
            "config_name": str(
                item.get("displayName")
                or item.get("display_name")
                or item.get("name")
                or item.get("modelName")
                or item.get("model_name")
                or model
            ).strip(),
            "provider": str(
                item.get("owned_by")
                or item.get("provider")
                or "litellm"
            ).strip(),
            "model": model,
            "purpose": str(purpose or "builder").strip() or "builder",
            "is_default": model == default_model,
        })
    if options and not any(option["is_default"] for option in options):
        # LiteLLM's standard ``/models`` schema has no default field.  Make
        # its first returned model the shared fallback rather than importing a
        # default alias that the gateway did not advertise.
        options[0]["is_default"] = True
    return options


def _model_table(response: httpx.Response) -> list[Any] | None:
    try:
        payload = response.json()
    except ValueError as exc:
        raise HTTPException(status_code=502, detail="LiteLLM 模型列表响应无效") from exc
    if isinstance(payload, list):
        return payload
    if not isinstance(payload, dict):
        return None
    table: Any = payload.get("data") or payload.get("models") or payload.get("items") or payload.get("list")
    if isinstance(table, dict):
        table = table.get("data") or table.get("models") or table.get("items") or table.get("list")
    return table if isinstance(table, list) else None


def _runtime_default_model(response: httpx.Response | None) -> str:
    if response is None or response.status_code >= 400:
        return ""
    try:
        payload = response.json()
    except ValueError:
        return ""
    if not isinstance(payload, dict):
        return ""
    return str(payload.get("defaultModel") or payload.get("default_model") or "").strip()
