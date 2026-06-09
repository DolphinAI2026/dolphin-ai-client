"""Phase D Task 3 — 直连 merge 拦截测试

mock provider via unittest.mock.AsyncMock；测三种 case：
1. proposal.status='applied'：跳过（Builder 自己 merge）
2. 未知 PR / 未 applied proposal：触发 revert + comment + 写 PlatformDriftLog
3. 缺失 merge_commit_sha：跳过 revert 但仍 comment + log
"""
from __future__ import annotations
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select

from app.models import Application, User
from app.models.collaboration import (
    GitConnection, ChangeProposal, PlatformDriftLog,
)
from app.models.spec import Spec as SpecORM
from app.models.tenant import Tenant, UserTenant
from app.git.connection import encrypt_token
from app.git.webhook import WebhookEvent
from app.git.inbound_intercept import handle_direct_merge


def _full_spec_dict(*, app_id: int, user_id: int, spec_id: str) -> dict:
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

    canonical_payload = _full_spec_dict(app_id=app.id, user_id=owner.id, spec_id="spec_canonical_v0")
    canonical = SpecORM(
        id=canonical_payload["id"], application_id=app.id, version=1,
        kind="canonical", payload=canonical_payload, phase="ready",
        created_by=owner.id, tenant_id=tenant.id,
    )
    db_session.add(canonical)
    app.canonical_spec_id = canonical.id

    conn = GitConnection(
        project_id=1,
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
async def test_applied_proposal_merge_skips_intercept(db_session):
    """proposal.status='applied' → 不调 revert / comment / drift log（Builder 自己干的）"""
    s = await _seed_app_with_conn(db_session)

    draft_payload = _full_spec_dict(app_id=s["app"].id, user_id=s["owner"].id, spec_id="spec_d_a")
    draft = SpecORM(
        id=draft_payload["id"], application_id=s["app"].id, version=1, kind="draft",
        payload=draft_payload, phase="drafting", created_by=s["owner"].id, tenant_id=s["tenant"].id,
    )
    db_session.add(draft)
    proposal = ChangeProposal(
        id="cp_applied",
        application_id=s["app"].id,
        title="t",
        description="d",
        draft_spec_id=draft.id,
        status="applied",
        git_branch="spec/proposal-cp_applied",
        git_pr_url="https://github.com/acme/widgets/pull/42",
        created_by=s["owner"].id,
    )
    db_session.add(proposal)
    await db_session.commit()

    event = WebhookEvent(
        provider="github", event_type="pr_merged",
        repo_full_path="acme/widgets",
        pr_number=42,
        pr_target_branch="main",
        actor_username="owner",
        raw_payload={"pull_request": {"merge_commit_sha": "abc123"}},
    )

    fake_provider = AsyncMock()
    with patch("app.git.inbound_intercept.make_provider", return_value=fake_provider):
        await handle_direct_merge(db_session, conn=s["conn"], event=event)

    fake_provider.revert_commit.assert_not_called()
    fake_provider.add_pr_comment.assert_not_called()
    drift_logs = (await db_session.execute(
        select(PlatformDriftLog).where(PlatformDriftLog.application_id == s["app"].id)
    )).scalars().all()
    assert drift_logs == []


@pytest.mark.asyncio
async def test_unknown_merge_reverts_and_comments_and_logs_drift(db_session):
    """未知 PR（无 proposal 关联）→ revert + comment + drift log"""
    s = await _seed_app_with_conn(db_session)

    event = WebhookEvent(
        provider="github", event_type="pr_merged",
        repo_full_path="acme/widgets",
        pr_number=99,
        pr_target_branch="main",
        actor_username="randomuser",
        raw_payload={"pull_request": {"merge_commit_sha": "deadbeef"}},
    )

    fake_provider = AsyncMock()
    with patch("app.git.inbound_intercept.make_provider", return_value=fake_provider):
        await handle_direct_merge(db_session, conn=s["conn"], event=event)

    fake_provider.revert_commit.assert_called_once_with(
        repo_full_path="acme/widgets", branch="main", commit_sha="deadbeef",
    )
    fake_provider.add_pr_comment.assert_called_once()
    comment_call = fake_provider.add_pr_comment.call_args
    assert comment_call.kwargs["pr_number"] == 99
    assert "Builder" in comment_call.kwargs["body"]

    drift_logs = (await db_session.execute(
        select(PlatformDriftLog).where(PlatformDriftLog.application_id == s["app"].id)
    )).scalars().all()
    assert len(drift_logs) == 1
    assert drift_logs[0].kind == "direct_merge_reverted"
    assert drift_logs[0].git_sha == "deadbeef"


@pytest.mark.asyncio
async def test_intercept_handles_missing_merge_commit_sha_gracefully(db_session):
    """raw_payload 缺 merge_commit_sha → 不调 revert 但仍 comment + 写 drift log"""
    s = await _seed_app_with_conn(db_session)

    event = WebhookEvent(
        provider="github", event_type="pr_merged",
        repo_full_path="acme/widgets",
        pr_number=66,
        pr_target_branch="main",
        actor_username="someone",
        raw_payload={"pull_request": {}},  # 没有 merge_commit_sha
    )

    fake_provider = AsyncMock()
    with patch("app.git.inbound_intercept.make_provider", return_value=fake_provider):
        await handle_direct_merge(db_session, conn=s["conn"], event=event)

    fake_provider.revert_commit.assert_not_called()
    fake_provider.add_pr_comment.assert_called_once()

    drift_logs = (await db_session.execute(
        select(PlatformDriftLog).where(PlatformDriftLog.application_id == s["app"].id)
    )).scalars().all()
    assert len(drift_logs) == 1
    assert drift_logs[0].kind == "direct_merge_reverted"
    assert drift_logs[0].git_sha is None


@pytest.mark.asyncio
async def test_intercept_with_unrelated_proposal_status_still_reverts(db_session):
    """proposal 存在但 status='open'（未 apply）→ 仍触发 revert（绕过了第二道门）"""
    s = await _seed_app_with_conn(db_session)

    draft_payload = _full_spec_dict(app_id=s["app"].id, user_id=s["owner"].id, spec_id="spec_d_o")
    draft = SpecORM(
        id=draft_payload["id"], application_id=s["app"].id, version=1, kind="draft",
        payload=draft_payload, phase="drafting", created_by=s["owner"].id, tenant_id=s["tenant"].id,
    )
    db_session.add(draft)
    proposal = ChangeProposal(
        id="cp_open",
        application_id=s["app"].id,
        title="t",
        description="d",
        draft_spec_id=draft.id,
        status="open",
        git_branch="spec/proposal-cp_open",
        git_pr_url="https://github.com/acme/widgets/pull/30",
        created_by=s["owner"].id,
    )
    db_session.add(proposal)
    await db_session.commit()

    event = WebhookEvent(
        provider="github", event_type="pr_merged",
        repo_full_path="acme/widgets",
        pr_number=30,
        pr_target_branch="main",
        actor_username="someone",
        raw_payload={"pull_request": {"merge_commit_sha": "feedface"}},
    )

    fake_provider = AsyncMock()
    with patch("app.git.inbound_intercept.make_provider", return_value=fake_provider):
        await handle_direct_merge(db_session, conn=s["conn"], event=event)

    fake_provider.revert_commit.assert_called_once()
    drift_logs = (await db_session.execute(
        select(PlatformDriftLog).where(PlatformDriftLog.application_id == s["app"].id)
    )).scalars().all()
    assert len(drift_logs) == 1
    assert drift_logs[0].git_sha == "feedface"
