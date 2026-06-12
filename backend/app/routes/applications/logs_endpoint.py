"""应用日志 — 4 kind 聚合 endpoint

GET /{app_id}/logs/{kind}

kind:
  - deploy:    DeployRecord 表 (部署 / 回滚 / 发布)
  - operation: ChangePlan 表 (配置变更) + ApiCallLog (用户触发的 admin API)
  - ai:        (旧 config-chat 链路已删, 当前无 app-bound AI 工具日志来源 → 空)
  - error:     filter status='failed' / success=false 的全部以上类别

返回统一 schema:
{
  ok: bool,
  items: [{
    timestamp: iso str,
    type: str ("部署" / "改配置" / "AI 工具" / ...),
    user: str (user_name / "system"),
    summary: str (一句话简介),
    status: str ("success" / "failed" / "in_progress"),
    details: object (raw payload 给详情 modal),
  }],
  total: int,
  has_more: bool,
  stats: {total, errors, ai_calls},
}
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from typing import Annotated, Optional, List, Dict, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, desc, func as sa_func, or_, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.deps import get_auth_context, AuthContext
from app.models import (
    Application,
    DeployRecord,
    ConfigSnapshot,
    ChangePlan,
    ApiCallLog,
    User,
)
from app.permissions import check_resource_permission, Action

logger = logging.getLogger(__name__)
router = APIRouter()


# 时间范围预设 → timedelta（None = 全部）
_TIME_RANGES: Dict[str, Optional[timedelta]] = {
    "1h": timedelta(hours=1),
    "today": timedelta(hours=24),  # 简化：最近 24h（不严格按自然日）
    "7d": timedelta(days=7),
    "all": None,
}


def _parse_time_range(time_range: Optional[str]) -> Optional[datetime]:
    """返回 cutoff datetime（早于此时间的过滤掉），None 表示不过滤"""
    if not time_range or time_range == "all":
        return None
    td = _TIME_RANGES.get(time_range)
    if td is None:
        return None
    return datetime.utcnow() - td


async def _load_user_name_map(
    db: AsyncSession, user_ids: List[int]
) -> Dict[int, str]:
    """批量拉 user.username 映射，避免 N+1"""
    if not user_ids:
        return {}
    uniq = list(set(user_ids))
    result = await db.execute(select(User).where(User.id.in_(uniq)))
    return {u.id: (u.username or u.email or f"user#{u.id}") for u in result.scalars().all()}


async def _verify_app_access(
    app_id: int, ctx: AuthContext, db: AsyncSession
) -> Application:
    result = await db.execute(
        select(Application).where(
            Application.id == app_id,
            Application.tenant_id == ctx.tenant_id,
        )
    )
    app = result.scalar_one_or_none()
    if not app:
        raise HTTPException(status_code=404, detail="应用不存在")
    await check_resource_permission(ctx, db, app, "application", Action.VIEW)
    return app


# ── kind: deploy ─────────────────────────────────────────────────────────────


async def _fetch_deploy_logs(
    db: AsyncSession,
    app_id: int,
    cutoff: Optional[datetime],
    status_filter: Optional[str],
    page: int,
    page_size: int,
) -> tuple[List[dict], int]:
    """部署历史 — 直接查 deploy_records"""
    conds = [DeployRecord.app_id == app_id]
    if cutoff is not None:
        conds.append(DeployRecord.created_at >= cutoff)
    if status_filter and status_filter != "all":
        if status_filter == "success":
            conds.append(DeployRecord.status == "success")
        elif status_filter == "failed":
            conds.append(DeployRecord.status == "failed")
        elif status_filter == "in_progress":
            conds.append(DeployRecord.status == "in_progress")

    total_result = await db.execute(
        select(sa_func.count()).select_from(DeployRecord).where(and_(*conds))
    )
    total = total_result.scalar() or 0

    result = await db.execute(
        select(DeployRecord)
        .where(and_(*conds))
        .order_by(desc(DeployRecord.created_at))
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    records = list(result.scalars().all())

    user_ids = [r.user_id for r in records if r.user_id]
    user_map = await _load_user_name_map(db, user_ids)

    items: List[dict] = []
    for r in records:
        type_label = {
            "deploy": "部署",
            "publish": "发布",
            "rollback": "回滚",
        }.get(r.deploy_type, r.deploy_type or "部署")

        summary_parts = [type_label]
        if r.version_label:
            summary_parts.append(r.version_label)
        if r.apaas_app_id_after:
            summary_parts.append(f"→ {r.apaas_app_id_after}")
        summary = " · ".join(summary_parts)
        if r.status == "failed" and r.error_message:
            err_brief = r.error_message[:80] + ("..." if len(r.error_message) > 80 else "")
            summary = f"{summary} (失败: {err_brief})"

        items.append({
            "id": f"deploy-{r.id}",
            "timestamp": r.created_at.isoformat() if r.created_at else None,
            "type": type_label,
            "user": user_map.get(r.user_id, f"user#{r.user_id}"),
            "summary": summary,
            "status": r.status,
            "details": {
                "deploy_record_id": r.id,
                "version_label": r.version_label,
                "deploy_type": r.deploy_type,
                "apaas_app_id_before": r.apaas_app_id_before,
                "apaas_app_id_after": r.apaas_app_id_after,
                "error_message": r.error_message,
                "event_log": r.event_log_json,
                "completed_at": r.completed_at.isoformat() if r.completed_at else None,
            },
        })
    return items, total


# ── kind: operation ──────────────────────────────────────────────────────────


async def _fetch_operation_logs(
    db: AsyncSession,
    app_id: int,
    cutoff: Optional[datetime],
    status_filter: Optional[str],
    page: int,
    page_size: int,
) -> tuple[List[dict], int]:
    """操作日志 = ChangePlan (配置变更) + ApiCallLog (用户触发的 API)

    注：ChangePlan / ApiCallLog 各自有自己的状态语义，统一映射:
    - ChangePlan.status: pending/confirmed/completed/cancelled → success/in_progress/failed
    - ApiCallLog.success bool → success/failed
    """
    # 1) ChangePlan
    cp_conds = [ChangePlan.application_id == app_id]
    if cutoff is not None:
        cp_conds.append(ChangePlan.created_at >= cutoff)

    # 2) ApiCallLog (绑定 application_id 的)
    ac_conds = [ApiCallLog.application_id == app_id]
    if cutoff is not None:
        ac_conds.append(ApiCallLog.created_at >= cutoff)
    if status_filter == "success":
        ac_conds.append(ApiCallLog.success == True)  # noqa: E712
    elif status_filter == "failed":
        ac_conds.append(ApiCallLog.success == False)  # noqa: E712

    cp_result = await db.execute(
        select(ChangePlan).where(and_(*cp_conds)).order_by(desc(ChangePlan.created_at)).limit(500)
    )
    cps = list(cp_result.scalars().all())

    ac_result = await db.execute(
        select(ApiCallLog).where(and_(*ac_conds)).order_by(desc(ApiCallLog.created_at)).limit(500)
    )
    acs = list(ac_result.scalars().all())

    user_ids: List[int] = []
    for cp in cps:
        # ChangePlan 没 user_id，conversation_id 也没直接关联; 走系统标记
        pass
    user_ids.extend([a.user_id for a in acs if a.user_id])
    user_map = await _load_user_name_map(db, user_ids)

    merged: List[dict] = []
    for cp in cps:
        cp_status = {
            "completed": "success",
            "confirmed": "in_progress",
            "pending": "in_progress",
            "cancelled": "failed",
        }.get(cp.status, "in_progress")
        if status_filter and status_filter != "all" and cp_status != status_filter:
            continue
        try:
            diff = json.loads(cp.diff_summary) if cp.diff_summary else {}
        except (json.JSONDecodeError, TypeError):
            diff = {}
        added = len(diff.get("added", []) or [])
        modified = len(diff.get("modified", []) or [])
        removed = len(diff.get("removed", []) or [])
        summary = f"改配置 v{cp.from_version}→v{cp.to_version}: 加 {added} 改 {modified} 删 {removed}"
        merged.append({
            "id": f"changeplan-{cp.id}",
            "timestamp": cp.created_at.isoformat() if cp.created_at else None,
            "type": "改配置",
            "user": "system",
            "summary": summary,
            "status": cp_status,
            "details": {
                "change_plan_id": cp.id,
                "from_version": cp.from_version,
                "to_version": cp.to_version,
                "diff_summary": diff,
                "executed_at": cp.executed_at.isoformat() if cp.executed_at else None,
            },
            "_ts": cp.created_at or datetime.min,
        })

    for a in acs:
        a_status = "success" if a.success else "failed"
        summary = f"{a.method} {a.step_key or a.url[:60]}"
        if not a.success and a.error_message:
            err_brief = a.error_message[:80] + ("..." if len(a.error_message) > 80 else "")
            summary = f"{summary} (失败: {err_brief})"
        merged.append({
            "id": f"apicall-{a.id}",
            "timestamp": a.created_at.isoformat() if a.created_at else None,
            "type": "API 调用",
            "user": user_map.get(a.user_id, f"user#{a.user_id}"),
            "summary": summary,
            "status": a_status,
            "details": {
                "api_call_id": a.id,
                "method": a.method,
                "url": a.url,
                "step_key": a.step_key,
                "response_status": a.response_status,
                "elapsed_ms": a.elapsed_ms,
                "error_message": a.error_message,
                "request_body": a.request_body,
                "response_body": a.response_body,
            },
            "_ts": a.created_at or datetime.min,
        })

    merged.sort(key=lambda x: x["_ts"], reverse=True)
    total = len(merged)
    start = (page - 1) * page_size
    page_items = merged[start:start + page_size]
    for it in page_items:
        it.pop("_ts", None)
    return page_items, total


# ── kind: ai ─────────────────────────────────────────────────────────────────


async def _fetch_ai_logs(
    db: AsyncSession,
    app_id: int,
    cutoff: Optional[datetime],
    status_filter: Optional[str],
    page: int,
    page_size: int,
) -> tuple[List[dict], int]:
    """AI 行为日志。

    旧数据源 = config-chat 助手的 ConfigChatMessage.tool_trace_json，该链路已整删
    (配置助手单一事实 = unified run_agent)。当前无 app-bound AI 工具日志来源，
    返空。后续若要恢复，应改接 unified 的 AIChatToolCall (按 AIChatSession.app_id 过滤)。
    """
    return [], 0


# ── kind: error ──────────────────────────────────────────────────────────────


async def _fetch_error_logs(
    db: AsyncSession,
    app_id: int,
    cutoff: Optional[datetime],
    page: int,
    page_size: int,
) -> tuple[List[dict], int]:
    """错误日志 = 所有 kind 失败合并"""
    # 复用 3 个 fetch，强制 status_filter='failed'
    deploy_items, _ = await _fetch_deploy_logs(db, app_id, cutoff, "failed", 1, 200)
    op_items, _ = await _fetch_operation_logs(db, app_id, cutoff, "failed", 1, 200)
    ai_items, _ = await _fetch_ai_logs(db, app_id, cutoff, "failed", 1, 200)

    all_items = deploy_items + op_items + ai_items

    def _ts_key(it: dict) -> datetime:
        ts = it.get("timestamp")
        if not ts:
            return datetime.min
        try:
            return datetime.fromisoformat(ts)
        except (ValueError, TypeError):
            return datetime.min

    all_items.sort(key=_ts_key, reverse=True)
    total = len(all_items)
    start = (page - 1) * page_size
    page_items = all_items[start:start + page_size]
    return page_items, total


# ── stats helper ─────────────────────────────────────────────────────────────


async def _compute_stats(db: AsyncSession, app_id: int) -> Dict[str, int]:
    """返 {total, errors, ai_calls} — 顶部 stats bar 用"""
    # total = deploy + change_plan + api_call + ai_tool
    deploy_total = (
        await db.execute(
            select(sa_func.count()).select_from(DeployRecord).where(DeployRecord.app_id == app_id)
        )
    ).scalar() or 0
    cp_total = (
        await db.execute(
            select(sa_func.count()).select_from(ChangePlan).where(ChangePlan.application_id == app_id)
        )
    ).scalar() or 0
    ac_total = (
        await db.execute(
            select(sa_func.count()).select_from(ApiCallLog).where(ApiCallLog.application_id == app_id)
        )
    ).scalar() or 0

    deploy_errors = (
        await db.execute(
            select(sa_func.count())
            .select_from(DeployRecord)
            .where(DeployRecord.app_id == app_id, DeployRecord.status == "failed")
        )
    ).scalar() or 0
    ac_errors = (
        await db.execute(
            select(sa_func.count())
            .select_from(ApiCallLog)
            .where(ApiCallLog.application_id == app_id, ApiCallLog.success == False)  # noqa: E712
        )
    ).scalar() or 0

    # AI 工具调用数 — 旧 config-chat 链路 (ConfigChatMessage.tool_trace_json) 已整删,
    # 暂无 app-bound AI 工具日志来源 → 0。恢复时改接 unified AIChatToolCall。
    ai_calls = 0

    return {
        "total": int(deploy_total) + int(cp_total) + int(ac_total) + int(ai_calls),
        "errors": int(deploy_errors) + int(ac_errors),
        "ai_calls": int(ai_calls),
    }


# ── 主 endpoint ──────────────────────────────────────────────────────────────


@router.get("/{app_id}/logs/{kind}")
async def get_application_logs(
    app_id: int,
    kind: str,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    time_range: Optional[str] = Query(None),  # 1h / today / 7d / all
    status: Optional[str] = Query(None),  # all / success / failed / in_progress
) -> dict:
    """统一日志拉取 endpoint。

    kind:
      - deploy:    DeployRecord 表
      - operation: ChangePlan + ApiCallLog (按 application_id 过滤)
      - ai:        (旧 config-chat 链路已删, 当前无来源 → 空)
      - error:     上面三类合并 + status=failed

    返回 {ok, items, total, has_more, stats}
    """
    await _verify_app_access(app_id, ctx, db)

    cutoff = _parse_time_range(time_range)

    if kind == "deploy":
        items, total = await _fetch_deploy_logs(db, app_id, cutoff, status, page, page_size)
    elif kind == "operation":
        items, total = await _fetch_operation_logs(db, app_id, cutoff, status, page, page_size)
    elif kind == "ai":
        items, total = await _fetch_ai_logs(db, app_id, cutoff, status, page, page_size)
    elif kind == "error":
        items, total = await _fetch_error_logs(db, app_id, cutoff, page, page_size)
    else:
        raise HTTPException(status_code=400, detail=f"未知日志类型: {kind} (支持: deploy/operation/ai/error)")

    has_more = (page * page_size) < total
    stats = await _compute_stats(db, app_id)

    return {
        "ok": True,
        "kind": kind,
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size,
        "has_more": has_more,
        "stats": stats,
    }
