import shutil
import subprocess
from pathlib import Path

from app.engineering_sessions.git_state import (
    current_branch,
    inspect_git_state,
    list_git_worktrees,
    rev_parse_head,
)


def run_git(repo: Path, *args: str) -> str:
    result = subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True)
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


def test_current_branch_and_head(tmp_path: Path):
    repo = make_repo(tmp_path)

    assert current_branch(repo) == "main"
    assert len(rev_parse_head(repo)) >= 7


def test_current_branch_is_not_confused_by_same_name_tag(tmp_path: Path):
    repo = make_repo(tmp_path)
    run_git(repo, "tag", "main")

    assert current_branch(repo) == "main"


def test_inspect_git_state_reports_dirty_and_ahead(tmp_path: Path):
    repo = make_repo(tmp_path)
    run_git(repo, "checkout", "-b", "session/S-001-bugfix-test")
    (repo / "feature.txt").write_text("feature\n", encoding="utf-8")
    run_git(repo, "add", "feature.txt")
    run_git(repo, "commit", "-m", "feature")
    (repo / "dirty.txt").write_text("dirty\n", encoding="utf-8")

    state = inspect_git_state(repo, base_branch="main")

    assert state.clean is False
    assert state.ahead == 1
    assert state.behind == 0
    assert state.stale is False
    assert state.current_branch == "session/S-001-bugfix-test"


def test_inspect_missing_worktree(tmp_path: Path):
    state = inspect_git_state(tmp_path / "missing", base_branch="main")

    assert state.missing_worktree is True
    assert state.clean is False


def test_inspect_existing_non_git_directory_is_missing_worktree(tmp_path: Path):
    not_repo = tmp_path / "not-repo"
    not_repo.mkdir()

    state = inspect_git_state(not_repo, base_branch="main")

    assert state.missing_worktree is True
    assert state.clean is False


def test_inspect_nested_repo_directory_is_not_a_worktree_root(tmp_path: Path):
    repo = make_repo(tmp_path)
    nested = repo / "nested"
    nested.mkdir()

    state = inspect_git_state(nested, base_branch="main")

    assert state.missing_worktree is True
    assert state.clean is False


def test_inspect_git_state_reports_branch_mismatch_and_very_stale(tmp_path: Path):
    repo = make_repo(tmp_path)
    run_git(repo, "checkout", "-b", "session/S-003-feature-stale")
    run_git(repo, "checkout", "main")
    for idx in range(2):
        (repo / "README.md").write_text(f"base {idx}\n", encoding="utf-8")
        run_git(repo, "add", "README.md")
        run_git(repo, "commit", "-m", f"base {idx}")
    run_git(repo, "checkout", "session/S-003-feature-stale")

    state = inspect_git_state(
        repo,
        base_branch="main",
        expected_branch="session/S-999-wrong",
        very_stale_behind=2,
    )

    assert state.ahead == 0
    assert state.behind == 2
    assert state.stale is True
    assert state.very_stale is True
    assert state.branch_mismatch is True


def test_merged_to_base_turns_true_after_branch_commit_is_merged(tmp_path: Path):
    repo = make_repo(tmp_path)
    base_commit = rev_parse_head(repo)
    run_git(repo, "checkout", "-b", "session/S-004-feature-merged")
    (repo / "feature.txt").write_text("feature\n", encoding="utf-8")
    run_git(repo, "add", "feature.txt")
    run_git(repo, "commit", "-m", "feature")
    run_git(repo, "checkout", "main")
    run_git(repo, "merge", "--no-ff", "session/S-004-feature-merged", "-m", "merge feature")
    run_git(repo, "checkout", "session/S-004-feature-merged")

    state = inspect_git_state(repo, base_branch="main", session_base_commit=base_commit)

    assert state.merged_to_base is True
    assert state.retained is True


def test_unmodified_session_branch_is_not_marked_merged(tmp_path: Path):
    repo = make_repo(tmp_path)
    base_commit = rev_parse_head(repo)
    run_git(repo, "checkout", "-b", "session/S-007-feature-empty")

    state = inspect_git_state(repo, base_branch="main", session_base_commit=base_commit)

    assert state.merged_to_base is False
    assert state.retained is False


def test_state_calculation_ignores_tag_with_same_name_as_base_branch(tmp_path: Path):
    repo = make_repo(tmp_path)
    base_commit = rev_parse_head(repo)
    run_git(repo, "checkout", "-b", "session/S-008-feature-tag-conflict")
    (repo / "feature.txt").write_text("feature\n", encoding="utf-8")
    run_git(repo, "add", "feature.txt")
    run_git(repo, "commit", "-m", "feature")
    run_git(repo, "tag", "main")

    state = inspect_git_state(repo, base_branch="main", session_base_commit=base_commit)

    assert state.ahead == 1
    assert state.behind == 0
    assert state.merged_to_base is False
    assert state.retained is False


def test_list_git_worktrees_parses_porcelain(tmp_path: Path):
    repo = make_repo(tmp_path)
    linked = tmp_path / "linked"
    run_git(repo, "worktree", "add", "-b", "session/S-002-feature-x", str(linked), "main")

    worktrees = list_git_worktrees(repo)

    assert str(repo) in worktrees
    assert str(linked) in worktrees
    assert worktrees[str(linked)]["branch"] == "session/S-002-feature-x"
    assert worktrees[str(linked)]["prunable"] is False


def test_git_ignores_inherited_repository_selection_env(tmp_path: Path, monkeypatch):
    target_root = tmp_path / "target"
    target_root.mkdir()
    target = make_repo(target_root)
    decoy_root = tmp_path / "decoy"
    decoy_root.mkdir()
    decoy = make_repo(decoy_root)
    run_git(decoy, "checkout", "-b", "wrong-branch")
    monkeypatch.setenv("GIT_DIR", str(decoy / ".git"))
    monkeypatch.setenv("GIT_WORK_TREE", str(decoy))
    monkeypatch.setenv("GIT_SHALLOW_FILE", str(tmp_path / "missing-shallow"))
    monkeypatch.setenv("GIT_CONFIG", str(tmp_path / "missing-config"))
    monkeypatch.setenv("GIT_CONFIG_COUNT", "1")
    monkeypatch.setenv("GIT_CONFIG_KEY_0", "core.bare")
    monkeypatch.setenv("GIT_CONFIG_VALUE_0", "true")

    assert current_branch(target) == "main"


def test_list_git_worktrees_marks_prunable_entries(tmp_path: Path):
    repo = make_repo(tmp_path)
    linked = tmp_path / "linked-prunable"
    run_git(repo, "worktree", "add", "-b", "session/S-005-feature-prunable", str(linked), "main")
    shutil.rmtree(linked)

    worktrees = list_git_worktrees(repo)

    assert worktrees[str(linked)]["prunable"] is True


def test_list_git_worktrees_preserves_newlines_in_paths(tmp_path: Path):
    repo = make_repo(tmp_path)
    linked = tmp_path / "linked\nnewline"
    run_git(repo, "worktree", "add", "-b", "session/S-006-feature-newline", str(linked), "main")

    worktrees = list_git_worktrees(repo)

    assert str(linked) in worktrees
    assert worktrees[str(linked)]["branch"] == "session/S-006-feature-newline"
