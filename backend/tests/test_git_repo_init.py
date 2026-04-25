"""repo 自动初始化测试 — mock provider，不发真实 HTTP。

覆盖：
- repo 不存在 → create_repo + commit_files 都被调
- repo 已存在 → 跳过 create_repo，但仍 commit_files
- application.git_repo_url / git_provider / git_default_branch 写回
- 端点 POST /api/applications/{id}/git-init 路径校验（缺 project_id / 缺 GitConnection / 不存在）
"""
import pytest
from unittest.mock import AsyncMock, patch
from fastapi import HTTPException

from app.deps import AuthContext
from app.models import Application, Project, ProjectMember, User
from app.models.collaboration import GitConnection
from app.models.tenant import Tenant, UserTenant
from app.git.connection import encrypt_token
from app.git.provider.base import CommitInfo
from app.git.repo_init import init_repo_for_application
from app.routes.git_connection import init_repo_endpoint


async def _make_user(db, username: str) -> User:
    u = User(username=username, hashed_password="x")
    db.add(u)
    await db.flush()
    return u


async def _seed(db_session, *, with_project: bool = True, with_conn: bool = True):
    tenant = Tenant(tenant_name="t1", tenant_code="t1")
    db_session.add(tenant)
    await db_session.flush()

    owner = await _make_user(db_session, "owner_u")
    contributor = await _make_user(db_session, "contrib_u")

    db_session.add_all([
        UserTenant(user_id=owner.id, tenant_id=tenant.id, status=1),
        UserTenant(user_id=contributor.id, tenant_id=tenant.id, status=1),
    ])

    project = None
    if with_project:
        project = Project(name="p1", user_id=owner.id, tenant_id=tenant.id)
        db_session.add(project)
        await db_session.flush()
        db_session.add(ProjectMember(project_id=project.id, user_id=owner.id, role="owner"))
        db_session.add(ProjectMember(project_id=project.id, user_id=contributor.id, role="contributor"))

    application = Application(
        user_id=owner.id,
        tenant_id=tenant.id,
        created_by=owner.id,
        project_id=project.id if project else None,
        app_name="测试应用",
        app_code="test_app",
        description="A test app",
    )
    db_session.add(application)
    await db_session.flush()

    git_conn = None
    if with_conn and project:
        git_conn = GitConnection(
            project_id=project.id,
            provider="github",
            host="https://github.com",
            access_token_enc=encrypt_token("ghp_fake"),
            group_id_or_org="myorg",
            status="connected",
        )
        db_session.add(git_conn)

    await db_session.commit()
    return {
        "tenant": tenant, "owner": owner, "contributor": contributor,
        "project": project, "application": application, "git_conn": git_conn,
    }


def _ctx_for(user: User, tenant_id: int) -> AuthContext:
    return AuthContext(
        user=user,
        tenant_id=tenant_id,
        tenant_role="tenant_admin",
        org_permissions={},
    )


def _mock_provider(*, repo_exists: bool):
    """构造 mock provider；create_repo 返回 'myorg/test_app'，commit_files 返回 fake CommitInfo。"""
    p = AsyncMock()
    p.name = "github"
    p.get_repo = AsyncMock(return_value={"path": "myorg/test_app"} if repo_exists else None)
    p.create_repo = AsyncMock(return_value="myorg/test_app")
    p.commit_files = AsyncMock(return_value=CommitInfo(sha="abc123", url="https://github.com/myorg/test_app/commit/abc123"))
    return p


@pytest.mark.asyncio
async def test_init_repo_creates_when_not_exists(db_session):
    s = await _seed(db_session)
    fake_provider = _mock_provider(repo_exists=False)

    with patch("app.git.repo_init.make_provider", return_value=fake_provider):
        full_path = await init_repo_for_application(
            db_session, application=s["application"], git_connection=s["git_conn"],
        )

    assert full_path == "myorg/test_app"
    fake_provider.get_repo.assert_awaited_once_with("myorg/test_app")
    fake_provider.create_repo.assert_awaited_once()
    fake_provider.commit_files.assert_awaited_once()

    # 验 commit_files 推的文件包含 manifest + README
    call_kwargs = fake_provider.commit_files.await_args.kwargs
    paths = [f.path for f in call_kwargs["files"]]
    assert ".builder/manifest.json" in paths
    assert "README.md" in paths
    assert call_kwargs["branch"] == "main"


