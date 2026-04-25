"""Phase C Task 6 测试 — apply 成功后 merge PR + tag canonical commit

Mock provider，不发真实 HTTP。
"""
import pytest
from unittest.mock import AsyncMock, patch

from app.models import Application, Project, User
from app.models.collaboration import ChangeProposal, GitConnection
from app.models.tenant import Tenant, UserTenant
from app.git.connection import encrypt_token
from app.git.provider.base import CommitInfo
from app.git.sync import finalize_apply_to_git
from app.spec.persistence import empty_spec, to_orm
from app.spec.schema import Goal, Phase
from app.proposal.persistence import create_proposal


async def _make_user(db, username: str) -> User:
    u = User(username=username, hashed_password="x")
    db.add(u)
    await db.flush()
    return u


async def _seed(
    db_session, *,
    with_git_url: bool = True,
    with_conn: bool = True,
    with_pr_url: bool = True,
    pr_url: str = "https://github.com/myorg/test_app/pull/42",
):
    tenant = Tenant(tenant_name="t1", tenant_code="t1")
    db_session.add(tenant)
    await db_session.flush()

    owner = await _make_user(db_session, "apply_owner")
    db_session.add(UserTenant(user_id=owner.id, tenant_id=tenant.id, status=1))

    project = Project(name="p1", user_id=owner.id, tenant_id=tenant.id)
    db_session.add(project)
    await db_session.flush()

    application = Application(
        user_id=owner.id,
        tenant_id=tenant.id,
        created_by=owner.id,
        project_id=project.id,
        app_name="测试应用",
        app_code="test_app",
    )
    if with_git_url:
        application.git_repo_url = "https://github.com/myorg/test_app"
        application.git_provider = "github"
        application.git_default_branch = "main"
    db_session.add(application)
    await db_session.flush()

    if with_conn:
        db_session.add(GitConnection(
            project_id=project.id,
            provider="github",
            host="https://github.com",
            access_token_enc=encrypt_token("ghp_fake"),
            group_id_or_org="myorg",
            status="connected",
        ))

    draft = empty_spec(created_by=owner.id, application_id=application.id)
    draft.phase = Phase.DRAFTING
    draft.goal = Goal(title="测试目标", summary="x", business_problem="y", confirmed=True)
    db_session.add(to_orm(draft, tenant_id=tenant.id, kind="draft"))
    await db_session.flush()

    proposal = await create_proposal(
        db_session,
        application_id=application.id,
        draft_spec_id=draft.id,
        base_canonical_spec_id=None,
        title="apply 测试提案",
        description="x",
        created_by=owner.id,
        status="approved",
    )
    if with_pr_url:
        proposal.git_branch = "spec/proposal-abcdef12"
        proposal.git_pr_url = pr_url
    await db_session.commit()

    return {
        "tenant": tenant, "owner": owner, "project": project,
        "application": application, "proposal": proposal,
    }


def _mock_provider():
    p = AsyncMock()
    p.name = "github"
    p.merge_pull_request = AsyncMock(return_value=CommitInfo(
        sha="merged123", url="https://github.com/myorg/test_app/commit/merged123",
    ))
    p.add_tag = AsyncMock(return_value="apply-20260425-120000-abcdef12")
    return p


@pytest.mark.asyncio
async def test_finalize_apply_noop_when_no_pr_url(db_session):
    s = await _seed(db_session, with_pr_url=False)
    fake = _mock_provider()
    with patch("app.git.sync.make_provider", return_value=fake):
        result = await finalize_apply_to_git(
            db_session, proposal=s["proposal"], application=s["application"],
        )
    assert result is None
    fake.merge_pull_request.assert_not_awaited()
    fake.add_tag.assert_not_awaited()


@pytest.mark.asyncio
async def test_finalize_apply_noop_when_no_git_url(db_session):
    s = await _seed(db_session, with_git_url=False, with_conn=False)
    # PR url 写上但 application 无 git_repo_url
    s["proposal"].git_pr_url = "https://github.com/myorg/test_app/pull/1"
    await db_session.commit()
    fake = _mock_provider()
    with patch("app.git.sync.make_provider", return_value=fake):
        result = await finalize_apply_to_git(
            db_session, proposal=s["proposal"], application=s["application"],
        )
    assert result is None
    fake.merge_pull_request.assert_not_awaited()


