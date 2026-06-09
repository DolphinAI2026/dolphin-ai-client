"""Phase D Task 2 — webhook 入方向 handlers 测试

mock provider via unittest.mock.AsyncMock；用 sqlite in-memory db_session fixture
+ 真实 ORM 创建 application/connection/proposal/spec。
"""
from __future__ import annotations
import json
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select

from app.models import Application, User
from app.models.collaboration import (
    GitConnection, ChangeProposal, ProposalReview,
)
from app.models.spec import Spec as SpecORM
from app.models.tenant import Tenant, UserTenant
from app.git.connection import encrypt_token
from app.git.webhook import WebhookEvent
from app.git.inbound import (
    dispatch_webhook_event,
    handle_push,
    handle_pr_open_or_update,
    handle_pr_review,
)


def _full_spec_dict(*, app_id: int, user_id: int, spec_id: str) -> dict:
    """构造一个 通过第一道门 的完整 Spec payload（match test_proposal_apply）。"""
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
        "completeness": {"confirmed": 0, "total": 0, "by_section": {}, "pending_decisions": 0, "blocking_decisions": 0},
        "created_at": now.isoformat(), "updated_at": now.isoformat(),
        "created_by": user_id,
    }


async def _seed_app_with_conn(db_session, *, repo_full_path: str = "acme/widgets"):
    tenant = Tenant(tenant_name="t1", tenant_code="t1")
    db_session.add(tenant)
    await db_session.flush()

    owner = User(username="owner", hashed_password="x")
    db_session.add(owner)
    await db_session.flush()
    db_session.add(UserTenant(user_id=owner.id, tenant_id=tenant.id, status=1))

    app = Application(
        user_id=owner.id, tenant_id=tenant.id, created_by=owner.id,
        app_name="App1", app_code="app1",
        git_repo_url=f"https://github.com/{repo_full_path}",
        git_provider="github",
        git_default_branch="main",
        project_id=None,
    )
    db_session.add(app)
    await db_session.flush()

    # canonical spec
    canonical_payload = _full_spec_dict(app_id=app.id, user_id=owner.id, spec_id="spec_canonical_v0")
    canonical = SpecORM(
        id=canonical_payload["id"], application_id=app.id, version=1,
        kind="canonical", payload=canonical_payload, phase="ready",
        created_by=owner.id, tenant_id=tenant.id,
    )
    db_session.add(canonical)
    app.canonical_spec_id = canonical.id

    conn = GitConnection(
        project_id=1,  # any
        provider="github",
        host="https://github.com",
        access_token_enc=encrypt_token("ghp_dummy"),
        webhook_secret_enc=encrypt_token("hookSecret"),
        group_id_or_org="acme",
        status="connected",
    )
    db_session.add(conn)
    await db_session.commit()
    return {"tenant": tenant, "owner": owner, "app": app, "conn": conn, "canonical": canonical}


