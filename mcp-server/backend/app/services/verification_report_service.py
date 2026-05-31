"""VerificationReport 持久化服务。

把 VerificationAgent.finalize() 的结果写入 verification_reports 表。
"""
from __future__ import annotations

import secrets
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import agent_models


def _new_report_id() -> str:
    ts = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    return f"vr_{ts}_{secrets.token_hex(3)}"


async def save_report(
    db: AsyncSession,
    *,
    coding_session_id: str,
    spec_id: str,
    finalize_result: dict[str, Any],
    model_used: Optional[str] = None,
) -> agent_models.VerificationReport:
    """把 VerificationAgent.finalize() 的 dict 持久化为 VerificationReport 行。

    `finalize_result` 结构（见 verification/agent.py finalize()）：
        overall_status / passed_count / failed_count / items / constraint_results / ...

    `report_id` 优先用 agent 里生成的（emit_report tool 赋的 emitted_report_id），
    否则生成新的（降级场景）。
    """
    report_id = finalize_result.get("report_id") or _new_report_id()
    row = agent_models.VerificationReport(
        id=report_id,
        coding_session_id=coding_session_id,
        spec_id=spec_id,
        overall_status=finalize_result.get("overall_status") or "failed",
        passed_count=int(finalize_result.get("passed_count") or 0),
        failed_count=int(finalize_result.get("failed_count") or 0),
        items=finalize_result.get("items") or [],
        constraint_results=finalize_result.get("constraint_results") or [],
        model_used=model_used,
    )
    db.add(row)
    await db.flush()
    return row


async def get_report(db: AsyncSession, report_id: str) -> Optional[agent_models.VerificationReport]:
    stmt = select(agent_models.VerificationReport).where(
        agent_models.VerificationReport.id == report_id
    )
    return (await db.execute(stmt)).scalar_one_or_none()


async def list_reports_for_spec(
    db: AsyncSession, spec_id: str,
) -> list[agent_models.VerificationReport]:
    """按 spec_id 查全部 report（最新在前）"""
    stmt = (
        select(agent_models.VerificationReport)
        .where(agent_models.VerificationReport.spec_id == spec_id)
        .order_by(desc(agent_models.VerificationReport.created_at))
    )
    return list((await db.execute(stmt)).scalars().all())


async def list_reports_for_coding_session(
    db: AsyncSession, coding_session_id: str,
) -> list[agent_models.VerificationReport]:
    stmt = (
        select(agent_models.VerificationReport)
        .where(agent_models.VerificationReport.coding_session_id == coding_session_id)
        .order_by(desc(agent_models.VerificationReport.created_at))
    )
    return list((await db.execute(stmt)).scalars().all())


def failed_ac_items(report: agent_models.VerificationReport) -> list[dict[str, Any]]:
    """从 report.items 里提取 status=failed 的 AC（用于触发 CodingAgent 重跑时附带问题清单）"""
    return [a for a in (report.items or []) if a.get("status") == "failed"]


def has_blocking_issues(report: agent_models.VerificationReport) -> bool:
    """判断 report 是否有"阻塞性问题"（需要重跑 coding）：
    - overall_status=failed，或
    - 有 constraint hard violated
    """
    if report.overall_status == "failed":
        return True
    for c in report.constraint_results or []:
        if c.get("severity") == "hard" and c.get("status") == "violated":
            return True
    return False
