from __future__ import annotations

import base64
import binascii
import json
import logging
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Iterable, Optional

from fastapi import HTTPException
from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.deps import AuthContext
from app.database import AsyncSessionLocal
from app.models import Application, AuditLog
from app.application_access import resolve_effective_application_role


SENSITIVE_KEY_PARTS = (
    "password", "passwd", "secret", "token", "credential", "authorization",
    "cookie", "private_key", "access_key", "api_key",
)
_CREDENTIAL_URL = re.compile(r"(?P<scheme>[a-z][a-z0-9+.-]*://)(?P<user>[^/@:\s]+):(?P<password>[^/@\s]+)@", re.I)
MAX_AUDIT_DEPTH = 8
MAX_AUDIT_JSON_BYTES = 64 * 1024
ALLOWED_AUDIT_EVENT_TYPES = {"application_member.direct_add", "application_member.role_changed", "application_member.removed"}
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AuditActorContext:
    tenant_id: int
    actor_id: Optional[int]
    actor_name: str


def snapshot_audit_actor(ctx: AuthContext) -> AuditActorContext:
    return AuditActorContext(
        tenant_id=ctx.tenant_id,
        actor_id=ctx.user.id,
        actor_name=ctx.user.display_name or ctx.user.username,
    )


@dataclass(frozen=True)
class AuditLogQuery:
    application_id: Optional[int] = None
    occurred_from: Optional[datetime] = None
    occurred_to: Optional[datetime] = None
    actor_id: Optional[int] = None
    event_type: Optional[str] = None
    result: Optional[str] = None
    cursor: Optional[str] = None
    limit: int = 50


@dataclass(frozen=True)
class AuditLogPage:
    items: list[AuditLog]
    next_cursor: Optional[str]
    total: int


def _is_sensitive_key(key: object) -> bool:
    normalized = str(key).strip().lower().replace("-", "_")
    return any(part in normalized for part in SENSITIVE_KEY_PARTS)


def redact_audit_value(value: Any, *, sensitive_values: Iterable[object] = ()) -> Any:
    secrets = [str(item) for item in sensitive_values if item is not None and str(item)]

    def redact(item: Any, depth: int = 0) -> Any:
        if depth > MAX_AUDIT_DEPTH:
            return "[TRUNCATED]"
        if isinstance(item, dict):
            return {
                str(key): "[REDACTED]" if _is_sensitive_key(key) else redact(child, depth + 1)
                for key, child in item.items()
            }
        if isinstance(item, list):
            return [redact(child, depth + 1) for child in item]
        if isinstance(item, tuple):
            return [redact(child, depth + 1) for child in item]
        if isinstance(item, str):
            item = _CREDENTIAL_URL.sub(lambda match: f"{match.group('scheme')}{match.group('user')}:[REDACTED]@", item)
            for secret in secrets:
                item = item.replace(secret, "[REDACTED]")
            return item
        return item

    result = redact(value)
    if len(json.dumps(result, ensure_ascii=False, default=str).encode()) > MAX_AUDIT_JSON_BYTES:
        return "[TRUNCATED]"
    return result


def _encode_cursor(occurred_at: datetime, audit_id: int) -> str:
    payload = json.dumps(
        {"occurred_at": occurred_at.isoformat(), "id": audit_id},
        separators=(",", ":"),
    ).encode()
    return base64.urlsafe_b64encode(payload).decode().rstrip("=")


