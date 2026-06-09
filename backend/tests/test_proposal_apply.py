"""ChangeProposal apply API + diff + plan 测试（Phase B Task 6 + Phase E Task 3）"""
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.deps import AuthContext
from app.incremental_executor import ExecutionResult
from app.models import Application, User
from app.models.collaboration import ApplicationMember, ChangeProposal
from app.models.spec import Spec as SpecORM
from app.models.tenant import Tenant, UserTenant
from app.proposal.apply import diff_spec
from app.builder_spec.schema import (
    Spec, Phase, Goal, Role, ObjectSpec, FieldSpec, Completeness, derive_completeness,
)
from app.routes.proposals import (
    ApplyRequest, PromoteRequest, ReviewRequest,
    apply_proposal, promote_to_proposal, submit_review,
)


def _fake_success_result() -> ExecutionResult:
    """模拟 IncrementalExecutor.execute_diff 返回成功结果（不真踩 aPaaS 平台）"""
    r = ExecutionResult()
    r.add_success("models", "fake created t_order")
    return r


def _fake_failure_result(*errors: str) -> ExecutionResult:
    r = ExecutionResult()
    for e in errors:
        r.add_error(e)
    return r


def _ctx_for(user: User, tenant_id: int) -> AuthContext:
    return AuthContext(user=user, tenant_id=tenant_id, tenant_role="member", org_permissions={})


def _build_full_spec(*, app_id: int, user_id: int, spec_id: str, type_for_amount: str = "数字",
                    extra_field: bool = False) -> dict:
    """构造一个 通过第一道门 的完整 Spec payload。"""
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    fields = [{"code": "amount", "name": "金额", "type": type_for_amount, "required": False, "confirmed": True}]
    if extra_field:
        fields.append({"code": "remark", "name": "备注", "type": "单行输入", "required": False, "confirmed": True})
    return {
        "id": spec_id,
        "application_id": app_id,
        "version": 1,
        "phase": "drafting",
        "goal": {"title": "测试", "summary": "s", "business_problem": "b", "confirmed": True},
        "roles": [{"code": "admin", "name": "管理员", "scope": "ALL", "confirmed": True}],
        "objects": [{
            "code": "t_order", "name": "订单",
            "fields": fields,
            "sub_objects": {}, "confirmed": True,
        }],
        "dicts": [], "permissions": [],
        "decisions_pending": [], "decisions_resolved": [],
        "completeness": {"confirmed": 0, "total": 0, "by_section": {}, "pending_decisions": 0, "blocking_decisions": 0},
        "created_at": now.isoformat(), "updated_at": now.isoformat(),
        "created_by": user_id,
    }


async def _seed(db_session, *, with_canonical: bool = True, draft_drops_field: bool = False,
                draft_adds_field: bool = False):
    """建 owner（creator/也是 maintainer）+ second_user（reviewer maintainer）+ application + canonical + draft + approved proposal。"""
    tenant = Tenant(tenant_name="t1", tenant_code="t1")
    db_session.add(tenant)
    await db_session.flush()

    owner = User(username="owner", hashed_password="x")
    reviewer = User(username="rv", hashed_password="x")
    db_session.add_all([owner, reviewer])
    await db_session.flush()
    db_session.add_all([
        UserTenant(user_id=owner.id, tenant_id=tenant.id, status=1),
        UserTenant(user_id=reviewer.id, tenant_id=tenant.id, status=1),
    ])

    app = Application(
        user_id=owner.id, tenant_id=tenant.id, created_by=owner.id,
        app_name="App1", app_code="app1",
    )
    db_session.add(app)
    await db_session.flush()

    db_session.add(ApplicationMember(
        application_id=app.id, user_id=reviewer.id, role="maintainer", invited_by=owner.id,
    ))

    canonical_id = None
    if with_canonical:
        canonical_payload = _build_full_spec(app_id=app.id, user_id=owner.id, spec_id="spec_canonical_v0")
        canonical = SpecORM(
            id=canonical_payload["id"], application_id=app.id, version=1,
            kind="canonical", payload=canonical_payload, phase="ready",
            created_by=owner.id, tenant_id=tenant.id,
        )
        db_session.add(canonical)
        canonical_id = canonical.id
        app.canonical_spec_id = canonical_id

    # draft
    if draft_drops_field:
        # canonical 有 amount，draft 没了 → drop_field（red）
        draft_payload = {
            **_build_full_spec(app_id=app.id, user_id=owner.id, spec_id="spec_draft_v1"),
        }
        # 把 amount 字段拿掉
        draft_payload["objects"][0]["fields"] = []
    elif draft_adds_field:
        # 仅在 amount 之外加 remark（yellow）
        draft_payload = _build_full_spec(
            app_id=app.id, user_id=owner.id, spec_id="spec_draft_v1", extra_field=True,
        )
    else:
        # 与 canonical 完全一致：无 ops（all green）
        draft_payload = _build_full_spec(app_id=app.id, user_id=owner.id, spec_id="spec_draft_v1")

    draft = SpecORM(
        id=draft_payload["id"], application_id=app.id, version=1, kind="draft",
        payload=draft_payload, phase="drafting",
        created_by=owner.id, tenant_id=tenant.id,
    )
    db_session.add(draft)
    await db_session.commit()

    # promote → approve
    ctx_owner = _ctx_for(owner, tenant.id)
    promoted = await promote_to_proposal(
        app.id, PromoteRequest(title="提案", draft_spec_id=draft.id), ctx_owner, db_session,
    )
    assert promoted["status"] == "open"

    ctx_reviewer = _ctx_for(reviewer, tenant.id)
    rv = await submit_review(
        promoted["id"], ReviewRequest(action="approve"), ctx_reviewer, db_session,
    )
    assert rv["proposal_status"] == "approved"

    return {
        "tenant": tenant, "owner": owner, "reviewer": reviewer,
        "app": app, "canonical_id": canonical_id, "draft_id": draft.id,
        "proposal_id": promoted["id"],
    }


