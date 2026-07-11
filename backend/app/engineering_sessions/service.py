from __future__ import annotations

import errno
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import threading
from hashlib import sha256
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from app.engineering_sessions.git_state import (
    GitCommandError,
    GitWorktreeEntry,
    ahead_behind,
    current_branch,
    discover_remote_default_branch,
    fetch_origin,
    git,
    git_common_dir,
    git_control_worktree,
    git_operation_in_progress,
    has_ref,
    inspect_git_state,
    list_git_worktrees,
    resolve_base_ref,
)
from app.engineering_sessions.models import (
    EngineeringSession,
    GitState,
    SessionStatus,
    SessionType,
    utc_now,
)
from app.engineering_sessions.paths import default_worktree_parent
from app.engineering_sessions.registry import SessionRegistry, SessionRegistryError

_COMMIT_IDENTITY = [
    "-c",
    "user.name=ai-builder",
    "-c",
    "user.email=ai-builder@local",
    "-c",
    "commit.gpgSign=false",
]
_CREATE_RETRY_LIMIT = 100
_GIT_MUTATION_LOCKS: dict[Path, threading.Lock] = {}
_GIT_MUTATION_LOCKS_GUARD = threading.Lock()


class _SessionIdentityConflict(RuntimeError):
    pass


class _WorktreeClaimConflict(RuntimeError):
    pass


@dataclass
class _SessionReservation:
    identity_ref: str
    owner_ref: str
    initial_commit: str
    branch: str
    branch_ref: str | None = None
    claim_ref: str | None = None
    path: Path | None = None
    worktree_created: bool = False