def _decode_cursor(cursor: str) -> tuple[datetime, int]:
    try:
        padding = "=" * (-len(cursor) % 4)
        raw = base64.b64decode(cursor + padding, altchars=b"-_", validate=True)
        payload = json.loads(raw.decode("utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("cursor payload must be an object")
        occurred_at = payload.get("occurred_at")
        audit_id = payload.get("id")
        if not isinstance(occurred_at, str) or not isinstance(audit_id, int) or isinstance(audit_id, bool):
            raise ValueError("cursor fields have invalid types")
        return datetime.fromisoformat(occurred_at), audit_id
    except (binascii.Error, UnicodeDecodeError, ValueError, TypeError, json.JSONDecodeError):
        raise HTTPException(status_code=400, detail="无效的审计日志游标")


async def require_audit_scope(
    db: AsyncSession,
    ctx: AuthContext,
    application_id: Optional[int],
) -> Optional[int]:
    if ctx.tenant_role in {"tenant_admin", "platform_admin"}:
        if application_id is not None:
            app_tenant_id = await db.scalar(
                select(Application.tenant_id).where(Application.id == application_id)
            )
            if app_tenant_id != ctx.tenant_id:
                raise HTTPException(status_code=403, detail="无权查看该应用审计日志")
        return application_id

    if application_id is None:
        raise HTTPException(status_code=403, detail="应用角色只能查看当前应用审计日志")
    app = await db.scalar(
        select(Application).where(
            Application.id == application_id,
            Application.tenant_id == ctx.tenant_id,
        )
    )
    if not app:
        raise HTTPException(status_code=403, detail="无权查看该应用审计日志")
    role = await resolve_effective_application_role(db, app, ctx.user.id)
    if role not in {"owner", "admin"}:
        raise HTTPException(status_code=403, detail="需要应用所有者或管理员权限")
    return application_id


def _audit_filters(tenant_id: int, query: AuditLogQuery) -> list[Any]:
    filters: list[Any] = [AuditLog.tenant_id == tenant_id]
    if query.application_id is not None:
        filters.append(AuditLog.application_id == query.application_id)
    if query.occurred_from is not None:
        filters.append(AuditLog.occurred_at >= query.occurred_from)
    if query.occurred_to is not None:
        filters.append(AuditLog.occurred_at <= query.occurred_to)
    if query.actor_id is not None:
        filters.append(AuditLog.actor_id == query.actor_id)
    if query.event_type:
        filters.append(AuditLog.event_type == query.event_type)
    if query.result:
        filters.append(AuditLog.result == query.result)
    return filters


async def list_audit_logs(
    db: AsyncSession,
    ctx: AuthContext,
    query: AuditLogQuery,
) -> AuditLogPage:
    application_id = await require_audit_scope(db, ctx, query.application_id)
    query = AuditLogQuery(**{**query.__dict__, "application_id": application_id})
    filters = _audit_filters(ctx.tenant_id, query)
    total = int(await db.scalar(select(func.count(AuditLog.id)).where(*filters)) or 0)
    page_filters = list(filters)
    if query.cursor:
        occurred_at, audit_id = _decode_cursor(query.cursor)
        page_filters.append(or_(
            AuditLog.occurred_at < occurred_at,
            and_(AuditLog.occurred_at == occurred_at, AuditLog.id < audit_id),
        ))
    limit = max(1, min(int(query.limit), 200))
    rows = list((await db.scalars(
        select(AuditLog)
        .where(*page_filters)
        .order_by(AuditLog.occurred_at.desc(), AuditLog.id.desc())
        .limit(limit + 1)
    )).all())
    has_more = len(rows) > limit
    items = rows[:limit]
    next_cursor = _encode_cursor(items[-1].occurred_at, items[-1].id) if has_more else None
    return AuditLogPage(items=items, next_cursor=next_cursor, total=total)


def add_audit_log(
    db: AsyncSession,
    *,
    ctx: AuthContext,
    event_type: str,
    target_type: str,
    target_id: Optional[object],
    result: str,
    application_id: Optional[int] = None,
    failure_reason: Optional[str] = None,
    ip_address: Optional[str] = None,
    request_id: Optional[str] = None,
    correlation_id: Optional[str] = None,
    before_value: Any = None,
    after_value: Any = None,
    sensitive_values: Iterable[object] = (),
) -> AuditLog:
    if event_type not in ALLOWED_AUDIT_EVENT_TYPES:
        raise ValueError(f"unsupported audit event type: {event_type}")
    fact = AuditLog(
        tenant_id=ctx.tenant_id,
        application_id=application_id,
        actor_id=ctx.user.id,
        actor_name=ctx.user.display_name or ctx.user.username,
        event_type=event_type,
        target_type=target_type,
        target_id=None if target_id is None else str(target_id),
        result=result,
        failure_reason=redact_audit_value(failure_reason, sensitive_values=sensitive_values),
        ip_address=ip_address,
        request_id=request_id,
        correlation_id=correlation_id,
        before_value=redact_audit_value(before_value, sensitive_values=sensitive_values),
        after_value=redact_audit_value(after_value, sensitive_values=sensitive_values),
    )
    db.add(fact)
    return fact


async def record_audit_log_best_effort(
    *,
    event_type: str,
    target_type: str,
    target_id: Optional[object],
    result: str,
    failure_reason: Optional[str] = None,
    application_id: Optional[int] = None,
    ctx: Optional[AuthContext] = None,
    actor: Optional[AuditActorContext] = None,
    ip_address: Optional[str] = None,
    request_id: Optional[str] = None,
    correlation_id: Optional[str] = None,
    before_value: Any = None,
    after_value: Any = None,
    sensitive_values: Iterable[object] = (),
    session_factory: Any = None,
) -> bool:
    """Persist a rejected or failed action without changing its original error."""

    actor = actor or (snapshot_audit_actor(ctx) if ctx is not None else None)
    if actor is None:
        raise ValueError("ctx or actor is required")
    factory = session_factory or AsyncSessionLocal
    try:
        async with factory() as db:
            try:
                safe_application_id = None
                if application_id is not None:
                    app_tenant_id = await db.scalar(
                        select(Application.tenant_id).where(Application.id == application_id)
                    )
                    if app_tenant_id == actor.tenant_id:
                        safe_application_id = application_id
                fact = AuditLog(
                    tenant_id=actor.tenant_id,
                    application_id=safe_application_id,
                    actor_id=actor.actor_id,
                    actor_name=actor.actor_name,
                    event_type=event_type,
                    target_type=target_type,
                    target_id=None if target_id is None else str(target_id),
                    result=result,
                    failure_reason=redact_audit_value(
                        failure_reason,
                        sensitive_values=sensitive_values,
                    ),
                    ip_address=ip_address,
                    request_id=request_id,
                    correlation_id=correlation_id,
                    before_value=redact_audit_value(
                        before_value,
                        sensitive_values=sensitive_values,
                    ),
                    after_value=redact_audit_value(
                        after_value,
                        sensitive_values=sensitive_values,
                    ),
                )
                if event_type not in ALLOWED_AUDIT_EVENT_TYPES:
                    raise ValueError(f"unsupported audit event type: {event_type}")
                db.add(fact)
                await db.commit()
            except Exception:
                await db.rollback()
                raise
        return True
    except Exception:
        logger.exception(
            "best-effort audit write failed",
            extra={
                "audit_event_type": event_type,
                "audit_result": result,
                "tenant_id": actor.tenant_id,
                "application_id": application_id,
            },
        )
        return False
