"""Read-only model options owned by Control Plane."""
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
    """Read and normalize the tenant-scoped Control Plane model catalog."""
    base_url = control_plane_base_url()
    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(connect=10, read=30, write=10, pool=10)
        ) as client:
            response = await client.get(
                f"{base_url}/api/platform-catalog/models",
                headers=_control_plane_headers(
                    authorization_header,
                    delegated_context=delegated_context,
                ),
            )
    except httpx.RequestError as exc:
        raise HTTPException(status_code=503, detail=f"无法连接 Control Plane: {base_url}") from exc
    if response.status_code >= 400:
        raise HTTPException(
            status_code=response.status_code,
            detail=_control_plane_error_detail(response),
        )

    try:
        payload = response.json()
    except ValueError as exc:
        raise HTTPException(status_code=502, detail="Control Plane 模型列表响应无效") from exc
    if isinstance(payload, list):
        table = payload
    elif isinstance(payload, dict):
        table = payload.get("items") or payload.get("list") or payload.get("data")
        if isinstance(table, dict):
            table = table.get("items") or table.get("list") or table.get("table")
    else:
        table = None
    if not isinstance(table, list):
        raise HTTPException(status_code=502, detail="Control Plane 模型目录数据无效")

    options: list[dict[str, Any]] = []
    for item in table:
        if not isinstance(item, dict):
            continue
        status = str(item.get("status") or "").strip().lower()
        if status in {"disabled", "disable", "inactive", "0", "false"}:
            continue
        model = str(
            item.get("modelCode")
            or item.get("model_code")
            or item.get("modelId")
            or item.get("model_id")
            or ""
        ).strip()
        if not model:
            continue
        capabilities = item.get("capabilities")
        if purpose == "coding" and isinstance(capabilities, list) and capabilities:
            normalized = {str(value).strip().lower() for value in capabilities}
            if not normalized.intersection(
                {"coding", "chat", "code", "code_generation", "text_generation", "tool_use"}
            ):
                continue
        digest = hashlib.sha1(f"control_plane:{model}".encode()).hexdigest()
        option_id = -((int(digest[:8], 16) % 2_000_000_000) + 1)
        options.append({
            "id": option_id,
            "config_name": str(
                item.get("displayName")
                or item.get("display_name")
                or item.get("modelName")
                or item.get("model_name")
                or model
            ).strip(),
            "provider": str(
                item.get("providerType")
                or item.get("provider_type")
                or item.get("source")
                or "control-plane"
            ).strip(),
            "model": model,
            "purpose": str(purpose or "builder").strip() or "builder",
            "is_default": bool(
                item.get("isDefault")
                or item.get("is_default")
                or item.get("defaultModel")
            ),
        })
    return options