@pytest.mark.asyncio
async def test_handle_push_to_proposal_branch_syncs_draft(db_session):
    """spec/proposal-* 分支 push → 拉 spec/canonical.json → 更新 draft Spec + 重跑 validation"""
    s = await _seed_app_with_conn(db_session)

    # 建一个 draft + proposal 关联到 branch
    draft_payload = _full_spec_dict(app_id=s["app"].id, user_id=s["owner"].id, spec_id="spec_draft_1")
    draft = SpecORM(
        id=draft_payload["id"], application_id=s["app"].id, version=1, kind="draft",
        payload=draft_payload, phase="drafting", created_by=s["owner"].id, tenant_id=s["tenant"].id,
    )
    db_session.add(draft)
    proposal = ChangeProposal(
        id="cp_test_1",
        application_id=s["app"].id,
        title="测试提案",
        description="d",
        draft_spec_id=draft.id,
        base_canonical_spec_id=s["canonical"].id,
        status="open",
        git_branch="spec/proposal-cp_test_1",
        git_pr_url="https://github.com/acme/widgets/pull/100",
        created_by=s["owner"].id,
    )
    db_session.add(proposal)
    await db_session.commit()

    # 模拟 push 到 spec/proposal-* 分支：repo 上的 spec/canonical.json 已被外部修改（goal 标题变了）
    new_spec_dict = _full_spec_dict(app_id=s["app"].id, user_id=s["owner"].id, spec_id="ignored")
    new_spec_dict["goal"]["title"] = "新标题（来自外部 push）"

    event = WebhookEvent(
        provider="github", event_type="push",
        repo_full_path="acme/widgets",
        branch="spec/proposal-cp_test_1",
        actor_username="owner",
        raw_payload={},
    )

    fake_provider = AsyncMock()
    fake_provider.read_file = AsyncMock(return_value=json.dumps(new_spec_dict))

    with patch("app.git.inbound.make_provider", return_value=fake_provider):
        await handle_push(db_session, conn=s["conn"], event=event)

    # draft spec 应被覆盖 — 重新 load 验证
    refreshed = (await db_session.execute(
        select(SpecORM).where(SpecORM.id == draft.id)
    )).scalar_one()
    assert refreshed.payload["goal"]["title"] == "新标题（来自外部 push）"
    # validation OK → status 维持 open
    refreshed_proposal = (await db_session.execute(
        select(ChangeProposal).where(ChangeProposal.id == proposal.id)
    )).scalar_one()
    assert refreshed_proposal.status == "open"
    assert refreshed_proposal.validation_report is not None
    assert refreshed_proposal.validation_report["ok"] is True
    fake_provider.read_file.assert_called_once_with(
        repo_full_path="acme/widgets", path="spec/canonical.json", ref="spec/proposal-cp_test_1",
    )


@pytest.mark.asyncio
async def test_handle_push_to_main_ignored(db_session):
    """push 到 main 分支：noop（不调 provider）"""
    s = await _seed_app_with_conn(db_session)

    event = WebhookEvent(
        provider="github", event_type="push",
        repo_full_path="acme/widgets",
        branch="main",
        actor_username="someone",
        raw_payload={},
    )
    fake_provider = AsyncMock()
    with patch("app.git.inbound.make_provider", return_value=fake_provider):
        await handle_push(db_session, conn=s["conn"], event=event)

    fake_provider.read_file.assert_not_called()


@pytest.mark.asyncio
async def test_handle_pr_opened_external_creates_new_proposal(db_session):
    """外部新建 PR（无对应 proposal）→ 拉 source_branch 的 spec/canonical.json → 自动创建 ChangeProposal"""
    s = await _seed_app_with_conn(db_session)

    new_spec_dict = _full_spec_dict(app_id=s["app"].id, user_id=s["owner"].id, spec_id="ignored")

    event = WebhookEvent(
        provider="github", event_type="pr_opened",
        repo_full_path="acme/widgets",
        pr_number=999,
        pr_title="External PR title",
        pr_description="external pr body",
        pr_source_branch="feature/external",
        pr_target_branch="main",
        actor_username="owner",
        raw_payload={
            "pull_request": {"html_url": "https://github.com/acme/widgets/pull/999"},
        },
    )

    fake_provider = AsyncMock()
    fake_provider.read_file = AsyncMock(return_value=json.dumps(new_spec_dict))

    with patch("app.git.inbound.make_provider", return_value=fake_provider):
        await handle_pr_open_or_update(db_session, conn=s["conn"], event=event)

    proposals = (await db_session.execute(
        select(ChangeProposal).where(ChangeProposal.application_id == s["app"].id)
    )).scalars().all()
    assert len(proposals) == 1
    p = proposals[0]
    assert p.title == "External PR title"
    assert p.git_branch == "feature/external"
    assert p.git_pr_url == "https://github.com/acme/widgets/pull/999"
    assert p.status == "open"
    assert p.validation_report["ok"] is True


