import json
import subprocess
import sys
from pathlib import Path

import pytest


def run_git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def make_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    run_git(repo, "init", "-b", "main")
    run_git(repo, "config", "user.email", "t@example.com")
    run_git(repo, "config", "user.name", "Tester")
    (repo / "README.md").write_text("base\n", encoding="utf-8")
    run_git(repo, "add", "README.md")
    run_git(repo, "commit", "-m", "base")
    return repo


def test_cli_create_list_resume(tmp_path: Path):
    repo = make_repo(tmp_path)
    registry = tmp_path / "sessions"
    worktrees = tmp_path / "worktrees"

    create = subprocess.run(
        [
            sys.executable,
            "-m",
            "app.engineering_sessions.cli",
            "--repo",
            str(repo),
            "--registry-root",
            str(registry),
            "--worktree-parent",
            str(worktrees),
            "create",
            "--type",
            "feature",
            "--title",
            "Fast new conversation",
        ],
        cwd=Path(__file__).resolve().parents[1],
        check=True,
        capture_output=True,
        text=True,
    )
    created = json.loads(create.stdout)

    assert created["id"] == "S-001"
    assert Path(created["worktree_path"]).exists()

    listed = subprocess.run(
        [
            sys.executable,
            "-m",
            "app.engineering_sessions.cli",
            "--repo",
            str(repo),
            "--registry-root",
            str(registry),
            "--worktree-parent",
            str(worktrees),
            "list",
        ],
        cwd=Path(__file__).resolve().parents[1],
        check=True,
        capture_output=True,
        text=True,
    )
    data = json.loads(listed.stdout)

    assert data[0]["id"] == "S-001"


@pytest.mark.parametrize("session_type", ["new-app", "spec-change"])
def test_cli_rejects_required_session_type_without_worktree(
    tmp_path: Path,
    session_type: str,
):
    repo = make_repo(tmp_path)
    registry = tmp_path / "sessions"
    worktrees = tmp_path / "worktrees"

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "app.engineering_sessions.cli",
            "--repo",
            str(repo),
            "--registry-root",
            str(registry),
            "--worktree-parent",
            str(worktrees),
            "create",
            "--type",
            session_type,
            "--title",
            "Required worktree",
            "--no-worktree",
        ],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
    )

    assert result.returncode == 2
    assert result.stdout == ""
    assert "requires a worktree" in result.stderr
    assert not list(registry.glob("S-*.yaml"))