def _spec_with_field(*, code: str, ftype: str) -> Spec:
    """便于 diff_spec 单元测试用 — 构造一个仅含一个 object/field 的 in-memory Spec。"""
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    s = Spec(
        id=f"spec_{code}",
        application_id=1, version=1, phase=Phase.DRAFTING,
        goal=Goal(title="t", summary="s", business_problem="b", confirmed=True),
        roles=[Role(code="admin", name="A", scope="ALL", confirmed=True)],
        objects=[ObjectSpec(
            code="t_order", name="订单",
            fields=[FieldSpec(code=code, name=code, type=ftype, confirmed=True)],
            confirmed=True,
        )],
        dicts=[], permissions=[],
        completeness=Completeness(),
        created_at=now, updated_at=now, created_by=1,
    )
    s.completeness = derive_completeness(s)
    return s


def test_diff_detects_drop_field_as_red():
    """canonical 有 amount，draft 没了 → drop_field（red）"""
    canonical = _spec_with_field(code="amount", ftype="数字")
    # draft = canonical 但 fields 清空
    draft = _spec_with_field(code="amount", ftype="数字")
    draft.objects[0].fields = []
    ops = diff_spec(canonical, draft)
    drop_ops = [o for o in ops if o.kind == "drop_field"]
    assert len(drop_ops) == 1
    assert drop_ops[0].reversibility == "red"
    assert drop_ops[0].target == "object:t_order.amount"


def test_diff_modify_field_type_is_red():
    canonical = _spec_with_field(code="amount", ftype="数字")
    draft = _spec_with_field(code="amount", ftype="单行输入")
    ops = diff_spec(canonical, draft)
    mod = [o for o in ops if o.kind == "modify_field"]
    assert len(mod) == 1
    assert mod[0].reversibility == "red"


def test_diff_add_field_is_yellow():
    canonical = _spec_with_field(code="amount", ftype="数字")
    # draft 多一个字段
    draft = _spec_with_field(code="amount", ftype="数字")
    draft.objects[0].fields.append(FieldSpec(code="remark", name="备注", type="单行输入", confirmed=True))
    ops = diff_spec(canonical, draft)
    add = [o for o in ops if o.kind == "add_field"]
    assert len(add) == 1
    assert add[0].reversibility == "yellow"


@pytest.mark.asyncio
async def test_apply_requires_approved_status(db_session):
    """proposal 状态须为 approved"""
    s = await _seed(db_session, draft_adds_field=True)
    # 把状态改回 'open'
    row = (await db_session.execute(
        select(ChangeProposal).where(ChangeProposal.id == s["proposal_id"])
    )).scalar_one()
    row.status = "open"
    await db_session.commit()

    ctx = _ctx_for(s["owner"], s["tenant"].id)
    with pytest.raises(HTTPException) as exc:
        await apply_proposal(
            s["proposal_id"], ApplyRequest(confirm_irreversible=False), ctx, db_session,
        )
    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_apply_rejects_irreversible_without_confirm(db_session):
    """draft 删掉 amount 字段 → red ops → 没 confirm 时返回 needs_confirmation"""
    s = await _seed(db_session, draft_drops_field=True)
    ctx = _ctx_for(s["owner"], s["tenant"].id)

    res = await apply_proposal(
        s["proposal_id"], ApplyRequest(confirm_irreversible=False), ctx, db_session,
    )
    assert res["status"] == "needs_confirmation"
    assert res["apply_plan"]["has_irreversible"] is True
    drop_ops = [o for o in res["apply_plan"]["ops"] if o["kind"] == "drop_field"]
    assert len(drop_ops) == 1
    assert drop_ops[0]["reversibility"] == "red"

    # apply_plan 已写入 DB
    row = (await db_session.execute(
        select(ChangeProposal).where(ChangeProposal.id == s["proposal_id"])
    )).scalar_one()
    assert row.apply_plan is not None
    assert row.status == "approved"  # 仍未真 apply


