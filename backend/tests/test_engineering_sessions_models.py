from datetime import timezone
from typing import get_type_hints

from app.engineering_sessions.models import (
    EngineeringSession,
    SessionStatus,
    SessionStatusValue,
    SessionType,
    SessionTypeValue,
    build_session_branch,
    slugify_title,
)


def test_slugify_title_keeps_ascii_and_compacts_separators():
    assert slugify_title("Fix Code 空白页 / Internal Server Error!") == "fix-code-internal-server-error"


def test_build_session_branch_includes_session_type_and_short_title():
    assert (
        build_session_branch("S-002", SessionType.FEATURE, "aPaaS 账号绑定")
        == "session/S-002-feature-apaas"
    )


def test_engineering_session_defaults_are_serializable():
    session = EngineeringSession(
        id="S-001",
        type=SessionType.BUGFIX,
        title="Code blank page",
        repo="apaas-builder-ai",
        repo_path="/repo",
        base_branch="main",
        branch="session/S-001-bugfix-code-blank-page",
        worktree_path="/worktrees/S-001-bugfix-code-blank-page",
    )

    data = session.model_dump(mode="json")

    assert data["status"] == SessionStatus.RUNNING.value
    assert data["git_state"]["clean"] is True
    assert data["verification"]["last_status"] == "pending"
    assert data["cleanup"]["auto_delete"] is False
    assert session.created_at.tzinfo == timezone.utc


def test_engineering_session_enum_defaults_dump_as_plain_strings():
    session = EngineeringSession(
        id="S-003",
        type=SessionType.DOC_CHANGE,
        title="README runbook",
        repo="apaas-builder-ai",
        repo_path="/repo",
        branch="session/S-003-doc-change-readme-runbook",
    )

    data = session.model_dump(mode="python")

    assert session.type == "doc-change"
    assert session.status == "running"
    assert data["type"] == "doc-change"
    assert data["status"] == "running"

    session.status = SessionStatus.VERIFYING
    assigned = session.model_dump(mode="python")

    assert session.status == "verifying"
    assert assigned["status"] == "verifying"


def test_engineering_session_annotations_match_string_runtime_contract():
    hints = get_type_hints(EngineeringSession)

    assert hints["type"] == SessionTypeValue
    assert hints["status"] == SessionStatusValue

    session = EngineeringSession(
        id="S-004",
        type=SessionType.FEATURE,
        title="Runtime strings",
        repo="apaas-builder-ai",
        repo_path="/repo",
        branch="session/S-004-feature-runtime-strings",
    )

    assert type(session.type) is str
    assert type(session.status) is str

    session.type = SessionType.BUGFIX
    session.status = SessionStatus.WAITING_MERGE

    assert type(session.type) is str
    assert type(session.status) is str
    assert session.type == "bugfix"
    assert session.status == "waiting_merge"
