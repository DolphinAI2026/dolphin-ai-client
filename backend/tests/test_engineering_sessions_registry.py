import errno
import os
import stat
import subprocess
from pathlib import Path

import pytest
import yaml

import app.engineering_sessions.registry as registry_module
from app.engineering_sessions.models import SessionType
from app.engineering_sessions.paths import registry_root_for_repo, repo_id_for_path
from app.engineering_sessions.registry import SessionRegistry, SessionRegistryError


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


def test_repo_id_is_stable_and_path_safe(tmp_path: Path):
    repo = tmp_path / "apaas-builder-ai"
    repo.mkdir()

    repo_id = repo_id_for_path(repo)

    assert repo_id.startswith("apaas-builder-ai-")
    assert "/" not in repo_id


def test_linked_worktree_uses_same_repo_id_and_registry_root(tmp_path: Path):
    repo = make_repo(tmp_path)
    linked = tmp_path / "linked"
    home = tmp_path / "agentic-home"
    run_git(repo, "worktree", "add", "-b", "linked-branch", str(linked), "main")

    assert repo_id_for_path(linked) == repo_id_for_path(repo)
    assert registry_root_for_repo(linked, home=home) == registry_root_for_repo(
        repo,
        home=home,
    )


def test_registry_root_uses_override_home(tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()

    root = registry_root_for_repo(repo, home=tmp_path / "agentic-home")

    assert root.parent.name == repo_id_for_path(repo)
    assert root.name == "sessions"


def test_registry_create_save_load_list(tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()
    registry = SessionRegistry(repo, root=tmp_path / "sessions")

    session = registry.create(
        session_type=SessionType.DOC_CHANGE,
        title="README 本地运行方式",
        base_branch="main",
        worktree_path=str(tmp_path / "worktrees" / "S-001-doc"),
        base_commit="abc123",
    )
    registry.save(session)

    loaded = registry.load("S-001")
    sessions = registry.list()

    assert loaded.id == "S-001"
    assert loaded.type == SessionType.DOC_CHANGE.value
    assert type(session.type) is str
    assert type(loaded.type) is str
    assert type(loaded.status) is str
    assert loaded.branch == "session/S-001-doc-change-readme"
    assert loaded.base_commit == "abc123"
    assert [item.id for item in sessions] == ["S-001"]


def test_registry_rejects_invalid_session_id_paths(tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()
    registry = SessionRegistry(repo, root=tmp_path / "sessions")

    try:
        registry.path_for("../S-001")
    except SessionRegistryError as exc:
        assert "invalid session id" in str(exc)
    else:
        raise AssertionError("expected invalid session id to be rejected")


def test_registry_reserves_ids_before_save_and_preserves_explicit_roles(tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()
    registry = SessionRegistry(repo, root=tmp_path / "sessions")

    first = registry.create(
        session_type=SessionType.FEATURE,
        title="First",
        base_branch="main",
        worktree_path=None,
        roles=[],
    )
    second = registry.create(
        session_type=SessionType.BUGFIX,
        title="Second",
        base_branch="main",
        worktree_path=None,
    )

    assert first.id == "S-001"
    assert first.roles == []
    assert second.id == "S-002"


def test_registry_save_dump_failure_preserves_existing_yaml(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    repo = tmp_path / "repo"
    repo.mkdir()
    registry = SessionRegistry(repo, root=tmp_path / "sessions")
    session = registry.create(
        session_type=SessionType.REVIEW,
        title="Original",
        base_branch="main",
        worktree_path=None,
    )
    registry.save(session)
    session.title = "Changed"

    def fail_dump(*args, **kwargs):
        raise RuntimeError("dump failed")

    monkeypatch.setattr(yaml, "safe_dump", fail_dump)

    with pytest.raises(RuntimeError, match="dump failed"):
        registry.save(session)

    assert registry.load(session.id).title == "Original"
    assert not list(registry.root.glob("*.tmp"))
    assert not list(registry.root.glob(".*.tmp"))


def test_registry_owner_dump_failure_does_not_publish_partial_owner(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    repo = tmp_path / "repo"
    repo.mkdir()
    registry = SessionRegistry(repo, root=tmp_path / "sessions")
    original_dump = yaml.safe_dump

    def fail_owner_dump(data, stream, *args, **kwargs):
        stream.write("repo_path: /partial")
        raise RuntimeError("owner dump failed")

    monkeypatch.setattr(yaml, "safe_dump", fail_owner_dump)

    with pytest.raises(RuntimeError, match="owner dump failed"):
        registry.list()

    assert not (registry.root / ".repository.yaml").exists()
    assert not list(registry.root.glob(".*.tmp"))

    monkeypatch.setattr(yaml, "safe_dump", original_dump)
    assert registry.list() == []


def test_registry_owner_creation_does_not_require_hard_links(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    repo = tmp_path / "repo"
    repo.mkdir()
    registry = SessionRegistry(repo, root=tmp_path / "sessions")

    def fail_link(*_args, **_kwargs):
        raise OSError(errno.ENOTSUP, "hard links unsupported")

    monkeypatch.setattr(os, "link", fail_link)

    assert registry.list() == []
    assert (registry.root / ".repository.yaml").exists()


def test_registry_save_replace_failure_preserves_existing_yaml(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    repo = tmp_path / "repo"
    repo.mkdir()
    registry = SessionRegistry(repo, root=tmp_path / "sessions")
    session = registry.create(
        session_type=SessionType.REVIEW,
        title="Original",
        base_branch="main",
        worktree_path=None,
    )
    registry.save(session)
    session.title = "Changed"
    original_replace = Path.replace

    def fail_replace(path: Path, target: Path) -> Path:
        if path.parent == registry.root and path.suffix == ".tmp":
            raise OSError("replace failed")
        return original_replace(path, target)

    monkeypatch.setattr(Path, "replace", fail_replace)

    with pytest.raises(OSError, match="replace failed"):
        registry.save(session)

    assert registry.load(session.id).title == "Original"
    assert not list(registry.root.glob("*.tmp"))
    assert not list(registry.root.glob(".*.tmp"))


def test_registry_list_skips_corrupt_record_and_reports_error(tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()
    registry = SessionRegistry(repo, root=tmp_path / "sessions")
    first = registry.create(
        session_type=SessionType.REVIEW,
        title="First",
        base_branch="main",
        worktree_path=None,
    )
    registry.save(first)
    second = registry.create(
        session_type=SessionType.REVIEW,
        title="Second",
        base_branch="main",
        worktree_path=None,
    )
    registry.save(second)
    registry.path_for(first.id).write_text("id: [broken\n", encoding="utf-8")

    sessions = registry.list()

    assert [session.id for session in sessions] == [second.id]
    assert len(registry.last_read_errors) == 1
    assert first.id in registry.last_read_errors[0]


def test_registry_owner_inference_skips_non_mapping_legacy_record(tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()
    root = tmp_path / "sessions"
    root.mkdir()
    (root / "S-001.yaml").write_text("- not\n- a\n- mapping\n", encoding="utf-8")
    healthy_registry = SessionRegistry(repo, root=tmp_path / "healthy-sessions")
    healthy = healthy_registry.create(
        session_type=SessionType.REVIEW,
        title="Healthy",
        base_branch="main",
        worktree_path=None,
    )
    healthy.id = "S-002"
    (root / "S-002.yaml").write_text(
        yaml.safe_dump(
            healthy.model_dump(mode="json"),
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    registry = SessionRegistry(repo, root=root)
    sessions = registry.list()

    assert [session.id for session in sessions] == ["S-002"]
    assert any("S-001" in message for message in registry.last_read_errors)


def test_registry_owner_inference_fails_closed_for_only_corrupt_records(
    tmp_path: Path,
):
    repo = tmp_path / "repo"
    repo.mkdir()
    root = tmp_path / "sessions"
    root.mkdir()
    (root / "S-001.yaml").write_text("id: [broken\n", encoding="utf-8")
    registry = SessionRegistry(repo, root=root)

    with pytest.raises(SessionRegistryError, match="cannot verify registry owner"):
        registry.list()

    assert not (root / ".repository.yaml").exists()


def test_registry_owner_inference_rejects_conflicting_legacy_owners(
    tmp_path: Path,
):
    first_repo = tmp_path / "first"
    second_repo = tmp_path / "second"
    first_repo.mkdir()
    second_repo.mkdir()
    root = tmp_path / "sessions"
    root.mkdir()
    for index, repo in enumerate((first_repo, second_repo), start=1):
        (root / f"S-{index:03d}.yaml").write_text(
            yaml.safe_dump({"repo_path": str(repo)}, sort_keys=False),
            encoding="utf-8",
        )

    registry = SessionRegistry(first_repo, root=root)

    with pytest.raises(SessionRegistryError, match="conflicting repository owners"):
        registry.list()

    assert not (root / ".repository.yaml").exists()


def test_registry_round_trips_unknown_fields(tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()
    registry = SessionRegistry(repo, root=tmp_path / "sessions")
    session = registry.create(
        session_type=SessionType.REVIEW,
        title="Forward compatible",
        base_branch="main",
        worktree_path=None,
    )
    registry.save(session)
    path = registry.path_for(session.id)
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    data["schema_version"] = 2
    data["future_state"] = {"owner": "new-runtime"}
    data["git_state"]["future_flag"] = True
    path.write_text(
        yaml.safe_dump(data, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )

    registry.save(registry.load(session.id))

    saved = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert saved["schema_version"] == 2
    assert saved["future_state"] == {"owner": "new-runtime"}
    assert saved["git_state"]["future_flag"] is True


def test_registry_root_rejects_a_different_repository_owner(tmp_path: Path):
    first_repo = tmp_path / "first-repo"
    second_repo = tmp_path / "second-repo"
    first_repo.mkdir()
    second_repo.mkdir()
    root = tmp_path / "shared-sessions"
    first_registry = SessionRegistry(first_repo, root=root)
    session = first_registry.create(
        session_type=SessionType.REVIEW,
        title="First repo",
        base_branch="main",
        worktree_path=None,
    )
    first_registry.save(session)

    second_registry = SessionRegistry(second_repo, root=root)

    with pytest.raises(SessionRegistryError, match="another repository"):
        second_registry.list()

    assert first_registry.load(session.id).title == "First repo"


def test_registry_save_fsyncs_file_and_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    repo = tmp_path / "repo"
    repo.mkdir()
    registry = SessionRegistry(repo, root=tmp_path / "sessions")
    session = registry.create(
        session_type=SessionType.REVIEW,
        title="Durable",
        base_branch="main",
        worktree_path=None,
    )
    fsync_calls: list[int] = []

    monkeypatch.setattr(os, "fsync", lambda fd: fsync_calls.append(fd))

    registry.save(session)

    assert len(fsync_calls) >= 2


def test_registry_directory_fsync_propagates_io_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    repo = tmp_path / "repo"
    repo.mkdir()
    registry = SessionRegistry(repo, root=tmp_path / "sessions")
    registry.list()
    session = registry.create(
        session_type=SessionType.REVIEW,
        title="Durable failure",
        base_branch="main",
        worktree_path=None,
    )
    original_fsync = os.fsync

    def fail_directory_fsync(fd: int) -> None:
        if stat.S_ISDIR(os.fstat(fd).st_mode):
            raise OSError(errno.EIO, "directory fsync failed")
        original_fsync(fd)

    monkeypatch.setattr(os, "fsync", fail_directory_fsync)

    with pytest.raises(OSError, match="directory fsync failed"):
        registry.save(session)


def test_registry_cleanup_failure_does_not_mask_primary_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    repo = tmp_path / "repo"
    repo.mkdir()
    registry = SessionRegistry(repo, root=tmp_path / "sessions")
    registry.list()
    session = registry.create(
        session_type=SessionType.REVIEW,
        title="Cleanup diagnostics",
        base_branch="main",
        worktree_path=None,
    )
    original_unlink = Path.unlink

    def fail_directory_fsync():
        raise OSError("directory fsync primary failure")

    def fail_temporary_cleanup(path: Path, *args, **kwargs):
        if path.name.endswith(".tmp"):
            raise OSError("registry temporary cleanup failed")
        return original_unlink(path, *args, **kwargs)

    monkeypatch.setattr(registry, "_fsync_directory", fail_directory_fsync)
    monkeypatch.setattr(Path, "unlink", fail_temporary_cleanup)

    with pytest.raises(
        OSError,
        match="directory fsync primary failure",
    ) as exc_info:
        registry.save(session)

    assert any(
        "registry temporary cleanup failed" in note
        for note in getattr(exc_info.value, "__notes__", [])
    )


@pytest.mark.skipif(os.name == "nt", reason="POSIX directory permissions")
def test_registry_directory_open_permission_error_is_not_ignored(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    repo = tmp_path / "repo"
    repo.mkdir()
    registry = SessionRegistry(repo, root=tmp_path / "sessions")
    registry.list()
    session = registry.create(
        session_type=SessionType.REVIEW,
        title="Permission failure",
        base_branch="main",
        worktree_path=None,
    )
    original_open = os.open

    def fail_directory_open(path, flags, *args, **kwargs):
        if Path(path) == registry.root:
            raise OSError(errno.EACCES, "directory open denied")
        return original_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(os, "open", fail_directory_open)

    with pytest.raises(OSError, match="directory open denied"):
        registry.save(session)


def test_transaction_lock_uses_windows_fallback_when_fcntl_is_unavailable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    repo = tmp_path / "repo"
    repo.mkdir()
    registry = SessionRegistry(repo, root=tmp_path / "sessions")

    class FakeMsvcrt:
        LK_LOCK = 1
        LK_UNLCK = 2
        LK_NBLCK = 3

        def __init__(self):
            self.calls: list[int] = []

        def locking(self, _fd: int, mode: int, _size: int) -> None:
            self.calls.append(mode)

    fake_msvcrt = FakeMsvcrt()
    monkeypatch.setattr(registry_module, "_fcntl", None, raising=False)
    monkeypatch.setattr(
        registry_module,
        "_msvcrt",
        fake_msvcrt,
        raising=False,
    )

    with registry.transaction_lock():
        pass

    assert fake_msvcrt.calls == [
        fake_msvcrt.LK_NBLCK,
        fake_msvcrt.LK_NBLCK,
        fake_msvcrt.LK_UNLCK,
        fake_msvcrt.LK_UNLCK,
    ]


def test_windows_fallback_reports_lock_timeout(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    repo = tmp_path / "repo"
    repo.mkdir()
    registry = SessionRegistry(repo, root=tmp_path / "sessions")

    class ContendedMsvcrt:
        LK_LOCK = 1
        LK_UNLCK = 2
        LK_NBLCK = 3

        def locking(self, _fd: int, mode: int, _size: int) -> None:
            if mode == self.LK_NBLCK:
                raise OSError(errno.EACCES, "lock busy")

    monkeypatch.setattr(registry_module, "_fcntl", None, raising=False)
    monkeypatch.setattr(
        registry_module,
        "_msvcrt",
        ContendedMsvcrt(),
        raising=False,
    )
    monkeypatch.setattr(
        registry_module,
        "_LOCK_TIMEOUT_SECONDS",
        0,
        raising=False,
    )

    with pytest.raises(SessionRegistryError, match="timed out acquiring"):
        with registry.transaction_lock():
            pass
