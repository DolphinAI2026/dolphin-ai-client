"""P3 Task 3 — clone 端点:bare 仓当远端,本地路径走 build_authed_url 非-https 分支免 PAT。"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from app.coding import workspace as ws_mod
from app.crypto import encrypt_password
from app.deps import AuthContext
from app.models import User, Project
from app.models.collaboration import GitConnection
from app.models.tenant import Tenant
from app.models.workspace_git import WorkspaceGitRemote
from app.routes.coding import CloneRepoRequest, git_clone_workspace_endpoint


def _run(cwd: Path, *a: str) -> None:
    subprocess.run(["git", "-C", str(cwd), *a], check=True, capture_output=True)


@pytest.fixture
def bare_remote(tmp_path: Path) -> Path:
    src = tmp_path / "src"; src.mkdir()
    _run(src, "init", "-b", "main")
    _run(src, "config", "user.email", "t@t.com"); _run(src, "config", "user.name", "t")
    (src / "main.py").write_text("print('hi')")
    _run(src, "add", "."); _run(src, "commit", "-m", "init")
    bare = tmp_path / "remote.git"
    subprocess.run(["git", "clone", "--bare", str(src), str(bare)], check=True, capture_output=True)
    return bare


def _ctx(user: User, tenant_id: int) -> AuthContext:
    return AuthContext(user=user, tenant_id=tenant_id, tenant_role="member", org_permissions={})


@pytest.mark.asyncio
async def test_clone_endpoint_creates_workspace_and_binds_remote(db_session, bare_remote, tmp_path, monkeypatch):
    # WORKSPACE_ROOT → tmp,避免污染真实工作区
    monkeypatch.setattr(ws_mod, "WORKSPACE_ROOT", tmp_path / "workspaces")
    (tmp_path / "workspaces").mkdir()
    monkeypatch.setattr(ws_mod, "WORKSPACE_SEARCH_ROOTS", [tmp_path / "workspaces"])

    tenant = Tenant(tenant_name="t_cl", tenant_code="t_cl"); db_session.add(tenant); await db_session.flush()
    user = User(username="cl_user", hashed_password="x"); db_session.add(user); await db_session.flush()
    proj = Project(name="p", user_id=user.id, tenant_id=tenant.id); db_session.add(proj); await db_session.flush()
    conn = GitConnection(project_id=proj.id, provider="gitlab", host="git.example.com",
                         access_token_enc=encrypt_password("x"))
    db_session.add(conn); await db_session.flush()
    ctx = _ctx(user, tenant.id)

    body = CloneRepoRequest(provider="gitlab", remote_url=str(bare_remote),
                            git_connection_id=conn.id, name="Acme CRM")
    result = await git_clone_workspace_endpoint(body, ctx, db_session)

    ws_id = result["id"]
    # 工作区文件 clone 下来了
    from app.coding.workspace import WorkspaceManager
    ws_path = WorkspaceManager().get_workspace_path(ws_id)
    assert (ws_path / "main.py").exists()
    # .git/config 的 origin 已被改成 clean remote_url(本测 remote_url==bare 路径,断言无 token 形式即可)
    cfg = (ws_path / ".git" / "config").read_text()
    assert "@" not in cfg.split("url = ")[1].splitlines()[0]  # 无 user:token@ 形式
    # WorkspaceGitRemote 落库
    from sqlalchemy import select
    row = (await db_session.execute(
        select(WorkspaceGitRemote).where(WorkspaceGitRemote.ws_id == ws_id)
    )).scalar_one()
    assert row.provider == "gitlab"
    assert row.remote_url == str(bare_remote)
    assert row.git_connection_id == conn.id
    assert row.tenant_id == tenant.id and row.user_id == user.id


@pytest.mark.asyncio
async def test_clone_endpoint_bad_remote_cleans_up_and_400(db_session, tmp_path, monkeypatch):
    monkeypatch.setattr(ws_mod, "WORKSPACE_ROOT", tmp_path / "workspaces")
    (tmp_path / "workspaces").mkdir()
    monkeypatch.setattr(ws_mod, "WORKSPACE_SEARCH_ROOTS", [tmp_path / "workspaces"])

    tenant = Tenant(tenant_name="t_bad", tenant_code="t_bad"); db_session.add(tenant); await db_session.flush()
    user = User(username="bad_user", hashed_password="x"); db_session.add(user); await db_session.flush()
    proj = Project(name="p", user_id=user.id, tenant_id=tenant.id); db_session.add(proj); await db_session.flush()
    conn = GitConnection(project_id=proj.id, provider="gitlab", host="git.example.com",
                         access_token_enc=encrypt_password("x"))
    db_session.add(conn); await db_session.flush()
    ctx = _ctx(user, tenant.id)

    from fastapi import HTTPException
    body = CloneRepoRequest(provider="gitlab", remote_url=str(tmp_path / "does-not-exist.git"),
                            git_connection_id=conn.id, name="x")
    with pytest.raises(HTTPException) as ei:
        await git_clone_workspace_endpoint(body, ctx, db_session)
    assert ei.value.status_code == 400
    # 没留下半成品工作区(clone 失败的目录被清理 → workspaces 根下无新 dir)
    leftover = [p for p in (tmp_path / "workspaces").iterdir() if p.is_dir()]
    assert leftover == []
