"""P3 Task 1 TDD — workspace_git.clone():git clone + 抹除 .git/config 里的 PAT。

本地 bare 仓当「远程」;authed_url 用带假 token 的本地路径形式无意义,
故直接用 bare 路径当 authed_url、另传一个 clean_url 验证 set-url 真的改了 origin。
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from app.git.workspace_git import (
    GitError,
    assert_https_remote,
    clone,
    current_branch,
    redact_credentials,
)


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


# ── 安全/正确性加固(P3 review 修复) ──────────────────────────

def test_redact_credentials_strips_pat_from_url():
    assert redact_credentials("git clone https://oauth2:SECRET_PAT@git.co/g/p.git 失败") \
        == "git clone https://***@git.co/g/p.git 失败"
    assert redact_credentials("https://TOKEN123@github.com/o/r.git") == "https://***@github.com/o/r.git"
    # 无凭证的 URL 原样保留
    assert redact_credentials("https://git.co/g/p.git") == "https://git.co/g/p.git"


@pytest.mark.asyncio
async def test_clone_failure_message_has_no_token(tmp_path: Path, monkeypatch):
    """clone 失败时,含 PAT 的 authed_url 不能出现在异常消息里。"""
    monkeypatch.delenv("ALLOW_INSECURE_GIT_REMOTE", raising=False)  # 不影响:这里直接调 clone
    from app.git.workspace_git import build_authed_url
    authed = build_authed_url("gitlab", "https://git.invalid.example/nope/nope.git", "SECRET_PAT_abc")
    with pytest.raises(GitError) as ei:
        await clone(tmp_path / "x", authed, "https://git.invalid.example/nope/nope.git")
    assert "SECRET_PAT_abc" not in str(ei.value)


def test_assert_https_remote_rejects_non_https_when_flag_off(monkeypatch):
    monkeypatch.delenv("ALLOW_INSECURE_GIT_REMOTE", raising=False)
    with pytest.raises(GitError):
        assert_https_remote("file:///etc/passwd-repo.git")
    with pytest.raises(GitError):
        assert_https_remote("/srv/workspaces/other-tenant.git")
    # https 始终放行
    assert_https_remote("https://git.example.com/g/p.git")  # no raise


def test_assert_https_remote_allows_local_when_flag_on(monkeypatch):
    monkeypatch.setenv("ALLOW_INSECURE_GIT_REMOTE", "1")
    assert_https_remote("/tmp/some/bare.git")  # no raise(测试放行)


@pytest.mark.asyncio
async def test_current_branch_empty_repo_returns_default(tmp_path: Path):
    """空仓(unborn branch)current_branch 不抛错,返回默认分支名。"""
    repo = tmp_path / "empty"
    repo.mkdir()
    subprocess.run(["git", "-C", str(repo), "init", "-b", "main"], check=True, capture_output=True)
    assert await current_branch(repo) == "main"
