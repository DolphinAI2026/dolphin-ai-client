"""Phase D Task 5 — Workspace → repo 子目录同步测试

mock provider via unittest.mock.AsyncMock；用 tmp_path fixture 写假 workspace
文件 + node_modules/binary 验证跳过逻辑。
"""
from __future__ import annotations
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from app.models import Application, Project, User
from app.models.collaboration import GitConnection
from app.models.tenant import Tenant, UserTenant
from app.git.connection import encrypt_token
from app.git.provider.base import CommitInfo
from app.git.workspace_sync import push_workspace_to_repo


async def _seed(
    db_session, *,
    with_git_url: bool = True,
    with_project: bool = True,
    with_conn: bool = True,
):
    tenant = Tenant(tenant_name="t1", tenant_code="t1")
    db_session.add(tenant)
    await db_session.flush()

    owner = User(username="ws_owner", hashed_password="x")
    db_session.add(owner)
    await db_session.flush()
    db_session.add(UserTenant(user_id=owner.id, tenant_id=tenant.id, status=1))

    project = None
    if with_project:
        project = Project(name="p1", user_id=owner.id, tenant_id=tenant.id)
        db_session.add(project)
        await db_session.flush()

    app = Application(
        user_id=owner.id, tenant_id=tenant.id, created_by=owner.id,
        app_name="App1", app_code="app_ws_sync",
        project_id=project.id if project else None,
    )
    if with_git_url:
        app.git_repo_url = "https://github.com/myorg/test_app"
        app.git_provider = "github"
        app.git_default_branch = "main"
    db_session.add(app)
    await db_session.flush()

    if with_conn and project is not None:
        db_session.add(GitConnection(
            project_id=project.id,
            provider="github",
            host="https://github.com",
            access_token_enc=encrypt_token("ghp_fake"),
            group_id_or_org="myorg",
            status="connected",
        ))

    await db_session.commit()
    return {"tenant": tenant, "owner": owner, "project": project, "app": app}


def _seed_workspace_files(workspace_root: Path, workspace_id: str) -> Path:
    """构造 workspace_root/<id>/ 目录结构，写若干文件。"""
    ws = workspace_root / workspace_id
    ws.mkdir(parents=True, exist_ok=True)
    (ws / "package.json").write_text('{"name": "demo"}', encoding="utf-8")
    (ws / "src").mkdir()
    (ws / "src" / "main.js").write_text("console.log('hi')", encoding="utf-8")
    (ws / "src" / "util.js").write_text("export const x = 1", encoding="utf-8")
    return ws


@pytest.mark.asyncio
async def test_push_workspace_collects_files_and_commits(db_session, tmp_path):
    """workspace 下的 utf-8 文本 → 全部 commit 到 code/workspace-<id> 分支"""
    s = await _seed(db_session)
    _seed_workspace_files(tmp_path, "ws-abc")

    fake_provider = AsyncMock()
    fake_provider.commit_files = AsyncMock(return_value=CommitInfo(
        sha="newsha999", url="https://github.com/myorg/test_app/commit/newsha999",
    ))
    with patch("app.git.workspace_sync.make_provider", return_value=fake_provider):
        result = await push_workspace_to_repo(
            db_session, application=s["app"], workspace_id="ws-abc",
            workspace_root=tmp_path,
        )

    assert result["status"] == "ok"
    assert result["branch"] == "code/workspace-ws-abc"
    assert result["commit_sha"] == "newsha999"
    assert result["file_count"] == 3

    fake_provider.commit_files.assert_awaited_once()
    call_kwargs = fake_provider.commit_files.await_args.kwargs
    assert call_kwargs["repo_full_path"] == "myorg/test_app"
    assert call_kwargs["branch"] == "code/workspace-ws-abc"
    assert "ws-abc sync from Builder" in call_kwargs["message"]
    paths = sorted(f.path for f in call_kwargs["files"])
    assert paths == [
        "workspaces/ws-abc/package.json",
        "workspaces/ws-abc/src/main.js",
        "workspaces/ws-abc/src/util.js",
    ]


@pytest.mark.asyncio
async def test_push_workspace_skips_node_modules_and_binaries(db_session, tmp_path):
    """node_modules / dist / __pycache__ 下的文件 + 二进制都不应 commit"""
    s = await _seed(db_session)
    ws = _seed_workspace_files(tmp_path, "ws-skip")
    # node_modules 一堆文件 — 应整体跳过
    (ws / "node_modules").mkdir()
    (ws / "node_modules" / "lodash.js").write_text("// huge", encoding="utf-8")
    (ws / "node_modules" / "nested").mkdir()
    (ws / "node_modules" / "nested" / "x.js").write_text("// nested skip", encoding="utf-8")
    # dist
    (ws / "dist").mkdir()
    (ws / "dist" / "bundle.js").write_text("// built", encoding="utf-8")
    # __pycache__
    (ws / "__pycache__").mkdir()
    (ws / "__pycache__" / "x.pyc").write_text("ignored", encoding="utf-8")
    # 二进制：合法文件名但内容是非 utf-8 字节
    (ws / "logo.png").write_bytes(b"\x89PNG\r\n\x1a\n\x00\x00\xff\xfe\xfdjpeg-binary-bytes")

    fake_provider = AsyncMock()
    fake_provider.commit_files = AsyncMock(return_value=CommitInfo(sha="s2", url=""))
    with patch("app.git.workspace_sync.make_provider", return_value=fake_provider):
        result = await push_workspace_to_repo(
            db_session, application=s["app"], workspace_id="ws-skip",
            workspace_root=tmp_path,
        )

    assert result["status"] == "ok"
    # 仅原始 3 个 utf-8 文件被收集（无 node_modules / dist / __pycache__ / .png）
    assert result["file_count"] == 3
    paths = sorted(f.path for f in fake_provider.commit_files.await_args.kwargs["files"])
    assert paths == [
        "workspaces/ws-skip/package.json",
        "workspaces/ws-skip/src/main.js",
        "workspaces/ws-skip/src/util.js",
    ]
    # 确认没漏出 skip 目录里的文件
    for p in paths:
        assert "node_modules" not in p
        assert "/dist/" not in p
        assert "__pycache__" not in p
        assert "logo.png" not in p


@pytest.mark.asyncio
async def test_push_workspace_no_git_binding_raises(db_session, tmp_path):
    s = await _seed(db_session, with_git_url=False)
    with pytest.raises(RuntimeError, match="未绑定 git"):
        await push_workspace_to_repo(
            db_session, application=s["app"], workspace_id="ws-x",
            workspace_root=tmp_path,
        )


@pytest.mark.asyncio
async def test_push_workspace_missing_dir_raises(db_session, tmp_path):
    s = await _seed(db_session)
    # 不创建目录
    with pytest.raises(RuntimeError, match="不存在"):
        await push_workspace_to_repo(
            db_session, application=s["app"], workspace_id="ws-missing",
            workspace_root=tmp_path,
        )


@pytest.mark.asyncio
async def test_push_workspace_empty_dir_returns_noop(db_session, tmp_path):
    s = await _seed(db_session)
    (tmp_path / "ws-empty").mkdir()
    fake_provider = AsyncMock()
    with patch("app.git.workspace_sync.make_provider", return_value=fake_provider):
        result = await push_workspace_to_repo(
            db_session, application=s["app"], workspace_id="ws-empty",
            workspace_root=tmp_path,
        )
    assert result["status"] == "noop"
    fake_provider.commit_files.assert_not_called()