@pytest.mark.asyncio
async def test_handle_pr_open_existing_proposal_updates_only(db_session):
    """已存在关联此 PR 的 proposal → 仅更新 title/description，不重建"""
    s = await _seed_app_with_conn(db_session)

    draft_payload = _full_spec_dict(app_id=s["app"].id, user_id=s["owner"].id, spec_id="spec_draft_x")
    draft = SpecORM(
        id=draft_payload["id"], application_id=s["app"].id, version=1, kind="draft",
        payload=draft_payload, phase="drafting", created_by=s["owner"].id, tenant_id=s["tenant"].id,
    )
    db_session.add(draft)
    existing = ChangeProposal(
        id="cp_existing",
        application_id=s["app"].id,
        title="old title",
        description="old desc",
        draft_spec_id=draft.id,
        status="open",
        git_branch="spec/proposal-cp_existing",
        git_pr_url="https://github.com/acme/widgets/pull/55",
        created_by=s["owner"].id,
    )
    db_session.add(existing)
    await db_session.commit()

    event = WebhookEvent(
        provider="github", event_type="pr_synchronized",
        repo_full_path="acme/widgets",
        pr_number=55,
        pr_title="updated title",
        pr_description="updated desc",
        pr_source_branch="spec/proposal-cp_existing",
        pr_target_branch="main",
        actor_username="owner",
        raw_payload={"pull_request": {}},
    )

    fake_provider = AsyncMock()
    with patch("app.git.inbound.make_provider", return_value=fake_provider):
        await handle_pr_open_or_update(db_session, conn=s["conn"], event=event)

    refreshed = (await db_session.execute(
        select(ChangeProposal).where(ChangeProposal.id == "cp_existing")
    )).scalar_one()
    assert refreshed.title == "updated title"
    assert refreshed.description == "updated desc"
    # 不应该建新 proposal
    all_props = (await db_session.execute(
        select(ChangeProposal).where(ChangeProposal.application_id == s["app"].id)
    )).scalars().all()
    assert len(all_props) == 1
    fake_provider.read_file.assert_not_called()  # 已存在路径不应读 spec


@pytest.mark.asyncio
async def test_handle_pr_review_approve_transitions_status(db_session):
    """review approve → ProposalReview 写入 + proposal.status = 'approved'"""
    s = await _seed_app_with_conn(db_session)

    draft_payload = _full_spec_dict(app_id=s["app"].id, user_id=s["owner"].id, spec_id="spec_draft_r")
    draft = SpecORM(
        id=draft_payload["id"], application_id=s["app"].id, version=1, kind="draft",
        payload=draft_payload, phase="drafting", created_by=s["owner"].id, tenant_id=s["tenant"].id,
    )
    db_session.add(draft)
    proposal = ChangeProposal(
        id="cp_review",
        application_id=s["app"].id,
        title="t",
        description="d",
        draft_spec_id=draft.id,
        status="open",
        git_branch="spec/proposal-cp_review",
        git_pr_url="https://github.com/acme/widgets/pull/77",
        created_by=s["owner"].id,
    )
    db_session.add(proposal)
    await db_session.commit()

    event = WebhookEvent(
        provider="github", event_type="pr_review",
        repo_full_path="acme/widgets",
        pr_number=77,
        review_action="approve",
        review_body="LGTM!",
        actor_username="owner",
        raw_payload={},
    )

    await handle_pr_review(db_session, conn=s["conn"], event=event)

    refreshed_proposal = (await db_session.execute(
        select(ChangeProposal).where(ChangeProposal.id == "cp_review")
    )).scalar_one()
    assert refreshed_proposal.status == "approved"

    reviews = (await db_session.execute(
        select(ProposalReview).where(ProposalReview.proposal_id == "cp_review")
    )).scalars().all()
    assert len(reviews) == 1
    assert reviews[0].action == "approve"
    assert reviews[0].body == "LGTM!"


@pytest.mark.asyncio
async def test_dispatch_routes_unknown_event_silently(db_session):
    """未知 event_type 不抛异常（仅 logger.info）"""
    s = await _seed_app_with_conn(db_session)
    event = WebhookEvent(
        provider="github", event_type="unknown",
        repo_full_path="acme/widgets",
        raw_payload={},
    )
    # 应 noop 不抛
    await dispatch_webhook_event(db_session, conn=s["conn"], event=event)
