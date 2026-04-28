"""ChangeProposal 持久化 helpers（Phase B）"""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime
from typing import Optional
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.collaboration import ChangeProposal, ProposalReview


def new_proposal_id() -> str:
    return f"cp_{uuid.uuid4().hex[:12]}"


@dataclass
class ProposalView:
    """ChangeProposal + 关联 reviews 的视图对象（避免 ORM lazy-load）"""
    id: str
    application_id: int
    title: str
    description: Optional[str]
    draft_spec_id: str
    base_canonical_spec_id: Optional[str]
    status: str
    validation_report: Optional[dict]
    apply_plan: Optional[dict]
    apply_log: Optional[dict]
    git_branch: Optional[str]
    git_pr_url: Optional[str]
    created_by: int
    created_at: Optional[datetime]
    updated_at: Optional[datetime]
    applied_at: Optional[datetime]
    reviews: list[dict]  # [{id, reviewer_id, action, body, created_at}, ...]


async def create_proposal(
    db: AsyncSession,
    *,
    application_id: int,
    draft_spec_id: str,
    base_canonical_spec_id: Optional[str],
    title: str,
    description: Optional[str],
    created_by: int,
    status: str = "draft",
) -> ChangeProposal:
    proposal = ChangeProposal(
        id=new_proposal_id(),
        application_id=application_id,
        draft_spec_id=draft_spec_id,
        base_canonical_spec_id=base_canonical_spec_id,
        title=title,
        description=description,
        status=status,
        created_by=created_by,
    )
    db.add(proposal)
    await db.commit()
    await db.refresh(proposal)
    return proposal


async def load_proposal(
    db: AsyncSession, proposal_id: str, *, with_reviews: bool = True
) -> Optional[ProposalView]:
    row = (await db.execute(
        select(ChangeProposal).where(ChangeProposal.id == proposal_id)
    )).scalar_one_or_none()
    if not row:
        return None

    reviews: list[dict] = []
    if with_reviews:
        review_rows = (await db.execute(
            select(ProposalReview).where(ProposalReview.proposal_id == proposal_id)
            .order_by(ProposalReview.created_at.asc())
        )).scalars().all()
        reviews = [
            {
                "id": r.id,
                "reviewer_id": r.reviewer_id,
                "action": r.action,
                "body": r.body,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in review_rows
        ]

    return ProposalView(
        id=row.id,
        application_id=row.application_id,
        title=row.title,
        description=row.description,
        draft_spec_id=row.draft_spec_id,
        base_canonical_spec_id=row.base_canonical_spec_id,
        status=row.status,
        validation_report=row.validation_report,
        apply_plan=row.apply_plan,
        apply_log=row.apply_log,
        git_branch=row.git_branch,
        git_pr_url=row.git_pr_url,
        created_by=row.created_by,
        created_at=row.created_at,
        updated_at=row.updated_at,
        applied_at=row.applied_at,
        reviews=reviews,
    )


async def list_proposals(
    db: AsyncSession,
    *,
    application_id: int,
    status: Optional[str] = None,
) -> list[ChangeProposal]:
    stmt = select(ChangeProposal).where(ChangeProposal.application_id == application_id)
    if status:
        stmt = stmt.where(ChangeProposal.status == status)
    stmt = stmt.order_by(ChangeProposal.created_at.desc())
    return list((await db.execute(stmt)).scalars().all())
