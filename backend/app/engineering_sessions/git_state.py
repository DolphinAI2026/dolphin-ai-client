from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import TypedDict

from app.engineering_sessions.models import GitState

_GIT_TIMEOUT = 90
_REPOSITORY_ENV_KEYS = (
    "GIT_ALTERNATE_OBJECT_DIRECTORIES",
    "GIT_COMMON_DIR",
    "GIT_DIR",
    "GIT_GRAFT_FILE",
    "GIT_IMPLICIT_WORK_TREE",
    "GIT_INDEX_FILE",
    "GIT_NAMESPACE",
    "GIT_NO_REPLACE_OBJECTS",
    "GIT_OBJECT_DIRECTORY",
    "GIT_PREFIX",
    "GIT_REPLACE_REF_BASE",
    "GIT_SHALLOW_FILE",
    "GIT_WORK_TREE",
)
_CONFIG_ENV_KEYS = {
    "GIT_CONFIG",
    "GIT_CONFIG_COUNT",
    "GIT_CONFIG_PARAMETERS",
}
_GIT_OPERATION_PATHS = (
    "MERGE_HEAD",
    "CHERRY_PICK_HEAD",
    "REVERT_HEAD",
    "REBASE_HEAD",
    "BISECT_LOG",
    "BISECT_START",
    "rebase-merge",
    "rebase-apply",
    "sequencer",
)


class GitWorktreeEntry(TypedDict):
    head: str | None
    branch: str | None
    prunable: bool


class GitCommandError(RuntimeError):
    pass


