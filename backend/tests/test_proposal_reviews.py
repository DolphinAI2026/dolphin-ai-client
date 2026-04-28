"""ChangeProposal review API 测试（Phase B Task 5）"""
from datetime import datetime, timezone

import pytest
from fastapi import HTTPException

from app.deps import AuthContext
from app.models import Application, User
from app.models.collaboration import ApplicationMember
from app.models.spec import Spec as SpecORM
from app.models.tenant import Tenant, UserTenant
from app.routes.proposals import (
    PromoteRequest, ReviewRequest,
    promote_to_proposal, submit_review,
)


def _ctx_for(user: User, tenant_id: int) -> AuthContext:
    return AuthContext(user=user, tenant_id=tenant_id, tenant_role="member", org_permissions={})


async def _build_full_spec_payload(*, app_id: int, user_id: int) -> dict:
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    return {
        "id": "ignored",
        "application_id": app_id,
        "version": 1,
        "phase": "drafting",
        "goal": {"title": "测试", "summary": "s", "business_problem": "b", "confirmed": True},
        "roles": [{"code": "admin", "name": "管理员", "scope": "ALL", "confirmed": True}],
        "objects": [{
            "code": "t_order", "name": "订单",
            "fields": [{"code": "amount", "name": "金额", "type": "数字", "required": False, "confirmed": True}],
            "sub_objects": {}, "confirmed": True,
        }],
        "dicts": [], "permissions": [],
        "decisions_pending": [], "decisions_resolved": [],
        "completeness": {"confirmed": 0, "total": 0, "by_section": {}, "pending_decisions": 0, "blocking_decisions": 0},
        "created_at": now.isoformat(), "updated_at": now.isoformat(),
        "created_by": user_id,
    }


async def _seed(db_session):
    """建 owner（creator）+ maintainer（reviewer）+ contributor（reviewer）+ application + draft + 已 promote 的 proposal。"""
    tenant = Tenant(tenant_name="t1", tenant_code="t1")
    db_session.add(tenant)
    await db_session.flush()

    owner = User(username="owner", hashed_password="x")
    maintainer = User(username="m1", hashed_password="x")
    contributor = User(username="c1", hashed_password="x")
    db_session.add_all([owner, maintainer, contributor])
    await db_session.flush()
    db_session.add_all([
        UserTenant(user_id=owner.id, tenant_id=tenant.id, status=1),
        UserTenant(user_id=maintainer.id, tenant_id=tenant.id, status=1),
        UserTenant(user_id=contributor.id, tenant_id=tenant.id, status=1),
    ])

    app = Application(
        user_id=owner.id, tenant_id=tenant.id, created_by=owner.id,
        app_name="App1", app_code="app1",
    )
    db_session.add(app)
    await db_session.flush()

    db_session.add_all([
        ApplicationMember(application_id=app.id, user_id=maintainer.id, role="maintainer", invited_by=owner.id),
        ApplicationMember(application_id=app.id, user_id=contributor.id, role="contributor", invited_by=owner.id),
    ])

    payload = await _build_full_spec_payload(app_id=app.id, user_id=owner.id)
    payload["id"] = "spec_for_proposal"
    spec = SpecORM(
        id=payload["id"],
        application_id=app.id, version=1, kind="draft",
        payload=payload, phase="drafting",
        created_by=owner.id, tenant_id=tenant.id,
    )
    db_session.add(spec)
    await db_session.commit()

    ctx_owner = _ctx_for(owner, tenant.id)
    promoted = await promote_to_proposal(
        app.id, PromoteRequest(title="提案", draft_spec_id=spec.id), ctx_owner, db_session,
    )
    assert promoted["status"] == "open"

    return {
        "tenant": tenant, "owner": owner, "maintainer": maintainer, "contributor": contributor,
        "app": app, "spec": spec, "proposal_id": promoted["id"],
    }


@pytest.mark.asyncio
async def test_approve_transitions_open_to_approved(db_session):
    s = await _seed(db_session)
    ctx_m = _ctx_for(s["maintainer"], s["tenant"].id)

    res = await submit_review(
        s["proposal_id"],
        ReviewRequest(action="approve", body="lgtm"),
        ctx_m, db_session,
    )
    assert res["action"] == "approve"
    assert res["proposal_status"] == "approved"


@pytest.mark.asyncio
async def test_request_changes_transitions_open_to_changes_requested(db_session):
    s = await _seed(db_session)
    ctx_m = _ctx_for(s["maintainer"], s["tenant"].id)

    res = await submit_review(
        s["proposal_id"],
        ReviewRequest(action="request_changes", body="改下命名"),
        ctx_m, db_session,
    )
    assert res["proposal_status"] == "changes_requested"


@pytest.mark.asyncio
async def test_comment_does_not_change_status(db_session):
    s = await _seed(db_session)
    ctx_c = _ctx_for(s["contributor"], s["tenant"].id)

    res = await submit_review(
        s["proposal_id"],
        ReviewRequest(action="comment", body="提个建议"),
        ctx_c, db_session,
    )
    assert res["action"] == "comment"
    assert res["proposal_status"] == "open"


@pytest.mark.asyncio
async def test_only_maintainer_or_owner_can_approve(db_session):
    """contributor approve → 403"""
    s = await _seed(db_session)
    ctx_c = _ctx_for(s["contributor"], s["tenant"].id)

    with pytest.raises(HTTPException) as exc:
        await submit_review(
            s["proposal_id"],
            ReviewRequest(action="approve", body="i can't really approve"),
            ctx_c, db_session,
        )
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_cannot_review_own_proposal(db_session):
    """proposal 创建者不能 approve / request_changes 自己的提案"""
    s = await _seed(db_session)
    ctx_owner = _ctx_for(s["owner"], s["tenant"].id)

    with pytest.raises(HTTPException) as exc:
        await submit_review(
            s["proposal_id"],
            ReviewRequest(action="approve"),
            ctx_owner, db_session,
        )
    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_review_rejects_invalid_action(db_session):
    s = await _seed(db_session)
    ctx_m = _ctx_for(s["maintainer"], s["tenant"].id)
    with pytest.raises(HTTPException) as exc:
        await submit_review(
            s["proposal_id"],
            ReviewRequest(action="explode"),
            ctx_m, db_session,
        )
    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_review_blocked_when_status_not_open_or_changes_requested(db_session):
    """proposal closed 后不能再 review"""
    s = await _seed(db_session)
    # 手动把 proposal 关掉
    from app.models.collaboration import ChangeProposal
    from sqlalchemy import select
    row = (await db_session.execute(
        select(ChangeProposal).where(ChangeProposal.id == s["proposal_id"])
    )).scalar_one()
    row.status = "closed"
    await db_session.commit()

    ctx_m = _ctx_for(s["maintainer"], s["tenant"].id)
    with pytest.raises(HTTPException) as exc:
        await submit_review(
            s["proposal_id"], ReviewRequest(action="comment", body="late"), ctx_m, db_session,
        )
    assert exc.value.status_code == 400
