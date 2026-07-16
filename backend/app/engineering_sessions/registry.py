from __future__ import annotations

import errno
import os
import re
import sys
import tempfile
import threading
import time
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
_OWNER_FILE = ".repository.yaml"
_LOCK_TIMEOUT_SECONDS = 30.0
_LOCK_RETRY_SECONDS = 0.05

try:
    import fcntl as _fcntl
except ImportError:
    _fcntl = None

try:
    import msvcrt as _msvcrt
except ImportError:
    _msvcrt = None


class SessionRegistryError(RuntimeError):
    pass


class SessionRegistry:
    def __init__(self, repo_path: str | Path, *, root: str | Path | None = None) -> None:
        self.repo_path = Path(repo_path).resolve()
        self.root = Path(root).resolve() if root is not None else registry_root_for_repo(self.repo_path)
        self._reserved_ids: set[str] = set()
        self.last_read_errors: list[str] = []
        self.last_unreadable_ids: set[str] = set()

    def path_for(self, session_id: str) -> Path:
        if not re.fullmatch(r"S-\d{3,}", session_id):
            raise SessionRegistryError(f"invalid session id: {session_id}")
        return self.root / f"{session_id}.yaml"

    def reserve_ids(self, session_ids: set[str]) -> None:
        self._reserved_ids.update(
            session_id
            for session_id in session_ids
            if re.fullmatch(r"S-\d{3,}", session_id)
        )

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
                self._lock_file(lock_file)
                try:
                    self._ensure_owner()
                    yield
                finally:
                    self._unlock_file(lock_file)

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
            type=normalized_type.value,
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
        self._ensure_owner()
        self._validate_session_owner(session)
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
                tmp_file.flush()
                os.fsync(tmp_file.fileno())
            tmp_path.replace(target)
            self._fsync_directory()
        finally:
            if tmp_path is not None:
                self._cleanup_path(
                    tmp_path,
                    "registry temporary file cleanup failed",
                )
        return session

    def load(self, session_id: str) -> EngineeringSession:
        self._ensure_owner()
        path = self.path_for(session_id)
        if not path.exists():
            raise SessionRegistryError(f"session not found: {session_id}")
        return self._load_path(path)

    def list(self) -> list[EngineeringSession]:
        self.last_read_errors = []
        self.last_unreadable_ids = set()
        self._ensure_owner()
        if not self.root.exists():
            return []
        sessions = []
        for path in sorted(self.root.glob("S-*.yaml")):
            try:
                sessions.append(self._load_path(path))
            except SessionRegistryError as exc:
                self._record_read_error(path, exc)
        return sessions

    @staticmethod
    def _lock_file(lock_file) -> None:
        if _fcntl is not None:
            _fcntl.flock(lock_file.fileno(), _fcntl.LOCK_EX)
            return
        if _msvcrt is not None:
            lock_file.seek(0, os.SEEK_END)
            if lock_file.tell() == 0:
                lock_file.write("\0")
                lock_file.flush()
            lock_file.seek(0)
            deadline = time.monotonic() + _LOCK_TIMEOUT_SECONDS
            while True:
                try:
                    _msvcrt.locking(
                        lock_file.fileno(),
                        _msvcrt.LK_NBLCK,
                        1,
                    )
                    return
                except OSError as exc:
                    contended = exc.errno in {
                        errno.EACCES,
                        errno.EAGAIN,
                        errno.EDEADLK,
                    } or getattr(exc, "winerror", None) in {33, 36}
                    if not contended:
                        raise SessionRegistryError(
                            "failed to acquire file lock"
                        ) from exc
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise SessionRegistryError(
                            "timed out acquiring file lock"
                        ) from exc
                    time.sleep(min(_LOCK_RETRY_SECONDS, remaining))
        raise SessionRegistryError("no supported file locking implementation")

    @staticmethod
    def _unlock_file(lock_file) -> None:
        if _fcntl is not None:
            _fcntl.flock(lock_file.fileno(), _fcntl.LOCK_UN)
            return
        if _msvcrt is not None:
            lock_file.seek(0)
            _msvcrt.locking(lock_file.fileno(), _msvcrt.LK_UNLCK, 1)

    def _owner_path(self) -> Path:
        return self.root / _OWNER_FILE

    def _ensure_owner(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        owner_path = self._owner_path()
        if owner_path.exists():
            self._validate_owner_file(owner_path)
            return

        record_paths = sorted(self.root.glob("S-*.yaml"))
        inferred_repo_paths: set[Path] = set()
        for path in record_paths:
            try:
                data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            except (OSError, yaml.YAMLError) as exc:
                self._record_read_error(path, exc)
                continue
            if not isinstance(data, dict):
                self._record_read_error(
                    path,
                    SessionRegistryError(
                        f"invalid session record {path.stem}: expected a mapping"
                    ),
                )
                continue
            value = data.get("repo_path")
            if not isinstance(value, str) or not value:
                self._record_read_error(
                    path,
                    SessionRegistryError(
                        f"invalid session record {path.stem}: "
                        "missing valid repo_path"
                    ),
                )
                continue
            inferred_repo_paths.add(Path(value).resolve())
        if record_paths and not inferred_repo_paths:
            raise SessionRegistryError(
                "cannot verify registry owner from existing session records"
            )
        if len(inferred_repo_paths) > 1:
            raise SessionRegistryError(
                "conflicting repository owners in existing session records"
            )
        if inferred_repo_paths and self.repo_path not in inferred_repo_paths:
            inferred_repo_path = next(iter(inferred_repo_paths))
            raise SessionRegistryError(
                f"registry belongs to another repository: {inferred_repo_path}"
            )

        payload = {"repo_path": str(self.repo_path)}
        tmp_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=self.root,
                prefix=f".{owner_path.name}.",
                suffix=".tmp",
                delete=False,
            ) as owner_file:
                tmp_path = Path(owner_file.name)
                yaml.safe_dump(payload, owner_file, sort_keys=False)
                owner_file.flush()
                os.fsync(owner_file.fileno())
            with self._owner_creation_lock():
                if owner_path.exists():
                    self._validate_owner_file(owner_path)
                else:
                    tmp_path.replace(owner_path)
                    self._fsync_directory()
        finally:
            if tmp_path is not None:
                self._cleanup_path(
                    tmp_path,
                    "registry owner temporary file cleanup failed",
                )

    def _validate_owner_file(self, owner_path: Path) -> None:
        try:
            data = yaml.safe_load(owner_path.read_text(encoding="utf-8")) or {}
        except (OSError, yaml.YAMLError) as exc:
            raise SessionRegistryError(
                f"invalid registry owner file: {owner_path}"
            ) from exc
        if not isinstance(data, dict):
            raise SessionRegistryError(f"invalid registry owner file: {owner_path}")
        owner_repo_path = data.get("repo_path")
        if not owner_repo_path:
            raise SessionRegistryError(f"invalid registry owner file: {owner_path}")
        resolved_owner = Path(owner_repo_path).resolve()
        if resolved_owner != self.repo_path:
            raise SessionRegistryError(
                f"registry belongs to another repository: {resolved_owner}"
            )

    def _validate_session_owner(self, session: EngineeringSession) -> None:
        session_repo_path = Path(session.repo_path).resolve()
        if session_repo_path != self.repo_path:
            raise SessionRegistryError(
                f"session {session.id} belongs to another repository: "
                f"{session_repo_path}"
            )

    def _load_path(self, path: Path) -> EngineeringSession:
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            if not isinstance(data, dict):
                raise ValueError("expected a mapping")
            session = EngineeringSession.model_validate(data)
            self._validate_session_owner(session)
            return session
        except SessionRegistryError:
            raise
        except (OSError, yaml.YAMLError, ValueError) as exc:
            raise SessionRegistryError(
                f"invalid session record {path.stem}: {exc}"
            ) from exc

    def _record_read_error(self, path: Path, exc: Exception) -> None:
        session_id = path.stem
        if re.fullmatch(r"S-\d{3,}", session_id):
            self.last_unreadable_ids.add(session_id)
        message = str(exc)
        if not message.startswith("invalid session record"):
            message = f"invalid session record {session_id}: {message}"
        if message not in self.last_read_errors:
            self.last_read_errors.append(message)

    @staticmethod
    def _cleanup_path(path: Path, context: str) -> None:
        primary_exc = sys.exc_info()[1]
        try:
            path.unlink(missing_ok=True)
        except Exception as cleanup_exc:
            if primary_exc is None:
                raise
            try:
                primary_exc.add_note(f"{context}: {cleanup_exc}")
            except AttributeError:
                pass

    @contextmanager
    def _owner_creation_lock(self) -> Iterator[None]:
        lock_path = self.root / ".repository.lock"
        with _TRANSACTION_LOCKS_GUARD:
            thread_lock = _TRANSACTION_LOCKS.setdefault(
                lock_path,
                threading.Lock(),
            )
        with thread_lock:
            with lock_path.open("a+", encoding="utf-8") as lock_file:
                self._lock_file(lock_file)
                try:
                    yield
                finally:
                    self._unlock_file(lock_file)

    def _fsync_directory(self) -> None:
        try:
            directory_fd = os.open(self.root, os.O_RDONLY)
        except OSError as exc:
            unsupported_errors = {
                errno.EINVAL,
                errno.ENOTSUP,
                getattr(errno, "EOPNOTSUPP", errno.ENOTSUP),
            }
            if os.name == "nt":
                unsupported_errors.update({errno.EACCES, errno.EPERM})
            if exc.errno in unsupported_errors:
                return
            raise
        try:
            os.fsync(directory_fd)
        except OSError as exc:
            if exc.errno not in {
                errno.EINVAL,
                errno.ENOTSUP,
                getattr(errno, "EOPNOTSUPP", errno.ENOTSUP),
            }:
                raise
        finally:
            os.close(directory_fd)
