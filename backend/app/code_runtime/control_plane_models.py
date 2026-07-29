from __future__ import annotations

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
    base_url = control_plane_base_url()
    params = {
        "enabled": "true",
        "modelType": "chat",
        "page": 1,
        "pageSize": 100,
    }
    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(connect=10, read=30, write=10, pool=10)
        ) as client:
            response = await client.get(
                f"{base_url}/api/ai-models",
                headers=_control_plane_headers(
                    authorization_header,
                    delegated_context=delegated_context,
                ),
                params=params,
            )
    except httpx.RequestError as exc:
        raise HTTPException(status_code=503, detail=f"无法连接 Code Control Plane: {base_url}") from exc
    if response.status_code >= 400:
        raise HTTPException(
            status_code=response.status_code,
            detail=_control_plane_error_detail(response),
        )

    try:
        payload = response.json()
    except ValueError as exc:
        raise HTTPException(status_code=502, detail="Code Control Plane 模型列表响应无效") from exc
    data = payload.get("data") if isinstance(payload, dict) else None
    table = data.get("table") if isinstance(data, dict) else None
    if not isinstance(table, list):
        raise HTTPException(status_code=502, detail="Code Control Plane 模型列表数据无效")

    options: list[dict[str, Any]] = []
    for item in table:
        if not isinstance(item, dict) or item.get("enabled") is False:
            continue
        provider = item.get("provider") if isinstance(item.get("provider"), dict) else {}
        if provider.get("enabled") is False:
            continue
        try:
            model_id = int(item.get("modelId"))
        except (TypeError, ValueError):
            continue
        model = str(item.get("modelCode") or "").strip()
        if model_id <= 0 or not model:
            continue
        provider_name = str(
            provider.get("providerCode")
            or provider.get("providerName")
            or "control-plane"
        ).strip()
        options.append({
            "id": model_id,
            "config_name": str(item.get("modelDisplayName") or model).strip(),
            "provider": provider_name,
            "model": model,
            "purpose": str(purpose or "coding").strip() or "coding",
            "is_default": bool(item.get("defaultModel")),
        })
    return options
