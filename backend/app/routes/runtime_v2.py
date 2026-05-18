# backend/app/routes/runtime_v2.py
"""V2 /runtime page — pipelines + deployments tabs.

These are read-only endpoints backed by `pipeline_runs` + `deployment_history`.
On first hit per tenant we lazy-seed the demo dataset (see
`app.services.runtime_seed`) so the page never shows an empty state.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Annotated, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.deps import AuthContext, get_auth_context, resolve_effective_tenant_id
from app.models.runtime_v2 import DeploymentHistory, PipelineRun
from app.services.runtime_seed import seed_runtime_for_tenant

router = APIRouter(prefix="/runtime", tags=["runtime-v2"])


# ─── Schemas ─────────────────────────────────────────────────────────────


class StageItem(BaseModel):
    name: str
    status: str
    duration_s: int = 0
    error: Optional[str] = None


class PipelineRunResp(BaseModel):
    id: str
    name: str
    source: str
    trigger: str
    user: str
    time: str  # formatted relative ("14:24" / "昨天 18:14" / "5/16")
    duration_s: int
    status: str
    branch: Optional[str] = None
    commit: Optional[str] = None
    env: Optional[str] = None
    stages: list[StageItem]


class PipelineListResp(BaseModel):
    pipelines: list[PipelineRunResp]
    total: int


class DeploymentResp(BaseModel):
    id: str
    app: str
    app_code: str
    env: str
    version: str
    user: str
    time: str
    status: str
    changes: str
    duration: str
    error: Optional[str] = None


class DeploymentListResp(BaseModel):
    deployments: list[DeploymentResp]
    total: int


# ─── Helpers ─────────────────────────────────────────────────────────────


def _format_time(dt: Optional[datetime]) -> str:
    """Match the inline seed's mixed format: HH:MM today / 昨天 HH:MM / M/D older."""
    if not dt:
        return "—"
    now = datetime.utcnow()
    if dt.date() == now.date():
        return dt.strftime("%H:%M")
    if dt.date() == (now - timedelta(days=1)).date():
        return f"昨天 {dt.strftime('%H:%M')}"
    # Older — drop leading zero on month/day to match the seed style.
    return f"{dt.month}/{dt.day}"


# ─── Routes ──────────────────────────────────────────────────────────────


@router.get("/pipelines", response_model=PipelineListResp)
async def list_pipelines(
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    tenant_id = await resolve_effective_tenant_id(db, ctx)
    # Lazy seed on first hit for this tenant.
    has_any = (
        await db.execute(
            select(PipelineRun).where(PipelineRun.tenant_id == tenant_id).limit(1)
        )
    ).scalar_one_or_none()
    if not has_any:
        await seed_runtime_for_tenant(db, tenant_id)

    rows = (
        await db.execute(
            select(PipelineRun)
            .where(PipelineRun.tenant_id == tenant_id)
            .order_by(desc(PipelineRun.started_at))
            .limit(50)
        )
    ).scalars().all()

    pipelines = [
        PipelineRunResp(
            id=p.id, name=p.name, source=p.source, trigger=p.trigger, user=p.user,
            time=_format_time(p.started_at),
            duration_s=p.duration_s, status=p.status,
            branch=p.branch, commit=p.commit, env=p.env,
            stages=[StageItem(**s) for s in (p.stages or [])],
        )
        for p in rows
    ]
    return PipelineListResp(pipelines=pipelines, total=len(pipelines))


@router.get("/deployments", response_model=DeploymentListResp)
async def list_deployments(
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    tenant_id = await resolve_effective_tenant_id(db, ctx)
    # Pipelines + deployments share the same seed routine — calling it from
    # either endpoint covers a tenant that only happens to visit history first.
    has_any = (
        await db.execute(
            select(DeploymentHistory).where(DeploymentHistory.tenant_id == tenant_id).limit(1)
        )
    ).scalar_one_or_none()
    if not has_any:
        await seed_runtime_for_tenant(db, tenant_id)

    rows = (
        await db.execute(
            select(DeploymentHistory)
            .where(DeploymentHistory.tenant_id == tenant_id)
            .order_by(desc(DeploymentHistory.started_at))
            .limit(50)
        )
    ).scalars().all()

    deployments = [
        DeploymentResp(
            id=d.id, app=d.app, app_code=d.app_code, env=d.env, version=d.version, user=d.user,
            time=_format_time(d.started_at),
            status=d.status, changes=d.changes, duration=d.duration, error=d.error,
        )
        for d in rows
    ]
    return DeploymentListResp(deployments=deployments, total=len(deployments))
