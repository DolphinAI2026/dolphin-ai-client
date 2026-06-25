"""Task 3 TDD — git remote endpoints: connect / push / pull / status 扩 ahead/behind。

本地 bare 仓当「远程」:build_authed_url 非 https 直接返回路径,免 PAT。
"""
from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from app.crypto import encrypt_password
from app.deps import AuthContext
from app.models import User, Project
from app.models.collaboration import GitConnection
from app.models.tenant import Tenant
from app.models.workspace_git import WorkspaceGitRemote
from app.routes.coding import (
    GitConnectRequest,
    git_connect_endpoint,
    git_push_endpoint,
    git_pull_endpoint,
    git_status_endpoint,
)


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------

def _run(cwd: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True)


@pytest.fixture
def bare_and_ws(tmp_path: Path):
    """bare 仓作远端 + 本地 ws 仓(已有初始提交)。"""
    bare = tmp_path / "remote.git"
    subprocess.run(["git", "init", "--bare", "-b", "main", str(bare)], check=True, capture_output=True)

    ws = tmp_path / "ws"
    ws.mkdir()
    _run(ws, "init", "-b", "main")
    _run(ws, "config", "user.email", "t@t.com")
    _run(ws, "config", "user.name", "t")
    (ws / "a.txt").write_text("hello")
    _run(ws, "add", ".")
    _run(ws, "commit", "-m", "init")
    return ws, bare


def _ctx(user: User, tenant_id: int) -> AuthContext:
    return AuthContext(user=user, tenant_id=tenant_id, tenant_role="member", org_permissions={})


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

async def _seed_db(db_session, tenant, user, bare: Path):
    """插入 Project + GitConnection;返回 GitConnection。"""
    proj = Project(name="p", user_id=user.id, tenant_id=tenant.id)
    db_session.add(proj)
    await db_session.flush()

    conn = GitConnection(
        project_id=proj.id,
        provider="gitlab",
        host="git.example.com",
        access_token_enc=encrypt_password("x"),
    )
    db_session.add(conn)
    await db_session.flush()
    return conn


# ---------------------------------------------------------------------------
# tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_git_connect_creates_remote_row(db_session, bare_and_ws):
    ws, bare = bare_and_ws

    tenant = Tenant(tenant_name="t_gc", tenant_code="t_gc"); db_session.add(tenant); await db_session.flush()
    user = User(username="gc_user", hashed_password="x"); db_session.add(user); await db_session.flush()
    ctx = _ctx(user, tenant.id)
    conn = await _seed_db(db_session, tenant, user, bare)

    fake_meta = {"ws_id": "ws-gc", "tenant_id": tenant.id, "project_id": None, "user_id": user.id}
    body = GitConnectRequest(provider="gitlab", remote_url=str(bare), git_connection_id=conn.id)

    with patch("app.routes.coding.workspace_mgr.get_workspace_path", return_value=ws), \
         patch("app.coding.workspace_access.workspace_mgr.get_workspace_info", return_value=fake_meta), \
         patch("app.coding.workspace_access.workspace_mgr.get_workspace_path", return_value=ws):
        result = await git_connect_endpoint("ws-gc", body, ctx, db_session)

    assert result["ok"] is True
    assert result["default_branch"] == "main"

    from sqlalchemy import select
    row = (await db_session.execute(
        select(WorkspaceGitRemote).where(WorkspaceGitRemote.ws_id == "ws-gc")
    )).scalar_one()
    assert row.provider == "gitlab"
    assert row.remote_url == str(bare)
    assert row.git_connection_id == conn.id
    assert row.tenant_id == tenant.id
    assert row.user_id == user.id


@pytest.mark.asyncio
async def test_git_push_then_pull_roundtrip(db_session, bare_and_ws):
    ws, bare = bare_and_ws

    tenant = Tenant(tenant_name="t_pp", tenant_code="t_pp"); db_session.add(tenant); await db_session.flush()
    user = User(username="pp_user", hashed_password="x"); db_session.add(user); await db_session.flush()
    ctx = _ctx(user, tenant.id)
    conn = await _seed_db(db_session, tenant, user, bare)

    # 先 connect(落 WorkspaceGitRemote)
    fake_meta = {"ws_id": "ws-pp", "tenant_id": tenant.id, "project_id": None, "user_id": user.id}
    body = GitConnectRequest(provider="gitlab", remote_url=str(bare), git_connection_id=conn.id)
    with patch("app.routes.coding.workspace_mgr.get_workspace_path", return_value=ws), \
         patch("app.coding.workspace_access.workspace_mgr.get_workspace_info", return_value=fake_meta), \
         patch("app.coding.workspace_access.workspace_mgr.get_workspace_path", return_value=ws):
        await git_connect_endpoint("ws-pp", body, ctx, db_session)

    # push
    with patch("app.routes.coding.workspace_mgr.get_workspace_path", return_value=ws), \
         patch("app.coding.workspace_access.workspace_mgr.get_workspace_info", return_value=fake_meta), \
         patch("app.coding.workspace_access.workspace_mgr.get_workspace_path", return_value=ws):
        push_result = await git_push_endpoint("ws-pp", ctx, db_session)

    assert push_result["ok"] is True
    assert "ahead" in push_result
    assert "behind" in push_result

    # 另一个 clone 推一笔新提交到 bare
    clone = ws.parent / "clone2"
    subprocess.run(["git", "clone", str(bare), str(clone)], check=True, capture_output=True)
    _run(clone, "config", "user.email", "t@t.com")
    _run(clone, "config", "user.name", "t")
    (clone / "b.txt").write_text("world")
    _run(clone, "add", ".")
    _run(clone, "commit", "-m", "c2")
    _run(clone, "push", "origin", "main")

    # pull — b.txt 应出现
    with patch("app.routes.coding.workspace_mgr.get_workspace_path", return_value=ws), \
         patch("app.coding.workspace_access.workspace_mgr.get_workspace_info", return_value=fake_meta), \
         patch("app.coding.workspace_access.workspace_mgr.get_workspace_path", return_value=ws):
        pull_result = await git_pull_endpoint("ws-pp", ctx, db_session)

    assert pull_result["ok"] is True
    assert (ws / "b.txt").exists()


@pytest.mark.asyncio
async def test_git_status_has_remote_and_ahead_behind(db_session, bare_and_ws):
    ws, bare = bare_and_ws

    tenant = Tenant(tenant_name="t_st", tenant_code="t_st"); db_session.add(tenant); await db_session.flush()
    user = User(username="st_user", hashed_password="x"); db_session.add(user); await db_session.flush()
    ctx = _ctx(user, tenant.id)
    conn = await _seed_db(db_session, tenant, user, bare)

    fake_meta = {"ws_id": "ws-st", "tenant_id": tenant.id, "project_id": None, "user_id": user.id}
    body = GitConnectRequest(provider="gitlab", remote_url=str(bare), git_connection_id=conn.id)

    with patch("app.routes.coding.workspace_mgr.get_workspace_path", return_value=ws), \
         patch("app.coding.workspace_access.workspace_mgr.get_workspace_info", return_value=fake_meta), \
         patch("app.coding.workspace_access.workspace_mgr.get_workspace_path", return_value=ws):
        await git_connect_endpoint("ws-st", body, ctx, db_session)
        # push 使 upstream 建立
        await git_push_endpoint("ws-st", ctx, db_session)
        status = await git_status_endpoint("ws-st", ctx, db_session)

    assert status["has_remote"] is True
    assert "ahead" in status
    assert "behind" in status
