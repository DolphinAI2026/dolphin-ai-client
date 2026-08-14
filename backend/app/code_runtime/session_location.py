"""Compatibility helpers for Code sessions created before application locations."""

from __future__ import annotations

import hashlib
from typing import Any, TypedDict

from app.code_runtime.application_locations import CodeExecutionLocation


_LOCAL_APPLICATION_PREFIX = "local-"


class SessionLocationValues(TypedDict):
    execution_location: CodeExecutionLocation
    logical_application_id: str


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
