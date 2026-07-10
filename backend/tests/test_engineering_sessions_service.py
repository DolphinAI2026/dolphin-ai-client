import shutil
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path
from threading import Event

import pytest

import app.engineering_sessions as engineering_sessions
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


def test_create_uses_captured_base_commit_if_base_advances_inside_lock(
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
    assert run_git(repo, "rev-parse", "main") != captured_base_commit
    assert session.base_commit == captured_base_commit
    assert run_git(worktree, "rev-parse", "HEAD") == captured_base_commit
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


@pytest.mark.parametrize("action", ["checkpoint", "archive"])
def test_missing_base_blocks_writes_and_recovers_running(
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
    run_git(repo, "update-ref", "-d", "refs/heads/main")
    (worktree / "blocked.txt").write_text("do not commit\n", encoding="utf-8")
    before_head = run_git(worktree, "rev-parse", "HEAD")

    blocked = service.sync(session.id)
    resumed = service.resume(session.id)
    if action == "checkpoint":
        assert service.checkpoint(session.id) is False
        observed = service.registry.load(session.id)
    else:
        observed = service.archive(session.id)

    assert blocked.status == SessionStatus.BLOCKED_RETAINED
    assert blocked.git_state.base_missing is True
    assert blocked.git_state.stale is True
    assert blocked.cleanup.suggested is False
    assert resumed.status == SessionStatus.BLOCKED_RETAINED
    assert observed.status == SessionStatus.BLOCKED_RETAINED
    assert run_git(worktree, "rev-parse", "HEAD") == before_head
    assert (worktree / "blocked.txt").read_text(encoding="utf-8") == "do not commit\n"
    assert run_git(worktree, "status", "--porcelain")

    run_git(repo, "update-ref", "refs/heads/main", base_head)
    restored = service.sync(session.id)

    assert restored.status == SessionStatus.RUNNING
    assert restored.git_state.base_missing is False
    assert restored.git_state.merged_to_base is False


def test_missing_base_recovers_merged_session_state(tmp_path: Path):
    repo = make_repo(tmp_path)
    service = make_service(tmp_path, repo)
    session = service.create(SessionType.FEATURE, "Missing merged base")
    worktree = Path(session.worktree_path)
    (worktree / "merged.txt").write_text("merged\n", encoding="utf-8")
    assert service.checkpoint(session.id) is True
    run_git(repo, "merge", "--no-ff", session.branch, "-m", "merge session")
    merged_head = run_git(repo, "rev-parse", "main")
    run_git(repo, "checkout", "-b", "parking")
    run_git(repo, "update-ref", "-d", "refs/heads/main")

    blocked = service.sync(session.id)

    assert blocked.status == SessionStatus.BLOCKED_RETAINED
    assert blocked.git_state.base_missing is True
    assert blocked.cleanup.suggested is False

    run_git(repo, "update-ref", "refs/heads/main", merged_head)
    restored = service.sync(session.id)

    assert restored.status == SessionStatus.MERGED_RETAINED
    assert restored.git_state.base_missing is False
    assert restored.git_state.merged_to_base is True
    assert restored.cleanup.suggested is True


@pytest.mark.parametrize(
    "initial_status",
    [
        SessionStatus.RUNNING,
        SessionStatus.MERGED_RETAINED,
        SessionStatus.ARCHIVED_DIRTY,
        SessionStatus.ABANDONED_RETAINED,
    ],
)
def test_base_outage_restores_recorded_session_status(
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

    base_head = run_git(repo, "rev-parse", "main")
    run_git(repo, "checkout", "-b", f"parking-{initial_status.value}")
    run_git(repo, "update-ref", "-d", "refs/heads/main")

    blocked = service.sync(session.id)
    blocked_again = service.sync(session.id)

    assert blocked.status == SessionStatus.BLOCKED_RETAINED
    assert blocked.blocked_from_status == initial_status.value
    assert blocked_again.blocked_from_status == initial_status.value

    run_git(repo, "update-ref", "refs/heads/main", base_head)
    restored = service.sync(session.id)

    assert restored.status == initial_status
    assert restored.blocked_from_status is None
    assert restored.cleanup.suggested is (
        initial_status == SessionStatus.MERGED_RETAINED
    )


def test_manual_blocked_session_remains_blocked_across_base_outage(tmp_path: Path):
    repo = make_repo(tmp_path)
    service = make_service(tmp_path, repo)
    session = service.create(SessionType.FEATURE, "Manual blocked outage")
    session.status = SessionStatus.BLOCKED_RETAINED
    service.registry.save(session)
    base_head = run_git(repo, "rev-parse", "main")
    run_git(repo, "checkout", "-b", "parking-manual-blocked")
    run_git(repo, "update-ref", "-d", "refs/heads/main")

    blocked = service.sync(session.id)
    blocked_again = service.sync(session.id)

    assert blocked.blocked_from_status == SessionStatus.BLOCKED_RETAINED.value
    assert blocked_again.blocked_from_status == SessionStatus.BLOCKED_RETAINED.value

    run_git(repo, "update-ref", "refs/heads/main", base_head)
    restored = service.sync(session.id)

    assert restored.status == SessionStatus.BLOCKED_RETAINED
    assert restored.blocked_from_status is None
    assert restored.cleanup.suggested is False


def test_legacy_blocked_session_without_origin_status_stays_blocked(tmp_path: Path):
    repo = make_repo(tmp_path)
    service = make_service(tmp_path, repo)
    session = service.create(SessionType.FEATURE, "Legacy blocked")
    session.status = SessionStatus.BLOCKED_RETAINED
    session.git_state.base_missing = True
    service.registry.save(session)

    restored = service.sync(session.id)

    assert restored.status == SessionStatus.BLOCKED_RETAINED
    assert restored.blocked_from_status is None
    assert restored.cleanup.suggested is False


@pytest.mark.parametrize("merged", [False, True])
def test_orphan_session_identity_survives_base_outage(
    tmp_path: Path,
    merged: bool,
):
    repo = make_repo(tmp_path)
    service = make_service(tmp_path, repo)
    branch = f"session/S-099-feature-outage-orphan-{merged}"
    worktree = tmp_path / f"outage-orphan-{merged}"
    run_git(repo, "worktree", "add", "-b", branch, str(worktree), "main")
    (worktree / "orphan.txt").write_text("orphan\n", encoding="utf-8")
    run_git(worktree, "add", "orphan.txt")
    run_git(worktree, "commit", "-m", "orphan change")
    if merged:
        run_git(repo, "merge", "--no-ff", branch, "-m", "merge orphan")
    orphan = next(item for item in service.reconcile() if item.branch == branch)
    assert orphan.status == SessionStatus.ORPHAN_SESSION

    base_head = run_git(repo, "rev-parse", "main")
    run_git(repo, "checkout", "-b", f"parking-orphan-{merged}")
    run_git(repo, "update-ref", "-d", "refs/heads/main")

    blocked = service.sync(orphan.id)
    blocked_again = service.sync(orphan.id)

    assert blocked.status == SessionStatus.BLOCKED_RETAINED
    assert blocked.blocked_from_status == SessionStatus.ORPHAN_SESSION.value
    assert blocked_again.blocked_from_status == SessionStatus.ORPHAN_SESSION.value

    run_git(repo, "update-ref", "refs/heads/main", base_head)
    restored = service.sync(orphan.id)

    assert restored.status == SessionStatus.ORPHAN_SESSION
    assert restored.blocked_from_status is None
    assert restored.git_state.merged_to_base is merged
    assert restored.cleanup.suggested is merged


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
    assert "invalid-date.txt" in run_git(worktree, "diff", "--cached", "--name-only")


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
