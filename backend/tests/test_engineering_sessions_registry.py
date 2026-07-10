import subprocess
from pathlib import Path

import pytest
import yaml

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
