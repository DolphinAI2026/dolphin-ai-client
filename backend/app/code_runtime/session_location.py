"""Compatibility helpers for Code sessions created before application locations."""

from __future__ import annotations

import hashlib
from typing import Any, Literal, TypedDict

from app.code_runtime.application_locations import CodeExecutionLocation


_LOCAL_APPLICATION_PREFIX = "local-"

CodeSessionPolicy = Literal["resume_recent", "create_new"]
CodeSessionPurpose = Literal["standard", "project_initialization", "project_recheck"]


class SessionLocationValues(TypedDict):
    execution_location: CodeExecutionLocation
    logical_application_id: str


class CodeApplicationLocationRequestError(ValueError):
    """A stable client error for an invalid Code application location request."""

    code = "CODE_APPLICATION_LOCATION_REQUIRED"


class CodeSessionLocationRequest(TypedDict):
    logical_application_id: str
    execution_location: CodeExecutionLocation
    session_policy: CodeSessionPolicy
    session_purpose: CodeSessionPurpose


def _text(value: object) -> str:
    return str(value or "").strip()


def _legacy_logical_application_id(external_application_id: str) -> str:
    prefix = "legacy:"
    if len(prefix) + len(external_application_id) <= 160:
        return f"{prefix}{external_application_id}"
    digest = hashlib.sha256(external_application_id.encode("utf-8")).hexdigest()
    return f"legacy-hash:{digest}"


def _derived_execution_location(external_application_id: str) -> CodeExecutionLocation:
    if external_application_id.startswith(_LOCAL_APPLICATION_PREFIX):
        return "local"
    return "remote"


def normalize_code_session_location_request(
    *,
    logical_application_id: object | None,
    external_application_id: object,
    execution_location: object | None,
    session_policy: object | None,
    session_purpose: object | None,
) -> CodeSessionLocationRequest:
    """Normalize the explicit location contract while retaining one legacy default path."""

    external_id = _text(external_application_id)
    logical_id = _text(logical_application_id)
    if logical_application_id is not None and not logical_id:
        raise CodeApplicationLocationRequestError("logical_application_id 不能为空")
    if not logical_id:
        logical_id = _legacy_logical_application_id(external_id)
    if len(logical_id) > 160:
        raise CodeApplicationLocationRequestError("logical_application_id 不能超过 160 个字符")

    raw_location = _text(execution_location).lower()
    if execution_location is None:
        location = _derived_execution_location(external_id)
    elif raw_location in {"local", "remote"}:
        location: CodeExecutionLocation = raw_location
    else:
        raise CodeApplicationLocationRequestError("execution_location 只能是 local 或 remote")

    raw_policy = _text(session_policy)
    if session_policy is None:
        policy: CodeSessionPolicy = "resume_recent"
    elif raw_policy in {"resume_recent", "create_new"}:
        policy = raw_policy  # type: ignore[assignment]
    else:
        raise CodeApplicationLocationRequestError(
            "session_policy 只能是 resume_recent 或 create_new"
        )

    raw_purpose = _text(session_purpose)
    if session_purpose is None:
        purpose: CodeSessionPurpose = "standard"
    elif raw_purpose in {"standard", "project_initialization", "project_recheck"}:
        purpose = raw_purpose  # type: ignore[assignment]
    else:
        raise CodeApplicationLocationRequestError(
            "session_purpose 只能是 standard、project_initialization 或 project_recheck"
        )

    return {
        "logical_application_id": logical_id,
        "execution_location": location,
        "session_policy": policy,
        "session_purpose": purpose,
    }


def derive_session_location(session: Any) -> SessionLocationValues | None:
    """Read legacy session fields and derive the location contract without writing."""

    external_application_id = _text(getattr(session, "external_application_id", None))
    if not external_application_id:
        return None
    stored_location = _text(getattr(session, "execution_location", None)).lower()
    if stored_location == "local":
        execution_location: CodeExecutionLocation = "local"
    elif stored_location == "remote":
        execution_location = "remote"
    else:
        execution_location = _derived_execution_location(external_application_id)
    return {
        "execution_location": execution_location,
        "logical_application_id": (
            _text(getattr(session, "logical_application_id", None))
            or _legacy_logical_application_id(external_application_id)
        ),
    }


def backfill_session_location(session: Any) -> SessionLocationValues | None:
    """Fill missing location fields when the caller is already writing a session."""

    derived = derive_session_location(session)
    if derived is None:
        return None
    if not _text(getattr(session, "execution_location", None)):
        session.execution_location = derived["execution_location"]
    if not _text(getattr(session, "logical_application_id", None)):
        session.logical_application_id = derived["logical_application_id"]
    return derived
