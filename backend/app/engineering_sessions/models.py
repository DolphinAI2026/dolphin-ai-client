from __future__ import annotations

import re
from datetime import datetime, timezone
from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class SessionType(str, Enum):
    NEW_APP = "new-app"
    FEATURE = "feature"
    BUGFIX = "bugfix"
    DEPLOY = "deploy"
    REVIEW = "review"
    DOC_CHANGE = "doc-change"
    SPEC_CHANGE = "spec-change"


class SessionStatus(str, Enum):
    RUNNING = "running"
    VERIFYING = "verifying"
    WAITING_MERGE = "waiting_merge"
    MERGED_RETAINED = "merged_retained"
    ARCHIVED_DIRTY = "archived_dirty"
    BLOCKED_RETAINED = "blocked_retained"
    ABANDONED_RETAINED = "abandoned_retained"
    MISSING_WORKTREE = "missing_worktree"
    ORPHAN_SESSION = "orphan_session"


class GitState(BaseModel):
    clean: bool = True
    ahead: int = 0
    behind: int = 0
    merged_to_base: bool = False
    dirty_uncheckpointed: bool = False
    stale: bool = False
    very_stale: bool = False
    missing_worktree: bool = False
    branch_mismatch: bool = False
    retained: bool = False
    current_branch: str | None = None
    head_commit: str | None = None


class RuntimeProfile(BaseModel):
    backend_port: int | None = None
    frontend_port: int | None = None
    db_profile: str | None = None
    env_file: str | None = None
    log_path: str | None = None
    started_from_worktree: str | None = None


class VerificationState(BaseModel):
    last_status: Literal["pending", "passed", "failed", "skipped"] = "pending"
    last_commands: list[str] = Field(default_factory=list)


class CleanupState(BaseModel):
    suggested: bool = False
    auto_delete: bool = False


class EngineeringSession(BaseModel):
    model_config = ConfigDict(
        use_enum_values=True,
        validate_default=True,
        validate_assignment=True,
    )

    id: str
    type: SessionType
    title: str
    status: SessionStatus = SessionStatus.RUNNING
    repo: str
    repo_path: str
    base_branch: str = "main"
    branch: str
    worktree_path: str | None = None
    base_commit: str | None = None
    head_commit: str | None = None
    merged_commit: str | None = None
    git_state: GitState = Field(default_factory=GitState)
    runtime_profile: RuntimeProfile = Field(default_factory=RuntimeProfile)
    roles: list[str] = Field(default_factory=lambda: ["engineering-manager"])
    verification: VerificationState = Field(default_factory=VerificationState)
    cleanup: CleanupState = Field(default_factory=CleanupState)
    depends_on: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
    last_sync_at: datetime | None = None
    summary: str | None = None

    @field_validator("id")
    @classmethod
    def validate_id(cls, value: str) -> str:
        if not re.fullmatch(r"S-\d{3,}", value):
            raise ValueError("session id must use S-001 format")
        return value


def slugify_title(title: str, *, max_length: int = 48) -> str:
    ascii_title = title.encode("ascii", "ignore").decode("ascii").lower()
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_title).strip("-")
    slug = re.sub(r"-{2,}", "-", slug)
    if not slug:
        slug = "session"
    return slug[:max_length].rstrip("-")


def build_session_branch(session_id: str, session_type: SessionType | str, title: str) -> str:
    type_value = session_type.value if isinstance(session_type, SessionType) else str(session_type)
    return f"session/{session_id}-{type_value}-{slugify_title(title, max_length=40)}"
