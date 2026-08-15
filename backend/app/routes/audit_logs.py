from __future__ import annotations

from datetime import datetime
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit_log import AuditLogQuery, list_audit_logs, require_audit_scope
from app.models import AuditLog
from fastapi import HTTPException
from sqlalchemy import select
from app.database import get_db
from app.deps import AuthContext, get_auth_context


router = APIRouter(prefix="/audit-logs", tags=["audit-logs"])
application_router = APIRouter(prefix="/applications", tags=["audit-logs"])


@router.get("")
async def query_audit_logs(
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
    application_id: Optional[int] = None,
    occurred_from: Optional[datetime] = None,
    occurred_to: Optional[datetime] = None,
    actor_id: Optional[int] = None,
    event_type: Optional[str] = None,
    result: Optional[str] = None,
    cursor: Optional[str] = None,
    limit: int = Query(default=50, ge=1, le=200),
):
    if ctx.tenant_role not in {"tenant_admin", "platform_admin"} or not ctx.tenant_id:
        raise HTTPException(403, "需要租户管理员权限")
    page = await list_audit_logs(db, ctx, AuditLogQuery(
        application_id=application_id,
        occurred_from=occurred_from,
        occurred_to=occurred_to,
        actor_id=actor_id,
        event_type=event_type,
        result=result,
        cursor=cursor,
        limit=limit,
    ))
    return {
        "items": [{
            "id": item.id,
            "occurred_at": item.occurred_at.isoformat(),
            "tenant_id": item.tenant_id,
            "application_id": item.application_id,
            "actor_id": item.actor_id,
            "actor_name": item.actor_name,
            "event_type": item.event_type,
            "target_type": item.target_type,
            "target_id": item.target_id,
            "result": item.result,
            "failure_reason": item.failure_reason,
            "ip_address": item.ip_address,
            "request_id": item.request_id,
            "correlation_id": item.correlation_id,
            "before_value": item.before_value,
            "after_value": item.after_value,
        } for item in page.items],
        "next_cursor": page.next_cursor,
        "total": page.total,
    }


@application_router.get("/{application_id}/audit-logs")
async def query_application_audit_logs(
    application_id: int,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
    cursor: Optional[str] = None,
    limit: int = Query(default=50, ge=1, le=200),
    occurred_from: Optional[datetime] = None,
    occurred_to: Optional[datetime] = None,
    actor_id: Optional[int] = None,
    event_type: Optional[str] = None,
    result: Optional[str] = None,
):
    page = await list_audit_logs(db, ctx, AuditLogQuery(
        application_id=application_id, occurred_from=occurred_from, occurred_to=occurred_to,
        actor_id=actor_id, event_type=event_type, result=result, cursor=cursor, limit=limit,
    ))
    return {"items": page.items, "next_cursor": page.next_cursor, "total": page.total}


@application_router.get("/{application_id}/audit-logs/{audit_id}")
async def get_application_audit_log(application_id: int, audit_id: int, ctx: Annotated[AuthContext, Depends(get_auth_context)], db: Annotated[AsyncSession, Depends(get_db)]):
    await require_audit_scope(db, ctx, application_id)
    item = await db.scalar(select(AuditLog).where(AuditLog.id == audit_id, AuditLog.tenant_id == ctx.tenant_id, AuditLog.application_id == application_id))
    if not item:
        raise HTTPException(404, "审计日志不存在")
    return item


@router.get("/{audit_id}")
async def get_audit_log(audit_id: int, ctx: Annotated[AuthContext, Depends(get_auth_context)], db: Annotated[AsyncSession, Depends(get_db)]):
    if ctx.tenant_role not in {"tenant_admin", "platform_admin"} or not ctx.tenant_id:
        raise HTTPException(403, "需要租户管理员权限")
    item = await db.scalar(select(AuditLog).where(AuditLog.id == audit_id, AuditLog.tenant_id == ctx.tenant_id))
    if not item:
        raise HTTPException(404, "审计日志不存在")
    await require_audit_scope(db, ctx, item.application_id)
    return item
