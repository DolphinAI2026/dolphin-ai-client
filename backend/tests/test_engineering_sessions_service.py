import os
import shutil
import stat
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path
from threading import Event

import pytest
import yaml

import app.engineering_sessions as engineering_sessions
import app.engineering_sessions.git_state as engineering_session_git_state
import app.engineering_sessions.service as engineering_session_service
from app.engineering_sessions.git_state import GitCommandError
from app.engineering_sessions.models import SessionStatus, SessionType
from app.engineering_sessions.registry import SessionRegistry
from app.engineering_sessions.service import EngineeringSessionService

_SYNCING_ENTRYPOINTS = (
    "sync",
    "list",
    "checkpoint",
    "archive",
    "reconcile",
    "resume",
)


def run_git(repo: Path, *args: str) -> str:
    result = subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True)
    return result.stdout.strip()


def make_repo(tmp_path: Path, name: str = "repo") -> Path:
    repo = tmp_path / name
    repo.mkdir()
    run_git(repo, "init", "-b", "main")
    run_git(repo, "config", "user.email", "t@example.com")
    run_git(repo, "config", "user.name", "Tester")
    (repo / "README.md").write_text("base\n", encoding="utf-8")
    run_git(repo, "add", "README.md")
    run_git(repo, "commit", "-m", "base")
    return repo


def make_service(tmp_path: Path, repo: Path) -> EngineeringSessionService:
    return EngineeringSessionService(
        repo,
        registry_root=tmp_path / "sessions",
        worktree_parent=tmp_path / "worktrees",
    )


def add_origin(repo: Path, tmp_path: Path) -> Path:
    origin = tmp_path / "origin.git"
    origin.mkdir()
    run_git(origin, "init", "--bare", "-b", "main")
    run_git(repo, "remote", "add", "origin", str(origin))
    run_git(repo, "push", "-u", "origin", "main")
    return origin


def invoke_syncing_entrypoint(
    service: EngineeringSessionService,
    session_id: str,
    entrypoint: str,
):
    if entrypoint == "sync":
        return service.sync(session_id)
    if entrypoint == "list":
        return next(item for item in service.list(sync=True) if item.id == session_id)
    if entrypoint == "checkpoint":
        assert service.checkpoint(session_id) is False
        return service.registry.load(session_id)
    if entrypoint == "archive":
        return service.archive(session_id)
    if entrypoint == "reconcile":
        return next(item for item in service.reconcile() if item.id == session_id)
    if entrypoint == "resume":
        return service.resume(session_id)
    raise AssertionError(f"unknown entrypoint: {entrypoint}")


def test_create_builds_registry_and_worktree(tmp_path: Path):
    repo = make_repo(tmp_path)
    service = make_service(tmp_path, repo)

    session = service.create(SessionType.FEATURE, "Worktree sync")

    worktree = Path(session.worktree_path)
    loaded = service.registry.load(session.id)
    assert session.id == "S-001"
    assert worktree.exists()
    assert run_git(worktree, "branch", "--show-current") == session.branch
    assert loaded.branch == session.branch
    assert loaded.status == SessionStatus.RUNNING
    assert loaded.git_state.merged_to_base is False


def test_ensure_application_session_reuses_the_same_worktree(tmp_path: Path):
    repo = make_repo(tmp_path)
    service = make_service(tmp_path, repo)

    first = service.ensure_application_session("app-1", "App One")
    second = service.ensure_application_session("app-1", "App One")

    assert first.id == second.id
    assert first.application_id == "app-1"
    assert first.worktree_path == second.worktree_path


def test_ensure_application_session_is_unique_across_concurrent_services(
    tmp_path: Path,
):
    repo = make_repo(tmp_path)
    registry_root = tmp_path / "sessions"
    worktree_parent = tmp_path / "worktrees"
    first_service = EngineeringSessionService(
        repo,
        registry_root=registry_root,
        worktree_parent=worktree_parent,
    )
    second_service = EngineeringSessionService(
        repo,
        registry_root=registry_root,
        worktree_parent=worktree_parent,
    )

    with ThreadPoolExecutor(max_workers=2) as executor:
        first, second = [
            future.result()
            for future in (
                executor.submit(
                    service.ensure_application_session,
                    "app-1",
                    "App One",
                )
                for service in (first_service, second_service)
            )
        ]

    assert first.id == second.id
    assert [item.id for item in first_service.registry.list()] == [first.id]
    assert Path(first.worktree_path).exists()


def test_ensure_application_session_rejects_duplicate_active_ownership(
    tmp_path: Path,
):
    repo = make_repo(tmp_path)
    service = make_service(tmp_path, repo)
    first = service.create(SessionType.NEW_APP, "First app")
    second = service.create(SessionType.NEW_APP, "Second app")
    first.application_id = "app-1"
    second.application_id = "app-1"
    service.registry.save(first)
    service.registry.save(second)

    with pytest.raises(
        ValueError,
        match="multiple active sessions claim application: app-1",
    ):
        service.ensure_application_session("app-1", "App One")


def test_ensure_application_session_rejects_blank_application_id(tmp_path: Path):
    repo = make_repo(tmp_path)
    service = make_service(tmp_path, repo)

    with pytest.raises(ValueError, match="application_id must not be blank"):
        service.ensure_application_session("  ", "App One")


def test_merge_keeps_worktree_and_marks_merged_retained(tmp_path: Path):
    repo = make_repo(tmp_path)
    service = make_service(tmp_path, repo)
    session = service.ensure_application_session("app-1", "App One")
    Path(session.worktree_path, "feature.txt").write_text(
        "done\n",
        encoding="utf-8",
    )
    assert service.checkpoint(session.id, "feat: local runtime change") is True

    merged = service.merge(session.id)

    assert merged.status == SessionStatus.MERGED_RETAINED
    assert Path(merged.worktree_path).exists()
    assert merged.merged_commit == run_git(repo, "rev-parse", "HEAD")


def test_merge_conflict_aborts_and_retains_session_worktree(tmp_path: Path):
    repo = make_repo(tmp_path)
    service = make_service(tmp_path, repo)
    session = service.ensure_application_session("app-1", "App One")
    worktree = Path(session.worktree_path)
    (worktree / "README.md").write_text("session change\n", encoding="utf-8")
    assert service.checkpoint(session.id, "feat: conflicting session change") is True
    (repo / "README.md").write_text("base change\n", encoding="utf-8")
    run_git(repo, "add", "README.md")
    run_git(repo, "commit", "-m", "base conflict")

    with pytest.raises(ValueError, match="WORKTREE_MERGE_CONFLICT"):
        service.merge(session.id)

    assert worktree.exists()
    assert run_git(worktree, "branch", "--show-current") == session.branch
    assert run_git(repo, "status", "--porcelain") == ""


def test_dispose_refuses_dirty_or_unmerged_session(tmp_path: Path):
    repo = make_repo(tmp_path)
    service = make_service(tmp_path, repo)
    session = service.ensure_application_session("app-1", "App One")
    Path(session.worktree_path, "dirty.txt").write_text("dirty", encoding="utf-8")

    with pytest.raises(ValueError, match="clean and merged"):
        service.dispose(session.id)


def test_dispose_removes_clean_merged_retained_worktree_and_branch(
    tmp_path: Path,
):
    repo = make_repo(tmp_path)
    service = make_service(tmp_path, repo)
    session = service.ensure_application_session("app-1", "App One")
    worktree = Path(session.worktree_path)
    (worktree / "feature.txt").write_text("done\n", encoding="utf-8")
    assert service.checkpoint(session.id) is True
    service.merge(session.id)

    service.dispose(session.id)

    assert not worktree.exists()
    assert run_git(repo, "branch", "--list", session.branch) == ""


def test_create_uses_explicit_base_branch_head(tmp_path: Path):
    repo = make_repo(tmp_path)
    run_git(repo, "checkout", "-b", "release")
    (repo / "release.txt").write_text("release\n", encoding="utf-8")
    run_git(repo, "add", "release.txt")
    run_git(repo, "commit", "-m", "release")
    release_head = run_git(repo, "rev-parse", "HEAD")
    run_git(repo, "checkout", "main")
    (repo / "main.txt").write_text("main\n", encoding="utf-8")
    run_git(repo, "add", "main.txt")
    run_git(repo, "commit", "-m", "main")
    service = make_service(tmp_path, repo)

    session = service.create(SessionType.FEATURE, "Release work", base_branch="release")

    worktree = Path(session.worktree_path)
    assert session.base_commit == release_head
    assert run_git(worktree, "rev-parse", "HEAD") == release_head
    assert session.status == SessionStatus.RUNNING
    assert session.git_state.merged_to_base is False


def test_create_uses_remote_default_head_when_local_default_is_stale(
    tmp_path: Path,
):
    repo = make_repo(tmp_path)
    origin = add_origin(repo, tmp_path)
    other = tmp_path / "other"
    subprocess.run(
        ["git", "clone", str(origin), str(other)],
        check=True,
        capture_output=True,
        text=True,
    )
    run_git(other, "config", "user.email", "other@example.com")
    run_git(other, "config", "user.name", "Other")
    (other / "remote.txt").write_text("remote\n", encoding="utf-8")
    run_git(other, "add", "remote.txt")
    run_git(other, "commit", "-m", "advance remote main")
    run_git(other, "push", "origin", "main")
    local_main = run_git(repo, "rev-parse", "main")

    session = make_service(tmp_path, repo).create(
        SessionType.FEATURE,
        "Fresh remote base",
    )

    remote_main = run_git(repo, "rev-parse", "origin/main")
    worktree = Path(session.worktree_path)
    assert remote_main != local_main
    assert session.base_branch == "main"
    assert session.base_commit == remote_main
    assert run_git(worktree, "rev-parse", "HEAD") == remote_main
    assert session.git_state.behind == 0
    assert session.git_state.stale is False


def test_create_defaults_to_origin_head_instead_of_control_or_linked_branch(
    tmp_path: Path,
):
    repo = make_repo(tmp_path)
    add_origin(repo, tmp_path)
    linked = tmp_path / "linked"
    run_git(repo, "worktree", "add", "-b", "release", str(linked), "main")
    (linked / "release.txt").write_text("release\n", encoding="utf-8")
    run_git(linked, "add", "release.txt")
    run_git(linked, "commit", "-m", "release")
    run_git(repo, "checkout", "-b", "integration")
    (repo / "integration.txt").write_text("integration\n", encoding="utf-8")
    run_git(repo, "add", "integration.txt")
    run_git(repo, "commit", "-m", "integration")

    session = EngineeringSessionService(
        linked,
        registry_root=tmp_path / "sessions",
        worktree_parent=tmp_path / "worktrees",
    ).create(SessionType.FEATURE, "Default base")

    assert session.base_branch == "main"
    assert session.base_commit == run_git(repo, "rev-parse", "origin/main")
    assert run_git(Path(session.worktree_path), "rev-parse", "HEAD") == session.base_commit


def test_create_discovers_nonstandard_remote_default_branch(tmp_path: Path):
    repo = make_repo(tmp_path)
    origin = tmp_path / "origin.git"
    origin.mkdir()
    run_git(origin, "init", "--bare", "-b", "develop")
    run_git(repo, "remote", "add", "origin", str(origin))
    run_git(repo, "push", "origin", "main:develop")
    assert (
        subprocess.run(
            [
                "git",
                "-C",
                str(repo),
                "symbolic-ref",
                "--quiet",
                "refs/remotes/origin/HEAD",
            ],
            capture_output=True,
            text=True,
        ).returncode
        != 0
    )

    session = make_service(tmp_path, repo).create(
        SessionType.FEATURE,
        "Develop default",
    )

    assert session.base_branch == "develop"
    assert session.base_commit == run_git(repo, "rev-parse", "origin/develop")


