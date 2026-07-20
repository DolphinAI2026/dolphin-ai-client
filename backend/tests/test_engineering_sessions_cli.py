import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

import app.engineering_sessions.cli as engineering_session_cli

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


def test_cli_linked_worktree_repo_sync_resume_and_checkpoint_target_only(
    tmp_path: Path,
):
    repo = make_repo(tmp_path)
    registry = tmp_path / "sessions"
    worktrees = tmp_path / "worktrees"
    created_result = subprocess.run(
        cli_command(
            repo,
            registry,
            worktrees,
            "create",
            "--type",
            "feature",
            "--title",
            "Linked invocation",
        ),
        cwd=BACKEND_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    created = json.loads(created_result.stdout)
    session_worktree = Path(created["worktree_path"])
    nested = session_worktree / "backend"
    nested.mkdir()
    (session_worktree / "linked-change.txt").write_text(
        "checkpoint me\n",
        encoding="utf-8",
    )
    main_head = run_git(repo, "rev-parse", "HEAD")
    session_head = run_git(session_worktree, "rev-parse", "HEAD")

    sync_result = subprocess.run(
        cli_command(
            nested,
            registry,
            worktrees,
            "sync",
            created["id"],
        ),
        cwd=BACKEND_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    synced = json.loads(sync_result.stdout)
    assert synced["status"] == "running"
    assert synced["git_state"]["missing_worktree"] is False

    resume_result = subprocess.run(
        cli_command(
            nested,
            registry,
            worktrees,
            "resume",
            created["id"],
        ),
        cwd=BACKEND_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    resumed = json.loads(resume_result.stdout)
    assert resumed["status"] == "running"
    assert resumed["git_state"]["missing_worktree"] is False

    checkpoint_result = subprocess.run(
        cli_command(
            nested,
            registry,
            worktrees,
            "checkpoint",
            created["id"],
        ),
        cwd=BACKEND_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )

    assert json.loads(checkpoint_result.stdout) == {"created": True}
    assert run_git(repo, "rev-parse", "HEAD") == main_head
    assert run_git(session_worktree, "rev-parse", "HEAD") != session_head
    assert run_git(session_worktree, "status", "--porcelain") == ""


def test_cli_checkpoint_commit_failure_exits_nonzero(tmp_path: Path):
    repo = make_repo(tmp_path)
    registry = tmp_path / "sessions"
    worktrees = tmp_path / "worktrees"
    created_result = subprocess.run(
        cli_command(
            repo,
            registry,
            worktrees,
            "create",
            "--type",
            "feature",
            "--title",
            "CLI commit failure",
        ),
        cwd=BACKEND_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    created = json.loads(created_result.stdout)
    worktree = Path(created["worktree_path"])
    (worktree / "invalid-date.txt").write_text("dirty\n", encoding="utf-8")
    before_head = run_git(worktree, "rev-parse", "HEAD")
    env = os.environ.copy()
    env["GIT_AUTHOR_DATE"] = "not-a-valid-git-date"

    checkpoint_result = subprocess.run(
        cli_command(
            repo,
            registry,
            worktrees,
            "checkpoint",
            created["id"],
        ),
        cwd=BACKEND_ROOT,
        capture_output=True,
        text=True,
        env=env,
    )

    assert checkpoint_result.returncode != 0
    assert "git commit failed" in checkpoint_result.stderr
    assert "invalid date" in checkpoint_result.stderr
    assert run_git(worktree, "rev-parse", "HEAD") == before_head


def test_cli_runtime_error_uses_stable_json_without_traceback(tmp_path: Path):
    repo = make_repo(tmp_path)
    result = subprocess.run(
        cli_command(
            repo,
            tmp_path / "sessions",
            tmp_path / "worktrees",
            "resume",
            "S-999",
        ),
        cwd=BACKEND_ROOT,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 1
    assert result.stdout == ""
    error = json.loads(result.stderr)
    assert error["error"]["code"] == "session_not_found"
    assert "S-999" in error["error"]["message"]
    assert "Traceback" not in result.stderr


def test_cli_argument_error_uses_stable_json(tmp_path: Path):
    repo = make_repo(tmp_path)
    result = subprocess.run(
        cli_command(
            repo,
            tmp_path / "sessions",
            tmp_path / "worktrees",
            "create",
            "--type",
            "feature",
        ),
        cwd=BACKEND_ROOT,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 2
    assert result.stdout == ""
    error = json.loads(result.stderr)
    assert error["error"]["code"] == "invalid_arguments"
    assert "--title" in error["error"]["message"]


def test_cli_error_includes_recovery_notes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    repo = make_repo(tmp_path)
    error = RuntimeError("registry save failed")
    error.add_note("retained worktree; run reconcile")

    class FailingService:
        def __init__(self, *_args, **_kwargs):
            raise error

    monkeypatch.setattr(
        engineering_session_cli,
        "EngineeringSessionService",
        FailingService,
    )

    result = engineering_session_cli.main(
        [
            "--repo",
            str(repo),
            "list",
        ]
    )

    captured = capsys.readouterr()
    assert result == 1
    payload = json.loads(captured.err)
    assert payload["error"]["details"] == [
        "retained worktree; run reconcile"
    ]


def test_cli_list_reports_corrupt_registry_records_as_json_warnings(
    tmp_path: Path,
):
    repo = make_repo(tmp_path)
    registry = tmp_path / "sessions"
    worktrees = tmp_path / "worktrees"
    for title in ("First", "Second"):
        subprocess.run(
            cli_command(
                repo,
                registry,
                worktrees,
                "create",
                "--type",
                "review",
                "--title",
                title,
                "--no-worktree",
            ),
            cwd=BACKEND_ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
    (registry / "S-001.yaml").write_text("id: [broken\n", encoding="utf-8")

    result = subprocess.run(
        cli_command(repo, registry, worktrees, "list"),
        cwd=BACKEND_ROOT,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert [item["id"] for item in json.loads(result.stdout)] == ["S-002"]
    warning = json.loads(result.stderr)
    assert len(warning["warnings"]) == 1
    assert "S-001" in warning["warnings"][0]


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


def test_cli_default_list_persists_static_base_missing_cleanup_without_git_scan(
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
            "feature",
            "--title",
            "Static cleanup list",
        ),
        cwd=BACKEND_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    created = json.loads(create.stdout)
    registry_path = registry / f"{created['id']}.yaml"
    persisted = yaml.safe_load(registry_path.read_text(encoding="utf-8"))
    persisted["status"] = "merged_retained"
    persisted["git_state"]["base_missing"] = True
    persisted["cleanup"]["suggested"] = True
    registry_path.write_text(
        yaml.safe_dump(persisted, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    run_git(repo, "remote", "add", "origin", str(tmp_path / "missing-origin.git"))

    real_git = shutil.which("git")
    assert real_git is not None
    wrapper_dir = tmp_path / "git-wrapper"
    wrapper_dir.mkdir()
    wrapper = wrapper_dir / "git"
    wrapper.write_text(
        "#!/bin/sh\n"
        'case " $* " in\n'
        '  *" fetch "*|*" worktree "*) exit 97 ;;\n'
        "esac\n"
        'exec "$REAL_GIT" "$@"\n',
        encoding="utf-8",
    )
    wrapper.chmod(0o755)
    env = os.environ.copy()
    env["PATH"] = f"{wrapper_dir}{os.pathsep}{env['PATH']}"
    env["REAL_GIT"] = real_git

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
        env=env,
    )

    assert listed.returncode == 0, listed.stderr
    data = json.loads(listed.stdout)
    assert data[0]["status"] == "merged_retained"
    assert data[0]["git_state"]["base_missing"] is True
    assert data[0]["cleanup"]["suggested"] is False
    saved = yaml.safe_load(registry_path.read_text(encoding="utf-8"))
    assert saved["status"] == "merged_retained"
    assert saved["git_state"]["base_missing"] is True
    assert saved["cleanup"]["suggested"] is False


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


def test_cli_merge_keeps_worktree_and_dispose_removes_it(tmp_path: Path):
    repo = make_repo(tmp_path)
    registry = tmp_path / "sessions"
    worktrees = tmp_path / "worktrees"
    created_result = subprocess.run(
        cli_command(
            repo,
            registry,
            worktrees,
            "create",
            "--type",
            "new-app",
            "--title",
            "App One",
        ),
        cwd=BACKEND_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    created = json.loads(created_result.stdout)
    worktree = Path(created["worktree_path"])
    (worktree / "feature.txt").write_text("done\n", encoding="utf-8")
    subprocess.run(
        cli_command(
            repo,
            registry,
            worktrees,
            "checkpoint",
            created["id"],
        ),
        cwd=BACKEND_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )

    merged_result = subprocess.run(
        cli_command(repo, registry, worktrees, "merge", created["id"]),
        cwd=BACKEND_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )

    assert json.loads(merged_result.stdout)["status"] == "merged_retained"
    assert worktree.exists()

    disposed_result = subprocess.run(
        cli_command(repo, registry, worktrees, "dispose", created["id"]),
        cwd=BACKEND_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )

    assert json.loads(disposed_result.stdout) is None
    assert not worktree.exists()
    assert run_git(repo, "branch", "--list", created["branch"]) == ""


def test_cli_merge_conflict_uses_worktree_merge_conflict_error_code(
    tmp_path: Path,
):
    repo = make_repo(tmp_path)
    registry = tmp_path / "sessions"
    worktrees = tmp_path / "worktrees"
    created_result = subprocess.run(
        cli_command(
            repo,
            registry,
            worktrees,
            "create",
            "--type",
            "new-app",
            "--title",
            "App One",
        ),
        cwd=BACKEND_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    created = json.loads(created_result.stdout)
    worktree = Path(created["worktree_path"])
    (worktree / "README.md").write_text("session change\n", encoding="utf-8")
    subprocess.run(
        cli_command(
            repo,
            registry,
            worktrees,
            "checkpoint",
            created["id"],
        ),
        cwd=BACKEND_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    (repo / "README.md").write_text("base change\n", encoding="utf-8")
    run_git(repo, "add", "README.md")
    run_git(repo, "commit", "-m", "base conflict")

    result = subprocess.run(
        cli_command(repo, registry, worktrees, "merge", created["id"]),
        cwd=BACKEND_ROOT,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 1
    assert json.loads(result.stderr)["error"]["code"] == "WORKTREE_MERGE_CONFLICT"
    assert worktree.exists()
    assert run_git(worktree, "branch", "--show-current") == created["branch"]
