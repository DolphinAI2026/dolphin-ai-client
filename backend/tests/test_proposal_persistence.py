"""ChangeProposal 持久化 helpers 测试（Phase B Task 1）"""
import pytest
from sqlalchemy import select

from app.models import User, Application, Tenant
from app.models.spec import Spec as SpecORM
from app.models.collaboration import ChangeProposal, ProposalReview
from app.proposal.persistence import (
    new_proposal_id, create_proposal, load_proposal, list_proposals, ProposalView,
)


async def _seed_basics(db_session):
    tenant = Tenant(tenant_name="t1", tenant_code="t1")
    db_session.add(tenant)
    await db_session.flush()

    user = User(username="u1", hashed_password="x")
    db_session.add(user)
    await db_session.flush()

    app = Application(
        user_id=user.id,
        tenant_id=tenant.id,
        created_by=user.id,
        app_name="app1",
        app_code="APP1",
    )
    db_session.add(app)
    await db_session.flush()

    spec = SpecORM(
        id="spec_seed_persist",
        application_id=app.id,
        version=1,
        payload={},
        phase="gathering",
        created_by=user.id,
        tenant_id=tenant.id,
    )
    db_session.add(spec)
    await db_session.flush()

    return {"tenant": tenant, "user": user, "app": app, "spec": spec}


def test_new_proposal_id_is_unique():
    ids = {new_proposal_id() for _ in range(50)}
    assert len(ids) == 50
    for i in ids:
        assert i.startswith("cp_")
        assert len(i) == 3 + 12  # "cp_" + 12 hex chars


@pytest.mark.asyncio
async def test_create_proposal_persists(db_session):
    seed = await _seed_basics(db_session)

    proposal = await create_proposal(
        db_session,
        application_id=seed["app"].id,
        draft_spec_id=seed["spec"].id,
        base_canonical_spec_id=None,
        title="新增退款流程",
        description="增加 refund_amount 字段",
        created_by=seed["user"].id,
    )

    assert proposal.id.startswith("cp_")
    assert proposal.application_id == seed["app"].id
    assert proposal.title == "新增退款流程"
    assert proposal.draft_spec_id == seed["spec"].id
    assert proposal.status == "draft"
    assert proposal.created_at is not None

    # DB 中确实有
    found = (await db_session.execute(
        select(ChangeProposal).where(ChangeProposal.id == proposal.id)
    )).scalar_one()
    assert found.title == "新增退款流程"


@pytest.mark.asyncio
async def test_load_proposal_returns_row_with_reviews(db_session):
    seed = await _seed_basics(db_session)
    proposal = await create_proposal(
        db_session,
        application_id=seed["app"].id,
        draft_spec_id=seed["spec"].id,
        base_canonical_spec_id=None,
        title="待评审",
        description=None,
        created_by=seed["user"].id,
        status="open",
    )
    review = ProposalReview(
        proposal_id=proposal.id,
        reviewer_id=seed["user"].id,
        action="comment",
        body="lgtm",
    )
    db_session.add(review)
    await db_session.commit()

    pv = await load_proposal(db_session, proposal.id, with_reviews=True)
    assert pv is not None
    assert isinstance(pv, ProposalView)
    assert pv.id == proposal.id
    assert pv.title == "待评审"
    assert pv.status == "open"
    assert len(pv.reviews) == 1
    assert pv.reviews[0]["action"] == "comment"
    assert pv.reviews[0]["body"] == "lgtm"

    # with_reviews=False 时应跳过加载
    pv_no_reviews = await load_proposal(db_session, proposal.id, with_reviews=False)
    assert pv_no_reviews is not None
    assert pv_no_reviews.reviews == []

    # 不存在的 id 返回 None
    none = await load_proposal(db_session, "cp_nonexistent")
    assert none is None


@pytest.mark.asyncio
async def test_list_proposals_filter_by_status(db_session):
    seed = await _seed_basics(db_session)
    p1 = await create_proposal(
        db_session,
        application_id=seed["app"].id,
        draft_spec_id=seed["spec"].id,
        base_canonical_spec_id=None,
        title="proposal-1",
        description=None,
        created_by=seed["user"].id,
        status="open",
    )
    p2 = await create_proposal(
        db_session,
        application_id=seed["app"].id,
        draft_spec_id=seed["spec"].id,
        base_canonical_spec_id=None,
        title="proposal-2",
        description=None,
        created_by=seed["user"].id,
        status="draft",
    )
    p3 = await create_proposal(
        db_session,
        application_id=seed["app"].id,
        draft_spec_id=seed["spec"].id,
        base_canonical_spec_id=None,
        title="proposal-3",
        description=None,
        created_by=seed["user"].id,
        status="open",
    )

    all_rows = await list_proposals(db_session, application_id=seed["app"].id)
    assert len(all_rows) == 3

    open_rows = await list_proposals(db_session, application_id=seed["app"].id, status="open")
    open_ids = {r.id for r in open_rows}
    assert open_ids == {p1.id, p3.id}

    draft_rows = await list_proposals(db_session, application_id=seed["app"].id, status="draft")
    assert {r.id for r in draft_rows} == {p2.id}
