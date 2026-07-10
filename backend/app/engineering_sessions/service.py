from __future__ import annotations

from pathlib import Path

from app.engineering_sessions.git_state import (
    GitCommandError,
    GitWorktreeEntry,
    current_branch,
    fetch_origin,
    git,
    git_operation_in_progress,
    has_ref,
    inspect_git_state,
    list_git_worktrees,
)
from app.engineering_sessions.models import (
    EngineeringSession,
    SessionStatus,
    SessionType,
    utc_now,
)
from app.engineering_sessions.paths import default_worktree_parent
from app.engineering_sessions.registry import SessionRegistry

_COMMIT_IDENTITY = [
    "-c",
    "user.name=ai-builder",
    "-c",
    "user.email=ai-builder@local",
]


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
        top_level = git(
            resolved_repo_path,
            "rev-parse",
            "--path-format=absolute",
            "--show-toplevel",
        ).stdout.rstrip("\n")
        self.repo_path = Path(top_level).resolve()
        self.worktree_parent = (
            Path(worktree_parent).resolve()
            if worktree_parent is not None
            else default_worktree_parent(self.repo_path)
        )
        self.registry = SessionRegistry(self.repo_path, root=registry_root)

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
        base = base_branch or current_branch(self.repo_path)
        base_ref = f"refs/heads/{base}"
        if not has_ref(self.repo_path, base_ref):
            raise ValueError(f"base branch does not exist: {base}")
        base_commit = git(self.repo_path, "rev-parse", base_ref).stdout.strip()
        with self.registry.transaction_lock():
            session = self.registry.create(
                session_type=normalized_type,
                title=title,
                base_branch=base,
                worktree_path=None,
                base_commit=base_commit,
                roles=roles,
            )
            if create_worktree:
                path = self.worktree_parent / session.branch.replace("/", "-")
                session.worktree_path = str(path)
                self._ensure_worktree(session)
            self._sync_session(session)
            return self.registry.save(session)

    def resume(self, session_id: str) -> EngineeringSession:
        with self.registry.transaction_lock():
            self._fetch_origin_or_raise()
            session = self.registry.load(session_id)
            self._sync_session(session)
            if (
                not session.git_state.missing_worktree
                and not session.git_state.branch_mismatch
            ):
                session.status = SessionStatus.RUNNING
                session.cleanup.suggested = False
            return self.registry.save(session)

    def sync(self, session_id: str) -> EngineeringSession:
        with self.registry.transaction_lock():
            self._fetch_origin_or_raise()
            return self._sync_and_save_locked(session_id)

    def sync_model(self, session: EngineeringSession) -> EngineeringSession:
        if self._violates_static_worktree_invariant(session):
            return self._mark_missing_worktree(session)

        if session.worktree_path is None:
            session.head_commit = session.base_commit
            session.last_sync_at = utc_now()
            return session

        previous_status = session.status
        dirty_uncheckpointed = session.git_state.dirty_uncheckpointed
        state = inspect_git_state(
            session.worktree_path,
            base_branch=session.base_branch,
            expected_branch=session.branch,
            session_base_commit=session.base_commit,
            expected_repo_path=self.repo_path,
        )
        state.dirty_uncheckpointed = dirty_uncheckpointed and (
            state.missing_worktree or state.branch_mismatch or not state.clean
        )
        session.git_state = state
        session.head_commit = state.head_commit
        session.last_sync_at = utc_now()
        if state.missing_worktree:
            session.status = SessionStatus.MISSING_WORKTREE
            session.cleanup.suggested = False
        elif state.branch_mismatch:
            if previous_status == SessionStatus.MERGED_RETAINED:
                session.status = SessionStatus.RUNNING
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
        ):
            session.status = SessionStatus.RUNNING
            session.cleanup.suggested = False
        elif previous_status == SessionStatus.ARCHIVED_DIRTY:
            session.cleanup.suggested = False
        return session

    def checkpoint(self, session_id: str, message: str | None = None) -> bool:
        with self.registry.transaction_lock():
            self._fetch_origin_or_raise()
            session = self._sync_and_save_locked(session_id)
            created, _ = self._checkpoint_locked(session, message)
            return created

    def archive(self, session_id: str, *, checkpoint: bool = True) -> EngineeringSession:
        with self.registry.transaction_lock():
            self._fetch_origin_or_raise()
            session = self._sync_and_save_locked(session_id)
            if session.git_state.missing_worktree:
                return session

            if checkpoint and not session.git_state.clean:
                _, session = self._checkpoint_locked(session)
                if session.git_state.missing_worktree:
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
                    if self._violates_static_worktree_invariant(session):
                        self._mark_missing_worktree(
                            session,
                            update_last_sync=False,
                        )
                        self.registry.save(session)
                return sessions
        with self.registry.transaction_lock():
            self._fetch_origin_or_raise()
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
        with self.registry.transaction_lock():
            self._fetch_origin_or_raise()
            worktrees = self._active_worktrees()
            paths_by_branch = self._worktree_paths_by_branch(worktrees)
            base_branch = current_branch(self.repo_path)
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
                    branch is None
                    or not branch.startswith("session/")
                    or branch in known_branches
                ):
                    continue

                session = self.registry.create(
                    session_type=SessionType.FEATURE,
                    title=branch.removeprefix("session/"),
                    base_branch=base_branch,
                    worktree_path=path,
                    base_commit=None,
                    roles=["engineering-manager"],
                )
                session.branch = branch
                session.status = SessionStatus.ORPHAN_SESSION
                self._sync_session(session, paths_by_branch=paths_by_branch)
                self.registry.save(session)
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
    ) -> tuple[bool, EngineeringSession]:
        if (
            session.worktree_path is None
            or session.git_state.missing_worktree
            or session.git_state.branch_mismatch
            or git_operation_in_progress(session.worktree_path)
            or session.git_state.clean
        ):
            return False, session

        git(session.worktree_path, *_COMMIT_IDENTITY, "add", "-A")
        commit_message = message or f"checkpoint: {session.id} {session.title}"
        result = git(
            session.worktree_path,
            *_COMMIT_IDENTITY,
            "commit",
            "--no-verify",
            "-m",
            commit_message,
            check=False,
        )
        session = self._refresh_and_save_locked(session)
        return result.returncode == 0, session

    def _sync_session(
        self,
        session: EngineeringSession,
        *,
        paths_by_branch: dict[str, str] | None = None,
    ) -> EngineeringSession:
        if paths_by_branch is None:
            paths_by_branch = self._worktree_paths_by_branch(self._active_worktrees())
        actual_path = paths_by_branch.get(session.branch)
        if actual_path is not None:
            session.worktree_path = actual_path
        return self.sync_model(session)

    def _refresh_and_save_locked(
        self,
        session: EngineeringSession,
    ) -> EngineeringSession:
        self._sync_session(session)
        return self.registry.save(session)

    @staticmethod
    def _mark_missing_worktree(
        session: EngineeringSession,
        *,
        update_last_sync: bool = True,
    ) -> EngineeringSession:
        dirty_uncheckpointed = session.git_state.dirty_uncheckpointed
        session.git_state = inspect_git_state(
            None,
            base_branch=session.base_branch,
        )
        session.git_state.dirty_uncheckpointed = dirty_uncheckpointed
        session.head_commit = None
        if update_last_sync:
            session.last_sync_at = utc_now()
        session.status = SessionStatus.MISSING_WORKTREE
        session.cleanup.suggested = False
        return session

    def _violates_static_worktree_invariant(
        self,
        session: EngineeringSession,
    ) -> bool:
        if session.worktree_path is None:
            return self.requires_worktree(session.type)
        return Path(session.worktree_path).resolve() == self.repo_path

    def _active_worktrees(self) -> dict[str, GitWorktreeEntry]:
        control_repo_path = self.repo_path.resolve()
        return {
            path: item
            for path, item in list_git_worktrees(self.repo_path).items()
            if not item["prunable"] and Path(path).resolve() != control_repo_path
        }

    @staticmethod
    def _worktree_paths_by_branch(
        worktrees: dict[str, GitWorktreeEntry],
    ) -> dict[str, str]:
        return {
            item["branch"]: str(Path(path).resolve())
            for path, item in worktrees.items()
            if item["branch"] is not None
        }

    def _fetch_origin_or_raise(self) -> None:
        remotes = git(self.repo_path, "remote").stdout.split()
        if "origin" not in remotes:
            return
        if not fetch_origin(self.repo_path):
            raise GitCommandError(f"failed to fetch origin for repository: {self.repo_path}")

    def _ensure_worktree(self, session: EngineeringSession) -> None:
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
            state = inspect_git_state(
                path,
                base_branch=session.base_branch,
                expected_branch=session.branch,
                session_base_commit=session.base_commit,
                expected_repo_path=self.repo_path,
            )
            if state.missing_worktree or state.branch_mismatch:
                raise ValueError(f"invalid existing worktree: {path}")
            return

        branch_ref = f"refs/heads/{session.branch}"
        if has_ref(self.repo_path, branch_ref):
            git(self.repo_path, "worktree", "add", str(path), session.branch)
            return

        start_point = session.base_commit
        if start_point is None:
            base_ref = f"refs/heads/{session.base_branch}"
            if not has_ref(self.repo_path, base_ref):
                raise ValueError(f"base branch does not exist: {session.base_branch}")
            start_point = base_ref
        git(
            self.repo_path,
            "worktree",
            "add",
            "-b",
            session.branch,
            str(path),
            start_point,
        )