@pytest.mark.asyncio
async def test_init_repo_skips_create_when_exists(db_session):
    s = await _seed(db_session)
    fake_provider = _mock_provider(repo_exists=True)

    with patch("app.git.repo_init.make_provider", return_value=fake_provider):
        full_path = await init_repo_for_application(
            db_session, application=s["application"], git_connection=s["git_conn"],
        )

    assert full_path == "myorg/test_app"
    fake_provider.get_repo.assert_awaited_once()
    fake_provider.create_repo.assert_not_awaited()
    # commit_files 仍被调（推首版 manifest）
    fake_provider.commit_files.assert_awaited_once()


@pytest.mark.asyncio
async def test_init_repo_writes_back_application_fields(db_session):
    s = await _seed(db_session)
    fake_provider = _mock_provider(repo_exists=False)

    with patch("app.git.repo_init.make_provider", return_value=fake_provider):
        await init_repo_for_application(
            db_session, application=s["application"], git_connection=s["git_conn"],
        )

    await db_session.refresh(s["application"])
    assert s["application"].git_repo_url == "https://github.com/myorg/test_app"
    assert s["application"].git_provider == "github"
    assert s["application"].git_default_branch == "main"


@pytest.mark.asyncio
async def test_init_repo_manifest_contains_app_metadata(db_session):
    """验 .builder/manifest.json 内容含 app_id / app_code / app_name"""
    import json
    s = await _seed(db_session)
    fake_provider = _mock_provider(repo_exists=False)

    with patch("app.git.repo_init.make_provider", return_value=fake_provider):
        await init_repo_for_application(
            db_session, application=s["application"], git_connection=s["git_conn"],
        )

    files = fake_provider.commit_files.await_args.kwargs["files"]
    manifest = next(f for f in files if f.path == ".builder/manifest.json")
    parsed = json.loads(manifest.content)
    assert parsed["app_code"] == "test_app"
    assert parsed["app_name"] == "测试应用"
    assert parsed["app_id"] == s["application"].id


@pytest.mark.asyncio
async def test_endpoint_404_when_app_missing(db_session):
    s = await _seed(db_session)
    ctx = _ctx_for(s["owner"], s["tenant"].id)

    with pytest.raises(HTTPException) as ei:
        await init_repo_endpoint(99999, ctx, db_session)
    assert ei.value.status_code == 404


@pytest.mark.asyncio
async def test_endpoint_400_when_app_has_no_project(db_session):
    s = await _seed(db_session, with_project=False, with_conn=False)
    ctx = _ctx_for(s["owner"], s["tenant"].id)

    with pytest.raises(HTTPException) as ei:
        await init_repo_endpoint(s["application"].id, ctx, db_session)
    assert ei.value.status_code == 400
    assert "project" in ei.value.detail


@pytest.mark.asyncio
async def test_endpoint_400_when_project_has_no_git_connection(db_session):
    s = await _seed(db_session, with_conn=False)
    ctx = _ctx_for(s["owner"], s["tenant"].id)

    with pytest.raises(HTTPException) as ei:
        await init_repo_endpoint(s["application"].id, ctx, db_session)
    assert ei.value.status_code == 400
    assert "git" in ei.value.detail


@pytest.mark.asyncio
async def test_endpoint_403_when_caller_below_maintainer(db_session):
    s = await _seed(db_session)
    contrib_ctx = _ctx_for(s["contributor"], s["tenant"].id)

    fake_provider = _mock_provider(repo_exists=False)
    with patch("app.git.repo_init.make_provider", return_value=fake_provider):
        with pytest.raises(HTTPException) as ei:
            await init_repo_endpoint(s["application"].id, contrib_ctx, db_session)
    assert ei.value.status_code == 403
    fake_provider.create_repo.assert_not_awaited()


@pytest.mark.asyncio
async def test_endpoint_happy_path(db_session):
    s = await _seed(db_session)
    ctx = _ctx_for(s["owner"], s["tenant"].id)

    fake_provider = _mock_provider(repo_exists=False)
    with patch("app.git.repo_init.make_provider", return_value=fake_provider):
        result = await init_repo_endpoint(s["application"].id, ctx, db_session)

    assert result["git_repo_url"] == "https://github.com/myorg/test_app"
    assert result["git_provider"] == "github"
    assert result["git_default_branch"] == "main"
    assert result["full_path"] == "myorg/test_app"
    fake_provider.create_repo.assert_awaited_once()
    fake_provider.commit_files.assert_awaited_once()
