import subprocess
from pathlib import Path
import pytest
from app.git.workspace_git import build_authed_url, push, pull, current_branch


def _run(cwd, *a):
    subprocess.run(["git", "-C", str(cwd), *a], check=True, capture_output=True)


def test_build_authed_url_gitlab():
    u = build_authed_url("gitlab", "https://git.co/g/p.git", "TOK")
    assert u == "https://oauth2:TOK@git.co/g/p.git"


def test_build_authed_url_github():
    u = build_authed_url("github", "https://gh.co/o/r.git", "TOK")
    assert u == "https://TOK@gh.co/o/r.git"


def test_build_authed_url_nonhttps():
    # ssh, file paths 等非 https 直接返回
    u = build_authed_url("github", "git@gh.co:o/r.git", "TOK")
    assert u == "git@gh.co:o/r.git"
    u2 = build_authed_url("gitlab", "/local/repo.git", "TOK")
    assert u2 == "/local/repo.git"


@pytest.fixture
def repo_and_remote(tmp_path):
    remote = tmp_path / "remote.git"
    subprocess.run(
        ["git", "init", "--bare", "-b", "main", str(remote)],
        check=True,
        capture_output=True,
    )
    ws = tmp_path / "ws"
    ws.mkdir()
    _run(ws, "init", "-b", "main")
    _run(ws, "config", "user.email", "t@t")
    _run(ws, "config", "user.name", "t")
    (ws / "a.txt").write_text("1")
    _run(ws, "add", ".")
    _run(ws, "commit", "-m", "c1")
    return ws, remote


@pytest.mark.asyncio
async def test_push_then_pull_roundtrip(repo_and_remote):
    ws, remote = repo_and_remote
    await push(ws, str(remote), "main")  # 本地 bare 路径当 authed_url
    # 另一个 clone 改一笔推回,验证 pull
    import subprocess as sp

    clone = ws.parent / "clone"
    sp.run(
        ["git", "clone", str(remote), str(clone)],
        check=True,
        capture_output=True,
    )
    _run(clone, "config", "user.email", "t@t")
    _run(clone, "config", "user.name", "t")
    (clone / "b.txt").write_text("2")
    _run(clone, "add", ".")
    _run(clone, "commit", "-m", "c2")
    _run(clone, "push", "origin", "main")
    await pull(ws, str(remote), "main")
    assert (ws / "b.txt").exists()
    assert await current_branch(ws) == "main"
