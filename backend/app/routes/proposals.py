"""ChangeProposal 生命周期 API（Phase B）

POST   /api/applications/{id}/proposals          create from draft (promote)
GET    /api/applications/{id}/proposals          list (filter by status)
GET    /api/proposals/{id}                       detail (含 validation_report)
PATCH  /api/proposals/{id}                       update title/desc
POST   /api/proposals/{id}/refresh-validation    重跑第一道门
POST   /api/proposals/{id}/close
"""
from __future__ import annotations
from typing import Annotated, Optional
import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.deps import get_auth_context, AuthContext
from app.models import Application
from app.models.collaboration import ChangeProposal
from app.proposal.persistence import create_proposal, load_proposal, list_proposals
from app.proposal.validation import validate as validate_spec
from app.spec.persistence import load_spec
# follow-up: 把 _require_application_access 提到 deps.py，目前跨 file 复用 Phase A 私有 helper
from app.routes.application_members import _require_application_access

logger = logging.getLogger(__name__)


# ============ schemas ============

class PromoteRequest(BaseModel):
    title: str
    description: Optional[str] = None
    draft_spec_id: str  # 必填：要 promote 的 personal draft


class UpdateProposalRequest(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None


# ============ application 子路由 ============

app_router = APIRouter(prefix="/applications", tags=["proposals"])


@app_router.post("/{application_id}/proposals")
async def promote_to_proposal(
    application_id: int,
    req: PromoteRequest,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """promote draft → ChangeProposal（status='open' if 第一道门通过, else 'draft' with issues）"""
    app, _role = await _require_application_access(
        db,
        application_id=application_id,
        user_id=ctx.user.id,
        tenant_id=ctx.tenant_id,
        minimum_role="contributor",
    )

    # 验证 draft 存在且属于当前 tenant
    draft = await load_spec(db, req.draft_spec_id, tenant_id=ctx.tenant_id)
    if not draft:
        raise HTTPException(404, "draft spec 不存在")

    # 第一道门
    report = validate_spec(draft)

    # base = application.canonical_spec_id（可为 None for 全新应用）
    base_id = app.canonical_spec_id

    proposal = await create_proposal(
        db,
        application_id=application_id,
        draft_spec_id=draft.id,
        base_canonical_spec_id=base_id,
        title=req.title,
        description=req.description,
        created_by=ctx.user.id,
        status="open" if report.ok else "draft",
    )
    proposal.validation_report = report.to_dict()
    await db.commit()
    await db.refresh(proposal)

    return {
        "id": proposal.id,
        "status": proposal.status,
        "validation_report": proposal.validation_report,
        "title": proposal.title,
    }


@app_router.get("/{application_id}/proposals")
async def list_application_proposals(
    application_id: int,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
    status: Optional[str] = None,
):
    await _require_application_access(
        db, application_id=application_id, user_id=ctx.user.id, tenant_id=ctx.tenant_id,
        minimum_role="viewer",
    )
    rows = await list_proposals(db, application_id=application_id, status=status)
    return [
        {
            "id": r.id,
            "title": r.title,
            "status": r.status,
            "created_by": r.created_by,
            "created_at": r.created_at.isoformat() if r.created_at else None,
            "applied_at": r.applied_at.isoformat() if r.applied_at else None,
            "draft_spec_id": r.draft_spec_id,
            "base_canonical_spec_id": r.base_canonical_spec_id,
        }
        for r in rows
    ]


# ============ proposal 直接路由 ============

prop_router = APIRouter(prefix="/proposals", tags=["proposals"])


async def _load_proposal_or_404(db: AsyncSession, proposal_id: str):
    pv = await load_proposal(db, proposal_id)
    if not pv:
        raise HTTPException(404, "提案不存在")
    return pv


@prop_router.get("/{proposal_id}")
async def get_proposal_detail(
    proposal_id: str,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    pv = await _load_proposal_or_404(db, proposal_id)
    # tenant 隔离：通过 application 检查
    await _require_application_access(
        db, application_id=pv.application_id, user_id=ctx.user.id, tenant_id=ctx.tenant_id,
        minimum_role="viewer",
    )
    return {
        "id": pv.id,
        "application_id": pv.application_id,
        "title": pv.title,
        "description": pv.description,
        "draft_spec_id": pv.draft_spec_id,
        "base_canonical_spec_id": pv.base_canonical_spec_id,
        "status": pv.status,
        "validation_report": pv.validation_report,
        "apply_plan": pv.apply_plan,
        "apply_log": pv.apply_log,
        "git_branch": pv.git_branch,
        "git_pr_url": pv.git_pr_url,
        "created_by": pv.created_by,
        "created_at": pv.created_at.isoformat() if pv.created_at else None,
        "updated_at": pv.updated_at.isoformat() if pv.updated_at else None,
        "applied_at": pv.applied_at.isoformat() if pv.applied_at else None,
        "reviews": pv.reviews,
    }


@prop_router.patch("/{proposal_id}")
async def update_proposal(
    proposal_id: str,
    req: UpdateProposalRequest,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    pv = await _load_proposal_or_404(db, proposal_id)
    await _require_application_access(
        db, application_id=pv.application_id, user_id=ctx.user.id, tenant_id=ctx.tenant_id,
        minimum_role="contributor",
    )
    if pv.created_by != ctx.user.id:
        raise HTTPException(403, "仅提案创建者可修改 title/description")
    if pv.status not in ("draft", "open", "changes_requested"):
        raise HTTPException(400, f"提案状态 {pv.status} 不可编辑")

    row = (await db.execute(select(ChangeProposal).where(ChangeProposal.id == proposal_id))).scalar_one()
    if req.title is not None:
        row.title = req.title
    if req.description is not None:
        row.description = req.description
    await db.commit()
    return {"id": row.id, "title": row.title, "description": row.description}


@prop_router.post("/{proposal_id}/refresh-validation")
async def refresh_validation(
    proposal_id: str,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """重跑第一道门（draft 内容变化后调用）"""
    pv = await _load_proposal_or_404(db, proposal_id)
    await _require_application_access(
        db, application_id=pv.application_id, user_id=ctx.user.id, tenant_id=ctx.tenant_id,
        minimum_role="contributor",
    )
    draft = await load_spec(db, pv.draft_spec_id, tenant_id=ctx.tenant_id)
    if not draft:
        raise HTTPException(404, "draft spec 已不存在")
    report = validate_spec(draft)
    row = (await db.execute(select(ChangeProposal).where(ChangeProposal.id == proposal_id))).scalar_one()
    row.validation_report = report.to_dict()
    if pv.status == "draft" and report.ok:
        row.status = "open"
    elif pv.status == "open" and not report.ok:
        row.status = "draft"
    await db.commit()
    return {"id": row.id, "status": row.status, "validation_report": row.validation_report}


@prop_router.post("/{proposal_id}/close")
async def close_proposal(
    proposal_id: str,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    pv = await _load_proposal_or_404(db, proposal_id)
    await _require_application_access(
        db, application_id=pv.application_id, user_id=ctx.user.id, tenant_id=ctx.tenant_id,
        minimum_role="contributor",
    )
    if pv.created_by != ctx.user.id:
        raise HTTPException(403, "仅提案创建者可关闭")
    if pv.status in ("applied", "applying", "closed"):
        raise HTTPException(400, f"状态 {pv.status} 不可再关闭")
    row = (await db.execute(select(ChangeProposal).where(ChangeProposal.id == proposal_id))).scalar_one()
    row.status = "closed"
    await db.commit()
    return {"id": row.id, "status": row.status}
