"""ChangeProposal 生命周期 API 测试（Phase B Task 4）— 函数级调用，绕过 HTTP 层"""
from datetime import datetime, timezone

import pytest
from fastapi import HTTPException

from app.deps import AuthContext
from app.models import Application, User
from app.models.collaboration import ApplicationMember
from app.models.spec import Spec as SpecORM
from app.models.tenant import Tenant, UserTenant
from app.routes.proposals import (
    PromoteRequest,
    UpdateProposalRequest,
    promote_to_proposal,
    list_application_proposals,
    get_proposal_detail,
    update_proposal,
    refresh_validation,
    close_proposal,
)


def _ctx_for(user: User, tenant_id: int) -> AuthContext:
    return AuthContext(user=user, tenant_id=tenant_id, tenant_role="member", org_permissions={})


async def _build_full_spec_payload(*, app_id: int, user_id: int) -> dict:
    """构造一个能通过第一道门的完整 Spec payload。"""
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    return {
        "id": "ignored_will_replace",
        "application_id": app_id,
        "version": 1,
        "phase": "drafting",
        "goal": {"title": "测试", "summary": "s", "business_problem": "b", "confirmed": True},
        "roles": [{"code": "admin", "name": "管理员", "scope": "ALL", "confirmed": True}],
        "objects": [{
            "code": "t_order", "name": "订单",
            "fields": [{"code": "amount", "name": "金额", "type": "数字", "required": False, "confirmed": True}],
            "sub_objects": {},
            "confirmed": True,
        }],
        "dicts": [],
        "permissions": [],
        "decisions_pending": [],
        "decisions_resolved": [],
        "completeness": {"confirmed": 0, "total": 0, "by_section": {}, "pending_decisions": 0, "blocking_decisions": 0},
        "created_at": now.isoformat(),
        "updated_at": now.isoformat(),
        "created_by": user_id,
    }


async def _seed(db_session, *, full_spec: bool = True):
    """建 tenant + owner + outsider + application + draft Spec。"""
    tenant = Tenant(tenant_name="t1", tenant_code="t1")
    db_session.add(tenant)
    await db_session.flush()

    owner = User(username="owner_u", hashed_password="x")
    outsider = User(username="outsider_u", hashed_password="x")
    db_session.add_all([owner, outsider])
    await db_session.flush()
    db_session.add_all([
        UserTenant(user_id=owner.id, tenant_id=tenant.id, status=1),
        UserTenant(user_id=outsider.id, tenant_id=tenant.id, status=1),
    ])

    app = Application(
        user_id=owner.id, tenant_id=tenant.id, created_by=owner.id,
        app_name="App1", app_code="app1",
    )
    db_session.add(app)
    await db_session.flush()

    payload = await _build_full_spec_payload(app_id=app.id, user_id=owner.id)
    payload["id"] = "spec_full_draft"
    if not full_spec:
        # 制造一个不通过完整性校验的 spec：删 goal
        payload["goal"] = None
    spec = SpecORM(
        id=payload["id"],
        application_id=app.id,
        version=1,
        kind="draft",
        payload=payload,
        phase="drafting",
        created_by=owner.id,
        tenant_id=tenant.id,
    )
    db_session.add(spec)
    await db_session.commit()

    return {"tenant": tenant, "owner": owner, "outsider": outsider, "app": app, "spec": spec}


@pytest.mark.asyncio
async def test_promote_full_spec_returns_open(db_session):
    s = await _seed(db_session, full_spec=True)
    ctx = _ctx_for(s["owner"], s["tenant"].id)
    req = PromoteRequest(title="提案A", description="加退款", draft_spec_id=s["spec"].id)
    res = await promote_to_proposal(s["app"].id, req, ctx, db_session)

    assert res["id"].startswith("cp_")
    assert res["status"] == "open"
    assert res["validation_report"]["ok"] is True
    assert res["title"] == "提案A"


@pytest.mark.asyncio
async def test_promote_incomplete_spec_returns_draft(db_session):
    s = await _seed(db_session, full_spec=False)
    ctx = _ctx_for(s["owner"], s["tenant"].id)
    req = PromoteRequest(title="未完成", draft_spec_id=s["spec"].id)
    res = await promote_to_proposal(s["app"].id, req, ctx, db_session)

    assert res["status"] == "draft"
    assert res["validation_report"]["ok"] is False
    assert res["validation_report"]["completeness"]["ok"] is False


