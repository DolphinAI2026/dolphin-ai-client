import asyncio
import subprocess
from pathlib import Path

import pytest

from app.git.workspace_git import (
    current_branch, is_dirty, list_local_branches, checkout, status, GitError,
)


@pytest.fixture
def git_repo(tmp_path: Path) -> Path:
    """一个有 1 次提交、分支=main 的临时 git 仓。"""
    def run(*a):
        subprocess.run(["git", "-C", str(tmp_path), *a], check=True,
                       capture_output=True)
    run("init", "-b", "main")
    run("config", "user.email", "t@t.com")
    run("config", "user.name", "t")
    (tmp_path / "a.txt").write_text("hi")
    run("add", "a.txt")
    run("commit", "-m", "init")
    return tmp_path


@pytest.mark.asyncio
async def test_current_branch(git_repo):
    assert await current_branch(git_repo) == "main"


@pytest.mark.asyncio
async def test_is_dirty(git_repo):
    assert await is_dirty(git_repo) is False
    (git_repo / "a.txt").write_text("changed")
    assert await is_dirty(git_repo) is True


@pytest.mark.asyncio
async def test_list_and_checkout_create(git_repo):
    assert await list_local_branches(git_repo) == ["main"]
    await checkout(git_repo, "feature/x", create=True)
    assert await current_branch(git_repo) == "feature/x"
    assert set(await list_local_branches(git_repo)) == {"main", "feature/x"}
    # 切回已存在分支(create=False)
    await checkout(git_repo, "main", create=False)
    assert await current_branch(git_repo) == "main"


@pytest.mark.asyncio
async def test_checkout_missing_branch_raises(git_repo):
    with pytest.raises(GitError):
        await checkout(git_repo, "nope", create=False)


@pytest.mark.asyncio
async def test_status(git_repo):
    s = await status(git_repo)
    assert s == {"branch": "main", "dirty": False, "has_remote": False}
