"""P3 Task 1 TDD — workspace_git.clone():git clone + 抹除 .git/config 里的 PAT。

本地 bare 仓当「远程」;authed_url 用带假 token 的本地路径形式无意义,
故直接用 bare 路径当 authed_url、另传一个 clean_url 验证 set-url 真的改了 origin。
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from app.git.workspace_git import clone, current_branch


def _run(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(cwd), *args], check=True, capture_output=True, text=True
    ).stdout


@pytest.fixture
def bare_remote(tmp_path: Path) -> Path:
    """带一笔初始提交的 bare 仓(默认分支 main)。"""
    src = tmp_path / "src"
    src.mkdir()
    _run(src, "init", "-b", "main")
    _run(src, "config", "user.email", "t@t.com")
    _run(src, "config", "user.name", "t")
    (src / "README.md").write_text("hello clone")
    _run(src, "add", ".")
    _run(src, "commit", "-m", "init")
    bare = tmp_path / "remote.git"
    subprocess.run(["git", "clone", "--bare", str(src), str(bare)], check=True, capture_output=True)
    return bare


@pytest.mark.asyncio
async def test_clone_pulls_files_and_returns_branch(bare_remote: Path, tmp_path: Path):
    target = tmp_path / "ws_clone"
    branch = await clone(target, str(bare_remote), str(bare_remote))
    assert (target / "README.md").read_text() == "hello clone"
    assert branch == "main"
    assert await current_branch(target) == "main"


@pytest.mark.asyncio
async def test_clone_scrubs_token_resets_origin_to_clean_url(bare_remote: Path, tmp_path: Path):
    target = tmp_path / "ws_clone2"
    clean = "https://git.example.com/grp/proj.git"  # 模拟「不含 token 的对外 URL」
    # authed_url = 真能 clone 的 bare 路径(代表「含 PAT 的 URL」);clean_url = 落盘的对外 URL
    await clone(target, str(bare_remote), clean)
    origin = _run(target, "remote", "get-url", "origin").strip()
    assert origin == clean
    # 关键:authed_url 不能残留在 .git 任何文件里。git clone 会把来源 URL 写进
    # reflog(.git/logs/*),set-url 只改 config,不清 reflog → 不彻底清会泄 PAT。
    # 扫整个 .git 树确认 authed_url(本测=bare 路径)彻底消失。
    secret = str(bare_remote)
    leaked = []
    for f in (target / ".git").rglob("*"):
        if f.is_file():
            try:
                if secret in f.read_text(encoding="utf-8", errors="ignore"):
                    leaked.append(str(f.relative_to(target / ".git")))
            except OSError:
                pass
    assert leaked == [], f"authed_url 泄漏在: {leaked}"
