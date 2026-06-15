from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.apaas_session import call_apaas_with_relogin
from app.database import get_db
from app.deps import AuthContext, get_auth_context
from app.routes.applications._helpers import _resolve_platform_env_for_tenant
from app.routes.applications.logs_endpoint import _verify_app_access
from app.services.lowcode_logs import (
    build_lowcode_log_analysis,
    build_operate_log_filters,
    extract_lowcode_log_records,
    extract_lowcode_log_total,
    filter_lowcode_logs_for_application,
    normalize_lowcode_log_record,
)

router = APIRouter()


@router.get("/{app_id}/lowcode-logs")
async def get_application_lowcode_logs(
    app_id: int,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    operation_type: str | None = Query(None),
    function_menu: str | None = Query(None),
    keyword: str | None = Query(None),
) -> dict:
    app = await _verify_app_access(app_id, ctx, db)
    env_id = app.platform_env_id
    if not env_id:
        env = await _resolve_platform_env_for_tenant(db, app.tenant_id)
        env_id = env.id if env else None
    if not env_id:
        raise HTTPException(status_code=400, detail="当前应用未绑定 aPaaS 平台环境，无法读取低代码租户日志")

    filters = build_operate_log_filters(
        operation_type=operation_type,
        function_menu=function_menu,
        keyword=keyword,
    )

    async def _query(client):
        return await client.query_operate_logs(page=page, page_size=page_size, filters=filters)

    raw_resp = await call_apaas_with_relogin(env_id, db, _query)
    raw_rows = extract_lowcode_log_records(raw_resp)
    app_rows = filter_lowcode_logs_for_application(raw_rows, app)
    items = [normalize_lowcode_log_record(row) for row in app_rows]
    analysis = build_lowcode_log_analysis(items)
    total = extract_lowcode_log_total(raw_resp, len(raw_rows))

    return {
        "ok": True,
        "kind": "lowcode",
        "items": items,
        "total": len(app_rows) if len(app_rows) != len(raw_rows) else total,
        "page": page,
        "page_size": page_size,
        "has_more": (page * page_size) < total,
        "analysis": analysis,
        "error_count": analysis["high_risk_total"],
    }
