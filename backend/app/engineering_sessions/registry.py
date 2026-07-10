from __future__ import annotations

import fcntl
import re
import tempfile
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import yaml

from app.engineering_sessions.models import (
    EngineeringSession,
    SessionType,
    build_session_branch,
    utc_now,
)
from app.engineering_sessions.paths import registry_root_for_repo

_TRANSACTION_LOCKS: dict[Path, threading.Lock] = {}
_TRANSACTION_LOCKS_GUARD = threading.Lock()


class SessionRegistryError(RuntimeError):
    pass


class SessionRegistry:
    def __init__(self, repo_path: str | Path, *, root: str | Path | None = None) -> None:
        self.repo_path = Path(repo_path).resolve()
        self.root = Path(root).resolve() if root is not None else registry_root_for_repo(self.repo_path)
        self._reserved_ids: set[str] = set()

    def path_for(self, session_id: str) -> Path:
        if not re.fullmatch(r"S-\d{3,}", session_id):
            raise SessionRegistryError(f"invalid session id: {session_id}")
        return self.root / f"{session_id}.yaml"

    def next_id(self) -> str:
        self.root.mkdir(parents=True, exist_ok=True)
        highest = 0
        for path in self.root.glob("S-*.yaml"):
            match = re.fullmatch(r"S-(\d+)\.yaml", path.name)
            if match:
                highest = max(highest, int(match.group(1)))
        candidate = highest + 1
        while True:
            session_id = f"S-{candidate:03d}"
            if session_id not in self._reserved_ids:
                self._reserved_ids.add(session_id)
                return session_id
            candidate += 1

    @contextmanager
    def transaction_lock(self) -> Iterator[None]:
        self.root.mkdir(parents=True, exist_ok=True)
        with _TRANSACTION_LOCKS_GUARD:
            thread_lock = _TRANSACTION_LOCKS.setdefault(self.root, threading.Lock())
        with thread_lock:
            lock_path = self.root / ".transaction.lock"
            with lock_path.open("a+", encoding="utf-8") as lock_file:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
                try:
                    yield
                finally:
                    fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)

    def create(
        self,
        *,
        session_type: SessionType | str,
        title: str,
        base_branch: str,
        worktree_path: str | None,
        base_commit: str | None = None,
        roles: list[str] | None = None,
    ) -> EngineeringSession:
        session_id = self.next_id()
        normalized_type = SessionType(session_type)
        return EngineeringSession(
            id=session_id,
            type=normalized_type,
            title=title,
            repo=self.repo_path.name,
            repo_path=str(self.repo_path),
            base_branch=base_branch,
            branch=build_session_branch(session_id, normalized_type, title),
            worktree_path=worktree_path,
            base_commit=base_commit,
            roles=roles if roles is not None else ["engineering-manager"],
        )

    def save(self, session: EngineeringSession) -> EngineeringSession:
        self.root.mkdir(parents=True, exist_ok=True)
        session.updated_at = utc_now()
        data = session.model_dump(mode="json")
        target = self.path_for(session.id)
        tmp_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=self.root,
                prefix=f".{target.name}.",
                suffix=".tmp",
                delete=False,
            ) as tmp_file:
                tmp_path = Path(tmp_file.name)
                yaml.safe_dump(data, tmp_file, allow_unicode=True, sort_keys=False)
            tmp_path.replace(target)
        finally:
            if tmp_path is not None:
                tmp_path.unlink(missing_ok=True)
        return session

    def load(self, session_id: str) -> EngineeringSession:
        path = self.path_for(session_id)
        if not path.exists():
            raise SessionRegistryError(f"session not found: {session_id}")
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        return EngineeringSession.model_validate(data)

    def list(self) -> list[EngineeringSession]:
        if not self.root.exists():
            return []
        sessions = []
        for path in sorted(self.root.glob("S-*.yaml")):
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            sessions.append(EngineeringSession.model_validate(data))
        return sessions