def git(repo_path: str | Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env.setdefault("HOME", str(Path.home()))
    for key in list(env):
        if (
            key in _REPOSITORY_ENV_KEYS
            or key in _CONFIG_ENV_KEYS
            or key.startswith("GIT_CONFIG_KEY_")
            or key.startswith("GIT_CONFIG_VALUE_")
        ):
            env.pop(key, None)
    result = subprocess.run(
        ["git", "-C", str(repo_path), *args],
        capture_output=True,
        text=True,
        timeout=_GIT_TIMEOUT,
        env=env,
    )
    if check and result.returncode != 0:
        message = (result.stderr or result.stdout).strip()[:500]
        raise GitCommandError(f"git {' '.join(args)} failed: {message}")
    return result


def is_work_tree_root(repo_path: str | Path) -> bool:
    result = git(repo_path, "rev-parse", "--path-format=absolute", "--show-toplevel", check=False)
    if result.returncode != 0:
        return False
    top_level = Path(result.stdout.rstrip("\n")).resolve()
    return top_level == Path(repo_path).resolve()


def git_common_dir(repo_path: str | Path) -> Path:
    result = git(
        repo_path,
        "rev-parse",
        "--path-format=absolute",
        "--git-common-dir",
    )
    return Path(result.stdout.rstrip("\n")).resolve()


def same_git_repository(
    first_path: str | Path,
    second_path: str | Path,
) -> bool:
    try:
        return git_common_dir(first_path) == git_common_dir(second_path)
    except GitCommandError:
        return False


def rev_parse_head(repo_path: str | Path) -> str:
    return git(repo_path, "rev-parse", "HEAD").stdout.strip()


def current_branch(repo_path: str | Path) -> str:
    result = git(repo_path, "symbolic-ref", "--quiet", "HEAD", check=False)
    name = result.stdout.strip()
    return name.removeprefix("refs/heads/") if result.returncode == 0 else "HEAD"


def has_ref(repo_path: str | Path, ref: str) -> bool:
    return git(repo_path, "rev-parse", "--verify", "--quiet", ref, check=False).returncode == 0


def status_clean(repo_path: str | Path) -> bool:
    result = git(repo_path, "status", "--porcelain", "-uall")
    return not result.stdout.strip()


def git_operation_in_progress(repo_path: str | Path) -> bool:
    if git(repo_path, "ls-files", "--unmerged").stdout.strip():
        return True
    for operation_path in _GIT_OPERATION_PATHS:
        result = git(
            repo_path,
            "rev-parse",
            "--path-format=absolute",
            "--git-path",
            operation_path,
            check=False,
        )
        if result.returncode == 0 and Path(result.stdout.rstrip("\n")).exists():
            return True
    return False


def ahead_behind(repo_path: str | Path, base_ref: str, head_ref: str = "HEAD") -> tuple[int, int]:
    if not has_ref(repo_path, base_ref) or not has_ref(repo_path, head_ref):
        return 0, 0
    result = git(repo_path, "rev-list", "--left-right", "--count", f"{base_ref}...{head_ref}")
    parts = result.stdout.split()
    if len(parts) != 2:
        return 0, 0
    behind, ahead = int(parts[0]), int(parts[1])
    return ahead, behind


def merged_to_base(repo_path: str | Path, base_ref: str, head_ref: str = "HEAD") -> bool:
    if not has_ref(repo_path, base_ref) or not has_ref(repo_path, head_ref):
        return False
    return git(repo_path, "merge-base", "--is-ancestor", head_ref, base_ref, check=False).returncode == 0


def inspect_git_state(
    worktree_path: str | Path | None,
    *,
    base_branch: str,
    expected_branch: str | None = None,
    session_base_commit: str | None = None,
    very_stale_behind: int = 20,
    expected_repo_path: str | Path | None = None,
    repository_path: str | Path | None = None,
) -> GitState:
    if worktree_path is None:
        return GitState(clean=False, missing_worktree=True, stale=True)

    worktree = Path(worktree_path)
    if not worktree.exists() or not is_work_tree_root(worktree):
        return GitState(clean=False, missing_worktree=True, stale=True)

    expected_repository = (
        expected_repo_path if expected_repo_path is not None else repository_path
    )
    if expected_repository is not None and not same_git_repository(
        worktree,
        expected_repository,
    ):
        return GitState(clean=False, missing_worktree=True, stale=True)

    branch = current_branch(worktree)
    head = rev_parse_head(worktree)
    clean = status_clean(worktree)
    remote_ref = f"refs/remotes/origin/{base_branch}"
    local_ref = f"refs/heads/{base_branch}"
    base_ref = remote_ref if has_ref(worktree, remote_ref) else local_ref
    ahead, behind = ahead_behind(worktree, base_ref)
    merged = merged_to_base(worktree, base_ref)
    branch_mismatch = expected_branch is not None and branch != expected_branch
    if branch_mismatch or (
        session_base_commit is not None and head == session_base_commit
    ):
        merged = False
    return GitState(
        clean=clean,
        ahead=ahead,
        behind=behind,
        merged_to_base=merged,
        stale=behind > 0,
        very_stale=behind >= very_stale_behind,
        missing_worktree=False,
        branch_mismatch=branch_mismatch,
        current_branch=branch,
        head_commit=head,
        retained=merged,
    )


def fetch_origin(repo_path: str | Path) -> bool:
    if not has_ref(repo_path, "refs/remotes/origin/HEAD"):
        remotes = git(repo_path, "remote", check=False)
        if "origin" not in remotes.stdout.split():
            return False
    return git(repo_path, "fetch", "origin", check=False).returncode == 0


def list_git_worktrees(repo_path: str | Path) -> dict[str, GitWorktreeEntry]:
    result = git(repo_path, "worktree", "list", "--porcelain", "-z")
    items: dict[str, GitWorktreeEntry] = {}
    for block in result.stdout.split("\0\0"):
        fields = [field for field in block.split("\0") if field]
        if not fields or not fields[0].startswith("worktree "):
            continue
        path = fields[0].removeprefix("worktree ")
        entry: GitWorktreeEntry = {"head": None, "branch": None, "prunable": False}
        for field in fields[1:]:
            if field.startswith("HEAD "):
                entry["head"] = field.removeprefix("HEAD ")
            elif field.startswith("branch "):
                entry["branch"] = field.removeprefix("branch refs/heads/")
            elif field.startswith("prunable"):
                entry["prunable"] = True
        items[path] = entry
    return items