@pytest.mark.asyncio
async def test_list_proposals_filter_status(db_session):
    s = await _seed(db_session, full_spec=True)
    ctx = _ctx_for(s["owner"], s["tenant"].id)

    # 1 开 + 1 关
    await promote_to_proposal(s["app"].id, PromoteRequest(title="p1", draft_spec_id=s["spec"].id), ctx, db_session)
    p2 = await promote_to_proposal(s["app"].id, PromoteRequest(title="p2", draft_spec_id=s["spec"].id), ctx, db_session)
    await close_proposal(p2["id"], ctx, db_session)

    all_rows = await list_application_proposals(s["app"].id, ctx, db_session)
    assert len(all_rows) == 2

    open_rows = await list_application_proposals(s["app"].id, ctx, db_session, status="open")
    assert len(open_rows) == 1
    assert open_rows[0]["status"] == "open"

    closed_rows = await list_application_proposals(s["app"].id, ctx, db_session, status="closed")
    assert len(closed_rows) == 1
    assert closed_rows[0]["status"] == "closed"


@pytest.mark.asyncio
async def test_get_proposal_detail(db_session):
    s = await _seed(db_session, full_spec=True)
    ctx = _ctx_for(s["owner"], s["tenant"].id)
    promoted = await promote_to_proposal(
        s["app"].id, PromoteRequest(title="详情", description="desc", draft_spec_id=s["spec"].id), ctx, db_session,
    )
    detail = await get_proposal_detail(promoted["id"], ctx, db_session)
    assert detail["id"] == promoted["id"]
    assert detail["title"] == "详情"
    assert detail["description"] == "desc"
    assert detail["status"] == "open"
    assert detail["application_id"] == s["app"].id
    assert detail["draft_spec_id"] == s["spec"].id
    assert detail["reviews"] == []


@pytest.mark.asyncio
async def test_close_proposal_only_creator(db_session):
    s = await _seed(db_session, full_spec=True)
    ctx_owner = _ctx_for(s["owner"], s["tenant"].id)
    promoted = await promote_to_proposal(
        s["app"].id, PromoteRequest(title="x", draft_spec_id=s["spec"].id), ctx_owner, db_session,
    )

    # outsider 必须先有应用访问权才能进流程；这里给 contributor，本来就不是 creator
    db_session.add(ApplicationMember(
        application_id=s["app"].id, user_id=s["outsider"].id, role="contributor", invited_by=s["owner"].id,
    ))
    await db_session.commit()

    ctx_outsider = _ctx_for(s["outsider"], s["tenant"].id)
    with pytest.raises(HTTPException) as exc:
        await close_proposal(promoted["id"], ctx_outsider, db_session)
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_refresh_validation_recomputes(db_session):
    """draft 内容修复后，refresh-validation 应把 status draft → open。"""
    s = await _seed(db_session, full_spec=False)
    ctx = _ctx_for(s["owner"], s["tenant"].id)
    promoted = await promote_to_proposal(
        s["app"].id, PromoteRequest(title="一开始不完整", draft_spec_id=s["spec"].id), ctx, db_session,
    )
    assert promoted["status"] == "draft"

    # 把 spec 修好（直接改 payload）
    payload = await _build_full_spec_payload(app_id=s["app"].id, user_id=s["owner"].id)
    payload["id"] = s["spec"].id
    s["spec"].payload = payload
    await db_session.commit()

    res = await refresh_validation(promoted["id"], ctx, db_session)
    assert res["status"] == "open"
    assert res["validation_report"]["ok"] is True


@pytest.mark.asyncio
async def test_update_proposal_title_only_creator(db_session):
    s = await _seed(db_session, full_spec=True)
    ctx_owner = _ctx_for(s["owner"], s["tenant"].id)
    promoted = await promote_to_proposal(
        s["app"].id, PromoteRequest(title="原标题", draft_spec_id=s["spec"].id), ctx_owner, db_session,
    )

    # owner 自己改 OK
    res = await update_proposal(
        promoted["id"], UpdateProposalRequest(title="新标题"), ctx_owner, db_session,
    )
    assert res["title"] == "新标题"

    # outsider 即便有 contributor 角色也不能改别人的提案
    db_session.add(ApplicationMember(
        application_id=s["app"].id, user_id=s["outsider"].id, role="contributor", invited_by=s["owner"].id,
    ))
    await db_session.commit()
    ctx_outsider = _ctx_for(s["outsider"], s["tenant"].id)
    with pytest.raises(HTTPException) as exc:
        await update_proposal(promoted["id"], UpdateProposalRequest(title="改不了"), ctx_outsider, db_session)
    assert exc.value.status_code == 403
