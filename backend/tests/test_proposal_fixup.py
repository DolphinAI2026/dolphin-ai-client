"""Phase E Task 4 — fix-up ChangeProposal 自动开机制测试。

不依赖 execute_apply，只单测 create_fixup_proposal 本身：
- failed proposal + ExecutionResult → 新 draft + 新 proposal（status=draft，不自动 promote）
- description 含 errors 摘要 + journal 标记 ✓/✗
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy import select

from app.incremental_executor import ExecutionResult
from app.models import Application, User
from app.models.collaboration import ChangeProposal
from app.models.spec import Spec as SpecORM
from app.models.tenant import Tenant, UserTenant
from app.proposal.fixup import create_fixup_proposal


def _build_full_spec(*, app_id: int, user_id: int, spec_id: str) -> dict:
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    return {
        "id": spec_id,
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
        "completeness": {"confirmed": 0, "total": 0, "by_section": {},
                         "pending_decisions": 0, "blocking_decisions": 0},
        "created_at": now.isoformat(), "updated_at": now.isoformat(),
        "created_by": user_id,
    }


async def _seed_failed_proposal(db_session) -> dict:
    tenant = Tenant(tenant_name="t1", tenant_code="t1")
    db_session.add(tenant)
    await db_session.flush()

    owner = User(username="owner_fixup", hashed_password="x")
    db_session.add(owner)
    await db_session.flush()
    db_session.add(UserTenant(user_id=owner.id, tenant_id=tenant.id, status=1))

    app = Application(
        user_id=owner.id, tenant_id=tenant.id, created_by=owner.id,
        app_name="App-Fixup", app_code="app_fixup",
    )
    db_session.add(app)
    await db_session.flush()

    # 起一个 canonical
    canonical_payload = _build_full_spec(app_id=app.id, user_id=owner.id, spec_id="spec_canonical_fxp")
    canonical = SpecORM(
        id=canonical_payload["id"], application_id=app.id, version=1, kind="canonical",
        payload=canonical_payload, phase="ready", created_by=owner.id, tenant_id=tenant.id,
    )
    db_session.add(canonical)

    draft_payload = _build_full_spec(app_id=app.id, user_id=owner.id, spec_id="spec_draft_fxp")
    draft = SpecORM(
        id=draft_payload["id"], application_id=app.id, version=1, kind="draft",
        payload=draft_payload, phase="drafting", created_by=owner.id, tenant_id=tenant.id,
    )
    db_session.add(draft)
    await db_session.commit()

    failed_proposal = ChangeProposal(
        id="cp_failed_001",
        application_id=app.id,
        draft_spec_id=draft.id,
        base_canonical_spec_id=canonical.id,
        title="加订单字段",
        description="失败前的提案",
        status="apply_failed",
        created_by=owner.id,
    )
    db_session.add(failed_proposal)
    await db_session.commit()
    await db_session.refresh(failed_proposal)

    return {
        "tenant": tenant, "owner": owner, "app": app,
        "canonical_id": canonical.id, "draft_id": draft.id,
        "failed_proposal": failed_proposal,
    }


def _build_failure_result() -> ExecutionResult:
    """造一个 partial failure：1 个成功（有 platform_id）+ 2 个失败"""
    r = ExecutionResult()
    r.journal.record(
        resource_type="model", operation="create", name="订单", code="t_order",
        platform_id="m_remote_001",
    )
    r.journal.record(
        resource_type="field", operation="create", name="金额", code="amount",
        platform_id=None,
    )
    r.add_error("create field amount failed: 字段名重复")
    r.add_error("create field tax failed: 字典 tax_type 不存在")
    return r


@pytest.mark.asyncio
async def test_fixup_creates_new_draft_and_proposal(db_session):
    """failed proposal + ExecutionResult → 新 draft + 新 proposal status='draft'"""
    s = await _seed_failed_proposal(db_session)
    exec_result = _build_failure_result()

    fixup_id = await create_fixup_proposal(
        db_session,
        failed_proposal=s["failed_proposal"],
        exec_result=exec_result,
        tenant_id=s["tenant"].id,
    )

    assert fixup_id is not None
    assert fixup_id.startswith("cp_")

    # 新 proposal 在 DB 中存在，且 status='draft'（不自动 promote）
    fixup_row = (await db_session.execute(
        select(ChangeProposal).where(ChangeProposal.id == fixup_id)
    )).scalar_one()
    assert fixup_row.status == "draft"
    assert fixup_row.application_id == s["app"].id
    assert fixup_row.title == "fix-up: 加订单字段"
    # base_canonical 继承自失败 proposal
    assert fixup_row.base_canonical_spec_id == s["canonical_id"]

    # 新 draft Spec 真存在，且 id != 原 draft.id
    assert fixup_row.draft_spec_id != s["draft_id"]
    new_draft_row = (await db_session.execute(
        select(SpecORM).where(SpecORM.id == fixup_row.draft_spec_id)
    )).scalar_one()
    assert new_draft_row.kind == "draft"
    assert new_draft_row.application_id == s["app"].id


@pytest.mark.asyncio
async def test_fixup_includes_error_summary_in_description(db_session):
    """description 含 ExecutionResult.errors 摘要 + journal entries（标 ✓/✗）"""
    s = await _seed_failed_proposal(db_session)
    exec_result = _build_failure_result()

    fixup_id = await create_fixup_proposal(
        db_session,
        failed_proposal=s["failed_proposal"],
        exec_result=exec_result,
        tenant_id=s["tenant"].id,
    )

    fixup_row = (await db_session.execute(
        select(ChangeProposal).where(ChangeProposal.id == fixup_id)
    )).scalar_one()
    desc = fixup_row.description or ""

    # 失败原因摘要
    assert "失败原因" in desc
    assert "字段名重复" in desc
    assert "tax_type 不存在" in desc

    # journal 标记
    assert "已执行的操作" in desc
    # ✓ 标记成功（platform_id 非空）
    assert "✓ create model:t_order" in desc
    # ✗ 标记失败（platform_id 空）
    assert "✗ create field:amount" in desc

    # 引用源 proposal id
    assert s["failed_proposal"].id in desc


@pytest.mark.asyncio
async def test_fixup_returns_none_when_draft_missing(db_session):
    """失败 proposal 的 draft 已被删 → 返回 None（容错）"""
    s = await _seed_failed_proposal(db_session)
    # 把原 draft 删了
    draft_row = (await db_session.execute(
        select(SpecORM).where(SpecORM.id == s["draft_id"])
    )).scalar_one()
    await db_session.delete(draft_row)
    await db_session.commit()

    exec_result = _build_failure_result()
    fixup_id = await create_fixup_proposal(
        db_session,
        failed_proposal=s["failed_proposal"],
        exec_result=exec_result,
        tenant_id=s["tenant"].id,
    )
    assert fixup_id is None