def test_create_fails_when_remote_default_head_cannot_be_discovered(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    repo = make_repo(tmp_path)
    origin = tmp_path / "origin.git"
    origin.mkdir()
    run_git(origin, "init", "--bare", "-b", "develop")
    run_git(repo, "remote", "add", "origin", str(origin))
    run_git(repo, "push", "origin", "main:develop")
    service = make_service(tmp_path, repo)
    original_git = engineering_session_git_state.git

    def fail_set_head(repo_path: str | Path, *args: str, **kwargs):
        if args == ("remote", "set-head", "origin", "--auto"):
            return subprocess.CompletedProcess(
                ["git", *args],
                1,
                "",
                "cannot determine remote HEAD",
            )
        return original_git(repo_path, *args, **kwargs)

    monkeypatch.setattr(engineering_session_git_state, "git", fail_set_head)

    with pytest.raises(GitCommandError, match="origin/HEAD"):
        service.create(SessionType.FEATURE, "Unknown remote default")

    assert service.registry.list() == []
    assert run_git(repo, "branch", "--list", "session/*") == ""


def test_create_refreshes_stale_origin_head_when_remote_default_changes(
    tmp_path: Path,
):
    repo = make_repo(tmp_path)
    origin = add_origin(repo, tmp_path)
    run_git(repo, "remote", "set-head", "origin", "main")
    run_git(origin, "symbolic-ref", "HEAD", "refs/heads/develop")
    run_git(repo, "push", "origin", "main:develop")

    session = make_service(tmp_path, repo).create(
        SessionType.FEATURE,
        "Changed remote default",
    )

    assert session.base_branch == "develop"
    assert session.base_commit == run_git(repo, "rev-parse", "origin/develop")


def test_create_captures_base_commit_after_acquiring_registry_lock(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    repo = make_repo(tmp_path)
    service = make_service(tmp_path, repo)
    captured_base_commit = run_git(repo, "rev-parse", "main")
    original_transaction_lock = service.registry.transaction_lock

    @contextmanager
    def advancing_transaction_lock():
        with original_transaction_lock():
            (repo / "advanced.txt").write_text("advanced\n", encoding="utf-8")
            run_git(repo, "add", "advanced.txt")
            run_git(repo, "commit", "-m", "advance main")
            yield

    monkeypatch.setattr(
        service.registry,
        "transaction_lock",
        advancing_transaction_lock,
    )

    session = service.create(SessionType.FEATURE, "Captured base")

    worktree = Path(session.worktree_path)
    advanced_base_commit = run_git(repo, "rev-parse", "main")
    assert advanced_base_commit != captured_base_commit
    assert session.base_commit == advanced_base_commit
    assert run_git(worktree, "rev-parse", "HEAD") == advanced_base_commit
    assert session.status == SessionStatus.RUNNING
    assert session.git_state.merged_to_base is False


def test_create_rejects_existing_worktree_owned_by_other_repo(tmp_path: Path):
    first_root = tmp_path / "first"
    first_root.mkdir()
    first_repo = make_repo(first_root)
    second_root = tmp_path / "second"
    second_root.mkdir()
    second_repo = make_repo(second_root)
    worktree_parent = tmp_path / "shared-worktrees"
    first_service = EngineeringSessionService(
        first_repo,
        registry_root=tmp_path / "first-sessions",
        worktree_parent=worktree_parent,
    )
    second_service = EngineeringSessionService(
        second_repo,
        registry_root=tmp_path / "second-sessions",
        worktree_parent=worktree_parent,
    )
    first_session = first_service.create(SessionType.FEATURE, "Shared path")
    first_worktree = Path(first_session.worktree_path)
    first_branch = run_git(first_worktree, "branch", "--show-current")
    first_head = run_git(first_worktree, "rev-parse", "HEAD")

    with pytest.raises(ValueError, match="does not belong"):
        second_service.create(SessionType.FEATURE, "Shared path")

    assert second_service.registry.list() == []
    assert not list(second_service.registry.root.glob("S-*.yaml"))
    assert run_git(second_repo, "branch", "--list", "session/*") == ""
    assert run_git(first_worktree, "branch", "--show-current") == first_branch
    assert run_git(first_worktree, "rev-parse", "HEAD") == first_head


def test_create_does_not_adopt_orphaned_session_branch_or_worktree(
    tmp_path: Path,
):
    repo = make_repo(tmp_path)
    service = make_service(tmp_path, repo)
    first = service.create(SessionType.FEATURE, "旧任务")
    first_worktree = Path(first.worktree_path)
    (first_worktree / "old-dirty.txt").write_text("old\n", encoding="utf-8")
    service.registry.path_for(first.id).unlink()

    second = make_service(tmp_path, repo).create(SessionType.FEATURE, "新任务")

    assert second.id == "S-002"
    assert second.branch != first.branch
    assert second.worktree_path != first.worktree_path
    assert Path(second.worktree_path).exists()
    assert (first_worktree / "old-dirty.txt").exists()
    assert run_git(first_worktree, "status", "--porcelain")


def test_create_rolls_back_branch_and_worktree_when_git_add_fails(
    tmp_path: Path,
):
    repo = make_repo(tmp_path)
    hook = repo / ".git" / "hooks" / "post-checkout"
    hook.write_text("#!/bin/sh\nexit 23\n", encoding="utf-8")
    hook.chmod(0o755)
    service = make_service(tmp_path, repo)
    branch = "session/S-001-feature-hook-failure"
    worktree = service.worktree_parent / branch.replace("/", "-")

    with pytest.raises(GitCommandError, match="git worktree add"):
        service.create(SessionType.FEATURE, "Hook failure")

    assert service.registry.list() == []
    assert run_git(repo, "branch", "--list", branch)
    assert not worktree.exists()
    assert str(worktree) not in run_git(repo, "worktree", "list", "--porcelain")
    assert run_git(
        repo,
        "rev-parse",
        "--verify",
        "refs/agentic/sessions/S-001",
    )


def test_failed_worktree_add_rollback_does_not_delete_advanced_branch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    repo = make_repo(tmp_path)
    run_git(repo, "checkout", "-b", "advanced-source")
    (repo / "advanced.txt").write_text("advanced\n", encoding="utf-8")
    run_git(repo, "add", "advanced.txt")
    run_git(repo, "commit", "-m", "advanced")
    advanced_commit = run_git(repo, "rev-parse", "HEAD")
    run_git(repo, "checkout", "main")
    service = make_service(tmp_path, repo)
    branch = "session/S-001-feature-advanced-rollback"
    original_git = engineering_session_service.git
    delete_attempted = False

    def race_branch_delete(repo_path: str | Path, *args: str, **kwargs):
        nonlocal delete_attempted
        if args[:2] == ("worktree", "add"):
            raise GitCommandError("git worktree add failed")
        if args[:3] == ("branch", "-D", branch):
            delete_attempted = True
            run_git(repo, "update-ref", f"refs/heads/{branch}", advanced_commit)
        return original_git(repo_path, *args, **kwargs)

    monkeypatch.setattr(
        engineering_session_service,
        "git",
        race_branch_delete,
    )

    with pytest.raises(GitCommandError, match="worktree add failed"):
        service.create(SessionType.FEATURE, "Advanced rollback")

    assert delete_attempted is False
    assert run_git(repo, "rev-parse", branch)


def test_create_recovers_identity_update_that_timed_out_after_success(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    repo = make_repo(tmp_path)
    service = make_service(tmp_path, repo)
    original_git = engineering_session_service.git
    timed_out = False

    def timeout_after_identity_update(
        repo_path: str | Path,
        *args: str,
        **kwargs,
    ):
        nonlocal timed_out
        result = original_git(repo_path, *args, **kwargs)
        if (
            not timed_out
            and args[:2] == (
                "update-ref",
                "refs/agentic/sessions/S-001",
            )
        ):
            timed_out = True
            try:
                raise subprocess.TimeoutExpired(["git", *args], timeout=90)
            except subprocess.TimeoutExpired as exc:
                raise GitCommandError("git update-ref timed out") from exc
        return result

    monkeypatch.setattr(
        engineering_session_service,
        "git",
        timeout_after_identity_update,
    )

    session = service.create(
        SessionType.REVIEW,
        "Identity timeout",
        create_worktree=False,
    )

    assert timed_out is True
    assert session.id == "S-001"
    assert service.registry.load(session.id).id == session.id
    assert run_git(
        repo,
        "rev-parse",
        "refs/agentic/sessions/S-001",
    ) == session.base_commit


def test_create_recovers_worktree_add_that_timed_out_after_success(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    repo = make_repo(tmp_path)
    service = make_service(tmp_path, repo)
    original_git = engineering_session_service.git
    timed_out = False

    def timeout_after_worktree_add(
        repo_path: str | Path,
        *args: str,
        **kwargs,
    ):
        nonlocal timed_out
        result = original_git(repo_path, *args, **kwargs)
        if not timed_out and args[:2] == ("worktree", "add"):
            timed_out = True
            worktree = Path(args[2])
            (worktree / "external.txt").write_text(
                "external work\n",
                encoding="utf-8",
            )
            try:
                raise subprocess.TimeoutExpired(["git", *args], timeout=90)
            except subprocess.TimeoutExpired as exc:
                raise GitCommandError("git worktree add timed out") from exc
        return result

    monkeypatch.setattr(
        engineering_session_service,
        "git",
        timeout_after_worktree_add,
    )

    session = service.create(SessionType.FEATURE, "Worktree timeout")

    worktree = Path(session.worktree_path)
    assert timed_out is True
    assert worktree.exists()
    assert (worktree / "external.txt").read_text(encoding="utf-8") == (
        "external work\n"
    )
    assert service.registry.load(session.id).worktree_path == str(worktree)


def test_identity_update_ref_infrastructure_error_is_not_retried_as_conflict(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    repo = make_repo(tmp_path)
    service = make_service(tmp_path, repo)
    original_git = engineering_session_service.git
    attempts = 0

    def fail_identity_update(
        repo_path: str | Path,
        *args: str,
        **kwargs,
    ):
        nonlocal attempts
        if args[:2] == (
            "update-ref",
            "refs/agentic/sessions/S-001",
        ):
            attempts += 1
            return subprocess.CompletedProcess(
                ["git", *args],
                returncode=128,
                stdout="",
                stderr="fatal: disk full",
            )
        return original_git(repo_path, *args, **kwargs)

    monkeypatch.setattr(
        engineering_session_service,
        "git",
        fail_identity_update,
    )

    with pytest.raises(GitCommandError, match="disk full"):
        service.create(
            SessionType.REVIEW,
            "Infrastructure failure",
            create_worktree=False,
        )

    assert attempts == 1
    assert service.registry.list() == []


def test_worktree_claim_infrastructure_error_is_not_retried_as_conflict(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    repo = make_repo(tmp_path)
    service = make_service(tmp_path, repo)
    original_git = engineering_session_service.git
    attempts = 0

    def fail_claim_write(
        repo_path: str | Path,
        *args: str,
        **kwargs,
    ):
        nonlocal attempts
        if (
            len(args) == 3
            and args[0] == "symbolic-ref"
            and args[1].startswith("refs/agentic/worktree-claims/")
        ):
            attempts += 1
            return subprocess.CompletedProcess(
                ["git", *args],
                returncode=128,
                stdout="",
                stderr="fatal: claim storage unavailable",
            )
        return original_git(repo_path, *args, **kwargs)

    monkeypatch.setattr(
        engineering_session_service,
        "git",
        fail_claim_write,
    )

    with pytest.raises(GitCommandError, match="claim storage unavailable"):
        service.create(SessionType.FEATURE, "Claim infrastructure failure")

    assert attempts == 1
    assert service.registry.list() == []


def test_create_recovers_worktree_claim_that_timed_out_after_success(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    repo = make_repo(tmp_path)
    service = make_service(tmp_path, repo)
    original_git = engineering_session_service.git
    timed_out = False

    def timeout_after_claim_write(
        repo_path: str | Path,
        *args: str,
        **kwargs,
    ):
        nonlocal timed_out
        result = original_git(repo_path, *args, **kwargs)
        if (
            not timed_out
            and len(args) == 3
            and args[0] == "symbolic-ref"
            and args[1].startswith("refs/agentic/worktree-claims/")
        ):
            timed_out = True
            try:
                raise subprocess.TimeoutExpired(["git", *args], timeout=90)
            except subprocess.TimeoutExpired as exc:
                raise GitCommandError("git symbolic-ref timed out") from exc
        return result

    monkeypatch.setattr(
        engineering_session_service,
        "git",
        timeout_after_claim_write,
    )

    session = service.create(SessionType.FEATURE, "Claim timeout")

    claim_ref = service._worktree_claim_ref(session.branch)
    assert timed_out is True
    assert run_git(repo, "symbolic-ref", claim_ref) == (
        service._registry_owner_ref(session.id)
    )
    assert service.registry.load(session.id).branch == session.branch


def test_create_rollback_does_not_delete_a_branch_created_by_another_process(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    repo = make_repo(tmp_path)
    service = make_service(tmp_path, repo)
    branch = "session/S-001-feature-branch-race"
    original_git = engineering_session_service.git
    raced = False

    def racing_git(repo_path: str | Path, *args: str, **kwargs):
        nonlocal raced
        if (
            not raced
            and args[:2] == ("update-ref", f"refs/heads/{branch}")
        ):
            raced = True
            run_git(repo, "branch", branch, "main")
        return original_git(repo_path, *args, **kwargs)

    monkeypatch.setattr(engineering_session_service, "git", racing_git)

    session = service.create(SessionType.FEATURE, "Branch race")

    assert raced is True
    assert run_git(repo, "branch", "--list", branch)
    assert session.id == "S-002"
    assert session.branch != branch
    assert Path(session.worktree_path).exists()


def test_concurrent_create_across_registry_roots_reserves_distinct_git_identities(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    repo = make_repo(tmp_path)
    worktree_parent = tmp_path / "worktrees"
    services = [
        EngineeringSessionService(
            repo,
            registry_root=tmp_path / f"sessions-{index}",
            worktree_parent=worktree_parent,
        )
        for index in range(2)
    ]
    mutation_started = Event()
    release_mutation = Event()
    original_reserve = services[0]._reserve_session_identity

    def slow_reserve(*args, **kwargs):
        mutation_started.set()
        assert release_mutation.wait(timeout=5)
        return original_reserve(*args, **kwargs)

    monkeypatch.setattr(
        services[0],
        "_reserve_session_identity",
        slow_reserve,
    )

    with ThreadPoolExecutor(max_workers=2) as executor:
        first_future = executor.submit(
            services[0].create,
            SessionType.FEATURE,
            "Concurrent identity",
        )
        assert mutation_started.wait(timeout=5)
        second_future = executor.submit(
            services[1].create,
            SessionType.FEATURE,
            "Concurrent identity",
        )
        time.sleep(0.2)
        second_blocked_by_repo_lock = not second_future.done()
        release_mutation.set()
        sessions = [
            first_future.result(timeout=10),
            second_future.result(timeout=10),
        ]

    assert second_blocked_by_repo_lock is True
    assert sorted(session.id for session in sessions) == ["S-001", "S-002"]
    assert len({session.branch for session in sessions}) == 2
    assert len({session.worktree_path for session in sessions}) == 2
    for session in sessions:
        worktree = Path(session.worktree_path)
        assert worktree.exists()
        assert run_git(worktree, "branch", "--show-current") == session.branch


def test_no_worktree_create_across_registry_roots_reserves_distinct_identities(
    tmp_path: Path,
):
    repo = make_repo(tmp_path)
    services = [
        EngineeringSessionService(
            repo,
            registry_root=tmp_path / f"review-sessions-{index}",
            worktree_parent=tmp_path / "worktrees",
        )
        for index in range(2)
    ]

    sessions = [
        service.create(
            SessionType.REVIEW,
            f"Review {index}",
            create_worktree=False,
        )
        for index, service in enumerate(services)
    ]

    assert [session.id for session in sessions] == ["S-001", "S-002"]
    identity_refs = run_git(
        repo,
        "for-each-ref",
        "--format=%(refname)",
        "refs/agentic/sessions/",
    ).splitlines()
    assert identity_refs == [
        "refs/agentic/sessions/S-001",
        "refs/agentic/sessions/S-002",
    ]


def test_no_worktree_create_supports_sha256_repository(tmp_path: Path):
    repo = tmp_path / "sha256-repo"
    result = subprocess.run(
        [
            "git",
            "init",
            "--object-format=sha256",
            "-b",
            "main",
            str(repo),
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        pytest.skip("installed Git does not support SHA-256 repositories")
    run_git(repo, "config", "user.email", "t@example.com")
    run_git(repo, "config", "user.name", "Tester")
    (repo / "README.md").write_text("base\n", encoding="utf-8")
    run_git(repo, "add", "README.md")
    run_git(repo, "commit", "-m", "base")
    service = make_service(tmp_path, repo)

    session = service.create(
        SessionType.REVIEW,
        "SHA-256 review",
        create_worktree=False,
    )

    assert session.id == "S-001"
    assert len(
        run_git(
            repo,
            "rev-parse",
            "refs/agentic/sessions/S-001",
        )
    ) == 64


def test_no_worktree_save_failure_releases_identity_reservation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    repo = make_repo(tmp_path)
    service = make_service(tmp_path, repo)

    def fail_save(_session):
        raise RuntimeError("registry save failed")

    monkeypatch.setattr(service.registry, "save", fail_save)

    with pytest.raises(RuntimeError, match="registry save failed"):
        service.create(
            SessionType.REVIEW,
            "Failed review",
            create_worktree=False,
        )

    assert run_git(
        repo,
        "for-each-ref",
        "--format=%(refname)",
        "refs/agentic/sessions/",
    ) == ""


def test_create_preserves_git_resources_when_registry_record_was_published(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    repo = make_repo(tmp_path)
    service = make_service(tmp_path, repo)
    service.registry.list()

    def fail_directory_fsync():
        raise OSError("directory fsync failed")

    monkeypatch.setattr(
        service.registry,
        "_fsync_directory",
        fail_directory_fsync,
    )

    with pytest.raises(OSError, match="directory fsync failed") as exc_info:
        service.create(SessionType.FEATURE, "Published registry")

    persisted = service.registry.load("S-001")
    assert Path(persisted.worktree_path).exists()
    assert run_git(
        repo,
        "rev-parse",
        "--verify",
        persisted.branch,
    )
    assert run_git(
        repo,
        "rev-parse",
        "--verify",
        "refs/agentic/sessions/S-001",
    )
    notes = getattr(exc_info.value, "__notes__", [])
    assert any("already published" in note for note in notes)


def test_save_failure_after_worktree_creation_retains_recoverable_git_resources(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    repo = make_repo(tmp_path)
    service = make_service(tmp_path, repo)

    def fail_save(_session):
        raise RuntimeError("registry save failed")

    monkeypatch.setattr(service.registry, "save", fail_save)

    with pytest.raises(RuntimeError, match="registry save failed") as exc_info:
        service.create(SessionType.FEATURE, "Recoverable save failure")

    branch = "session/S-001-feature-recoverable-save-failure"
    worktree = service.worktree_parent / branch.replace("/", "-")
    assert worktree.exists()
    assert run_git(worktree, "branch", "--show-current") == branch
    assert run_git(repo, "rev-parse", "--verify", branch)
    assert run_git(
        repo,
        "rev-parse",
        "--verify",
        "refs/agentic/sessions/S-001",
    )
    notes = getattr(exc_info.value, "__notes__", [])
    assert any("reconcile" in note for note in notes)


def test_reconcile_recovers_worktree_retained_after_registry_save_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    repo = make_repo(tmp_path)
    service = make_service(tmp_path, repo)
    original_save = service.registry.save
    failed = False

    def fail_once(session):
        nonlocal failed
        if not failed:
            failed = True
            raise RuntimeError("registry save failed")
        return original_save(session)

    monkeypatch.setattr(service.registry, "save", fail_once)

    with pytest.raises(RuntimeError, match="registry save failed"):
        service.create(SessionType.FEATURE, "Recover retained")

    sessions = service.reconcile()

    assert len(sessions) == 1
    assert sessions[0].id == "S-001"
    assert sessions[0].branch == "session/S-001-feature-recover-retained"
    assert sessions[0].status == SessionStatus.ORPHAN_SESSION


def test_create_rollback_failure_preserves_original_exception(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    repo = make_repo(tmp_path)
    service = make_service(tmp_path, repo)
    original_git = engineering_session_service.git

    def fail_save(_session):
        raise RuntimeError("registry save failed")

    def fail_worktree_remove(repo_path: str | Path, *args: str, **kwargs):
        if args[:3] == ("worktree", "remove", "--force"):
            raise GitCommandError("rollback remove failed")
        return original_git(repo_path, *args, **kwargs)

    monkeypatch.setattr(service.registry, "save", fail_save)
    monkeypatch.setattr(
        engineering_session_service,
        "git",
        fail_worktree_remove,
    )

    with pytest.raises(RuntimeError, match="registry save failed") as exc_info:
        service.create(SessionType.FEATURE, "Rollback failure")

    notes = getattr(exc_info.value, "__notes__", [])
    assert any("rollback" in note for note in notes)


def test_separate_registry_roots_cannot_claim_the_same_session_identity(
    tmp_path: Path,
):
    repo = make_repo(tmp_path)
    first = EngineeringSessionService(
        repo,
        registry_root=tmp_path / "first-sessions",
        worktree_parent=tmp_path / "worktrees",
    ).create(SessionType.FEATURE, "Shared identity")

    second = EngineeringSessionService(
        repo,
        registry_root=tmp_path / "second-sessions",
        worktree_parent=tmp_path / "worktrees",
    ).create(SessionType.FEATURE, "Shared identity")

    assert first.id == "S-001"
    assert second.id == "S-002"
    assert first.branch != second.branch
    assert first.worktree_path != second.worktree_path


def test_concurrent_create_allocates_distinct_sessions(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    repo = make_repo(tmp_path)
    registry_root = tmp_path / "shared-sessions"
    worktree_parent = tmp_path / "shared-worktrees"
    first_service = EngineeringSessionService(
        repo,
        registry_root=registry_root,
        worktree_parent=worktree_parent,
    )
    second_service = EngineeringSessionService(
        repo,
        registry_root=registry_root,
        worktree_parent=worktree_parent,
    )
    original_next_id = SessionRegistry.next_id

    def delayed_next_id(registry: SessionRegistry) -> str:
        session_id = original_next_id(registry)
        time.sleep(0.1)
        return session_id

    monkeypatch.setattr(SessionRegistry, "next_id", delayed_next_id)
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [
            executor.submit(first_service.create, SessionType.FEATURE, "Concurrent first"),
            executor.submit(second_service.create, SessionType.FEATURE, "Concurrent second"),
        ]
        sessions = [future.result() for future in futures]

    assert sorted(session.id for session in sessions) == ["S-001", "S-002"]
    assert sorted(path.name for path in registry_root.glob("S-*.yaml")) == [
        "S-001.yaml",
        "S-002.yaml",
    ]
    assert all(not path.name.endswith(".tmp") for path in registry_root.iterdir())
    assert len({session.branch for session in sessions}) == 2
    assert len({session.worktree_path for session in sessions}) == 2
    for session in sessions:
        worktree = Path(session.worktree_path)
        persisted = first_service.registry.load(session.id)
        assert worktree.exists()
        assert run_git(worktree, "branch", "--show-current") == session.branch
        assert persisted.branch == session.branch
        assert persisted.worktree_path == session.worktree_path


def test_linked_worktree_services_share_default_registry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    repo = make_repo(tmp_path)
    linked = tmp_path / "linked"
    run_git(repo, "worktree", "add", "-b", "linked-base", str(linked), "main")
    monkeypatch.setenv("AGENTIC_SESSION_HOME", str(tmp_path / "agentic-home"))
    main_service = EngineeringSessionService(repo)
    linked_service = EngineeringSessionService(linked)

    first = main_service.create(
        SessionType.REVIEW,
        "Main review",
        create_worktree=False,
    )
    second = linked_service.create(
        SessionType.REVIEW,
        "Linked review",
        create_worktree=False,
    )

    assert main_service.registry.root == linked_service.registry.root
    assert [first.id, second.id] == ["S-001", "S-002"]
    assert [session.id for session in main_service.registry.list()] == [
        "S-001",
        "S-002",
    ]


def test_linked_worktree_subdirectory_resolves_control_repository(tmp_path: Path):
    repo = make_repo(tmp_path)
    linked = tmp_path / "linked"
    run_git(repo, "worktree", "add", "-b", "linked-base", str(linked), "main")
    nested = linked / "backend"
    nested.mkdir()

    service = EngineeringSessionService(
        nested,
        registry_root=tmp_path / "sessions",
        worktree_parent=tmp_path / "worktrees",
    )

    assert service.repo_path == repo.resolve()
    assert service.registry.repo_path == repo.resolve()


def test_default_worktree_parent_is_namespaced_for_sibling_repositories(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    first_repo = make_repo(tmp_path, "first-repo")
    second_repo = make_repo(tmp_path, "second-repo")
    monkeypatch.setenv("AGENTIC_SESSION_HOME", str(tmp_path / "agentic-home"))

    first_service = EngineeringSessionService(first_repo)
    second_service = EngineeringSessionService(second_repo)

    assert first_service.worktree_parent != second_service.worktree_parent
    assert first_service.worktree_parent.parent == tmp_path / "worktrees"
    assert second_service.worktree_parent.parent == tmp_path / "worktrees"

    first_session = first_service.create(SessionType.FEATURE, "Same title")
    second_session = second_service.create(SessionType.FEATURE, "Same title")

    assert first_session.worktree_path != second_session.worktree_path
    assert Path(first_session.worktree_path).exists()
    assert Path(second_session.worktree_path).exists()

    explicit_parent = tmp_path / "explicit-worktrees"
    explicit_service = EngineeringSessionService(
        first_repo,
        registry_root=tmp_path / "explicit-sessions",
        worktree_parent=explicit_parent,
    )
    assert explicit_service.worktree_parent == explicit_parent.resolve()


def test_create_without_worktree_remains_running(tmp_path: Path):
    repo = make_repo(tmp_path)
    service = make_service(tmp_path, repo)

    session = service.create(SessionType.REVIEW, "Review only", create_worktree=False)

    assert session.worktree_path is None
    assert session.status == SessionStatus.RUNNING
    assert session.git_state.missing_worktree is False


def test_no_worktree_session_becomes_stale_when_base_advances(tmp_path: Path):
    repo = make_repo(tmp_path)
    service = make_service(tmp_path, repo)
    session = service.create(
        SessionType.REVIEW,
        "Review snapshot",
        create_worktree=False,
    )
    (repo / "advanced.txt").write_text("advanced\n", encoding="utf-8")
    run_git(repo, "add", "advanced.txt")
    run_git(repo, "commit", "-m", "advance main")

    synced = service.sync(session.id)

    assert synced.head_commit == session.base_commit
    assert synced.git_state.behind == 1
    assert synced.git_state.stale is True


@pytest.mark.parametrize(
    "session_type",
    [SessionType.NEW_APP, SessionType.SPEC_CHANGE],
)
def test_create_rejects_required_session_type_without_worktree(
    tmp_path: Path,
    session_type: SessionType,
):
    repo = make_repo(tmp_path)
    service = make_service(tmp_path, repo)

    with pytest.raises(ValueError, match="requires a worktree"):
        service.create(
            session_type,
            "Required worktree",
            create_worktree=False,
        )

    assert not list(service.registry.root.glob("S-*.yaml"))


def test_sync_updates_dirty_state(tmp_path: Path):
    repo = make_repo(tmp_path)
    service = make_service(tmp_path, repo)
    session = service.create(SessionType.FEATURE, "Dirty state")
    worktree = Path(session.worktree_path)
    (worktree / "draft.txt").write_text("draft\n", encoding="utf-8")

    synced = service.sync(session.id)

    assert synced.git_state.clean is False
    assert synced.git_state.current_branch == session.branch


def test_sync_recovers_running_after_missing_worktree_is_restored(tmp_path: Path):
    repo = make_repo(tmp_path)
    service = make_service(tmp_path, repo)
    session = service.create(SessionType.FEATURE, "Restore worktree")
    worktree = Path(session.worktree_path)
    run_git(repo, "worktree", "remove", str(worktree))

    missing = service.sync(session.id)

    assert missing.status == SessionStatus.MISSING_WORKTREE
    assert missing.git_state.missing_worktree is True

    run_git(repo, "worktree", "add", str(worktree), session.branch)
    restored = service.sync(session.id)

    assert restored.status == SessionStatus.RUNNING
    assert restored.git_state.missing_worktree is False


def test_restored_worktree_clears_missing_status_while_base_is_unavailable(
    tmp_path: Path,
):
    repo = make_repo(tmp_path)
    service = make_service(tmp_path, repo)
    session = service.create(SessionType.FEATURE, "Restore without base")
    worktree = Path(session.worktree_path)
    base_head = run_git(repo, "rev-parse", "main")
    run_git(repo, "worktree", "remove", str(worktree))
    run_git(repo, "checkout", "-b", "parking-restore-without-base")
    run_git(repo, "update-ref", "-d", "refs/heads/main")

    missing = service.sync(session.id)

    assert missing.status == SessionStatus.MISSING_WORKTREE
    assert missing.git_state.missing_worktree is True
    assert missing.cleanup.suggested is False

    run_git(repo, "worktree", "add", str(worktree), session.branch)
    unavailable = service.sync(session.id)

    assert unavailable.status == SessionStatus.RUNNING
    assert unavailable.git_state.missing_worktree is False
    assert unavailable.git_state.branch_mismatch is False
    assert unavailable.git_state.base_missing is True
    assert unavailable.cleanup.suggested is False

    run_git(repo, "update-ref", "refs/heads/main", base_head)
    restored = service.sync(session.id)

    assert restored.status == SessionStatus.RUNNING
    assert restored.git_state.base_missing is False
    assert restored.git_state.merged_to_base is False
    assert restored.cleanup.suggested is False


@pytest.mark.parametrize("action", ["checkpoint", "archive"])
def test_base_outage_preserves_running_and_rejects_writes(
    tmp_path: Path,
    action: str,
):
    repo = make_repo(tmp_path)
    service = make_service(tmp_path, repo)
    session = service.create(SessionType.FEATURE, f"Missing base {action}")
    worktree = Path(session.worktree_path)
    base_head = run_git(repo, "rev-parse", "main")
    (worktree / "committed.txt").write_text("committed\n", encoding="utf-8")
    assert service.checkpoint(session.id) is True
    run_git(repo, "checkout", "-b", f"parking-{action}")
    run_git(repo, "update-ref", "-d", "refs/heads/main")
    (worktree / "blocked.txt").write_text("do not commit\n", encoding="utf-8")
    before_head = run_git(worktree, "rev-parse", "HEAD")

    unavailable = service.sync(session.id)
    resumed = service.resume(session.id)
    if action == "checkpoint":
        assert service.checkpoint(session.id) is False
        observed = service.registry.load(session.id)
    else:
        observed = service.archive(session.id)

    assert unavailable.status == SessionStatus.RUNNING
    assert unavailable.git_state.base_missing is True
    assert unavailable.git_state.stale is True
    assert unavailable.cleanup.suggested is False
    assert resumed.status == SessionStatus.RUNNING
    assert observed.status == SessionStatus.RUNNING
    assert run_git(worktree, "rev-parse", "HEAD") == before_head
    assert (worktree / "blocked.txt").read_text(encoding="utf-8") == "do not commit\n"
    assert run_git(worktree, "status", "--porcelain")

    run_git(repo, "update-ref", "refs/heads/main", base_head)
    restored = service.sync(session.id)

    assert restored.status == SessionStatus.RUNNING
    assert restored.git_state.base_missing is False
    assert restored.git_state.merged_to_base is False


@pytest.mark.parametrize("restore_contains_session", [False, True])
def test_base_outage_suppresses_cleanup_for_merged_session(
    tmp_path: Path,
    restore_contains_session: bool,
):
    repo = make_repo(tmp_path)
    service = make_service(tmp_path, repo)
    session = service.create(SessionType.FEATURE, "Missing merged base")
    worktree = Path(session.worktree_path)
    base_before_merge = run_git(repo, "rev-parse", "main")
    (worktree / "merged.txt").write_text("merged\n", encoding="utf-8")
    assert service.checkpoint(session.id) is True
    run_git(repo, "merge", "--no-ff", session.branch, "-m", "merge session")
    merged = service.sync(session.id)
    assert merged.status == SessionStatus.MERGED_RETAINED
    merged_head = run_git(repo, "rev-parse", "main")
    run_git(repo, "checkout", "-b", "parking")
    run_git(repo, "update-ref", "-d", "refs/heads/main")

    unavailable = service.sync(session.id)

    assert unavailable.status == SessionStatus.MERGED_RETAINED
    assert unavailable.git_state.base_missing is True
    assert unavailable.cleanup.suggested is False

    restored_base = merged_head if restore_contains_session else base_before_merge
    run_git(repo, "update-ref", "refs/heads/main", restored_base)
    restored = service.sync(session.id)

    assert restored.git_state.base_missing is False
    assert restored.git_state.merged_to_base is restore_contains_session
    if restore_contains_session:
        assert restored.status == SessionStatus.MERGED_RETAINED
        assert restored.cleanup.suggested is True
    else:
        assert restored.status == SessionStatus.RUNNING
        assert restored.cleanup.suggested is False


@pytest.mark.parametrize(
    "initial_status",
    [
        SessionStatus.RUNNING,
        SessionStatus.MERGED_RETAINED,
        SessionStatus.ARCHIVED_DIRTY,
        SessionStatus.ABANDONED_RETAINED,
    ],
)
def test_base_outage_keeps_lifecycle_status_orthogonal(
    tmp_path: Path,
    initial_status: SessionStatus,
):
    repo = make_repo(tmp_path)
    service = make_service(tmp_path, repo)
    session = service.create(SessionType.FEATURE, f"Restore {initial_status.value}")
    worktree = Path(session.worktree_path)

    if initial_status == SessionStatus.MERGED_RETAINED:
        (worktree / "merged.txt").write_text("merged\n", encoding="utf-8")
        assert service.checkpoint(session.id) is True
        run_git(repo, "merge", "--no-ff", session.branch, "-m", "merge session")
        observed = service.sync(session.id)
    elif initial_status == SessionStatus.ARCHIVED_DIRTY:
        (worktree / "dirty.txt").write_text("dirty\n", encoding="utf-8")
        observed = service.archive(session.id, checkpoint=False)
    elif initial_status == SessionStatus.ABANDONED_RETAINED:
        observed = service.archive(session.id, checkpoint=False)
    else:
        observed = service.sync(session.id)
    assert observed.status == initial_status
    initial_cleanup = observed.cleanup.suggested

    base_head = run_git(repo, "rev-parse", "main")
    run_git(repo, "checkout", "-b", f"parking-{initial_status.value}")
    run_git(repo, "update-ref", "-d", "refs/heads/main")

    unavailable = service.sync(session.id)
    unavailable_again = service.sync(session.id)

    assert unavailable.status == initial_status
    assert unavailable.git_state.base_missing is True
    assert unavailable.cleanup.suggested is False
    assert unavailable_again.status == initial_status

    run_git(repo, "update-ref", "refs/heads/main", base_head)
    restored = service.sync(session.id)

    assert restored.status == initial_status
    assert restored.git_state.base_missing is False
    assert restored.cleanup.suggested is initial_cleanup


def test_manual_blocked_session_remains_blocked_across_base_outage(tmp_path: Path):
    repo = make_repo(tmp_path)
    service = make_service(tmp_path, repo)
    session = service.create(SessionType.FEATURE, "Manual blocked outage")
    session.status = SessionStatus.BLOCKED_RETAINED
    service.registry.save(session)
    base_head = run_git(repo, "rev-parse", "main")
    run_git(repo, "checkout", "-b", "parking-manual-blocked")
    run_git(repo, "update-ref", "-d", "refs/heads/main")

    unavailable = service.sync(session.id)
    unavailable_again = service.sync(session.id)

    assert unavailable.status == SessionStatus.BLOCKED_RETAINED
    assert unavailable.git_state.base_missing is True
    assert unavailable_again.status == SessionStatus.BLOCKED_RETAINED

    run_git(repo, "update-ref", "refs/heads/main", base_head)
    restored = service.sync(session.id)

    assert restored.status == SessionStatus.BLOCKED_RETAINED
    assert restored.git_state.base_missing is False
    assert restored.cleanup.suggested is False


@pytest.mark.parametrize(
    "updated_status",
    [SessionStatus.ORPHAN_SESSION, SessionStatus.BLOCKED_RETAINED],
)
def test_lifecycle_change_during_base_outage_is_not_overwritten(
    tmp_path: Path,
    updated_status: SessionStatus,
):
    repo = make_repo(tmp_path)
    service = make_service(tmp_path, repo)
    session = service.create(SessionType.FEATURE, "Lifecycle during outage")
    base_head = run_git(repo, "rev-parse", "main")
    run_git(repo, "checkout", "-b", f"parking-{updated_status.value}")
    run_git(repo, "update-ref", "-d", "refs/heads/main")
    unavailable = service.sync(session.id)
    assert unavailable.status == SessionStatus.RUNNING
    assert unavailable.git_state.base_missing is True
    unavailable.status = updated_status
    service.registry.save(unavailable)

    during_outage = service.sync(session.id)

    assert during_outage.status == updated_status
    assert during_outage.git_state.base_missing is True

    run_git(repo, "update-ref", "refs/heads/main", base_head)
    restored = service.sync(session.id)

    assert restored.status == updated_status
    assert restored.git_state.base_missing is False


@pytest.mark.parametrize(
    ("initially_merged", "restore_contains_session"),
    [
        (False, False),
        (True, False),
        (True, True),
    ],
)
def test_orphan_session_identity_survives_base_outage(
    tmp_path: Path,
    initially_merged: bool,
    restore_contains_session: bool,
):
    repo = make_repo(tmp_path)
    service = make_service(tmp_path, repo)
    branch = (
        "session/S-099-feature-outage-orphan-"
        f"{initially_merged}-{restore_contains_session}"
    )
    worktree = tmp_path / f"outage-orphan-{initially_merged}-{restore_contains_session}"
    base_before_merge = run_git(repo, "rev-parse", "main")
    run_git(repo, "worktree", "add", "-b", branch, str(worktree), "main")
    (worktree / "orphan.txt").write_text("orphan\n", encoding="utf-8")
    run_git(worktree, "add", "orphan.txt")
    run_git(worktree, "commit", "-m", "orphan change")
    if initially_merged:
        run_git(repo, "merge", "--no-ff", branch, "-m", "merge orphan")
    orphan = next(item for item in service.reconcile() if item.branch == branch)
    assert orphan.status == SessionStatus.ORPHAN_SESSION
    assert orphan.git_state.merged_to_base is initially_merged
    assert orphan.cleanup.suggested is initially_merged

    merged_head = run_git(repo, "rev-parse", "main")
    run_git(
        repo,
        "checkout",
        "-b",
        f"parking-orphan-{initially_merged}-{restore_contains_session}",
    )
    run_git(repo, "update-ref", "-d", "refs/heads/main")

    unavailable = service.sync(orphan.id)
    unavailable_again = service.sync(orphan.id)

    assert unavailable.status == SessionStatus.ORPHAN_SESSION
    assert unavailable.git_state.base_missing is True
    assert unavailable.cleanup.suggested is False
    assert unavailable_again.status == SessionStatus.ORPHAN_SESSION

    restored_base = (
        merged_head if restore_contains_session else base_before_merge
    )
    run_git(repo, "update-ref", "refs/heads/main", restored_base)
    restored = service.sync(orphan.id)

    assert restored.status == SessionStatus.ORPHAN_SESSION
    assert restored.git_state.base_missing is False
    assert restored.git_state.merged_to_base is restore_contains_session
    assert restored.cleanup.suggested is restore_contains_session


def test_sync_rejects_replacement_worktree_from_other_repository(tmp_path: Path):
    repo = make_repo(tmp_path)
    service = make_service(tmp_path, repo)
    session = service.create(SessionType.FEATURE, "Repository ownership")
    worktree = Path(session.worktree_path)
    session_branch_head = run_git(repo, "rev-parse", session.branch)
    run_git(repo, "worktree", "remove", str(worktree))
    worktree.mkdir()
    run_git(worktree, "init", "-b", "main")
    run_git(worktree, "config", "user.email", "other@example.com")
    run_git(worktree, "config", "user.name", "Other")
    (worktree / "README.md").write_text("other\n", encoding="utf-8")
    run_git(worktree, "add", "README.md")
    run_git(worktree, "commit", "-m", "other base")
    run_git(worktree, "checkout", "-b", session.branch)
    (worktree / "dirty.txt").write_text("do not commit\n", encoding="utf-8")
    other_head = run_git(worktree, "rev-parse", "HEAD")

    synced = service.sync(session.id)
    checkpointed = service.checkpoint(session.id)

    assert synced.status == SessionStatus.MISSING_WORKTREE
    assert synced.git_state.missing_worktree is True
    assert checkpointed is False
    assert run_git(worktree, "rev-parse", "HEAD") == other_head
    assert (worktree / "dirty.txt").read_text(encoding="utf-8") == "do not commit\n"
    assert run_git(worktree, "status", "--porcelain")
    assert run_git(repo, "rev-parse", session.branch) == session_branch_head


def test_sync_does_not_rebind_session_to_control_repository(tmp_path: Path):
    repo = make_repo(tmp_path)
    service = make_service(tmp_path, repo)
    session = service.create(SessionType.FEATURE, "Control repository isolation")
    session_worktree_path = session.worktree_path
    assert session_worktree_path is not None
    linked_worktree = Path(session_worktree_path)
    run_git(repo, "worktree", "remove", str(linked_worktree))
    run_git(repo, "checkout", session.branch)
    dirty_file = repo / "control-dirty.txt"
    dirty_file.write_text("do not checkpoint\n", encoding="utf-8")
    control_head = run_git(repo, "rev-parse", "HEAD")

    try:
        synced = service.sync(session.id)
        checkpointed = service.checkpoint(session.id)

        assert synced.worktree_path == session_worktree_path
        assert synced.status == SessionStatus.MISSING_WORKTREE
        assert synced.git_state.missing_worktree is True
        assert checkpointed is False
        assert run_git(repo, "rev-parse", "HEAD") == control_head
        assert dirty_file.read_text(encoding="utf-8") == "do not checkpoint\n"
        assert run_git(repo, "status", "--porcelain")
    finally:
        run_git(repo, "checkout", "main")


def test_sync_rejects_registry_worktree_path_pointing_to_control_repository(
    tmp_path: Path,
):
    repo = make_repo(tmp_path)
    service = make_service(tmp_path, repo)
    session = service.create(SessionType.FEATURE, "Persisted control repository")
    linked_worktree = Path(session.worktree_path)
    run_git(repo, "worktree", "remove", str(linked_worktree))
    run_git(repo, "checkout", session.branch)
    session.worktree_path = str(repo.resolve())
    service.registry.save(session)
    dirty_file = repo / "control-dirty.txt"
    dirty_file.write_text("do not checkpoint\n", encoding="utf-8")
    control_head = run_git(repo, "rev-parse", "HEAD")

    try:
        synced = service.sync(session.id)
        checkpointed = service.checkpoint(session.id)

        persisted = service.registry.load(session.id)
        assert synced.worktree_path == str(repo.resolve())
        assert synced.status == SessionStatus.MISSING_WORKTREE
        assert synced.git_state.missing_worktree is True
        assert checkpointed is False
        assert persisted.status == SessionStatus.MISSING_WORKTREE
        assert persisted.git_state.missing_worktree is True
        assert run_git(repo, "rev-parse", "HEAD") == control_head
        assert dirty_file.read_text(encoding="utf-8") == "do not checkpoint\n"
        assert run_git(repo, "status", "--porcelain")
    finally:
        run_git(repo, "checkout", "main")


def test_nested_repo_path_does_not_rebind_session_to_control_repository(
    tmp_path: Path,
):
    repo = make_repo(tmp_path)
    nested = repo / "backend"
    nested.mkdir()
    service = EngineeringSessionService(
        nested,
        registry_root=tmp_path / "sessions",
        worktree_parent=tmp_path / "worktrees",
    )
    session = service.create(SessionType.FEATURE, "Nested control isolation")
    session_worktree_path = session.worktree_path
    assert session_worktree_path is not None
    linked_worktree = Path(session_worktree_path)
    run_git(repo, "worktree", "remove", str(linked_worktree))
    run_git(repo, "checkout", session.branch)
    dirty_file = repo / "control-dirty.txt"
    dirty_file.write_text("do not checkpoint\n", encoding="utf-8")
    control_head = run_git(repo, "rev-parse", "HEAD")

    try:
        synced = service.sync(session.id)
        checkpointed = service.checkpoint(session.id)

        assert service.repo_path == repo.resolve()
        assert synced.worktree_path == session_worktree_path
        assert synced.status == SessionStatus.MISSING_WORKTREE
        assert synced.git_state.missing_worktree is True
        assert checkpointed is False
        assert run_git(repo, "rev-parse", "HEAD") == control_head
        assert dirty_file.read_text(encoding="utf-8") == "do not checkpoint\n"
        assert run_git(repo, "status", "--porcelain")
    finally:
        run_git(repo, "checkout", "main")


def test_resume_updates_worktree_path_after_move(tmp_path: Path):
    repo = make_repo(tmp_path)
    service = make_service(tmp_path, repo)
    session = service.create(SessionType.FEATURE, "Resume moved worktree")
    original = Path(session.worktree_path)
    moved = tmp_path / "resumed-worktree"
    run_git(repo, "worktree", "move", str(original), str(moved))

    resumed = service.resume(session.id)

    persisted = service.registry.load(session.id)
    assert resumed.worktree_path == str(moved.resolve())
    assert persisted.worktree_path == str(moved.resolve())
    assert persisted.status == SessionStatus.RUNNING
    assert persisted.git_state.missing_worktree is False


def test_resume_reactivates_clean_abandoned_session(tmp_path: Path):
    repo = make_repo(tmp_path)
    service = make_service(tmp_path, repo)
    session = service.create(SessionType.FEATURE, "Resume abandoned")
    archived = service.archive(session.id, checkpoint=False)
    assert archived.status == SessionStatus.ABANDONED_RETAINED

    resumed = service.resume(session.id)

    assert resumed.status == SessionStatus.RUNNING
    assert resumed.cleanup.suggested is False


def test_resume_reactivates_abandoned_session_without_worktree(tmp_path: Path):
    repo = make_repo(tmp_path)
    service = make_service(tmp_path, repo)
    session = service.create(
        SessionType.REVIEW,
        "Resume review",
        create_worktree=False,
    )
    archived = service.archive(session.id, checkpoint=False)
    assert archived.status == SessionStatus.ABANDONED_RETAINED

    resumed = service.resume(session.id)

    assert resumed.status == SessionStatus.RUNNING
    assert resumed.worktree_path is None
    assert resumed.git_state.missing_worktree is False
    assert resumed.cleanup.suggested is False


@pytest.mark.parametrize(
    "session_type",
    [SessionType.NEW_APP, SessionType.SPEC_CHANGE],
)
@pytest.mark.parametrize("entrypoint", _SYNCING_ENTRYPOINTS)
def test_required_session_missing_worktree_is_enforced_by_all_entrypoints(
    tmp_path: Path,
    session_type: SessionType,
    entrypoint: str,
):
    repo = make_repo(tmp_path)
    service = make_service(tmp_path, repo)
    session = service.create(session_type, "Required resume")
    worktree = Path(session.worktree_path)
    run_git(repo, "worktree", "remove", str(worktree))
    session.worktree_path = None
    session.status = SessionStatus.ABANDONED_RETAINED
    service.registry.save(session)

    observed = invoke_syncing_entrypoint(service, session.id, entrypoint)

    persisted = service.registry.load(session.id)
    assert observed.status == SessionStatus.MISSING_WORKTREE
    assert observed.worktree_path is None
    assert observed.git_state.missing_worktree is True
    assert observed.git_state.clean is False
    assert observed.cleanup.suggested is False
    assert persisted.status == SessionStatus.MISSING_WORKTREE
    assert persisted.git_state.missing_worktree is True


@pytest.mark.parametrize("entrypoint", _SYNCING_ENTRYPOINTS)
def test_review_without_worktree_remains_valid_across_entrypoints(
    tmp_path: Path,
    entrypoint: str,
):
    repo = make_repo(tmp_path)
    service = make_service(tmp_path, repo)
    session = service.create(
        SessionType.REVIEW,
        "Review without worktree",
        create_worktree=False,
    )

    observed = invoke_syncing_entrypoint(service, session.id, entrypoint)

    expected_status = (
        SessionStatus.ABANDONED_RETAINED
        if entrypoint == "archive"
        else SessionStatus.RUNNING
    )
    persisted = service.registry.load(session.id)
    assert observed.status == expected_status
    assert observed.worktree_path is None
    assert observed.git_state.missing_worktree is False
    assert persisted.status == expected_status
    assert persisted.git_state.missing_worktree is False


@pytest.mark.parametrize(
    "session_type",
    [SessionType.REVIEW, SessionType.DEPLOY],
)
def test_optional_no_worktree_session_tracks_base_availability(
    tmp_path: Path,
    session_type: SessionType,
):
    repo = make_repo(tmp_path)
    service = make_service(tmp_path, repo)
    session = service.create(
        session_type,
        "Optional no worktree outage",
        create_worktree=False,
    )
    base_head = run_git(repo, "rev-parse", "main")
    run_git(repo, "checkout", "-b", f"parking-{session_type.value}")
    run_git(repo, "update-ref", "-d", "refs/heads/main")

    unavailable = service.sync(session.id)

    assert unavailable.status == SessionStatus.RUNNING
    assert unavailable.git_state.base_missing is True
    assert unavailable.git_state.stale is True
    assert unavailable.git_state.missing_worktree is False
    assert service.checkpoint(session.id) is False

    archived = service.archive(session.id)

    assert archived.status == SessionStatus.RUNNING
    assert archived.git_state.base_missing is True

    archived.status = SessionStatus.ABANDONED_RETAINED
    service.registry.save(archived)
    resumed = service.resume(session.id)

    assert resumed.status == SessionStatus.ABANDONED_RETAINED
    assert resumed.git_state.base_missing is True

    run_git(repo, "update-ref", "refs/heads/main", base_head)
    restored = service.sync(session.id)

    assert restored.status == SessionStatus.ABANDONED_RETAINED
    assert restored.git_state.base_missing is False
    assert restored.git_state.stale is False


def test_optional_no_worktree_base_outage_suppresses_cleanup(tmp_path: Path):
    repo = make_repo(tmp_path)
    service = make_service(tmp_path, repo)
    session = service.create(
        SessionType.REVIEW,
        "No worktree cleanup outage",
        create_worktree=False,
    )
    session.cleanup.suggested = True
    service.registry.save(session)
    run_git(repo, "checkout", "-b", "parking-review-cleanup")
    run_git(repo, "update-ref", "-d", "refs/heads/main")

    unavailable = service.sync(session.id)

    assert unavailable.status == SessionStatus.RUNNING
    assert unavailable.git_state.base_missing is True
    assert unavailable.cleanup.suggested is False


def test_resume_reactivates_archived_dirty_and_preserves_marker(tmp_path: Path):
    repo = make_repo(tmp_path)
    service = make_service(tmp_path, repo)
    session = service.create(SessionType.FEATURE, "Resume dirty archive")
    worktree = Path(session.worktree_path)
    (worktree / "dirty.txt").write_text("dirty\n", encoding="utf-8")
    archived = service.archive(session.id, checkpoint=False)
    assert archived.status == SessionStatus.ARCHIVED_DIRTY
    assert archived.git_state.dirty_uncheckpointed is True

    resumed = service.resume(session.id)

    assert resumed.status == SessionStatus.RUNNING
    assert resumed.git_state.dirty_uncheckpointed is True
    assert resumed.cleanup.suggested is False


def test_resume_does_not_reactivate_missing_worktree(tmp_path: Path):
    repo = make_repo(tmp_path)
    service = make_service(tmp_path, repo)
    session = service.create(SessionType.FEATURE, "Resume missing")
    worktree = Path(session.worktree_path)
    service.archive(session.id, checkpoint=False)
    run_git(repo, "worktree", "remove", str(worktree))

    resumed = service.resume(session.id)

    assert resumed.status == SessionStatus.MISSING_WORKTREE
    assert resumed.git_state.missing_worktree is True


def test_resume_does_not_reactivate_branch_mismatch(tmp_path: Path):
    repo = make_repo(tmp_path)
    service = make_service(tmp_path, repo)
    session = service.create(SessionType.FEATURE, "Resume mismatch")
    worktree = Path(session.worktree_path)
    archived = service.archive(session.id, checkpoint=False)
    assert archived.status == SessionStatus.ABANDONED_RETAINED
    run_git(worktree, "checkout", "-b", "wrong-resume-branch")

    resumed = service.resume(session.id)

    assert resumed.status == SessionStatus.ABANDONED_RETAINED
    assert resumed.git_state.branch_mismatch is True


@pytest.mark.parametrize(
    "previous_status",
    [SessionStatus.MISSING_WORKTREE, SessionStatus.MERGED_RETAINED],
)
@pytest.mark.parametrize("entrypoint", _SYNCING_ENTRYPOINTS)
def test_branch_mismatch_precedes_base_missing_across_syncing_entrypoints(
    tmp_path: Path,
    previous_status: SessionStatus,
    entrypoint: str,
):
    repo = make_repo(tmp_path)
    service = make_service(tmp_path, repo)
    session = service.create(
        SessionType.FEATURE,
        f"Priority {previous_status.value} {entrypoint}",
    )
    worktree = Path(session.worktree_path)

    if previous_status == SessionStatus.MISSING_WORKTREE:
        run_git(repo, "worktree", "remove", str(worktree))
        missing = service.sync(session.id)
        assert missing.status == SessionStatus.MISSING_WORKTREE
        run_git(repo, "worktree", "add", str(worktree), session.branch)
    else:
        (worktree / "merged.txt").write_text("merged\n", encoding="utf-8")
        assert service.checkpoint(session.id) is True
        run_git(repo, "merge", "--no-ff", session.branch, "-m", "merge session")
        merged = service.sync(session.id)
        assert merged.status == SessionStatus.MERGED_RETAINED

    wrong_branch = f"wrong-{previous_status.value}-{entrypoint}"
    run_git(worktree, "checkout", "-b", wrong_branch)
    dirty_file = worktree / "mismatch-dirty.txt"
    dirty_file.write_text("do not commit\n", encoding="utf-8")
    before_head = run_git(worktree, "rev-parse", "HEAD")
    run_git(repo, "checkout", "-b", f"parking-{previous_status.value}-{entrypoint}")
    run_git(repo, "update-ref", "-d", "refs/heads/main")

    observed = invoke_syncing_entrypoint(service, session.id, entrypoint)

    assert observed.status == SessionStatus.RUNNING
    assert observed.git_state.missing_worktree is False
    assert observed.git_state.branch_mismatch is True
    assert observed.git_state.base_missing is True
    assert observed.cleanup.suggested is False
    assert run_git(worktree, "rev-parse", "HEAD") == before_head
    assert dirty_file.read_text(encoding="utf-8") == "do not commit\n"
    assert service.checkpoint(session.id) is False
    persisted = service.registry.load(session.id)
    assert persisted.status == SessionStatus.RUNNING
    assert persisted.git_state.branch_mismatch is True
    assert persisted.git_state.base_missing is True


def test_resume_preserves_clean_merged_retained_session(tmp_path: Path):
    repo = make_repo(tmp_path)
    service = make_service(tmp_path, repo)
    session = service.create(SessionType.FEATURE, "Resume merged")
    worktree = Path(session.worktree_path)
    (worktree / "merged.txt").write_text("merged\n", encoding="utf-8")
    assert service.checkpoint(session.id) is True
    run_git(repo, "merge", "--no-ff", session.branch, "-m", "merge session")
    assert service.sync(session.id).status == SessionStatus.MERGED_RETAINED

    resumed = service.resume(session.id)

    assert resumed.status == SessionStatus.MERGED_RETAINED
    assert resumed.git_state.merged_to_base is True
    assert resumed.cleanup.suggested is True


def test_resume_preserves_merged_orphan_session(tmp_path: Path):
    repo = make_repo(tmp_path)
    service = make_service(tmp_path, repo)
    branch = "session/S-099-feature-resume-orphan"
    worktree = tmp_path / "resume-orphan"
    run_git(repo, "worktree", "add", "-b", branch, str(worktree), "main")
    (worktree / "orphan.txt").write_text("orphan\n", encoding="utf-8")
    run_git(worktree, "add", "orphan.txt")
    run_git(worktree, "commit", "-m", "orphan change")
    run_git(repo, "merge", "--no-ff", branch, "-m", "merge orphan")
    orphan = next(item for item in service.reconcile() if item.branch == branch)

    resumed = service.resume(orphan.id)

    assert resumed.status == SessionStatus.ORPHAN_SESSION
    assert resumed.git_state.merged_to_base is True
    assert resumed.cleanup.suggested is True


def test_resume_preserves_blocked_session_without_recovered_base(tmp_path: Path):
    repo = make_repo(tmp_path)
    service = make_service(tmp_path, repo)
    session = service.create(SessionType.FEATURE, "Resume blocked")
    session.status = SessionStatus.BLOCKED_RETAINED
    session.git_state.base_missing = False
    service.registry.save(session)

    resumed = service.resume(session.id)

    assert resumed.status == SessionStatus.BLOCKED_RETAINED
    assert resumed.git_state.base_missing is False
    assert resumed.cleanup.suggested is False


def test_create_fetch_failure_has_no_registry_branch_or_worktree_side_effects(
    tmp_path: Path,
):
    repo = make_repo(tmp_path)
    add_origin(repo, tmp_path)
    service = make_service(tmp_path, repo)
    run_git(repo, "remote", "set-url", "origin", str(tmp_path / "missing-origin.git"))

    with pytest.raises(GitCommandError, match="failed to fetch origin"):
        service.create(SessionType.FEATURE, "Broken origin create")

    assert service.registry.list() == []
    assert not list(service.registry.root.glob("S-*.yaml"))
    assert run_git(repo, "branch", "--list", "session/*") == ""
    assert not service.worktree_parent.exists()


def test_sync_fetch_failure_does_not_update_registry_state(tmp_path: Path):
    repo = make_repo(tmp_path)
    add_origin(repo, tmp_path)
    service = make_service(tmp_path, repo)
    session = service.create(SessionType.FEATURE, "Fetch failure")
    before = service.registry.load(session.id)
    before_git_state = before.git_state.model_dump()
    run_git(repo, "remote", "set-url", "origin", str(tmp_path / "missing-origin.git"))

    with pytest.raises(GitCommandError, match="failed to fetch origin"):
        service.sync(session.id)

    persisted = service.registry.load(session.id)
    assert persisted.last_sync_at == before.last_sync_at
    assert persisted.git_state.model_dump() == before_git_state


def test_archive_fetch_failure_preserves_registry_and_head(tmp_path: Path):
    repo = make_repo(tmp_path)
    add_origin(repo, tmp_path)
    service = make_service(tmp_path, repo)
    session = service.create(SessionType.FEATURE, "Broken origin archive")
    worktree = Path(session.worktree_path)
    registry_path = service.registry.path_for(session.id)
    before_yaml = registry_path.read_bytes()
    before = service.registry.load(session.id)
    before_head = run_git(worktree, "rev-parse", "HEAD")
    run_git(repo, "remote", "set-url", "origin", str(tmp_path / "missing-origin.git"))

    with pytest.raises(GitCommandError, match="failed to fetch origin"):
        service.archive(session.id, checkpoint=False)

    persisted = service.registry.load(session.id)
    assert registry_path.read_bytes() == before_yaml
    assert persisted.head_commit == before.head_commit
    assert persisted.last_sync_at == before.last_sync_at
    assert run_git(worktree, "rev-parse", "HEAD") == before_head


def test_reconcile_fetch_failure_preserves_registry_and_head(tmp_path: Path):
    repo = make_repo(tmp_path)
    add_origin(repo, tmp_path)
    service = make_service(tmp_path, repo)
    session = service.create(SessionType.FEATURE, "Broken origin reconcile")
    worktree = Path(session.worktree_path)
    registry_path = service.registry.path_for(session.id)
    before_yaml = registry_path.read_bytes()
    before = service.registry.load(session.id)
    before_head = run_git(worktree, "rev-parse", "HEAD")
    run_git(repo, "remote", "set-url", "origin", str(tmp_path / "missing-origin.git"))

    with pytest.raises(GitCommandError, match="failed to fetch origin"):
        service.reconcile()

    persisted = service.registry.load(session.id)
    assert registry_path.read_bytes() == before_yaml
    assert persisted.head_commit == before.head_commit
    assert persisted.last_sync_at == before.last_sync_at
    assert run_git(worktree, "rev-parse", "HEAD") == before_head


def test_sync_recovers_running_after_new_commit_on_merged_session(tmp_path: Path):
    repo = make_repo(tmp_path)
    service = make_service(tmp_path, repo)
    session = service.create(SessionType.FEATURE, "Continue after merge")
    worktree = Path(session.worktree_path)
    (worktree / "first.txt").write_text("first\n", encoding="utf-8")
    assert service.checkpoint(session.id) is True
    run_git(repo, "merge", "--no-ff", session.branch, "-m", "merge session")

    merged = service.sync(session.id)

    assert merged.status == SessionStatus.MERGED_RETAINED
    assert merged.cleanup.suggested is True

    (worktree / "second.txt").write_text("second\n", encoding="utf-8")
    assert service.checkpoint(session.id) is True
    continued = service.sync(session.id)

    assert continued.status == SessionStatus.RUNNING
    assert continued.git_state.merged_to_base is False
    assert continued.cleanup.suggested is False


def test_branch_mismatch_does_not_become_merged_retained(tmp_path: Path):
    repo = make_repo(tmp_path)
    service = make_service(tmp_path, repo)
    session = service.create(SessionType.FEATURE, "Mismatch merged")
    worktree = Path(session.worktree_path)
    wrong_branch = "wrong-merged-branch"
    run_git(worktree, "checkout", "-b", wrong_branch)
    (worktree / "wrong.txt").write_text("wrong\n", encoding="utf-8")
    run_git(worktree, "add", "wrong.txt")
    run_git(worktree, "commit", "-m", "wrong branch commit")
    run_git(repo, "merge", "--no-ff", wrong_branch, "-m", "merge wrong branch")

    synced = service.sync(session.id)

    assert synced.git_state.branch_mismatch is True
    assert synced.git_state.merged_to_base is False
    assert synced.git_state.retained is False
    assert synced.cleanup.suggested is False
    assert synced.status != SessionStatus.MERGED_RETAINED


def test_checkpoint_commits_dirty_changes(tmp_path: Path):
    repo = make_repo(tmp_path)
    service = make_service(tmp_path, repo)
    session = service.create(SessionType.FEATURE, "Checkpoint")
    worktree = Path(session.worktree_path)
    (worktree / "runbook.md").write_text("# Runbook\n", encoding="utf-8")

    created = service.checkpoint(session.id)
    synced = service.sync(session.id)

    assert created is True
    assert synced.git_state.clean is True
    assert synced.git_state.ahead == 1


def test_checkpoint_fetches_once_and_refreshes_registry_locally(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    repo = make_repo(tmp_path)
    service = make_service(tmp_path, repo)
    session = service.create(SessionType.FEATURE, "Single fetch checkpoint")
    worktree = Path(session.worktree_path)
    before_head = run_git(worktree, "rev-parse", "HEAD")
    (worktree / "single-fetch.txt").write_text("single fetch\n", encoding="utf-8")
    fetch_calls = 0

    def fetch_once() -> None:
        nonlocal fetch_calls
        fetch_calls += 1
        if fetch_calls > 1:
            raise GitCommandError("unexpected second fetch")

    monkeypatch.setattr(service, "_fetch_origin_or_raise", fetch_once)

    created = service.checkpoint(session.id)

    after_head = run_git(worktree, "rev-parse", "HEAD")
    persisted = service.registry.load(session.id)
    assert created is True
    assert fetch_calls == 1
    assert after_head != before_head
    assert persisted.git_state.clean is True
    assert persisted.head_commit == after_head


def test_checkpoint_bypasses_hook_and_uses_custom_message(tmp_path: Path):
    repo = make_repo(tmp_path)
    service = make_service(tmp_path, repo)
    session = service.create(SessionType.FEATURE, "Hook bypass")
    worktree = Path(session.worktree_path)
    hooks_dir = Path(
        run_git(worktree, "rev-parse", "--path-format=absolute", "--git-common-dir")
    ) / "hooks"
    hooks_dir.mkdir(parents=True, exist_ok=True)
    pre_commit = hooks_dir / "pre-commit"
    pre_commit.write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
    pre_commit.chmod(0o755)
    (worktree / "hooked.txt").write_text("hook bypassed\n", encoding="utf-8")

    created = service.checkpoint(session.id, message="custom checkpoint")

    assert created is True
    assert run_git(worktree, "log", "-1", "--pretty=%s") == "custom checkpoint"
    assert run_git(worktree, "show", "HEAD:hooked.txt") == "hook bypassed"


@pytest.mark.parametrize("action", ["checkpoint", "archive"])
def test_checkpoint_commit_failure_refreshes_registry_and_propagates(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    action: str,
):
    repo = make_repo(tmp_path)
    service = make_service(tmp_path, repo)
    session = service.create(SessionType.FEATURE, f"Failed {action}")
    worktree = Path(session.worktree_path)
    (worktree / "invalid-date.txt").write_text("dirty\n", encoding="utf-8")
    before_head = run_git(worktree, "rev-parse", "HEAD")
    refresh_calls = 0
    original_refresh = service._refresh_and_save_locked

    def refresh_and_count(current):
        nonlocal refresh_calls
        refresh_calls += 1
        return original_refresh(current)

    monkeypatch.setattr(service, "_refresh_and_save_locked", refresh_and_count)
    monkeypatch.setenv("GIT_AUTHOR_DATE", "not-a-valid-git-date")

    with pytest.raises(GitCommandError, match="git commit failed:.*invalid date"):
        if action == "checkpoint":
            service.checkpoint(session.id)
        else:
            service.archive(session.id)

    persisted = service.registry.load(session.id)
    assert refresh_calls == 1
    assert persisted.git_state.clean is False
    assert persisted.head_commit == before_head
    assert run_git(worktree, "rev-parse", "HEAD") == before_head
    assert run_git(worktree, "diff", "--cached", "--name-only") == ""
    assert "invalid-date.txt" in run_git(worktree, "status", "--porcelain")


def test_checkpoint_disables_repository_commit_signing(tmp_path: Path):
    repo = make_repo(tmp_path)
    service = make_service(tmp_path, repo)
    session = service.create(SessionType.FEATURE, "Unsigned checkpoint")
    worktree = Path(session.worktree_path)
    run_git(repo, "config", "commit.gpgSign", "true")
    run_git(repo, "config", "gpg.program", str(tmp_path / "missing-gpg"))
    (worktree / "unsigned.txt").write_text("unsigned\n", encoding="utf-8")

    created = service.checkpoint(session.id)

    assert created is True
    assert run_git(worktree, "show", "HEAD:unsigned.txt") == "unsigned"


def test_checkpoint_timeout_refreshes_registry_after_commit_side_effect(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    repo = make_repo(tmp_path)
    service = make_service(tmp_path, repo)
    session = service.create(SessionType.FEATURE, "Timeout checkpoint")
    worktree = Path(session.worktree_path)
    (worktree / "timeout.txt").write_text("timeout\n", encoding="utf-8")
    before_head = run_git(worktree, "rev-parse", "HEAD")
    original_git = engineering_session_service.git

    def timeout_after_commit(repo_path: str | Path, *args: str, **kwargs):
        result = original_git(repo_path, *args, **kwargs)
        if "update-ref" in args:
            raise subprocess.TimeoutExpired(["git", *args], timeout=90)
        return result

    monkeypatch.setattr(
        engineering_session_service,
        "git",
        timeout_after_commit,
    )

    with pytest.raises(subprocess.TimeoutExpired):
        service.checkpoint(session.id)

    persisted = service.registry.load(session.id)
    assert persisted.head_commit != before_head
    assert persisted.head_commit == run_git(worktree, "rev-parse", "HEAD")
    assert persisted.git_state.clean is True


def test_checkpoint_timeout_with_external_index_change_cleans_temporary_index(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    repo = make_repo(tmp_path)
    service = make_service(tmp_path, repo)
    session = service.create(SessionType.FEATURE, "Timeout index race")
    worktree = Path(session.worktree_path)
    changed = worktree / "timeout-index.txt"
    changed.write_text("timeout index\n", encoding="utf-8")
    index_path = Path(
        run_git(
            worktree,
            "rev-parse",
            "--path-format=absolute",
            "--git-path",
            "index",
        )
    )
    original_git = engineering_session_service.git

    def timeout_after_external_index_change(
        repo_path: str | Path,
        *args: str,
        **kwargs,
    ):
        result = original_git(repo_path, *args, **kwargs)
        if "update-ref" in args:
            run_git(worktree, "add", changed.name)
            raise subprocess.TimeoutExpired(["git", *args], timeout=90)
        return result

    monkeypatch.setattr(
        engineering_session_service,
        "git",
        timeout_after_external_index_change,
    )

    with pytest.raises(subprocess.TimeoutExpired):
        service.checkpoint(session.id)

    assert not list(
        index_path.parent.glob(".agentic-checkpoint-index.*")
    )


def test_checkpoint_cleanup_failure_does_not_mask_git_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    repo = make_repo(tmp_path)
    service = make_service(tmp_path, repo)
    session = service.create(SessionType.FEATURE, "Cleanup diagnostics")
    worktree = Path(session.worktree_path)
    (worktree / "changed.txt").write_text("changed\n", encoding="utf-8")
    original_git = engineering_session_service.git
    original_unlink = Path.unlink

    def fail_git_add(repo_path: str | Path, *args: str, **kwargs):
        if "add" in args and "-A" in args:
            raise GitCommandError("git add primary failure")
        return original_git(repo_path, *args, **kwargs)

    def fail_temporary_index_cleanup(path: Path, *args, **kwargs):
        if path.name.startswith(".agentic-checkpoint-index."):
            raise OSError("temporary index cleanup failed")
        return original_unlink(path, *args, **kwargs)

    monkeypatch.setattr(engineering_session_service, "git", fail_git_add)
    monkeypatch.setattr(Path, "unlink", fail_temporary_index_cleanup)

    with pytest.raises(
        GitCommandError,
        match="git add primary failure",
    ) as exc_info:
        service.checkpoint(session.id)

    assert any(
        "temporary index cleanup failed" in note
        for note in getattr(exc_info.value, "__notes__", [])
    )


def test_checkpoint_post_publish_cleanup_failure_remains_successful(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    repo = make_repo(tmp_path)
    service = make_service(tmp_path, repo)
    session = service.create(SessionType.FEATURE, "Published cleanup warning")
    worktree = Path(session.worktree_path)
    (worktree / "changed.txt").write_text("changed\n", encoding="utf-8")
    original_unlink = Path.unlink

    def fail_published_temporary_cleanup(path: Path, *args, **kwargs):
        if path.name.startswith(".agentic-checkpoint-index."):
            raise OSError("published temporary cleanup failed")
        return original_unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", fail_published_temporary_cleanup)

    assert service.checkpoint(session.id) is True

    persisted = service.registry.load(session.id)
    assert persisted.git_state.clean is True
    assert any(
        "published temporary cleanup failed" in warning
        for warning in service.registry.last_read_errors
    )


@pytest.mark.skipif(os.name == "nt", reason="POSIX index permissions")
def test_checkpoint_preserves_existing_index_permissions(tmp_path: Path):
    repo = make_repo(tmp_path)
    service = make_service(tmp_path, repo)
    session = service.create(SessionType.FEATURE, "Index permissions")
    worktree = Path(session.worktree_path)
    index_path = Path(
        run_git(
            worktree,
            "rev-parse",
            "--path-format=absolute",
            "--git-path",
            "index",
        )
    )
    index_path.chmod(0o664)
    (worktree / "changed.txt").write_text("changed\n", encoding="utf-8")
    assert service._index_mode(session) == 0o664

    assert service.checkpoint(session.id) is True

    assert stat.S_IMODE(index_path.stat().st_mode) == 0o664


def test_checkpoint_fsyncs_index_directory_after_publish(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    repo = make_repo(tmp_path)
    service = make_service(tmp_path, repo)
    session = service.create(SessionType.FEATURE, "Index directory fsync")
    worktree = Path(session.worktree_path)
    index_path = Path(
        run_git(
            worktree,
            "rev-parse",
            "--path-format=absolute",
            "--git-path",
            "index",
        )
    )
    (worktree / "changed.txt").write_text("changed\n", encoding="utf-8")
    fsynced_directories: list[Path] = []
    monkeypatch.setattr(
        EngineeringSessionService,
        "_fsync_directory",
        staticmethod(
            lambda path: fsynced_directories.append(Path(path).resolve())
        ),
        raising=False,
    )

    assert service.checkpoint(session.id) is True

    assert fsynced_directories == [index_path.parent.resolve()]


def test_checkpoint_index_publish_lock_preserves_external_staging(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    repo = make_repo(tmp_path)
    service = make_service(tmp_path, repo)
    session = service.create(SessionType.FEATURE, "Index publish lock")
    worktree = Path(session.worktree_path)
    (worktree / "checkpoint.txt").write_text("checkpoint\n", encoding="utf-8")
    external = worktree / "external.txt"
    index_path = Path(
        run_git(
            worktree,
            "rev-parse",
            "--path-format=absolute",
            "--git-path",
            "index",
        )
    )
    original_open = engineering_session_service.os.open
    raced = False
    before_head = run_git(worktree, "rev-parse", "HEAD")

    def race_before_index_lock(path, flags, mode=0o777):
        nonlocal raced
        if not raced and Path(path) == index_path.with_name("index.lock"):
            raced = True
            external.write_text("external\n", encoding="utf-8")
            run_git(worktree, "add", external.name)
        return original_open(path, flags, mode)

    monkeypatch.setattr(
        engineering_session_service.os,
        "open",
        race_before_index_lock,
    )

    with pytest.raises(
        GitCommandError,
        match="live index publish was refused",
    ):
        service.checkpoint(session.id)

    assert raced is True
    after_head = run_git(worktree, "rev-parse", "HEAD")
    assert after_head != before_head
    assert service.registry.load(session.id).head_commit == after_head
    cached = run_git(worktree, "diff", "--cached", "--name-only").splitlines()
    assert "external.txt" in cached
    assert "external.txt" not in run_git(
        worktree,
        "ls-files",
        "--others",
        "--exclude-standard",
    ).splitlines()


def test_checkpoint_does_not_delete_a_new_index_lock_after_publish(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    repo = make_repo(tmp_path)
    service = make_service(tmp_path, repo)
    session = service.create(SessionType.FEATURE, "New index lock")
    worktree = Path(session.worktree_path)
    (worktree / "checkpoint.txt").write_text("checkpoint\n", encoding="utf-8")
    index_path = Path(
        run_git(
            worktree,
            "rev-parse",
            "--path-format=absolute",
            "--git-path",
            "index",
        )
    )
    index_lock = index_path.with_name("index.lock")
    original_replace = engineering_session_service.os.replace

    def create_new_lock_after_publish(source, target):
        original_replace(source, target)
        if Path(source) == index_lock:
            index_lock.write_bytes(b"new owner")

    monkeypatch.setattr(
        engineering_session_service.os,
        "replace",
        create_new_lock_after_publish,
    )

    assert service.checkpoint(session.id) is True

    assert index_lock.read_bytes() == b"new owner"
    index_lock.unlink()


def test_checkpoint_ref_change_before_index_publish_reports_partial_success(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    repo = make_repo(tmp_path)
    service = make_service(tmp_path, repo)
    session = service.create(SessionType.FEATURE, "Branch reset race")
    worktree = Path(session.worktree_path)
    changed = worktree / "changed.txt"
    changed.write_text("changed\n", encoding="utf-8")
    before_head = run_git(worktree, "rev-parse", "HEAD")
    original_publish = service._publish_checkpoint_index
    raced = False

    def reset_branch_before_publish(*args, **kwargs):
        nonlocal raced
        if not raced:
            raced = True
            run_git(
                repo,
                "update-ref",
                f"refs/heads/{session.branch}",
                before_head,
            )
        return original_publish(*args, **kwargs)

    monkeypatch.setattr(
        service,
        "_publish_checkpoint_index",
        reset_branch_before_publish,
    )

    with pytest.raises(
        GitCommandError,
        match="live index publish was refused",
    ):
        service.checkpoint(session.id)

    assert raced is True
    assert run_git(repo, "rev-parse", session.branch) == before_head
    assert run_git(worktree, "diff", "--cached", "--name-only") == ""
    assert changed.name in run_git(
        worktree,
        "ls-files",
        "--others",
        "--exclude-standard",
    ).splitlines()


def test_checkpoint_branch_lock_blocks_reset_during_index_replace(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    repo = make_repo(tmp_path)
    service = make_service(tmp_path, repo)
    session = service.create(SessionType.FEATURE, "Branch lock publish")
    worktree = Path(session.worktree_path)
    changed = worktree / "changed.txt"
    changed.write_text("changed\n", encoding="utf-8")
    before_head = run_git(worktree, "rev-parse", "HEAD")
    index_path = Path(
        run_git(
            worktree,
            "rev-parse",
            "--path-format=absolute",
            "--git-path",
            "index",
        )
    )
    index_lock = index_path.with_name("index.lock")
    original_replace = engineering_session_service.os.replace
    reset_returncode: int | None = None

    def attempt_reset_before_index_replace(source, target):
        nonlocal reset_returncode
        if Path(source) == index_lock:
            reset = subprocess.run(
                [
                    "git",
                    "-C",
                    str(repo),
                    "update-ref",
                    f"refs/heads/{session.branch}",
                    before_head,
                ],
                capture_output=True,
                text=True,
            )
            reset_returncode = reset.returncode
        return original_replace(source, target)

    monkeypatch.setattr(
        engineering_session_service.os,
        "replace",
        attempt_reset_before_index_replace,
    )

    assert service.checkpoint(session.id) is True

    assert reset_returncode not in {None, 0}
    assert run_git(repo, "rev-parse", session.branch) != before_head
    assert run_git(worktree, "show", f"HEAD:{changed.name}") == "changed"


def test_checkpoint_index_publish_failure_refreshes_registry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    repo = make_repo(tmp_path)
    service = make_service(tmp_path, repo)
    session = service.create(SessionType.FEATURE, "Index publish failure")
    worktree = Path(session.worktree_path)
    (worktree / "publish-failure.txt").write_text("failure\n", encoding="utf-8")
    before_head = run_git(worktree, "rev-parse", "HEAD")

    def fail_publish(*_args, **_kwargs):
        raise OSError("index publish failed")

    monkeypatch.setattr(service, "_publish_checkpoint_index", fail_publish)

    with pytest.raises(OSError, match="index publish failed"):
        service.checkpoint(session.id)

    after_head = run_git(worktree, "rev-parse", "HEAD")
    persisted = service.registry.load(session.id)
    assert after_head != before_head
    assert persisted.head_commit == after_head


def test_checkpoint_recovery_failure_does_not_mask_primary_git_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    repo = make_repo(tmp_path)
    service = make_service(tmp_path, repo)
    session = service.create(SessionType.FEATURE, "Recovery error")
    worktree = Path(session.worktree_path)
    (worktree / "recovery.txt").write_text("recovery\n", encoding="utf-8")
    original_git = engineering_session_service.git

    def fail_add(repo_path: str | Path, *args: str, **kwargs):
        if args[-2:] == ("add", "-A"):
            raise GitCommandError("primary add failure")
        return original_git(repo_path, *args, **kwargs)

    def fail_refresh(_session):
        raise OSError("secondary refresh failure")

    monkeypatch.setattr(engineering_session_service, "git", fail_add)
    monkeypatch.setattr(service, "_refresh_and_save_locked", fail_refresh)

    with pytest.raises(GitCommandError, match="primary add failure") as exc_info:
        service.checkpoint(session.id)

    notes = getattr(exc_info.value, "__notes__", [])
    assert any("secondary refresh failure" in note for note in notes)


def test_checkpoint_rejects_unresolved_merge_conflict_without_mutation(
    tmp_path: Path,
):
    repo = make_repo(tmp_path)
    service = make_service(tmp_path, repo)
    session = service.create(SessionType.FEATURE, "Conflict checkpoint")
    worktree = Path(session.worktree_path)
    (worktree / "README.md").write_text("session\n", encoding="utf-8")
    run_git(worktree, "add", "README.md")
    run_git(worktree, "commit", "-m", "session change")
    (repo / "README.md").write_text("main\n", encoding="utf-8")
    run_git(repo, "add", "README.md")
    run_git(repo, "commit", "-m", "main change")
    merge = subprocess.run(
        ["git", "-C", str(worktree), "merge", "main"],
        check=False,
        capture_output=True,
        text=True,
    )
    assert merge.returncode != 0
    before_head = run_git(worktree, "rev-parse", "HEAD")
    merge_head = Path(
        run_git(
            worktree,
            "rev-parse",
            "--path-format=absolute",
            "--git-path",
            "MERGE_HEAD",
        )
    )
    assert merge_head.exists()
    assert run_git(worktree, "ls-files", "--unmerged")

    created = service.checkpoint(session.id)

    assert created is False
    assert run_git(worktree, "rev-parse", "HEAD") == before_head
    assert merge_head.exists()
    assert run_git(worktree, "ls-files", "--unmerged")
    assert "<<<<<<< HEAD" in (worktree / "README.md").read_text(encoding="utf-8")


def test_archive_default_checkpoint_rejects_merge_in_progress_without_mutation(
    tmp_path: Path,
):
    repo = make_repo(tmp_path)
    service = make_service(tmp_path, repo)
    session = service.create(SessionType.FEATURE, "Merge archive")
    worktree = Path(session.worktree_path)
    run_git(repo, "checkout", "-b", "integration")
    (repo / "integration.txt").write_text("integration\n", encoding="utf-8")
    run_git(repo, "add", "integration.txt")
    run_git(repo, "commit", "-m", "integration change")
    run_git(repo, "checkout", "main")
    run_git(worktree, "merge", "--no-ff", "--no-commit", "integration")
    before_head = run_git(worktree, "rev-parse", "HEAD")
    merge_head = Path(
        run_git(
            worktree,
            "rev-parse",
            "--path-format=absolute",
            "--git-path",
            "MERGE_HEAD",
        )
    )
    assert merge_head.exists()
    assert run_git(worktree, "diff", "--cached", "--name-only") == "integration.txt"

    archived = service.archive(session.id)

    assert archived.status == SessionStatus.ARCHIVED_DIRTY
    assert archived.git_state.dirty_uncheckpointed is True
    assert run_git(worktree, "rev-parse", "HEAD") == before_head
    assert merge_head.exists()
    assert run_git(worktree, "diff", "--cached", "--name-only") == "integration.txt"


def test_checkpoint_missing_worktree_saves_missing_status(tmp_path: Path):
    repo = make_repo(tmp_path)
    service = make_service(tmp_path, repo)
    session = service.create(SessionType.FEATURE, "Missing checkpoint")
    worktree = Path(session.worktree_path)
    run_git(repo, "worktree", "remove", str(worktree))

    created = service.checkpoint(session.id)

    persisted = service.registry.load(session.id)
    assert created is False
    assert persisted.status == SessionStatus.MISSING_WORKTREE
    assert persisted.git_state.missing_worktree is True


def test_checkpoint_merged_clean_session_saves_merged_status(tmp_path: Path):
    repo = make_repo(tmp_path)
    service = make_service(tmp_path, repo)
    session = service.create(SessionType.FEATURE, "Merged checkpoint")
    worktree = Path(session.worktree_path)
    (worktree / "merged.txt").write_text("merged\n", encoding="utf-8")
    assert service.checkpoint(session.id) is True
    run_git(repo, "merge", "--no-ff", session.branch, "-m", "merge session")

    created = service.checkpoint(session.id)

    persisted = service.registry.load(session.id)
    assert created is False
    assert persisted.status == SessionStatus.MERGED_RETAINED
    assert persisted.cleanup.suggested is True


def test_archive_dirty_without_checkpoint_marks_archived_dirty(tmp_path: Path):
    repo = make_repo(tmp_path)
    service = make_service(tmp_path, repo)
    session = service.create(SessionType.FEATURE, "Archive dirty")
    worktree = Path(session.worktree_path)
    (worktree / "notes.txt").write_text("unfinished\n", encoding="utf-8")

    archived = service.archive(session.id, checkpoint=False)
    synced = service.sync(session.id)

    assert archived.status == SessionStatus.ARCHIVED_DIRTY
    assert archived.git_state.dirty_uncheckpointed is True
    assert synced.git_state.dirty_uncheckpointed is True


def test_archive_preserves_blocked_session_and_disables_cleanup(
    tmp_path: Path,
):
    repo = make_repo(tmp_path)
    service = make_service(tmp_path, repo)
    session = service.create(SessionType.FEATURE, "Blocked archive")
    worktree = Path(session.worktree_path)
    (worktree / "blocked.txt").write_text("blocked\n", encoding="utf-8")
    assert service.checkpoint(session.id) is True
    run_git(repo, "merge", "--no-ff", session.branch, "-m", "merge blocked")
    session = service.registry.load(session.id)
    session.status = SessionStatus.BLOCKED_RETAINED
    service.registry.save(session)

    archived = service.archive(session.id, checkpoint=False)

    assert archived.status == SessionStatus.BLOCKED_RETAINED
    assert archived.git_state.merged_to_base is True
    assert archived.cleanup.suggested is False


def test_sync_missing_worktree_preserves_dirty_uncheckpointed_marker(tmp_path: Path):
    repo = make_repo(tmp_path)
    service = make_service(tmp_path, repo)
    session = service.create(SessionType.FEATURE, "Missing dirty archive")
    worktree = Path(session.worktree_path)
    (worktree / "dirty.txt").write_text("dirty\n", encoding="utf-8")
    archived = service.archive(session.id, checkpoint=False)
    assert archived.status == SessionStatus.ARCHIVED_DIRTY
    assert archived.git_state.dirty_uncheckpointed is True
    shutil.rmtree(worktree)

    missing = service.sync(session.id)

    assert missing.status == SessionStatus.MISSING_WORKTREE
    assert missing.git_state.dirty_uncheckpointed is True


def test_archive_missing_clean_worktree_preserves_missing_status(tmp_path: Path):
    repo = make_repo(tmp_path)
    service = make_service(tmp_path, repo)
    session = service.create(SessionType.FEATURE, "Archive missing")
    worktree = Path(session.worktree_path)
    run_git(repo, "worktree", "remove", str(worktree))

    archived = service.archive(session.id)

    persisted = service.registry.load(session.id)
    assert archived.status == SessionStatus.MISSING_WORKTREE
    assert persisted.status == SessionStatus.MISSING_WORKTREE
    assert persisted.git_state.dirty_uncheckpointed is False


def test_default_list_applies_and_persists_static_worktree_invariants_without_git_io(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    repo = make_repo(tmp_path)
    service = make_service(tmp_path, repo)
    required = service.create(SessionType.NEW_APP, "Required list")
    required.worktree_path = None
    required.status = SessionStatus.RUNNING
    required.git_state.missing_worktree = False
    service.registry.save(required)
    control = service.create(SessionType.FEATURE, "Control list")
    control.worktree_path = str(repo.resolve())
    control.status = SessionStatus.RUNNING
    control.git_state.missing_worktree = False
    service.registry.save(control)
    review = service.create(
        SessionType.REVIEW,
        "Review list",
        create_worktree=False,
    )

    def fail_git_io():
        raise AssertionError("default list must not access Git")

    monkeypatch.setattr(service, "_fetch_origin_or_raise", fail_git_io)
    monkeypatch.setattr(service, "_active_worktrees", fail_git_io)

    listed = {session.id: session for session in service.list()}

    assert listed[required.id].status == SessionStatus.MISSING_WORKTREE
    assert listed[required.id].git_state.missing_worktree is True
    assert listed[control.id].status == SessionStatus.MISSING_WORKTREE
    assert listed[control.id].git_state.missing_worktree is True
    assert listed[review.id].status == SessionStatus.RUNNING
    assert listed[review.id].git_state.missing_worktree is False
    assert service.registry.load(required.id).status == SessionStatus.MISSING_WORKTREE
    assert service.registry.load(control.id).status == SessionStatus.MISSING_WORKTREE
    assert service.registry.load(review.id).status == SessionStatus.RUNNING


def test_default_list_persists_static_base_missing_cleanup_without_git_io(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    repo = make_repo(tmp_path)
    service = make_service(tmp_path, repo)
    session = service.create(SessionType.FEATURE, "Static cleanup list")
    session.status = SessionStatus.MERGED_RETAINED
    session.git_state.base_missing = True
    session.cleanup.suggested = True
    service.registry.save(session)

    def fail_git_io():
        raise AssertionError("default list must not fetch or scan worktrees")

    monkeypatch.setattr(service, "_fetch_origin_or_raise", fail_git_io)
    monkeypatch.setattr(service, "_active_worktrees", fail_git_io)

    listed = service.list(sync=False)

    assert listed[0].status == SessionStatus.MERGED_RETAINED
    assert listed[0].git_state.base_missing is True
    assert listed[0].cleanup.suggested is False
    persisted = service.registry.load(session.id)
    assert persisted.status == SessionStatus.MERGED_RETAINED
    assert persisted.git_state.base_missing is True
    assert persisted.cleanup.suggested is False


def test_checkpoint_archived_dirty_session_becomes_abandoned_when_clean(tmp_path: Path):
    repo = make_repo(tmp_path)
    service = make_service(tmp_path, repo)
    session = service.create(SessionType.FEATURE, "Finish archived work")
    worktree = Path(session.worktree_path)
    (worktree / "finish.txt").write_text("finish\n", encoding="utf-8")
    archived = service.archive(session.id, checkpoint=False)
    assert archived.status == SessionStatus.ARCHIVED_DIRTY

    created = service.checkpoint(session.id)

    persisted = service.registry.load(session.id)
    assert created is True
    assert persisted.status == SessionStatus.ABANDONED_RETAINED
    assert persisted.git_state.clean is True
    assert persisted.git_state.dirty_uncheckpointed is False
    assert persisted.cleanup.suggested is False


def test_slow_fetch_does_not_hold_registry_transaction_lock(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    repo = make_repo(tmp_path)
    sync_service = make_service(tmp_path, repo)
    session = sync_service.create(SessionType.FEATURE, "Slow fetch")
    list_service = make_service(tmp_path, repo)
    fetch_started = Event()
    release_fetch = Event()

    def slow_fetch():
        fetch_started.set()
        assert release_fetch.wait(timeout=5)

    monkeypatch.setattr(sync_service, "_fetch_origin_or_raise", slow_fetch)
    with ThreadPoolExecutor(max_workers=2) as executor:
        sync_future = executor.submit(sync_service.sync, session.id)
        assert fetch_started.wait(timeout=2)
        list_future = executor.submit(list_service.list)
        time.sleep(0.2)
        list_completed_before_fetch = list_future.done()
        release_fetch.set()
        sync_future.result(timeout=5)
        listed = list_future.result(timeout=5)

    assert list_completed_before_fetch is True
    assert [item.id for item in listed] == [session.id]


def test_checkpoint_rejects_branch_mismatch(tmp_path: Path):
    repo = make_repo(tmp_path)
    service = make_service(tmp_path, repo)
    session = service.create(SessionType.FEATURE, "Branch mismatch")
    worktree = Path(session.worktree_path)
    run_git(worktree, "checkout", "-b", "wrong-branch")
    (worktree / "wrong.txt").write_text("wrong\n", encoding="utf-8")

    created = service.checkpoint(session.id)

    assert created is False
    assert run_git(worktree, "status", "--porcelain")


def test_checkpoint_rechecks_branch_after_staging(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    repo = make_repo(tmp_path)
    service = make_service(tmp_path, repo)
    session = service.create(SessionType.FEATURE, "Branch race")
    worktree = Path(session.worktree_path)
    (worktree / "race.txt").write_text("race\n", encoding="utf-8")
    session_head = run_git(worktree, "rev-parse", "HEAD")
    original_git = engineering_session_service.git
    switched = False

    def switching_git(repo_path: str | Path, *args: str, **kwargs):
        nonlocal switched
        if not switched and args[-2:] == ("add", "-A"):
            switched = True
            run_git(worktree, "checkout", "-b", "wrong-target")
        return original_git(repo_path, *args, **kwargs)

    monkeypatch.setattr(engineering_session_service, "git", switching_git)

    created = service.checkpoint(session.id)

    assert switched is True
    assert created is False
    assert run_git(repo, "rev-parse", session.branch) == session_head
    assert run_git(worktree, "branch", "--show-current") == "wrong-target"
    assert run_git(worktree, "diff", "--cached", "--name-only") == ""
    persisted = service.registry.load(session.id)
    assert persisted.git_state.branch_mismatch is True


def test_checkpoint_never_updates_the_branch_selected_by_an_external_checkout(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    repo = make_repo(tmp_path)
    service = make_service(tmp_path, repo)
    session = service.create(SessionType.FEATURE, "Commit branch race")
    worktree = Path(session.worktree_path)
    (worktree / "race-after-check.txt").write_text("race\n", encoding="utf-8")
    session_head = run_git(worktree, "rev-parse", "HEAD")
    original_git = engineering_session_service.git
    switched = False

    def switching_git(repo_path: str | Path, *args: str, **kwargs):
        nonlocal switched
        if not switched and (
            "commit" in args
            or "commit-tree" in args
        ):
            switched = True
            run_git(worktree, "checkout", "-b", "wrong-after-check")
        return original_git(repo_path, *args, **kwargs)

    monkeypatch.setattr(engineering_session_service, "git", switching_git)

    created = service.checkpoint(session.id)

    assert switched is True
    assert created is False
    assert run_git(repo, "rev-parse", session.branch) == session_head
    assert run_git(repo, "rev-parse", "wrong-after-check") == session_head
    assert run_git(worktree, "diff", "--cached", "--name-only") == ""
    persisted = service.registry.load(session.id)
    assert persisted.git_state.branch_mismatch is True


def test_control_worktree_duplicate_branch_is_ambiguous(
    tmp_path: Path,
):
    repo = make_repo(tmp_path)
    service = make_service(tmp_path, repo)
    session = service.create(SessionType.FEATURE, "Control duplicate")
    run_git(
        repo,
        "checkout",
        "--ignore-other-worktrees",
        session.branch,
    )

    synced = service.sync(session.id)

    assert synced.status == SessionStatus.AMBIGUOUS_WORKTREE
    assert synced.git_state.worktree_ambiguous is True
    assert service.checkpoint(session.id) is False


def test_duplicate_worktrees_for_branch_are_blocked_without_rebinding(
    tmp_path: Path,
):
    repo = make_repo(tmp_path)
    service = make_service(tmp_path, repo)
    session = service.create(SessionType.FEATURE, "Duplicate worktree")
    original = Path(session.worktree_path)
    duplicate = tmp_path / "duplicate"
    run_git(
        repo,
        "worktree",
        "add",
        "--force",
        str(duplicate),
        session.branch,
    )
    (duplicate / "duplicate.txt").write_text("duplicate\n", encoding="utf-8")

    synced = service.sync(session.id)

    assert synced.status == SessionStatus.AMBIGUOUS_WORKTREE
    assert synced.worktree_path == str(original)
    assert synced.git_state.worktree_ambiguous is True
    assert service.checkpoint(session.id) is False
    assert run_git(duplicate, "status", "--porcelain")


def test_blocked_lifecycle_survives_ambiguous_worktree_recovery(tmp_path: Path):
    repo = make_repo(tmp_path)
    service = make_service(tmp_path, repo)
    session = service.create(SessionType.FEATURE, "Blocked ambiguity")
    session.status = SessionStatus.BLOCKED_RETAINED
    service.registry.save(session)
    duplicate = tmp_path / "blocked-duplicate"
    run_git(
        repo,
        "worktree",
        "add",
        "--force",
        str(duplicate),
        session.branch,
    )

    ambiguous = service.sync(session.id)
    run_git(repo, "worktree", "remove", "--force", str(duplicate))
    recovered = service.sync(session.id)

    assert ambiguous.status == SessionStatus.AMBIGUOUS_WORKTREE
    assert recovered.status == SessionStatus.BLOCKED_RETAINED
    assert recovered.cleanup.suggested is False


def test_blocked_lifecycle_survives_missing_worktree_recovery(tmp_path: Path):
    repo = make_repo(tmp_path)
    service = make_service(tmp_path, repo)
    session = service.create(SessionType.FEATURE, "Blocked missing")
    session.status = SessionStatus.BLOCKED_RETAINED
    service.registry.save(session)
    worktree = Path(session.worktree_path)
    run_git(repo, "worktree", "remove", "--force", str(worktree))

    missing = service.sync(session.id)
    run_git(repo, "worktree", "add", str(worktree), session.branch)
    recovered = service.sync(session.id)

    assert missing.status == SessionStatus.MISSING_WORKTREE
    assert recovered.status == SessionStatus.BLOCKED_RETAINED
    assert recovered.cleanup.suggested is False


def test_archived_lifecycle_survives_missing_worktree_recovery(tmp_path: Path):
    repo = make_repo(tmp_path)
    service = make_service(tmp_path, repo)
    session = service.create(SessionType.FEATURE, "Archived missing")
    worktree = Path(session.worktree_path)
    (worktree / "archived.txt").write_text("unfinished\n", encoding="utf-8")
    archived = service.archive(session.id, checkpoint=False)
    assert archived.status == SessionStatus.ARCHIVED_DIRTY
    moved = tmp_path / "temporarily-moved-archived"
    worktree.rename(moved)

    missing = service.sync(session.id)
    moved.rename(worktree)
    recovered = service.sync(session.id)

    assert missing.status == SessionStatus.MISSING_WORKTREE
    assert recovered.status == SessionStatus.ARCHIVED_DIRTY
    assert recovered.git_state.dirty_uncheckpointed is True


def test_manual_lifecycle_change_replaces_stale_unavailable_marker(
    tmp_path: Path,
):
    repo = make_repo(tmp_path)
    service = make_service(tmp_path, repo)
    session = service.create(SessionType.FEATURE, "Manual lifecycle recovery")
    worktree = Path(session.worktree_path)
    moved = tmp_path / "temporarily-moved"
    worktree.rename(moved)
    missing = service.sync(session.id)
    assert missing.status == SessionStatus.MISSING_WORKTREE
    base_head = run_git(repo, "rev-parse", "main")
    run_git(repo, "checkout", "-b", "parking-manual-lifecycle")
    run_git(repo, "update-ref", "-d", "refs/heads/main")
    moved.rename(worktree)
    base_missing = service.sync(session.id)
    assert base_missing.status == SessionStatus.RUNNING
    assert base_missing.git_state.base_missing is True
    base_missing.status = SessionStatus.BLOCKED_RETAINED
    service.registry.save(base_missing)

    still_blocked = service.sync(session.id)

    assert still_blocked.status == SessionStatus.BLOCKED_RETAINED
    assert (
        still_blocked.unavailable_lifecycle_status
        == SessionStatus.BLOCKED_RETAINED
    )
    run_git(repo, "update-ref", "refs/heads/main", base_head)


def test_sync_preserves_unknown_nested_git_state_fields(tmp_path: Path):
    repo = make_repo(tmp_path)
    service = make_service(tmp_path, repo)
    session = service.create(SessionType.FEATURE, "Future git state")
    path = service.registry.path_for(session.id)
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    data["git_state"]["future_flag"] = {"source": "new-runtime"}
    path.write_text(
        yaml.safe_dump(
            data,
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    service.sync(session.id)

    saved = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert saved["git_state"]["future_flag"] == {"source": "new-runtime"}


def test_reconcile_creates_orphan_session_for_unregistered_worktree(tmp_path: Path):
    repo = make_repo(tmp_path)
    service = make_service(tmp_path, repo)
    branch = "session/S-099-feature-orphan"
    worktree = tmp_path / "orphan"
    run_git(repo, "worktree", "add", "-b", branch, str(worktree), "main")

    sessions = service.reconcile()

    orphan = next(item for item in sessions if item.branch == branch)
    assert orphan.status == SessionStatus.ORPHAN_SESSION
    assert orphan.worktree_path == str(worktree)
    assert orphan.git_state.current_branch == branch


def test_reconcile_does_not_duplicate_identity_for_corrupt_registry_record(
    tmp_path: Path,
):
    repo = make_repo(tmp_path)
    service = make_service(tmp_path, repo)
    service.registry.list()
    service.registry.path_for("S-001").write_text(
        "id: [broken\n",
        encoding="utf-8",
    )
    branch = "session/S-001-feature-corrupt-record"
    worktree = tmp_path / "corrupt-orphan"
    run_git(repo, "worktree", "add", "-b", branch, str(worktree), "main")

    sessions = service.reconcile()

    assert sessions == []
    assert not service.registry.path_for("S-002").exists()
    assert any(
        "S-001" in warning and "reconcile" in warning
        for warning in service.registry.last_read_errors
    )


def test_reconcile_does_not_overwrite_corrupt_same_owner_claim_record(
    tmp_path: Path,
):
    repo = make_repo(tmp_path)
    service = make_service(tmp_path, repo)
    branch = "session/S-099-feature-owned-corrupt"
    worktree = tmp_path / "owned-corrupt"
    run_git(repo, "worktree", "add", "-b", branch, str(worktree), "main")
    orphan = next(item for item in service.reconcile() if item.branch == branch)
    record = service.registry.path_for(orphan.id)
    corrupt = "id: [broken\n"
    record.write_text(corrupt, encoding="utf-8")

    sessions = service.reconcile()

    assert sessions == []
    assert record.read_text(encoding="utf-8") == corrupt
    assert any(
        orphan.id in warning and "unreadable" in warning
        for warning in service.registry.last_read_errors
    )


def test_reconcile_does_not_reuse_valid_session_id_from_conflicting_claim(
    tmp_path: Path,
):
    repo = make_repo(tmp_path)
    service = make_service(tmp_path, repo)
    existing = service.create(SessionType.FEATURE, "Existing session")
    conflicting_branch = "session/S-099-feature-conflicting-claim"
    conflicting_worktree = tmp_path / "conflicting-claim"
    run_git(
        repo,
        "worktree",
        "add",
        "-b",
        conflicting_branch,
        str(conflicting_worktree),
        "main",
    )
    run_git(
        repo,
        "symbolic-ref",
        service._worktree_claim_ref(conflicting_branch),
        service._registry_owner_ref(existing.id),
    )

    sessions = service.reconcile()

    assert [session.id for session in sessions] == [existing.id]
    persisted = service.registry.load(existing.id)
    assert persisted.branch == existing.branch
    assert any(
        existing.id in warning and "already registered" in warning
        for warning in service.registry.last_read_errors
    )


def test_reconcile_skips_malformed_same_owner_claim_id(tmp_path: Path):
    repo = make_repo(tmp_path)
    service = make_service(tmp_path, repo)
    branch = "session/S-099-feature-malformed-claim"
    worktree = tmp_path / "malformed-claim"
    run_git(repo, "worktree", "add", "-b", branch, str(worktree), "main")
    run_git(
        repo,
        "symbolic-ref",
        service._worktree_claim_ref(branch),
        f"{service._registry_owner_ref('')}/not-valid",
    )

    sessions = service.reconcile()

    assert sessions == []
    assert any(
        branch in warning and "invalid" in warning
        for warning in service.registry.last_read_errors
    )


def test_reconcile_registers_branch_retained_after_worktree_add_failure(
    tmp_path: Path,
):
    repo = make_repo(tmp_path)
    hook = repo / ".git" / "hooks" / "post-checkout"
    hook.write_text("#!/bin/sh\nexit 23\n", encoding="utf-8")
    hook.chmod(0o755)
    service = make_service(tmp_path, repo)

    with pytest.raises(GitCommandError, match="git worktree add"):
        service.create(SessionType.FEATURE, "Branch only recovery")

    hook.unlink()
    sessions = service.reconcile()

    assert len(sessions) == 1
    recovered = sessions[0]
    assert recovered.id == "S-001"
    assert recovered.status == SessionStatus.MISSING_WORKTREE
    assert (
        recovered.unavailable_lifecycle_status
        == SessionStatus.ORPHAN_SESSION
    )
    assert not Path(recovered.worktree_path).exists()


def test_reconcile_assigns_orphans_to_remote_default_branch(
    tmp_path: Path,
):
    repo = make_repo(tmp_path)
    add_origin(repo, tmp_path)
    orphan_branch = "session/S-099-feature-orphan-default"
    orphan = tmp_path / "orphan-default"
    run_git(repo, "worktree", "add", "-b", orphan_branch, str(orphan), "main")
    run_git(repo, "checkout", "-b", "integration")
    (repo / "integration.txt").write_text("integration\n", encoding="utf-8")
    run_git(repo, "add", "integration.txt")
    run_git(repo, "commit", "-m", "integration")
    service = make_service(tmp_path, repo)

    reconciled = next(
        item for item in service.reconcile() if item.branch == orphan_branch
    )

    assert reconciled.base_branch == "main"
    assert reconciled.git_state.behind == 0
    assert reconciled.git_state.stale is False


def test_different_registries_do_not_claim_the_same_orphan_worktree(
    tmp_path: Path,
):
    repo = make_repo(tmp_path)
    branch = "session/S-099-feature-shared-orphan"
    worktree = tmp_path / "shared-orphan"
    run_git(repo, "worktree", "add", "-b", branch, str(worktree), "main")
    first = EngineeringSessionService(
        repo,
        registry_root=tmp_path / "first-sessions",
        worktree_parent=tmp_path / "worktrees",
    )
    second = EngineeringSessionService(
        repo,
        registry_root=tmp_path / "second-sessions",
        worktree_parent=tmp_path / "worktrees",
    )

    first_sessions = first.reconcile()
    second_sessions = second.reconcile()

    assert [session.branch for session in first_sessions] == [branch]
    assert second_sessions == []
    assert any(
        "already claimed" in warning
        for warning in second.registry.last_read_errors
    )


def test_reconcile_marks_merged_orphan_for_cleanup_without_losing_orphan_status(
    tmp_path: Path,
):
    repo = make_repo(tmp_path)
    service = make_service(tmp_path, repo)
    branch = "session/S-099-feature-merged-orphan"
    worktree = tmp_path / "merged-orphan"
    run_git(repo, "worktree", "add", "-b", branch, str(worktree), "main")
    (worktree / "orphan.txt").write_text("orphan\n", encoding="utf-8")
    run_git(worktree, "add", "orphan.txt")
    run_git(worktree, "commit", "-m", "orphan change")
    orphan_head = run_git(worktree, "rev-parse", "HEAD")
    run_git(repo, "merge", "--no-ff", branch, "-m", "merge orphan")

    sessions = service.reconcile()

    orphan = next(item for item in sessions if item.branch == branch)
    persisted = service.registry.load(orphan.id)
    assert orphan.base_commit is None
    assert orphan.head_commit == orphan_head
    assert orphan.status == SessionStatus.ORPHAN_SESSION
    assert orphan.git_state.clean is True
    assert orphan.git_state.merged_to_base is True
    assert orphan.git_state.retained is True
    assert orphan.cleanup.suggested is True
    assert persisted.status == SessionStatus.ORPHAN_SESSION
    assert persisted.cleanup.suggested is True


def test_reconcile_skips_prunable_worktree_entries(tmp_path: Path):
    repo = make_repo(tmp_path)
    service = make_service(tmp_path, repo)
    branch = "session/S-100-feature-prunable"
    worktree = tmp_path / "prunable"
    run_git(repo, "worktree", "add", "-b", branch, str(worktree), "main")
    shutil.rmtree(worktree)

    sessions = service.reconcile()

    assert all(item.branch != branch for item in sessions)


def test_reconcile_updates_registered_worktree_path_after_move(tmp_path: Path):
    repo = make_repo(tmp_path)
    service = make_service(tmp_path, repo)
    session = service.create(SessionType.FEATURE, "Moved worktree")
    original = Path(session.worktree_path)
    moved = tmp_path / "moved-worktree"
    run_git(repo, "worktree", "move", str(original), str(moved))

    sessions = service.reconcile()

    reconciled = next(item for item in sessions if item.id == session.id)
    persisted = service.registry.load(session.id)
    assert reconciled.worktree_path == str(moved.resolve())
    assert persisted.worktree_path == str(moved.resolve())
    assert persisted.status == SessionStatus.RUNNING
    assert persisted.git_state.missing_worktree is False


def test_concurrent_create_and_reconcile_allocate_distinct_sessions(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    repo = make_repo(tmp_path)
    orphan_branch = "session/S-099-feature-orphan-race"
    orphan_worktree = tmp_path / "orphan-race"
    run_git(
        repo,
        "worktree",
        "add",
        "-b",
        orphan_branch,
        str(orphan_worktree),
        "main",
    )
    registry_root = tmp_path / "shared-sessions"
    worktree_parent = tmp_path / "shared-worktrees"
    create_service = EngineeringSessionService(
        repo,
        registry_root=registry_root,
        worktree_parent=worktree_parent,
    )
    reconcile_service = EngineeringSessionService(
        repo,
        registry_root=registry_root,
        worktree_parent=worktree_parent,
    )
    original_next_id = SessionRegistry.next_id

    def delayed_next_id(registry: SessionRegistry) -> str:
        session_id = original_next_id(registry)
        time.sleep(0.1)
        return session_id

    monkeypatch.setattr(SessionRegistry, "next_id", delayed_next_id)
    with ThreadPoolExecutor(max_workers=2) as executor:
        create_future = executor.submit(
            create_service.create,
            SessionType.FEATURE,
            "Concurrent create",
        )
        reconcile_future = executor.submit(reconcile_service.reconcile)
        created = create_future.result()
        reconciled = reconcile_future.result()

    persisted = create_service.registry.list()
    assert sorted(session.id for session in persisted) == ["S-001", "S-002"]
    assert sorted(path.name for path in registry_root.glob("S-*.yaml")) == [
        "S-001.yaml",
        "S-002.yaml",
    ]
    assert {session.branch for session in persisted} == {
        created.branch,
        orphan_branch,
    }
    assert any(session.branch == orphan_branch for session in reconciled)
    for session in persisted:
        assert session.worktree_path is not None
        worktree = Path(session.worktree_path)
        assert worktree.exists()
        assert run_git(worktree, "branch", "--show-current") == session.branch


def test_concurrent_reconcile_registers_orphan_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    repo = make_repo(tmp_path)
    orphan_branch = "session/S-099-feature-single-orphan"
    orphan_worktree = tmp_path / "single-orphan"
    run_git(
        repo,
        "worktree",
        "add",
        "-b",
        orphan_branch,
        str(orphan_worktree),
        "main",
    )
    registry_root = tmp_path / "shared-sessions"
    first_service = EngineeringSessionService(
        repo,
        registry_root=registry_root,
        worktree_parent=tmp_path / "shared-worktrees",
    )
    second_service = EngineeringSessionService(
        repo,
        registry_root=registry_root,
        worktree_parent=tmp_path / "shared-worktrees",
    )
    original_create = SessionRegistry.create
    create_calls = 0

    def delayed_create(
        registry: SessionRegistry,
        **kwargs,
    ):
        nonlocal create_calls
        create_calls += 1
        time.sleep(0.1)
        return original_create(registry, **kwargs)

    monkeypatch.setattr(SessionRegistry, "create", delayed_create)
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [
            executor.submit(first_service.reconcile),
            executor.submit(second_service.reconcile),
        ]
        results = [future.result() for future in futures]

    persisted = first_service.registry.list()
    expected = [(persisted[0].id, orphan_branch)]
    assert create_calls == 1
    assert len(persisted) == 1
    assert persisted[0].branch == orphan_branch
    assert [
        sorted((session.id, session.branch) for session in result)
        for result in results
    ] == [expected, expected]


def test_reconcile_does_not_overwrite_concurrent_archive_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    repo = make_repo(tmp_path)
    registry_root = tmp_path / "shared-sessions"
    worktree_parent = tmp_path / "shared-worktrees"
    reconcile_service = EngineeringSessionService(
        repo,
        registry_root=registry_root,
        worktree_parent=worktree_parent,
    )
    archive_service = EngineeringSessionService(
        repo,
        registry_root=registry_root,
        worktree_parent=worktree_parent,
    )
    session = archive_service.create(SessionType.FEATURE, "Concurrent archive")
    worktree = Path(session.worktree_path)
    (worktree / "dirty.txt").write_text("dirty\n", encoding="utf-8")
    listed = Event()
    archive_started = Event()
    original_list = reconcile_service.registry.list

    def delayed_list():
        sessions = original_list()
        listed.set()
        assert archive_started.wait(timeout=2)
        time.sleep(0.1)
        return sessions

    def archive_session():
        archive_started.set()
        return archive_service.archive(session.id, checkpoint=False)

    monkeypatch.setattr(reconcile_service.registry, "list", delayed_list)
    with ThreadPoolExecutor(max_workers=2) as executor:
        reconcile_future = executor.submit(reconcile_service.reconcile)
        assert listed.wait(timeout=2)
        archive_future = executor.submit(archive_session)
        reconcile_future.result(timeout=5)
        archived = archive_future.result(timeout=5)

    persisted = archive_service.registry.load(session.id)
    assert archived.status == SessionStatus.ARCHIVED_DIRTY
    assert persisted.status == SessionStatus.ARCHIVED_DIRTY
    assert persisted.git_state.dirty_uncheckpointed is True


def test_package_exports_service_after_service_module_exists():
    assert "EngineeringSessionService" in engineering_sessions.__all__
    assert engineering_sessions.EngineeringSessionService is EngineeringSessionService
