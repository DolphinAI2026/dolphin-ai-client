"""Agent 可观测写入门面（旁路）。

所有写入只经此处。任何异常都被吞掉 —— observability 绝不能影响主 agent 流程。
每个方法用独立 AsyncSessionLocal 会话，跟主 agent 的 db session 隔离，避免 recorder
的 commit 把主流程半成品事务带翻 / 被主流程 rollback 牵连。
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import case, func, select

from app.database import AsyncSessionLocal
from app.models.agent_observability import AgentRun, AgentStep
from app.system_assistant.telemetry import governance_telemetry, log_governance_event

async def start_run(
    *,
    agent_type: str,
    tenant_id: Optional[int] = None,
    user_id: Optional[int] = None,
    session_id: Optional[Any] = None,
    app_id: Optional[Any] = None,
    model: Optional[str] = None,
) -> str:
    """开一条 run，返回 run_id（uuid hex）。

    即便写库失败也返回一个 id —— 后续 record_step 写的是孤儿 step（无害），
    end_run 查不到 run 自然 no-op。调用方因此永远拿到一个非空 run_id，省去 None 判断。
    """
    run_id = uuid.uuid4().hex
    try:
        async with AsyncSessionLocal() as db:
            db.add(
                AgentRun(
                    run_id=run_id,
                    agent_type=agent_type,
                    tenant_id=tenant_id,
                    user_id=user_id,
                    session_id=None if session_id is None else str(session_id),
                    app_id=None if app_id is None else str(app_id),
                    model=model,
                    status="running",
                    started_at=datetime.utcnow(),
                )
            )
            await db.commit()
    except Exception:
        governance_telemetry.record_observability_projection("failed")
        log_governance_event("observability_projection_failed", error_code="RECORDER_START_FAILED")
    return run_id


async def record_step(
    run_id: str,
    *,
    step_type: str,
    seq: int,
    tool_name: Optional[str] = None,
    args: Optional[dict] = None,
    result_text: Optional[str] = None,
    status: Optional[str] = None,
    duration_ms: Optional[int] = None,
    prompt_tokens: Optional[int] = None,
    completion_tokens: Optional[int] = None,
) -> None:
    """记一步。llm step 传 prompt/completion tokens；tool step 传 tool_name/args/result。"""
    try:
        async with AsyncSessionLocal() as db:
            db.add(
                AgentStep(
                    run_id=run_id,
                    seq=seq,
                    step_type=step_type,
                    tool_name=tool_name,
                    args_json=args,
                    result_text=result_text,
                    status=status,
                    duration_ms=duration_ms,
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                    ts=datetime.utcnow(),
                )
            )
            await db.commit()
    except Exception:
        governance_telemetry.record_observability_projection("failed")
        log_governance_event("observability_projection_failed", error_code="RECORDER_STEP_FAILED")


async def end_run(run_id: str, *, status: str, error: Optional[str] = None) -> None:
    """收尾：状态 + duration + 从 steps 聚合 tokens / turn_count（llm step 数）。"""
    try:
        async with AsyncSessionLocal() as db:
            run = (
                await db.execute(select(AgentRun).where(AgentRun.run_id == run_id))
            ).scalar_one_or_none()
            if run is None:
                return
            now = datetime.utcnow()
            run.status = status
            run.error_message = error
            run.ended_at = now
            if run.started_at is not None:
                run.duration_ms = int((now - run.started_at).total_seconds() * 1000)
            agg = (
                await db.execute(
                    select(
                        func.coalesce(func.sum(AgentStep.prompt_tokens), 0),
                        func.coalesce(func.sum(AgentStep.completion_tokens), 0),
                        # turn_count = llm step 数；用 case-sum 而非 FILTER，跨 SQLite/MySQL 都稳
                        func.coalesce(
                            func.sum(case((AgentStep.step_type == "llm", 1), else_=0)), 0
                        ),
                    ).where(AgentStep.run_id == run_id)
                )
            ).one()
            run.total_prompt_tokens = int(agg[0] or 0)
            run.total_completion_tokens = int(agg[1] or 0)
            run.total_tokens = run.total_prompt_tokens + run.total_completion_tokens
            run.turn_count = int(agg[2] or 0)
            await db.commit()
    except Exception:
        governance_telemetry.record_observability_projection("failed")
        log_governance_event("observability_projection_failed", error_code="RECORDER_END_FAILED")
