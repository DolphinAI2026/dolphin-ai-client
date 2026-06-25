"""P3 Task 2 — WorkspaceManager clone 辅助:分配目标路径 + 写 meta。"""
from __future__ import annotations

import subprocess
from pathlib import Path

from app.coding import workspace as ws_mod
from app.coding.workspace import WorkspaceManager


def _git(cwd: Path, *a: str) -> None:
    subprocess.run(["git", "-C", str(cwd), *a], check=True, capture_output=True)


def test_prepare_then_register_clone_workspace(tmp_path: Path, monkeypatch):
    # 把 WORKSPACE_ROOT 指到 tmp,避免污染真实工作区根
    monkeypatch.setattr(ws_mod, "WORKSPACE_ROOT", tmp_path / "workspaces")
    (tmp_path / "workspaces").mkdir()
    monkeypatch.setattr(ws_mod, "WORKSPACE_SEARCH_ROOTS", [tmp_path / "workspaces"])

    mgr = WorkspaceManager()
    ws_id, ws_path = mgr.prepare_clone_target(project_name="acme-crm", user_id=7)
    assert ws_id.startswith("7_")
    assert not ws_path.exists()  # 还没建,留给 clone

    # 模拟 clone 出一个真 git 仓(register 前 ws_path 必须已是带内容的目录)
    ws_path.mkdir(parents=True)
    _git(ws_path, "init", "-b", "main")
    _git(ws_path, "config", "user.email", "t@t.com")
    _git(ws_path, "config", "user.name", "t")
    (ws_path / "app.js").write_text("x")
    _git(ws_path, "add", ".")
    _git(ws_path, "commit", "-m", "c1")

    meta = mgr.register_cloned_workspace(
        ws_id, ws_path, project_name="acme-crm", display_name="Acme CRM",
        user_id=7, tenant_id=3, project_id=None, remote_url="https://git.co/g/acme.git",
    )
    assert meta["id"] == ws_id
    assert meta["project_type"] == "git-clone"
    assert meta["display_name"] == "Acme CRM"
    # .workspace.json 落盘且含 tenant_id/user_id(否则 list_accessible_workspaces 会隐藏)
    import json
    saved = json.loads((ws_path / ".workspace.json").read_text())
    assert saved["tenant_id"] == 3 and saved["user_id"] == 7
    assert saved["cloned_from"] == "https://git.co/g/acme.git"
    # 能被可访问工作区列表查到
    listed = mgr.list_accessible_workspaces(user_id=7, tenant_id=3)
    assert any(w["id"] == ws_id for w in listed)