@pytest.mark.asyncio
async def test_finalize_apply_calls_merge_and_tag(db_session):
    s = await _seed(db_session)
    fake = _mock_provider()
    with patch("app.git.sync.make_provider", return_value=fake):
        tag = await finalize_apply_to_git(
            db_session, proposal=s["proposal"], application=s["application"],
        )

    assert tag is not None
    assert tag.startswith("apply-")
    assert tag.endswith(s["proposal"].id[-8:])

    fake.merge_pull_request.assert_awaited_once()
    mk = fake.merge_pull_request.await_args.kwargs
    assert mk["repo_full_path"] == "myorg/test_app"
    assert mk["pr_number"] == 42

    fake.add_tag.assert_awaited_once()
    tk = fake.add_tag.await_args.kwargs
    assert tk["repo_full_path"] == "myorg/test_app"
    assert tk["ref"] == "merged123"
    assert tk["tag"] == tag


@pytest.mark.asyncio
async def test_finalize_apply_extracts_pr_number_from_gitlab_url(db_session):
    s = await _seed(
        db_session,
        pr_url="https://gitlab.com/g/r/-/merge_requests/42",
    )
    fake = _mock_provider()
    with patch("app.git.sync.make_provider", return_value=fake):
        await finalize_apply_to_git(
            db_session, proposal=s["proposal"], application=s["application"],
        )
    fake.merge_pull_request.assert_awaited_once()
    assert fake.merge_pull_request.await_args.kwargs["pr_number"] == 42


@pytest.mark.asyncio
async def test_execute_apply_records_git_tag_in_apply_log(db_session):
    """集成：execute_apply 成功 → apply_log 含 git_tag"""
    from app.proposal.apply import build_apply_plan, execute_apply

    s = await _seed(db_session)
    plan = await build_apply_plan(
        db_session,
        application_id=s["application"].id,
        draft_spec_id=s["proposal"].draft_spec_id,
        base_canonical_id=None,
        tenant_id=s["tenant"].id,
    )

    fake = _mock_provider()
    with patch("app.git.sync.make_provider", return_value=fake):
        result = await execute_apply(
            db_session, proposal_id=s["proposal"].id, plan=plan, tenant_id=s["tenant"].id,
        )

    assert result["success"] is True
    # reload 看 apply_log
    from sqlalchemy import select
    row = (await db_session.execute(
        select(ChangeProposal).where(ChangeProposal.id == s["proposal"].id)
    )).scalar_one()
    await db_session.refresh(row)
    assert row.status == "applied"
    assert "git_tag" in (row.apply_log or {})
    assert row.apply_log["git_tag"].startswith("apply-")


@pytest.mark.asyncio
async def test_execute_apply_git_failure_does_not_fail_apply(db_session):
    """git finalize 抛异常 → apply 仍 success（apply_log 记 git_finalize_failed）"""
    from app.proposal.apply import build_apply_plan, execute_apply

    s = await _seed(db_session)
    plan = await build_apply_plan(
        db_session,
        application_id=s["application"].id,
        draft_spec_id=s["proposal"].draft_spec_id,
        base_canonical_id=None,
        tenant_id=s["tenant"].id,
    )

    fake = _mock_provider()
    fake.merge_pull_request = AsyncMock(side_effect=RuntimeError("merge conflict"))
    with patch("app.git.sync.make_provider", return_value=fake):
        result = await execute_apply(
            db_session, proposal_id=s["proposal"].id, plan=plan, tenant_id=s["tenant"].id,
        )

    assert result["success"] is True
    from sqlalchemy import select
    row = (await db_session.execute(
        select(ChangeProposal).where(ChangeProposal.id == s["proposal"].id)
    )).scalar_one()
    await db_session.refresh(row)
    assert row.status == "applied"
    assert "git_finalize_failed" in (row.apply_log or {})
    assert "merge conflict" in row.apply_log["git_finalize_failed"]
