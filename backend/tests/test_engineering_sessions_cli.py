import json
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

BACKEND_ROOT = Path(__file__).resolve().parents[1]
CLI_SCRIPT = BACKEND_ROOT / "scripts" / "agentic_session.py"


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


def cli_command(
    repo: Path,
    registry: Path,
    worktrees: Path,
    *args: str,
) -> list[str]:
    return [
        sys.executable,
        str(CLI_SCRIPT),
        "--repo",
        str(repo),
        "--registry-root",
        str(registry),
        "--worktree-parent",
        str(worktrees),
        *args,
    ]


def test_cli_create_list_resume(tmp_path: Path):
    repo = make_repo(tmp_path)
    registry = tmp_path / "sessions"
    worktrees = tmp_path / "worktrees"

    create = subprocess.run(
        cli_command(
            repo,
            registry,
            worktrees,
            "create",
            "--type",
            "feature",
            "--title",
            "Fast new conversation",
        ),
        cwd=BACKEND_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    created = json.loads(create.stdout)

    assert created["id"] == "S-001"
    assert Path(created["worktree_path"]).exists()

    listed = subprocess.run(
        cli_command(
            repo,
            registry,
            worktrees,
            "list",
        ),
        cwd=BACKEND_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    data = json.loads(listed.stdout)

    assert data[0]["id"] == "S-001"


def test_cli_default_list_outputs_and_persists_static_missing_worktree(
    tmp_path: Path,
):
    repo = make_repo(tmp_path)
    registry = tmp_path / "sessions"
    worktrees = tmp_path / "worktrees"
    create = subprocess.run(
        cli_command(
            repo,
            registry,
            worktrees,
            "create",
            "--type",
            "new-app",
            "--title",
            "Required list",
        ),
        cwd=BACKEND_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    created = json.loads(create.stdout)
    registry_path = registry / f"{created['id']}.yaml"
    persisted = yaml.safe_load(registry_path.read_text(encoding="utf-8"))
    persisted["worktree_path"] = None
    persisted["status"] = "running"
    persisted["git_state"]["missing_worktree"] = False
    registry_path.write_text(
        yaml.safe_dump(persisted, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    run_git(repo, "remote", "add", "origin", str(tmp_path / "missing-origin.git"))

    listed = subprocess.run(
        cli_command(
            repo,
            registry,
            worktrees,
            "list",
        ),
        cwd=BACKEND_ROOT,
        capture_output=True,
        text=True,
    )

    assert listed.returncode == 0, listed.stderr
    data = json.loads(listed.stdout)
    assert data[0]["status"] == "missing_worktree"
    assert data[0]["git_state"]["missing_worktree"] is True
    saved = yaml.safe_load(registry_path.read_text(encoding="utf-8"))
    assert saved["status"] == "missing_worktree"
    assert saved["git_state"]["missing_worktree"] is True


@pytest.mark.parametrize("session_type", ["new-app", "spec-change"])
def test_cli_rejects_required_session_type_without_worktree(
    tmp_path: Path,
    session_type: str,
):
    repo = make_repo(tmp_path)
    registry = tmp_path / "sessions"
    worktrees = tmp_path / "worktrees"

    result = subprocess.run(
        cli_command(
            repo,
            registry,
            worktrees,
            "create",
            "--type",
            session_type,
            "--title",
            "Required worktree",
            "--no-worktree",
        ),
        cwd=BACKEND_ROOT,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 2
    assert result.stdout == ""
    assert "requires a worktree" in result.stderr
    assert not list(registry.glob("S-*.yaml"))


def test_cli_concurrent_no_worktree_creates_use_process_lock(tmp_path: Path):
    repo = make_repo(tmp_path)
    registry = tmp_path / "sessions"
    worktrees = tmp_path / "worktrees"
    processes = [
        subprocess.Popen(
            cli_command(
                repo,
                registry,
                worktrees,
                "create",
                "--type",
                "review",
                "--title",
                f"Concurrent review {index}",
                "--no-worktree",
            ),
            cwd=BACKEND_ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        for index in range(4)
    ]

    outputs = []
    for process in processes:
        stdout, stderr = process.communicate(timeout=15)
        assert process.returncode == 0, stderr
        outputs.append(json.loads(stdout))

    assert sorted(item["id"] for item in outputs) == [
        "S-001",
        "S-002",
        "S-003",
        "S-004",
    ]
    assert sorted(path.name for path in registry.glob("S-*.yaml")) == [
        "S-001.yaml",
        "S-002.yaml",
        "S-003.yaml",
        "S-004.yaml",
    ]
    assert not list(registry.glob("*.tmp"))
    assert not list(registry.glob(".*.tmp"))
