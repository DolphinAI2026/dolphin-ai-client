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


class ReviewRequest(BaseModel):
    action: str  # 'approve' | 'request_changes' | 'comment'
    body: Optional[str] = None


class ApplyRequest(BaseModel):
    confirm_irreversible: bool = False


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

    # git 同步（如绑定 git_repo_url）
    if app.git_repo_url:
        try:
            from app.git.sync import push_proposal_branch
            result = await push_proposal_branch(db, proposal=proposal, application=app)
            if result:
                branch, pr_url = result
                proposal.git_branch = branch
                proposal.git_pr_url = pr_url
                await db.commit()
        except Exception as e:
            logger.warning(f"git push for proposal {proposal.id} failed: {e}")
            # 不阻断 promote；git 后续可 retry

    return {
        "id": proposal.id,
        "status": proposal.status,
        "validation_report": proposal.validation_report,
        "title": proposal.title,
        "git_branch": proposal.git_branch,
        "git_pr_url": proposal.git_pr_url,
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


@prop_router.post("/{proposal_id}/reviews")
async def submit_review(
    proposal_id: str,
    req: ReviewRequest,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """提交一条 review。

    action：
    - 'approve' → status 转 'approved'
    - 'request_changes' → status 转 'changes_requested'
    - 'comment' → status 不变

    权限：
    - approve / request_changes 需 maintainer+
    - comment 需 viewer+
    - 不能 review 自己的提案（创建者 != reviewer）
    - proposal 状态须为 open / changes_requested 才能 review
    """
    from app.models.collaboration import ProposalReview

    pv = await _load_proposal_or_404(db, proposal_id)

    if req.action not in ("approve", "request_changes", "comment"):
        raise HTTPException(400, "action 仅支持 approve/request_changes/comment")

    # role 检查：approve / request_changes 需要 maintainer+
    min_role = "maintainer" if req.action in ("approve", "request_changes") else "viewer"
    _app, _role = await _require_application_access(
        db, application_id=pv.application_id, user_id=ctx.user.id, tenant_id=ctx.tenant_id,
        minimum_role=min_role,
    )

    if pv.created_by == ctx.user.id and req.action in ("approve", "request_changes"):
        raise HTTPException(400, "不能审阅自己的提案")
    if pv.status not in ("open", "changes_requested"):
        raise HTTPException(400, f"状态 {pv.status} 不可评审")

    review = ProposalReview(
        proposal_id=proposal_id,
        reviewer_id=ctx.user.id,
        action=req.action,
        body=req.body,
    )
    db.add(review)
    row = (await db.execute(select(ChangeProposal).where(ChangeProposal.id == proposal_id))).scalar_one()
    if req.action == "approve":
        row.status = "approved"
    elif req.action == "request_changes":
        row.status = "changes_requested"
    await db.commit()
    await db.refresh(review)
    return {
        "id": review.id,
        "action": review.action,
        "body": review.body,
        "proposal_status": row.status,
        "created_at": review.created_at.isoformat() if review.created_at else None,
    }


@prop_router.post("/{proposal_id}/apply")
async def apply_proposal(
    proposal_id: str,
    req: ApplyRequest,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """触发 apply（第二道门 + 不可逆确认 + ops 执行）。

    流程：
    - 状态须为 'approved'，调用者 role 须为 maintainer+
    - 算 plan：第二道门 validate + diff + reversibility
    - 若 plan.issues 非空 → 400
    - 若 rebase_required → 409
    - 若 has_irreversible 且未 confirm → 返回 needs_confirmation + plan
    - 否则 status='applying' → execute_apply → 'applied' / 'apply_failed'
    """
    from app.proposal.apply import build_apply_plan, execute_apply

    pv = await _load_proposal_or_404(db, proposal_id)
    _app, _role = await _require_application_access(
        db, application_id=pv.application_id, user_id=ctx.user.id, tenant_id=ctx.tenant_id,
        minimum_role="maintainer",
    )
    if pv.status != "approved":
        raise HTTPException(400, f"提案状态 {pv.status} 不可 apply（需要 approved）")

    plan = await build_apply_plan(
        db,
        application_id=pv.application_id,
        draft_spec_id=pv.draft_spec_id,
        base_canonical_id=pv.base_canonical_spec_id,
        tenant_id=ctx.tenant_id,
    )
    if plan.issues:
        raise HTTPException(400, f"apply 前校验失败：{'; '.join(plan.issues)}")
    if plan.rebase_required:
        raise HTTPException(409, f"需要 rebase：{plan.rebase_reason}")
    if plan.has_irreversible and not req.confirm_irreversible:
        # 把 plan 写回，让前端展示"不可逆"提示
        row = (await db.execute(select(ChangeProposal).where(ChangeProposal.id == proposal_id))).scalar_one()
        row.apply_plan = plan.to_dict()
        await db.commit()
        return {"status": "needs_confirmation", "apply_plan": plan.to_dict()}

    # 标 applying
    row = (await db.execute(select(ChangeProposal).where(ChangeProposal.id == proposal_id))).scalar_one()
    row.status = "applying"
    row.apply_plan = plan.to_dict()
    await db.commit()

    result = await execute_apply(db, proposal_id=proposal_id, plan=plan, tenant_id=ctx.tenant_id)
    return {"status": "applied" if result["success"] else "apply_failed", **result}