class EngineeringSessionService:
    @staticmethod
    def requires_worktree(session_type: SessionType | str) -> bool:
        normalized_type = SessionType(session_type)
        return normalized_type in {
            SessionType.NEW_APP,
            SessionType.SPEC_CHANGE,
        }

    def __init__(
        self,
        repo_path: str | Path,
        *,
        registry_root: str | Path | None = None,
        worktree_parent: str | Path | None = None,
    ) -> None:
        resolved_repo_path = Path(repo_path).resolve()
        self.repo_path = git_control_worktree(resolved_repo_path)
        self.worktree_parent = (
            Path(worktree_parent).resolve()
            if worktree_parent is not None
            else default_worktree_parent(self.repo_path)
        )
        self.registry = SessionRegistry(self.repo_path, root=registry_root)
        object_format = git(
            self.repo_path,
            "rev-parse",
            "--show-object-format",
        ).stdout.strip()
        self._zero_object_id = "0" * (
            64 if object_format == "sha256" else 40
        )

    def create(
        self,
        session_type: SessionType | str,
        title: str,
        *,
        base_branch: str | None = None,
        create_worktree: bool = True,
        roles: list[str] | None = None,
    ) -> EngineeringSession:
        normalized_type = SessionType(session_type)
        if not create_worktree and self.requires_worktree(normalized_type):
            raise ValueError(
                f"session type '{normalized_type.value}' requires a worktree"
            )

        self._fetch_origin_or_raise()
        base = base_branch or self._default_base_branch()
        with self.registry.transaction_lock(), self._git_mutation_lock():
            base_ref = resolve_base_ref(self.repo_path, base)
            if base_ref is None:
                raise ValueError(f"base branch does not exist: {base}")
            base_commit = git(self.repo_path, "rev-parse", base_ref).stdout.strip()
            self.registry.reserve_ids(self._git_session_ids())
            for _attempt in range(_CREATE_RETRY_LIMIT):
                session = self.registry.create(
                    session_type=normalized_type,
                    title=title,
                    base_branch=base,
                    worktree_path=None,
                    base_commit=base_commit,
                    roles=roles,
                )
                reservation: _SessionReservation | None = None
                try:
                    reservation = self._reserve_session_identity(
                        session,
                        base_commit,
                    )
                    if create_worktree:
                        path = (
                            self.worktree_parent
                            / session.branch.replace("/", "-")
                        )
                        session.worktree_path = str(path)
                        self._ensure_worktree(session, reservation)
                    self._sync_session(session)
                    return self.registry.save(session)
                except (
                    _SessionIdentityConflict,
                    _WorktreeClaimConflict,
                ):
                    if reservation is not None:
                        self._rollback_reservation(reservation)
                    self.registry.reserve_ids(self._git_session_ids())
                    continue
                except Exception as exc:
                    if reservation is not None:
                        if self._registry_record_is_published(session):
                            self._attach_rollback_notes(
                                exc,
                                [
                                    f"registry record {session.id} was already "
                                    "published; retained reserved Git resources"
                                ],
                            )
                        else:
                            self._attach_rollback_notes(
                                exc,
                                self._rollback_reservation(reservation),
                            )
                    raise
            raise SessionRegistryError(
                f"unable to reserve a unique session identity after "
                f"{_CREATE_RETRY_LIMIT} attempts"
            )

    def resume(self, session_id: str) -> EngineeringSession:
        self._fetch_origin_or_raise()
        with self.registry.transaction_lock():
            session = self.registry.load(session_id)
            self._sync_session(session)
            if (
                not session.git_state.missing_worktree
                and not session.git_state.base_missing
                and not session.git_state.branch_mismatch
                and not session.git_state.worktree_ambiguous
                and not session.git_state.merged_to_base
                and session.status
                not in {
                    SessionStatus.BLOCKED_RETAINED,
                    SessionStatus.ORPHAN_SESSION,
                }
            ):
                session.status = SessionStatus.RUNNING
                session.cleanup.suggested = False
            return self.registry.save(session)

    def sync(self, session_id: str) -> EngineeringSession:
        self._fetch_origin_or_raise()
        with self.registry.transaction_lock():
            return self._sync_and_save_locked(session_id)

    def sync_model(self, session: EngineeringSession) -> EngineeringSession:
        if self._violates_static_worktree_invariant(session):
            return self._mark_missing_worktree(session)

        if session.worktree_path is None:
            base_ref = resolve_base_ref(
                self.repo_path,
                session.base_branch,
            )
            base_missing = base_ref is None
            ahead = 0
            behind = 0
            if (
                base_ref is not None
                and session.base_commit is not None
                and has_ref(self.repo_path, session.base_commit)
            ):
                ahead, behind = ahead_behind(
                    self.repo_path,
                    base_ref,
                    session.base_commit,
                )
            self._replace_git_state(
                session,
                GitState(
                    clean=True,
                    ahead=ahead,
                    behind=behind,
                    stale=base_missing or ahead > 0 or behind > 0,
                    very_stale=behind >= 20,
                    base_missing=base_missing,
                    head_commit=session.base_commit,
                ),
            )
            session.head_commit = session.base_commit
            session.last_sync_at = utc_now()
            if base_missing:
                session.cleanup.suggested = False
            return session

        transient_statuses = {
            SessionStatus.MISSING_WORKTREE,
            SessionStatus.AMBIGUOUS_WORKTREE,
        }
        if session.status in transient_statuses:
            previous_status = (
                session.unavailable_lifecycle_status
                or session.status
            )
        else:
            previous_status = session.status
            if (
                session.unavailable_lifecycle_status is not None
                and session.unavailable_lifecycle_status != session.status
            ):
                session.unavailable_lifecycle_status = session.status
        dirty_uncheckpointed = session.git_state.dirty_uncheckpointed
        state = inspect_git_state(
            session.worktree_path,
            base_branch=session.base_branch,
            expected_branch=session.branch,
            session_base_commit=session.base_commit,
            expected_repo_path=self.repo_path,
        )
        state.dirty_uncheckpointed = dirty_uncheckpointed and (
            state.missing_worktree
            or state.base_missing
            or state.branch_mismatch
            or state.worktree_ambiguous
            or not state.clean
        )
        self._replace_git_state(session, state)
        session.head_commit = state.head_commit
        session.last_sync_at = utc_now()
        if (
            session.unavailable_lifecycle_status is not None
            and not state.missing_worktree
            and not state.worktree_ambiguous
        ):
            session.status = previous_status
        if state.missing_worktree:
            self._remember_unavailable_lifecycle(session)
            session.status = SessionStatus.MISSING_WORKTREE
            session.cleanup.suggested = False
        elif state.worktree_ambiguous:
            session.status = SessionStatus.AMBIGUOUS_WORKTREE
            session.cleanup.suggested = False
        elif state.branch_mismatch:
            if previous_status in (
                SessionStatus.MISSING_WORKTREE,
                SessionStatus.MERGED_RETAINED,
            ):
                session.status = SessionStatus.RUNNING
            session.cleanup.suggested = False
        elif state.base_missing:
            if previous_status == SessionStatus.MISSING_WORKTREE:
                session.status = SessionStatus.RUNNING
            session.cleanup.suggested = False
            return session
        elif previous_status == SessionStatus.BLOCKED_RETAINED:
            session.status = SessionStatus.BLOCKED_RETAINED
            session.cleanup.suggested = False
        elif previous_status == SessionStatus.ORPHAN_SESSION:
            session.status = SessionStatus.ORPHAN_SESSION
            session.cleanup.suggested = state.clean and state.merged_to_base
        elif previous_status == SessionStatus.ARCHIVED_DIRTY and state.clean:
            if state.merged_to_base:
                session.status = SessionStatus.MERGED_RETAINED
                session.cleanup.suggested = True
            else:
                session.status = SessionStatus.ABANDONED_RETAINED
                session.cleanup.suggested = False
        elif state.merged_to_base and state.clean:
            session.status = SessionStatus.MERGED_RETAINED
            session.cleanup.suggested = True
        elif previous_status in (
            SessionStatus.MISSING_WORKTREE,
            SessionStatus.MERGED_RETAINED,
            SessionStatus.AMBIGUOUS_WORKTREE,
        ):
            session.status = SessionStatus.RUNNING
            session.cleanup.suggested = False
        elif previous_status == SessionStatus.ARCHIVED_DIRTY:
            session.cleanup.suggested = False
        if not (
            state.missing_worktree
            or state.worktree_ambiguous
            or state.branch_mismatch
            or state.base_missing
        ):
            session.unavailable_lifecycle_status = None
        return session

    def checkpoint(self, session_id: str, message: str | None = None) -> bool:
        self._fetch_origin_or_raise()
        with self.registry.transaction_lock(), self._git_mutation_lock():
            session = self.registry.load(session_id)
            live_index_mode = self._index_mode(session)
            self._sync_session(session)
            session = self.registry.save(session)
            created, _ = self._checkpoint_locked(
                session,
                message,
                live_index_mode=live_index_mode,
            )
            return created

    def archive(self, session_id: str, *, checkpoint: bool = True) -> EngineeringSession:
        self._fetch_origin_or_raise()
        with self.registry.transaction_lock(), self._git_mutation_lock():
            session = self.registry.load(session_id)
            live_index_mode = self._index_mode(session)
            self._sync_session(session)
            session = self.registry.save(session)
            if session.status == SessionStatus.BLOCKED_RETAINED:
                session.cleanup.suggested = False
                return self.registry.save(session)
            if (
                session.git_state.missing_worktree
                or session.git_state.base_missing
                or session.git_state.worktree_ambiguous
            ):
                return session

            if checkpoint and not session.git_state.clean:
                _, session = self._checkpoint_locked(
                    session,
                    live_index_mode=live_index_mode,
                )
                if (
                    session.git_state.missing_worktree
                    or session.git_state.base_missing
                    or session.git_state.worktree_ambiguous
                ):
                    return session

            if session.git_state.clean and session.git_state.merged_to_base:
                session.status = SessionStatus.MERGED_RETAINED
                session.cleanup.suggested = True
            elif session.git_state.clean:
                session.status = SessionStatus.ABANDONED_RETAINED
                session.cleanup.suggested = False
            else:
                session.status = SessionStatus.ARCHIVED_DIRTY
                session.git_state.dirty_uncheckpointed = True
                session.cleanup.suggested = False
            return self.registry.save(session)

    def list(self, *, sync: bool = False) -> list[EngineeringSession]:
        if not sync:
            with self.registry.transaction_lock():
                sessions = self.registry.list()
                for session in sessions:
                    if self._normalize_static_session_invariants(session):
                        self.registry.save(session)
                return sessions
        self._fetch_origin_or_raise()
        with self.registry.transaction_lock():
            sessions = self.registry.list()
            worktrees = self._active_worktrees()
            paths_by_branch = self._worktree_paths_by_branch(worktrees)
            return [
                self.registry.save(
                    self._sync_session(session, paths_by_branch=paths_by_branch)
                )
                for session in sessions
            ]

    def reconcile(self) -> list[EngineeringSession]:
        self._fetch_origin_or_raise()
        base_branch = self._default_base_branch()
        with self.registry.transaction_lock(), self._git_mutation_lock():
            all_worktrees = list_git_worktrees(self.repo_path)
            worktrees = {
                path: item
                for path, item in all_worktrees.items()
                if not item["prunable"]
            }
            prunable_branches = {
                item["branch"]
                for item in all_worktrees.values()
                if item["prunable"] and item["branch"] is not None
            }
            paths_by_branch = self._worktree_paths_by_branch(worktrees)
            registry_sessions = self.registry.list()
            sessions = [
                self.registry.save(
                    self._sync_session(session, paths_by_branch=paths_by_branch)
                )
                for session in registry_sessions
            ]
            known_branches = {session.branch for session in sessions}
            for path, item in worktrees.items():
                branch = item["branch"]
                if (
                    Path(path).resolve() == self.repo_path
                    or branch is None
                    or not branch.startswith("session/")
                    or branch in known_branches
                ):
                    continue
                match = re.match(r"^session/(S-\d{3,})(?:-|$)", branch)
                if (
                    match is not None
                    and match.group(1) in self.registry.last_unreadable_ids
                ):
                    warning = (
                        f"reconcile skipped {branch}: registry record "
                        f"{match.group(1)} is unreadable"
                    )
                    if warning not in self.registry.last_read_errors:
                        self.registry.last_read_errors.append(warning)
                    continue

                session = self._register_orphan_session(
                    branch=branch,
                    path=path,
                    head_commit=item["head"],
                    base_branch=base_branch,
                    paths_by_branch=paths_by_branch,
                )
                if session is None:
                    continue
                sessions.append(session)
                known_branches.add(branch)
            for branch, head_commit in self._session_branch_heads().items():
                if (
                    branch in known_branches
                    or branch in paths_by_branch
                    or branch in prunable_branches
                ):
                    continue
                match = re.match(r"^session/(S-\d{3,})(?:-|$)", branch)
                if (
                    match is not None
                    and match.group(1) in self.registry.last_unreadable_ids
                ):
                    warning = (
                        f"reconcile skipped {branch}: registry record "
                        f"{match.group(1)} is unreadable"
                    )
                    if warning not in self.registry.last_read_errors:
                        self.registry.last_read_errors.append(warning)
                    continue
                session = self._register_orphan_session(
                    branch=branch,
                    path=str(
                        (
                            self.worktree_parent
                            / branch.replace("/", "-")
                        ).resolve()
                    ),
                    head_commit=head_commit,
                    base_branch=base_branch,
                    paths_by_branch=paths_by_branch,
                )
                if session is None:
                    continue
                sessions.append(session)
                known_branches.add(branch)
            return sessions

    def _sync_and_save_locked(self, session_id: str) -> EngineeringSession:
        session = self.registry.load(session_id)
        self._sync_session(session)
        return self.registry.save(session)

    def _checkpoint_locked(
        self,
        session: EngineeringSession,
        message: str | None = None,
        *,
        live_index_mode: int | None = None,
    ) -> tuple[bool, EngineeringSession]:
        if (
            session.worktree_path is None
            or session.git_state.missing_worktree
            or session.git_state.base_missing
            or session.git_state.branch_mismatch
            or session.git_state.worktree_ambiguous
            or git_operation_in_progress(session.worktree_path)
            or session.git_state.clean
        ):
            return False, session

        commit_message = message or f"checkpoint: {session.id} {session.title}"
        branch_ref = f"refs/heads/{session.branch}"
        temporary_index: Path | None = None
        live_index: Path | None = None
        live_index_snapshot: bytes | None = None
        index_published = False
        try:
            try:
                expected_head = git(
                    self.repo_path,
                    "rev-parse",
                    branch_ref,
                ).stdout.strip()
                if (
                    session.head_commit is not None
                    and expected_head != session.head_commit
                ):
                    return False, self._refresh_and_save_locked(session)
                live_index = Path(
                    git(
                        session.worktree_path,
                        "rev-parse",
                        "--path-format=absolute",
                        "--git-path",
                        "index",
                    ).stdout.rstrip("\n")
                )
                live_index_snapshot = (
                    live_index.read_bytes()
                    if live_index.exists()
                    else None
                )
                live_index.parent.mkdir(parents=True, exist_ok=True)
                temporary_fd, temporary_name = tempfile.mkstemp(
                    prefix=".agentic-checkpoint-index.",
                    dir=live_index.parent,
                )
                os.close(temporary_fd)
                temporary_index = Path(temporary_name)
                if live_index_snapshot is None:
                    temporary_index.unlink()
                    git(
                        session.worktree_path,
                        "read-tree",
                        expected_head,
                        env_overrides={
                            "GIT_INDEX_FILE": str(temporary_index)
                        },
                    )
                else:
                    temporary_index.write_bytes(live_index_snapshot)
                index_env = {"GIT_INDEX_FILE": str(temporary_index)}
                git(
                    session.worktree_path,
                    *_COMMIT_IDENTITY,
                    "add",
                    "-A",
                    env_overrides=index_env,
                )
                if (
                    current_branch(session.worktree_path) != session.branch
                    or git_operation_in_progress(session.worktree_path)
                ):
                    return False, self._refresh_and_save_locked(session)
                tree = git(
                    session.worktree_path,
                    "write-tree",
                    env_overrides=index_env,
                ).stdout.strip()
                result = git(
                    session.worktree_path,
                    *_COMMIT_IDENTITY,
                    "commit-tree",
                    tree,
                    "-p",
                    expected_head,
                    "-m",
                    commit_message,
                    check=False,
                )
            except Exception as exc:
                self._refresh_after_checkpoint_failure(session, exc)
                raise
            if result.returncode != 0:
                detail = (result.stderr or result.stdout).strip()[:500]
                exc = GitCommandError(f"git commit failed: {detail}")
                self._refresh_after_checkpoint_failure(session, exc)
                raise exc
            if (
                current_branch(session.worktree_path) != session.branch
                or git_operation_in_progress(session.worktree_path)
            ):
                return False, self._refresh_and_save_locked(session)
            new_commit = result.stdout.strip()
            try:
                update_result = git(
                    self.repo_path,
                    "update-ref",
                    branch_ref,
                    new_commit,
                    expected_head,
                    check=False,
                )
            except Exception as exc:
                branch_advanced = False
                try:
                    branch_advanced = (
                        git(
                            self.repo_path,
                            "rev-parse",
                            branch_ref,
                            check=False,
                        ).stdout.strip()
                        == new_commit
                    )
                except Exception as recovery_exc:
                    self._attach_exception_note(
                        exc,
                        "checkpoint branch verification failed",
                        recovery_exc,
                    )
                if branch_advanced:
                    try:
                        if self._publish_checkpoint_index(
                            session,
                            live_index,
                            live_index_snapshot,
                            temporary_index,
                            live_index_mode,
                            new_commit,
                        ):
                            temporary_index = None
                            index_published = True
                        else:
                            self._attach_exception_note(
                                exc,
                                "checkpoint index recovery skipped",
                                GitCommandError(
                                    "live index publish was refused because "
                                    "Git state changed"
                                ),
                            )
                    except Exception as recovery_exc:
                        self._attach_exception_note(
                            exc,
                            "checkpoint index recovery failed",
                            recovery_exc,
                        )
                self._refresh_after_checkpoint_failure(session, exc)
                raise
            if update_result.returncode != 0:
                detail = (update_result.stderr or update_result.stdout).strip()[:500]
                exc = GitCommandError(f"git update-ref failed: {detail}")
                self._refresh_after_checkpoint_failure(session, exc)
                raise exc
            try:
                published = self._publish_checkpoint_index(
                    session,
                    live_index,
                    live_index_snapshot,
                    temporary_index,
                    live_index_mode,
                    new_commit,
                )
                if not published:
                    raise GitCommandError(
                        "checkpoint commit was created but live index publish "
                        "was refused because Git state changed"
                    )
                temporary_index = None
                index_published = True
            except Exception as exc:
                self._refresh_after_checkpoint_failure(session, exc)
                raise
            session = self._refresh_and_save_locked(session)
            return True, session
        finally:
            if temporary_index is not None:
                self._cleanup_path(
                    temporary_index,
                    "checkpoint temporary index cleanup failed",
                )
            if (
                index_published
                and live_index is not None
                and live_index_mode is not None
            ):
                self._restore_file_mode(
                    live_index,
                    live_index_mode,
                    "checkpoint index permission restore failed",
                )

    def _sync_session(
        self,
        session: EngineeringSession,
        *,
        paths_by_branch: dict[str, list[str]] | None = None,
    ) -> EngineeringSession:
        if paths_by_branch is None:
            paths_by_branch = self._worktree_paths_by_branch(self._active_worktrees())
        actual_paths = paths_by_branch.get(session.branch, [])
        if len(actual_paths) > 1:
            return self._mark_ambiguous_worktree(session)
        if actual_paths:
            actual_path = Path(actual_paths[0]).resolve()
            if actual_path == self.repo_path:
                return self._mark_missing_worktree(session)
            session.worktree_path = str(actual_path)
        return self.sync_model(session)

    def _refresh_and_save_locked(
        self,
        session: EngineeringSession,
    ) -> EngineeringSession:
        self._sync_session(session)
        return self.registry.save(session)

    def _refresh_after_checkpoint_failure(
        self,
        session: EngineeringSession,
        primary_exc: Exception,
    ) -> None:
        try:
            self._refresh_and_save_locked(session)
        except Exception as recovery_exc:
            self._attach_exception_note(
                primary_exc,
                "checkpoint registry refresh failed",
                recovery_exc,
            )

    @staticmethod
    def _mark_missing_worktree(
        session: EngineeringSession,
        *,
        update_last_sync: bool = True,
    ) -> EngineeringSession:
        EngineeringSessionService._remember_unavailable_lifecycle(session)
        dirty_uncheckpointed = session.git_state.dirty_uncheckpointed
        EngineeringSessionService._replace_git_state(
            session,
            inspect_git_state(
                None,
                base_branch=session.base_branch,
            ),
        )
        session.git_state.dirty_uncheckpointed = dirty_uncheckpointed
        session.head_commit = None
        if update_last_sync:
            session.last_sync_at = utc_now()
        session.status = SessionStatus.MISSING_WORKTREE
        session.cleanup.suggested = False
        return session

    @staticmethod
    def _mark_ambiguous_worktree(
        session: EngineeringSession,
    ) -> EngineeringSession:
        EngineeringSessionService._remember_unavailable_lifecycle(session)
        EngineeringSessionService._replace_git_state(
            session,
            GitState(
                clean=False,
                stale=True,
                dirty_uncheckpointed=session.git_state.dirty_uncheckpointed,
                worktree_ambiguous=True,
                current_branch=session.branch,
                head_commit=session.head_commit,
            ),
        )
        session.last_sync_at = utc_now()
        session.status = SessionStatus.AMBIGUOUS_WORKTREE
        session.cleanup.suggested = False
        return session

    def _violates_static_worktree_invariant(
        self,
        session: EngineeringSession,
    ) -> bool:
        if session.worktree_path is None:
            return self.requires_worktree(session.type)
        return Path(session.worktree_path).resolve() == self.repo_path

    def _normalize_static_session_invariants(
        self,
        session: EngineeringSession,
    ) -> bool:
        changed = False
        if self._violates_static_worktree_invariant(session):
            self._mark_missing_worktree(
                session,
                update_last_sync=False,
            )
            changed = True
        if session.git_state.base_missing and session.cleanup.suggested:
            session.cleanup.suggested = False
            changed = True
        return changed

    def _active_worktrees(self) -> dict[str, GitWorktreeEntry]:
        return {
            path: item
            for path, item in list_git_worktrees(self.repo_path).items()
            if not item["prunable"]
        }

    @staticmethod
    def _worktree_paths_by_branch(
        worktrees: dict[str, GitWorktreeEntry],
    ) -> dict[str, list[str]]:
        paths_by_branch: dict[str, list[str]] = {}
        for path, item in worktrees.items():
            branch = item["branch"]
            if branch is None:
                continue
            paths_by_branch.setdefault(branch, []).append(str(Path(path).resolve()))
        for paths in paths_by_branch.values():
            paths.sort()
        return paths_by_branch

    def _default_base_branch(self) -> str:
        remote_branch = discover_remote_default_branch(self.repo_path)
        if remote_branch is not None:
            return remote_branch
        for candidate in ("main", "master"):
            if resolve_base_ref(self.repo_path, candidate) is not None:
                return candidate
        branch = current_branch(self.repo_path)
        if branch != "HEAD" and not branch.startswith("session/"):
            return branch
        raise ValueError("cannot infer default base branch; pass --base-branch")

    def _git_session_ids(self) -> set[str]:
        result = git(
            self.repo_path,
            "for-each-ref",
            "--format=%(refname)",
            "refs/heads/session/",
            "refs/agentic/sessions/",
        )
        session_ids: set[str] = set()
        for ref_name in result.stdout.splitlines():
            match = re.match(
                r"^(?:refs/heads/session/|refs/agentic/sessions/)"
                r"(S-\d{3,})(?:-|$)",
                ref_name,
            )
            if match:
                session_ids.add(match.group(1))
        return session_ids

    def _session_branch_heads(self) -> dict[str, str]:
        result = git(
            self.repo_path,
            "for-each-ref",
            "--format=%(refname:short)\t%(objectname)",
            "refs/heads/session/",
        )
        branches: dict[str, str] = {}
        for line in result.stdout.splitlines():
            branch, separator, head_commit = line.partition("\t")
            if separator and branch and head_commit:
                branches[branch] = head_commit
        return branches

    def _fetch_origin_or_raise(self) -> None:
        remotes = git(self.repo_path, "remote").stdout.split()
        if "origin" not in remotes:
            return
        if not fetch_origin(self.repo_path):
            raise GitCommandError(f"failed to fetch origin for repository: {self.repo_path}")

    def _ensure_worktree(
        self,
        session: EngineeringSession,
        reservation: _SessionReservation,
    ) -> None:
        if session.worktree_path is None:
            raise ValueError("session worktree path is required")

        path = Path(session.worktree_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            registered_worktrees = {
                Path(registered_path).resolve(): item
                for registered_path, item in list_git_worktrees(self.repo_path).items()
            }
            entry = registered_worktrees.get(path.resolve())
            if entry is None or entry["prunable"]:
                raise ValueError(f"existing worktree does not belong to repository: {path}")
            if entry["branch"] != session.branch:
                raise ValueError(f"existing worktree branch mismatch: {path}")
            raise SessionRegistryError(
                f"session worktree already exists; run reconcile first: {path}"
            )

        branch_ref = f"refs/heads/{session.branch}"
        start_point = session.base_commit
        if start_point is None:
            base_ref = f"refs/heads/{session.base_branch}"
            if not has_ref(self.repo_path, base_ref):
                raise ValueError(f"base branch does not exist: {session.base_branch}")
            start_point = base_ref
        start_commit = git(self.repo_path, "rev-parse", start_point).stdout.strip()
        self._reserve_worktree_claim(reservation)
        try:
            reserve_result = git(
                self.repo_path,
                "update-ref",
                branch_ref,
                start_commit,
                self._zero_object_id,
                check=False,
            )
        except GitCommandError as exc:
            if not (
                self._is_ambiguous_git_timeout(exc)
                and self._ref_matches(branch_ref, start_commit)
            ):
                raise
            reserve_result = None
        if reserve_result is not None and reserve_result.returncode != 0:
            if has_ref(self.repo_path, branch_ref):
                raise _SessionIdentityConflict(session.branch)
            detail = (
                reserve_result.stderr or reserve_result.stdout
            ).strip()[:500]
            raise GitCommandError(
                f"git update-ref failed reserving branch "
                f"{session.branch}: {detail}"
            )
        reservation.branch_ref = branch_ref
        reservation.path = path.resolve()
        try:
            git(
                self.repo_path,
                "worktree",
                "add",
                str(path),
                session.branch,
            )
        except GitCommandError as exc:
            if not self._is_ambiguous_git_timeout(exc):
                raise
            reservation.worktree_created = True
            try:
                entry = list_git_worktrees(self.repo_path).get(
                    str(path.resolve())
                )
            except Exception as recovery_exc:
                self._attach_exception_note(
                    exc,
                    "worktree timeout verification failed",
                    recovery_exc,
                )
                raise
            if entry is None or entry["branch"] != session.branch:
                raise
        reservation.worktree_created = True

    def _reserve_session_identity(
        self,
        session: EngineeringSession,
        commit: str,
    ) -> _SessionReservation:
        identity_ref = f"refs/agentic/sessions/{session.id}"
        try:
            result = git(
                self.repo_path,
                "update-ref",
                identity_ref,
                commit,
                self._zero_object_id,
                check=False,
            )
        except GitCommandError as exc:
            if not (
                self._is_ambiguous_git_timeout(exc)
                and self._ref_matches(identity_ref, commit)
            ):
                raise
            result = None
        if result is not None and result.returncode != 0:
            if has_ref(self.repo_path, identity_ref):
                raise _SessionIdentityConflict(session.id)
            detail = (result.stderr or result.stdout).strip()[:500]
            raise GitCommandError(
                f"git update-ref failed reserving session identity "
                f"{session.id}: {detail}"
            )
        return _SessionReservation(
            identity_ref=identity_ref,
            owner_ref=self._registry_owner_ref(session.id),
            initial_commit=commit,
            branch=session.branch,
        )

    def _register_orphan_session(
        self,
        *,
        branch: str,
        path: str,
        head_commit: str | None,
        base_branch: str,
        paths_by_branch: dict[str, list[str]],
    ) -> EngineeringSession | None:
        commit = head_commit or git(
            self.repo_path,
            "rev-parse",
            f"refs/heads/{branch}",
        ).stdout.strip()
        claim_ref = self._worktree_claim_ref(branch)
        claim_target = git(
            self.repo_path,
            "symbolic-ref",
            "--quiet",
            claim_ref,
            check=False,
        )
        if claim_target.returncode == 0:
            target = claim_target.stdout.strip()
            owner_prefix = self._registry_owner_ref("").rstrip("/")
            if not target.startswith(f"{owner_prefix}/"):
                warning = (
                    f"reconcile skipped {branch}: worktree branch is "
                    "already claimed by another registry"
                )
                if warning not in self.registry.last_read_errors:
                    self.registry.last_read_errors.append(warning)
                return None
            claimed_id = target.rsplit("/", 1)[-1]
            if not re.fullmatch(r"S-\d{3,}", claimed_id):
                warning = (
                    f"reconcile skipped {branch}: worktree claim is invalid"
                )
                if warning not in self.registry.last_read_errors:
                    self.registry.last_read_errors.append(warning)
                return None
            if claimed_id in self.registry.last_unreadable_ids:
                warning = (
                    f"reconcile skipped {branch}: registry record "
                    f"{claimed_id} is unreadable"
                )
                if warning not in self.registry.last_read_errors:
                    self.registry.last_read_errors.append(warning)
                return None
            claimed_path = self.registry.path_for(claimed_id)
            if claimed_path.exists():
                try:
                    existing_session = self.registry.load(claimed_id)
                except SessionRegistryError:
                    warning = (
                        f"reconcile skipped {branch}: registry record "
                        f"{claimed_id} is unreadable"
                    )
                else:
                    warning = (
                        f"reconcile skipped {branch}: session "
                        f"{claimed_id} is already registered for "
                        f"{existing_session.branch}"
                    )
                if warning not in self.registry.last_read_errors:
                    self.registry.last_read_errors.append(warning)
                return None
            if (
                not has_ref(
                    self.repo_path,
                    f"refs/agentic/sessions/{claimed_id}",
                )
            ):
                warning = (
                    f"reconcile skipped {branch}: worktree claim is invalid"
                )
                if warning not in self.registry.last_read_errors:
                    self.registry.last_read_errors.append(warning)
                return None
            session = self.registry.create(
                session_type=SessionType.FEATURE,
                title=branch.removeprefix("session/"),
                base_branch=base_branch,
                worktree_path=path,
                base_commit=None,
                roles=["engineering-manager"],
            )
            session.id = claimed_id
            session.branch = branch
            session.status = SessionStatus.ORPHAN_SESSION
            self._sync_session(
                session,
                paths_by_branch=paths_by_branch,
            )
            return self.registry.save(session)
        self.registry.reserve_ids(self._git_session_ids())
        for _attempt in range(_CREATE_RETRY_LIMIT):
            session = self.registry.create(
                session_type=SessionType.FEATURE,
                title=branch.removeprefix("session/"),
                base_branch=base_branch,
                worktree_path=path,
                base_commit=None,
                roles=["engineering-manager"],
            )
            reservation: _SessionReservation | None = None
            try:
                reservation = self._reserve_session_identity(
                    session,
                    commit,
                )
                reservation.branch = branch
                self._reserve_worktree_claim(reservation)
                session.branch = branch
                session.status = SessionStatus.ORPHAN_SESSION
                self._sync_session(
                    session,
                    paths_by_branch=paths_by_branch,
                )
                return self.registry.save(session)
            except _SessionIdentityConflict:
                self.registry.reserve_ids(self._git_session_ids())
                continue
            except _WorktreeClaimConflict:
                if reservation is not None:
                    self._rollback_reservation(reservation)
                warning = (
                    f"reconcile skipped {branch}: worktree branch is "
                    "already claimed by another registry"
                )
                if warning not in self.registry.last_read_errors:
                    self.registry.last_read_errors.append(warning)
                return None
            except Exception as exc:
                if reservation is not None:
                    if self._registry_record_is_published(session):
                        self._attach_rollback_notes(
                            exc,
                            [
                                f"registry record {session.id} was already "
                                "published; retained reserved Git resources"
                            ],
                        )
                    else:
                        self._attach_rollback_notes(
                            exc,
                            self._rollback_reservation(reservation),
                        )
                raise
        raise SessionRegistryError(
            f"unable to reserve a unique orphan session identity after "
            f"{_CREATE_RETRY_LIMIT} attempts"
        )

    def _reserve_worktree_claim(
        self,
        reservation: _SessionReservation,
    ) -> None:
        claim_ref = self._worktree_claim_ref(reservation.branch)
        existing = git(
            self.repo_path,
            "symbolic-ref",
            "--quiet",
            claim_ref,
            check=False,
        )
        if existing.returncode == 0 or has_ref(self.repo_path, claim_ref):
            raise _WorktreeClaimConflict(reservation.branch)
        try:
            result = git(
                self.repo_path,
                "symbolic-ref",
                claim_ref,
                reservation.owner_ref,
                check=False,
            )
        except GitCommandError as exc:
            if not self._is_ambiguous_git_timeout(exc):
                raise
            reservation.claim_ref = claim_ref
            try:
                existing = git(
                    self.repo_path,
                    "symbolic-ref",
                    "--quiet",
                    claim_ref,
                    check=False,
                )
            except Exception as recovery_exc:
                self._attach_exception_note(
                    exc,
                    "worktree claim timeout verification failed",
                    recovery_exc,
                )
                raise
            if (
                existing.returncode == 0
                and existing.stdout.strip() == reservation.owner_ref
            ):
                return
            if existing.returncode == 0:
                raise _WorktreeClaimConflict(reservation.branch) from exc
            raise
        if result.returncode != 0:
            existing = git(
                self.repo_path,
                "symbolic-ref",
                "--quiet",
                claim_ref,
                check=False,
            )
            if existing.returncode == 0 or has_ref(
                self.repo_path,
                claim_ref,
            ):
                raise _WorktreeClaimConflict(reservation.branch)
            detail = (result.stderr or result.stdout).strip()[:500]
            raise GitCommandError(
                f"git symbolic-ref failed reserving worktree claim "
                f"{reservation.branch}: {detail}"
            )
        reservation.claim_ref = claim_ref

    def _registry_owner_ref(self, session_id: str) -> str:
        registry_hash = sha256(
            str(self.registry.root).encode("utf-8")
        ).hexdigest()[:16]
        base = f"refs/agentic/registry-owners/{registry_hash}"
        return f"{base}/{session_id}" if session_id else base

    @staticmethod
    def _worktree_claim_ref(branch: str) -> str:
        return f"refs/agentic/worktree-claims/{branch}"

    def _rollback_reservation(
        self,
        reservation: _SessionReservation,
    ) -> list[str]:
        notes: list[str] = []
        if reservation.worktree_created:
            return [
                f"rollback retained worktree and refs for "
                f"{reservation.branch}; run reconcile to recover the session"
            ]
        path = reservation.path
        remaining_worktrees: dict[Path, GitWorktreeEntry] = {}
        if path is not None:
            try:
                worktrees = {
                    Path(registered_path).resolve(): item
                    for registered_path, item in list_git_worktrees(
                        self.repo_path
                    ).items()
                }
            except Exception as exc:
                notes.append(f"rollback could not inspect worktrees: {exc}")
                worktrees = {}
            entry = worktrees.get(path)
            if entry is not None and entry["branch"] == reservation.branch:
                try:
                    remove_result = git(
                        self.repo_path,
                        "worktree",
                        "remove",
                        "--force",
                        str(path),
                        check=False,
                    )
                    if remove_result.returncode != 0:
                        detail = (
                            remove_result.stderr or remove_result.stdout
                        ).strip()
                        notes.append(
                            f"rollback could not remove worktree {path}: "
                            f"{detail}"
                        )
                except Exception as exc:
                    notes.append(
                        f"rollback could not remove worktree {path}: {exc}"
                    )
            try:
                remaining_worktrees = {
                    Path(registered_path).resolve(): item
                    for registered_path, item in list_git_worktrees(
                        self.repo_path
                    ).items()
                }
            except Exception as exc:
                notes.append(f"rollback could not verify worktrees: {exc}")
                remaining_worktrees = {
                    path: {
                        "head": None,
                        "branch": reservation.branch,
                        "prunable": False,
                    }
                }
            remaining_entry = remaining_worktrees.get(path)
            if remaining_entry is None and path.exists():
                try:
                    shutil.rmtree(path)
                except Exception as exc:
                    notes.append(
                        f"rollback could not remove directory {path}: {exc}"
                    )
            elif (
                remaining_entry is not None
                and remaining_entry.get("branch") == reservation.branch
            ):
                notes.append(f"rollback left registered worktree {path}")
            try:
                git(self.repo_path, "worktree", "prune", check=False)
            except Exception as exc:
                notes.append(f"rollback could not prune worktrees: {exc}")
        branch_left = False
        if reservation.branch_ref is not None:
            try:
                branch_left = has_ref(
                    self.repo_path,
                    reservation.branch_ref,
                )
                if branch_left:
                    notes.append(
                        f"rollback retained branch {reservation.branch} "
                        "to avoid deleting concurrent Git work; run "
                        "reconcile or clean it manually"
                    )
            except Exception as exc:
                branch_left = True
                notes.append(
                    f"rollback could not verify branch cleanup: {exc}"
                )
        path_left = path is not None and path.exists()
        if not branch_left and not path_left:
            if reservation.claim_ref is not None:
                try:
                    claim_target = git(
                        self.repo_path,
                        "symbolic-ref",
                        "--quiet",
                        reservation.claim_ref,
                        check=False,
                    )
                    if (
                        claim_target.returncode == 0
                        and claim_target.stdout.strip() == reservation.owner_ref
                    ):
                        claim_delete = git(
                            self.repo_path,
                            "symbolic-ref",
                            "--delete",
                            reservation.claim_ref,
                            check=False,
                        )
                        if claim_delete.returncode != 0:
                            detail = (
                                claim_delete.stderr or claim_delete.stdout
                            ).strip()
                            notes.append(
                                f"rollback could not release worktree claim "
                                f"{reservation.claim_ref}: {detail}"
                            )
                except Exception as exc:
                    notes.append(
                        f"rollback could not release worktree claim "
                        f"{reservation.claim_ref}: {exc}"
                    )
            try:
                delete_result = git(
                    self.repo_path,
                    "update-ref",
                    "-d",
                    reservation.identity_ref,
                    reservation.initial_commit,
                    check=False,
                )
                if delete_result.returncode != 0 and has_ref(
                    self.repo_path,
                    reservation.identity_ref,
                ):
                    detail = (
                        delete_result.stderr or delete_result.stdout
                    ).strip()
                    notes.append(
                        f"rollback could not release identity "
                        f"{reservation.identity_ref}: {detail}"
                    )
            except Exception as exc:
                notes.append(
                    f"rollback could not release identity "
                    f"{reservation.identity_ref}: {exc}"
                )
        else:
            notes.append(
                f"rollback retained identity {reservation.identity_ref} "
                f"because Git resources remain"
            )
        return notes

    @staticmethod
    def _attach_rollback_notes(exc: Exception, notes: list[str]) -> None:
        for note in notes:
            try:
                exc.add_note(note)
            except AttributeError:
                break

    @staticmethod
    def _attach_exception_note(
        exc: Exception,
        context: str,
        detail: Exception,
    ) -> None:
        try:
            exc.add_note(f"{context}: {detail}")
        except AttributeError:
            pass

    @staticmethod
    def _is_ambiguous_git_timeout(exc: BaseException) -> bool:
        current: BaseException | None = exc
        while current is not None:
            if isinstance(current, subprocess.TimeoutExpired):
                return True
            current = current.__cause__ or current.__context__
        return False

    def _ref_matches(self, ref: str, expected_commit: str) -> bool:
        try:
            result = git(
                self.repo_path,
                "rev-parse",
                "--verify",
                ref,
                check=False,
            )
        except Exception:
            return False
        return (
            result.returncode == 0
            and result.stdout.strip() == expected_commit
        )

    def _registry_record_is_published(
        self,
        session: EngineeringSession,
    ) -> bool:
        try:
            persisted = self.registry.load(session.id)
        except (OSError, SessionRegistryError, ValueError):
            return False
        return (
            persisted.branch == session.branch
            and persisted.worktree_path == session.worktree_path
            and persisted.repo_path == session.repo_path
        )

    @contextmanager
    def _git_mutation_lock(self) -> Iterator[None]:
        lock_path = git_common_dir(self.repo_path) / "agentic-sessions.lock"
        with _GIT_MUTATION_LOCKS_GUARD:
            thread_lock = _GIT_MUTATION_LOCKS.setdefault(
                lock_path,
                threading.Lock(),
            )
        with thread_lock:
            with lock_path.open("a+", encoding="utf-8") as lock_file:
                SessionRegistry._lock_file(lock_file)
                try:
                    yield
                finally:
                    SessionRegistry._unlock_file(lock_file)

    @staticmethod
    def _remember_unavailable_lifecycle(session: EngineeringSession) -> None:
        if session.status not in {
            SessionStatus.MISSING_WORKTREE,
            SessionStatus.AMBIGUOUS_WORKTREE,
        }:
            session.unavailable_lifecycle_status = session.status

    @staticmethod
    def _replace_git_state(
        session: EngineeringSession,
        state: GitState,
    ) -> None:
        extras = session.git_state.model_extra or {}
        if not extras:
            session.git_state = state
            return
        session.git_state = GitState.model_validate(
            {
                **state.model_dump(mode="python"),
                **extras,
            }
        )

    def _publish_checkpoint_index(
        self,
        session: EngineeringSession,
        live_index: Path | None,
        live_index_snapshot: bytes | None,
        temporary_index: Path | None,
        live_index_mode: int | None,
        expected_branch_commit: str,
    ) -> bool:
        if (
            live_index is None
            or temporary_index is None
        ):
            return False
        branch_ref = f"refs/heads/{session.branch}"
        branch_ref_path = Path(
            git(
                self.repo_path,
                "rev-parse",
                "--path-format=absolute",
                "--git-path",
                branch_ref,
            ).stdout.rstrip("\n")
        )
        branch_lock_path = branch_ref_path.with_name(
            f"{branch_ref_path.name}.lock"
        )
        branch_lock_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            branch_lock_fd = os.open(
                branch_lock_path,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                0o600,
            )
        except FileExistsError:
            return False
        owns_branch_lock = True
        lock_path = live_index.with_name(f"{live_index.name}.lock")
        lock_fd = -1
        owns_lock_path = False
        try:
            os.close(branch_lock_fd)
            branch_lock_fd = -1
            if current_branch(session.worktree_path) != session.branch:
                return False
            if not self._ref_matches(
                branch_ref,
                expected_branch_commit,
            ):
                return False
            try:
                lock_fd = os.open(
                    lock_path,
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                    0o600,
                )
            except FileExistsError:
                return False
            owns_lock_path = True
            if current_branch(session.worktree_path) != session.branch:
                return False
            if not self._ref_matches(
                branch_ref,
                expected_branch_commit,
            ):
                return False
            current_snapshot = (
                live_index.read_bytes()
                if live_index.exists()
                else None
            )
            if current_snapshot != live_index_snapshot:
                return False
            publish_mode = live_index_mode
            if publish_mode is None and live_index.exists():
                publish_mode = stat.S_IMODE(live_index.stat().st_mode)
            if publish_mode is not None and os.name != "nt":
                os.fchmod(lock_fd, publish_mode)
            with os.fdopen(lock_fd, "wb") as lock_file:
                lock_fd = -1
                lock_file.write(temporary_index.read_bytes())
                lock_file.flush()
                os.fsync(lock_file.fileno())
            os.replace(lock_path, live_index)
            owns_lock_path = False
            EngineeringSessionService._fsync_directory(live_index.parent)
            try:
                temporary_index.unlink(missing_ok=True)
            except OSError as cleanup_exc:
                warning = (
                    "checkpoint temporary index cleanup failed after "
                    f"durable publish: {cleanup_exc}"
                )
                if warning not in self.registry.last_read_errors:
                    self.registry.last_read_errors.append(warning)
            return True
        finally:
            if branch_lock_fd >= 0:
                os.close(branch_lock_fd)
            if lock_fd >= 0:
                os.close(lock_fd)
            if owns_lock_path:
                EngineeringSessionService._cleanup_path(
                    lock_path,
                    "checkpoint index lock cleanup failed",
                )
            if owns_branch_lock:
                EngineeringSessionService._cleanup_path(
                    branch_lock_path,
                    "checkpoint branch lock cleanup failed",
                )

    @staticmethod
    def _cleanup_path(path: Path, context: str) -> None:
        primary_exc = sys.exc_info()[1]
        try:
            path.unlink(missing_ok=True)
        except Exception as cleanup_exc:
            if primary_exc is None:
                raise
            EngineeringSessionService._attach_exception_note(
                primary_exc,
                context,
                cleanup_exc,
            )

    @staticmethod
    def _index_mode(session: EngineeringSession) -> int | None:
        if session.worktree_path is None or os.name == "nt":
            return None
        try:
            index_path = Path(
                git(
                    session.worktree_path,
                    "rev-parse",
                    "--path-format=absolute",
                    "--git-path",
                    "index",
                ).stdout.rstrip("\n")
            )
            return stat.S_IMODE(index_path.stat().st_mode)
        except (GitCommandError, OSError):
            return None

    @staticmethod
    def _restore_file_mode(
        path: Path,
        mode: int,
        context: str,
    ) -> None:
        primary_exc = sys.exc_info()[1]
        try:
            path.chmod(mode)
        except Exception as mode_exc:
            if primary_exc is None:
                raise
            EngineeringSessionService._attach_exception_note(
                primary_exc,
                context,
                mode_exc,
            )

    @staticmethod
    def _fsync_directory(path: Path) -> None:
        try:
            directory_fd = os.open(path, os.O_RDONLY)
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