@pytest.mark.asyncio
async def test_apply_succeeds_with_confirm_advances_canonical(db_session):
    """draft 加字段（yellow） + confirm → apply 成功，canonical_spec_id 推进到 draft

    Phase E：execute_apply 现在真调 IncrementalExecutor，测试通过 mock
    execute_platform_apply 返回 success=True 的 ExecutionResult，避免真踩平台 API。
    """
    s = await _seed(db_session, draft_adds_field=True)
    ctx = _ctx_for(s["owner"], s["tenant"].id)

    with patch(
        "app.proposal.apply.execute_platform_apply",
        new=AsyncMock(return_value=_fake_success_result()),
    ):
        res = await apply_proposal(
            s["proposal_id"], ApplyRequest(confirm_irreversible=True), ctx, db_session,
        )
    assert res["status"] == "applied"
    assert res["success"] is True

    # canonical 推进
    app_row = (await db_session.execute(
        select(Application).where(Application.id == s["app"].id)
    )).scalar_one()
    assert app_row.canonical_spec_id == s["draft_id"]

    # proposal 状态
    p_row = (await db_session.execute(
        select(ChangeProposal).where(ChangeProposal.id == s["proposal_id"])
    )).scalar_one()
    assert p_row.status == "applied"
    assert p_row.applied_at is not None
    assert p_row.apply_log is not None
    # Phase E：apply_log 升级为 v2 shape，previous_canonical 在 ops 列表里
    ops = p_row.apply_log.get("ops", [])
    assert any(op.get("previous_canonical") == s["canonical_id"] for op in ops)
    # executor_result 写入
    assert p_row.apply_log.get("executor_result", {}).get("success") is True

    # spec kind 改成 canonical
    spec_row = (await db_session.execute(
        select(SpecORM).where(SpecORM.id == s["draft_id"])
    )).scalar_one()
    assert spec_row.kind == "canonical"


@pytest.mark.asyncio
async def test_apply_executor_failure_marks_apply_failed(db_session):
    """execute_platform_apply 返 success=False → proposal status='apply_failed'

    Phase E Task 3 新增：验证 IncrementalExecutor 失败时 execute_apply 不切 canonical 指针、
    标 apply_failed、apply_log 含 failure_reason + executor_result。
    """
    s = await _seed(db_session, draft_adds_field=True)
    ctx = _ctx_for(s["owner"], s["tenant"].id)

    fake_failure = _fake_failure_result(
        "create model t_order failed: 字段冲突",
        "create field amount failed: 字段已存在",
    )

    with patch(
        "app.proposal.apply.execute_platform_apply",
        new=AsyncMock(return_value=fake_failure),
    ):
        res = await apply_proposal(
            s["proposal_id"], ApplyRequest(confirm_irreversible=True), ctx, db_session,
        )

    assert res["status"] == "apply_failed"
    assert res["success"] is False
    assert "字段冲突" in (res.get("failure_reason") or "")

    # canonical 不应被推进
    app_row = (await db_session.execute(
        select(Application).where(Application.id == s["app"].id)
    )).scalar_one()
    assert app_row.canonical_spec_id == s["canonical_id"]

    # proposal 状态 + apply_log
    p_row = (await db_session.execute(
        select(ChangeProposal).where(ChangeProposal.id == s["proposal_id"])
    )).scalar_one()
    assert p_row.status == "apply_failed"
    assert p_row.apply_log is not None
    assert p_row.apply_log.get("success") is False
    assert "字段冲突" in (p_row.apply_log.get("failure_reason") or "")
    assert p_row.apply_log.get("executor_result", {}).get("success") is False


@pytest.mark.asyncio
async def test_apply_blocks_when_rebase_required(db_session):
    """canonical 已被推进 → base != current_canonical → 409"""
    s = await _seed(db_session, draft_adds_field=True)
    # 制造 rebase 状况：把 application.canonical_spec_id 换成另一个 spec
    new_canonical_payload = _build_full_spec(
        app_id=s["app"].id, user_id=s["owner"].id, spec_id="spec_canonical_v_new",
    )
    new_canonical = SpecORM(
        id=new_canonical_payload["id"], application_id=s["app"].id, version=1,
        kind="canonical", payload=new_canonical_payload, phase="ready",
        created_by=s["owner"].id, tenant_id=s["tenant"].id,
    )
    db_session.add(new_canonical)
    app_row = (await db_session.execute(
        select(Application).where(Application.id == s["app"].id)
    )).scalar_one()
    app_row.canonical_spec_id = "spec_canonical_v_new"
    await db_session.commit()

    ctx = _ctx_for(s["owner"], s["tenant"].id)
    with pytest.raises(HTTPException) as exc:
        await apply_proposal(
            s["proposal_id"], ApplyRequest(confirm_irreversible=True), ctx, db_session,
        )
    assert exc.value.status_code == 409
    assert "rebase" in exc.value.detail.lower()
