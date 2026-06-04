"""Agent 可观测读 API（Phase 1：租户只看自己）。

- GET /api/agent-runs            当前租户的 run 列表（倒序，支持 agent_type / session_id 过滤）
- GET /api/agent-runs/{run_id}   单次 run 的 trace：run + 有序 steps（强制租户隔离）
"""
from __future__ import annotations

from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.deps import AuthContext, get_auth_context
from app.models.agent_observability import AgentRun, AgentStep

router = APIRouter(prefix="/agent-runs", tags=["agent-observability"])


def _run_to_dict(r: AgentRun) -> dict:
    return {
        "run_id": r.run_id,
        "agent_type": r.agent_type,
        "status": r.status,
        "model": r.model,
        "session_id": r.session_id,
        "app_id": r.app_id,
        "started_at": r.started_at.isoformat() if r.started_at else None,
        "ended_at": r.ended_at.isoformat() if r.ended_at else None,
        "duration_ms": r.duration_ms,
        "total_prompt_tokens": r.total_prompt_tokens,
        "total_completion_tokens": r.total_completion_tokens,
        "total_tokens": r.total_tokens,
        "turn_count": r.turn_count,
        "error_message": r.error_message,
        "created_at": r.created_at.isoformat() if r.created_at else None,
    }


def _step_to_dict(s: AgentStep) -> dict:
    return {
        "seq": s.seq,
        "step_type": s.step_type,
        "tool_name": s.tool_name,
        "args_json": s.args_json,
        "result_text": s.result_text,
        "status": s.status,
        "duration_ms": s.duration_ms,
        "prompt_tokens": s.prompt_tokens,
        "completion_tokens": s.completion_tokens,
        "ts": s.ts.isoformat() if s.ts else None,
    }


@router.get("")
async def list_agent_runs(
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
    agent_type: Optional[str] = None,
    session_id: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
):
    """当前租户的 run 列表（按创建时间倒序）。"""
    # limit/offset 用普通 int 默认（兼容本仓直调路由函数的测试约定，跟 list_sessions 一致），
    # 这里手动 clamp 补回边界：避免恶意/误传 limit 一次拉爆全表。
    limit = max(1, min(limit, 200))
    offset = max(0, offset)
    q = select(AgentRun).where(AgentRun.tenant_id == ctx.tenant_id)
    if agent_type:
        q = q.where(AgentRun.agent_type == agent_type)
    if session_id:
        q = q.where(AgentRun.session_id == session_id)
    q = q.order_by(desc(AgentRun.created_at)).limit(limit).offset(offset)
    rows = (await db.execute(q)).scalars().all()
    return {"runs": [_run_to_dict(r) for r in rows]}


@router.get("/{run_id}")
async def get_agent_run_detail(
    run_id: str,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """单次 run 的 trace：run + 有序 steps。强制租户隔离。"""
    run = (
        await db.execute(
            select(AgentRun).where(
                AgentRun.run_id == run_id,
                AgentRun.tenant_id == ctx.tenant_id,
            )
        )
    ).scalar_one_or_none()
    if run is None:
        raise HTTPException(status_code=404, detail="trace 不存在")
    steps = (
        await db.execute(
            select(AgentStep)
            .where(AgentStep.run_id == run_id)
            .order_by(AgentStep.seq.asc())
        )
    ).scalars().all()
    return {"run": _run_to_dict(run), "steps": [_step_to_dict(s) for s in steps]}
