"""Phase C Task 5 测试 — promote → push spec/proposal-<id> 分支 + open PR

Mock provider，不发真实 HTTP。
"""
import pytest
from unittest.mock import AsyncMock, patch

from app.models import Application, Project, User
from app.models.collaboration import ChangeProposal, GitConnection
from app.models.tenant import Tenant, UserTenant
from app.git.connection import encrypt_token
from app.git.provider.base import CommitInfo, PullRequestInfo
from app.git.sync import push_proposal_branch, _extract_repo_path
from app.builder_spec.persistence import empty_spec, save_spec, to_orm
from app.builder_spec.schema import Goal, Phase
from app.proposal.persistence import create_proposal


async def _make_user(db, username: str) -> User:
    u = User(username=username, hashed_password="x")
    db.add(u)
    await db.flush()
    return u


async def _seed(db_session, *, with_git_url: bool = True, with_conn: bool = True):
    tenant = Tenant(tenant_name="t1", tenant_code="t1")
    db_session.add(tenant)
    await db_session.flush()

    owner = await _make_user(db_session, "promote_owner")
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

    git_conn = None
    if with_conn:
        git_conn = GitConnection(
            project_id=project.id,
            provider="github",
            host="https://github.com",
            access_token_enc=encrypt_token("ghp_fake"),
            group_id_or_org="myorg",
            status="connected",
        )
        db_session.add(git_conn)

    # 准备 draft spec
    draft = empty_spec(created_by=owner.id, application_id=application.id)
    draft.phase = Phase.DRAFTING
    draft.goal = Goal(title="测试目标", summary="x", business_problem="y", confirmed=True)
    spec_orm = to_orm(draft, tenant_id=tenant.id, kind="draft")
    db_session.add(spec_orm)
    await db_session.flush()

    proposal = await create_proposal(
        db_session,
        application_id=application.id,
        draft_spec_id=draft.id,
        base_canonical_spec_id=None,
        title="增加客户对象",
        description="新增 Customer + 字段",
        created_by=owner.id,
        status="open",
    )

    await db_session.commit()
    return {
        "tenant": tenant, "owner": owner, "project": project,
        "application": application, "git_conn": git_conn,
        "draft": draft, "proposal": proposal,
    }


def _mock_provider():
    p = AsyncMock()
    p.name = "github"
    p.commit_files = AsyncMock(return_value=CommitInfo(
        sha="def456", url="https://github.com/myorg/test_app/commit/def456",
    ))
    p.create_pull_request = AsyncMock(return_value=PullRequestInfo(
        id="pr_1", number=42, url="https://github.com/myorg/test_app/pull/42", state="open",
    ))
    return p


@pytest.mark.asyncio
async def test_push_proposal_branch_noop_when_no_git_url(db_session):
    s = await _seed(db_session, with_git_url=False, with_conn=False)
    fake = _mock_provider()
    with patch("app.git.sync.make_provider", return_value=fake):
        result = await push_proposal_branch(
            db_session, proposal=s["proposal"], application=s["application"],
        )
    assert result is None
    fake.commit_files.assert_not_awaited()
    fake.create_pull_request.assert_not_awaited()


@pytest.mark.asyncio
async def test_push_proposal_branch_noop_when_no_connection(db_session):
    s = await _seed(db_session, with_git_url=True, with_conn=False)
    fake = _mock_provider()
    with patch("app.git.sync.make_provider", return_value=fake):
        result = await push_proposal_branch(
            db_session, proposal=s["proposal"], application=s["application"],
        )
    assert result is None
    fake.commit_files.assert_not_awaited()
    fake.create_pull_request.assert_not_awaited()


@pytest.mark.asyncio
async def test_push_proposal_branch_calls_commit_and_pr(db_session):
    s = await _seed(db_session, with_git_url=True, with_conn=True)
    fake = _mock_provider()
    with patch("app.git.sync.make_provider", return_value=fake):
        result = await push_proposal_branch(
            db_session, proposal=s["proposal"], application=s["application"],
        )

    assert result is not None
    branch, pr_url = result
    assert branch.startswith("spec/proposal-")
    assert branch.endswith(s["proposal"].id[-8:])
    assert pr_url == "https://github.com/myorg/test_app/pull/42"

    # commit_files 被调，文件含 spec/canonical.{json,md}
    fake.commit_files.assert_awaited_once()
    ck = fake.commit_files.await_args.kwargs
    paths = [f.path for f in ck["files"]]
    assert "spec/canonical.json" in paths
    assert "spec/canonical.md" in paths
    assert ck["branch"] == branch
    assert ck["repo_full_path"] == "myorg/test_app"

    # create_pull_request 被调
    fake.create_pull_request.assert_awaited_once()
    pk = fake.create_pull_request.await_args.kwargs
    assert pk["source_branch"] == branch
    assert pk["target_branch"] == "main"
    assert pk["title"] == "增加客户对象"
    assert pk["repo_full_path"] == "myorg/test_app"


def test_extract_repo_path_with_matching_host():
    assert _extract_repo_path("https://github.com/myorg/repo", "https://github.com") == "myorg/repo"
    assert _extract_repo_path("https://gitlab.com/group/sub/repo", "https://gitlab.com") == "group/sub/repo"


def test_extract_repo_path_fallback_when_host_mismatch():
    # host 不匹配 → fallback 取末两段
    assert _extract_repo_path("https://other-host/myorg/repo", "https://github.com") == "myorg/repo"
