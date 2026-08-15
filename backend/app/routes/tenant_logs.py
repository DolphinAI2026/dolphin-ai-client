from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.apaas_session import call_apaas_with_relogin
from app.database import get_db
from app.deps import (
    AuthContext,
    get_auth_context,
    is_control_plane_context,
    resolve_effective_tenant_id,
)
from app.routes.applications._helpers import _resolve_platform_env_for_tenant
from app.services.lowcode_logs import (
    build_lowcode_log_analysis,
    build_operate_log_filters,
    extract_lowcode_log_records,
    extract_lowcode_log_total,
    normalize_lowcode_log_record,
)

router = APIRouter()


@router.get("/tenant-logs")
async def get_tenant_lowcode_logs(
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    operation_type: str | None = Query(None),
    function_menu: str | None = Query(None),
    keyword: str | None = Query(None),
) -> dict:
    if is_control_plane_context(ctx):
        raise HTTPException(
            status_code=409,
            detail={
                "code": "CONTROL_PLANE_REMOTE_MANAGEMENT_REQUIRED",
                "message": "aPaaS 租户日志由 Control Plane 远程管理，本地 Builder 不读取 PlatformEnv",
            },
        )
    tenant_id = await resolve_effective_tenant_id(db, ctx)
    env = await _resolve_platform_env_for_tenant(db, tenant_id)
    if not env:
        raise HTTPException(status_code=400, detail="当前租户未绑定 aPaaS 平台环境，无法读取低代码租户日志")

    filters = build_operate_log_filters(
        operation_type=operation_type,
        function_menu=function_menu,
        keyword=keyword,
    )

    async def _query(client):
        return await client.query_operate_logs(page=page, page_size=page_size, filters=filters)

    raw_resp = await call_apaas_with_relogin(env.id, db, _query)
    raw_rows = extract_lowcode_log_records(raw_resp)
    items = [normalize_lowcode_log_record(row) for row in raw_rows]
    total = extract_lowcode_log_total(raw_resp, len(raw_rows))
    analysis = build_lowcode_log_analysis(items)

    return {
        "ok": True,
        "kind": "tenant_lowcode",
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size,
        "has_more": (page * page_size) < total,
        "analysis": analysis,
        "error_count": analysis["high_risk_total"],
    }
