from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.deps import AuthContext, get_auth_context
from app.routes.applications._helpers import _resolve_platform_env_for_tenant
from app.routes.applications.logs_endpoint import _verify_app_access
from app.services.app_health.service import run_app_health

router = APIRouter()


@router.get("/{app_id}/health")
async def get_application_health(
    app_id: int,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
    persist: bool = Query(True),
) -> dict:
    app = await _verify_app_access(app_id, ctx, db)
    env_id = app.platform_env_id
    if not env_id:
        env = await _resolve_platform_env_for_tenant(db, app.tenant_id)
        env_id = env.id if env else None
    if not env_id or not app.apaas_app_id:
        raise HTTPException(status_code=400, detail="当前应用未绑定 aPaaS 平台环境或缺少 appId，无法体检")
    report = await run_app_health(app, env_id, db, as_of=datetime.utcnow(), persist=persist)
    return {"ok": True, **report}
