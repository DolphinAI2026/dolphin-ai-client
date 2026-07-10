from __future__ import annotations

import hashlib
import os
import re
from pathlib import Path


def _safe_name(value: str) -> str:
    name = re.sub(r"[^A-Za-z0-9_.-]+", "-", value).strip("-")
    return name or "repo"


def repo_id_for_path(repo_path: str | Path) -> str:
    resolved = Path(repo_path).resolve()
    digest = hashlib.sha1(str(resolved).encode("utf-8")).hexdigest()[:8]
    return f"{_safe_name(resolved.name)}-{digest}"


def registry_root_for_repo(repo_path: str | Path, *, home: str | Path | None = None) -> Path:
    override = os.environ.get("AGENTIC_SESSION_HOME")
    if home is not None:
        base = Path(home)
    elif override:
        base = Path(override)
    else:
        base = Path.home() / ".codex" / ".agentic-coding" / "workspaces"
    return base / repo_id_for_path(repo_path) / "sessions"


def default_worktree_parent(repo_path: str | Path) -> Path:
    return Path(repo_path).resolve().parent / "worktrees"
