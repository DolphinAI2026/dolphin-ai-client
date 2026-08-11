"""Canonical, run-scoped capability snapshots for B0 shadow diagnostics."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Mapping


MAX_SNAPSHOT_TTL = timedelta(minutes=15)


class SnapshotValidationError(ValueError):
    """A typed snapshot validation failure that is safe to expose to diagnostics."""


def _utc_z(value: datetime) -> str:
    if value.tzinfo is None:
        raise SnapshotValidationError("SNAPSHOT_TIME_INVALID")
    normalized = value.astimezone(UTC)
    timespec = "microseconds" if normalized.microsecond else "seconds"
    return normalized.isoformat(timespec=timespec).replace("+00:00", "Z")


def _sorted_unique(values: Any) -> list[str]:
    if values is None:
        return []
    if isinstance(values, (str, bytes)):
        raise SnapshotValidationError("SNAPSHOT_COLLECTION_INVALID")
    try:
        normalized = {str(value) for value in values}
    except TypeError as error:
        raise SnapshotValidationError("SNAPSHOT_COLLECTION_INVALID") from error
    if any(not value for value in normalized):
        raise SnapshotValidationError("SNAPSHOT_COLLECTION_INVALID")
    return sorted(normalized)


def _canonical_json(value: Mapping[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


@dataclass(frozen=True)
class CapabilitySnapshot:
    tenant_id: int
    control_plane_tenant_id: str | None
    user_id: int
    session_id: int | None
    assistant_profile: str
    object_refs: tuple[str, ...]
    access_roles: tuple[str, ...]
    allowed_capability_ids: tuple[str, ...]
    tool_contract_revisions: dict[str, int]
    projection_digest: str
    policy_revision: int
    issued_at: datetime
    expires_at: datetime
    canonical_json: str
    snapshot_digest: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "tenant_id": self.tenant_id,
            "control_plane_tenant_id": self.control_plane_tenant_id,
            "user_id": self.user_id,
            "session_id": self.session_id,
            "assistant_profile": self.assistant_profile,
            "object_refs": list(self.object_refs),
            "access_roles": list(self.access_roles),
            "allowed_capability_ids": list(self.allowed_capability_ids),
            "tool_contract_revisions": dict(self.tool_contract_revisions),
            "projection_digest": self.projection_digest,
            "policy_revision": self.policy_revision,
            "issued_at": _utc_z(self.issued_at),
            "expires_at": _utc_z(self.expires_at),
            "snapshot_digest": self.snapshot_digest,
        }


def build_capability_snapshot(
    *,
    tenant_id: int,
    control_plane_tenant_id: str | None,
    user_id: int,
    session_id: int | None,
    assistant_profile: str,
    object_refs: Any,
    access_roles: Any,
    allowed_capability_ids: Any,
    tool_contract_revisions: Mapping[str, Any],
    projection_digest: str,
    policy_revision: int,
    issued_at: datetime,
    expires_at: datetime,
) -> CapabilitySnapshot:
    """Build one canonical snapshot; it cannot span more than one 15-minute run."""
    if not isinstance(tenant_id, int) or isinstance(tenant_id, bool) or tenant_id <= 0:
        raise SnapshotValidationError("SNAPSHOT_TENANT_INVALID")
    if not isinstance(user_id, int) or isinstance(user_id, bool) or user_id <= 0:
        raise SnapshotValidationError("SNAPSHOT_USER_INVALID")
    if session_id is not None and (not isinstance(session_id, int) or isinstance(session_id, bool)):
        raise SnapshotValidationError("SNAPSHOT_SESSION_INVALID")
    if not isinstance(assistant_profile, str) or not assistant_profile.strip():
        raise SnapshotValidationError("SNAPSHOT_PROFILE_INVALID")
    if not isinstance(policy_revision, int) or isinstance(policy_revision, bool) or policy_revision <= 0:
        raise SnapshotValidationError("SNAPSHOT_POLICY_INVALID")
    if not isinstance(projection_digest, str) or not projection_digest:
        raise SnapshotValidationError("SNAPSHOT_PROJECTION_INVALID")
    if issued_at.tzinfo is None or expires_at.tzinfo is None:
        raise SnapshotValidationError("SNAPSHOT_TIME_INVALID")
    issued = issued_at.astimezone(UTC)
    expires = expires_at.astimezone(UTC)
    if expires <= issued:
        raise SnapshotValidationError("SNAPSHOT_TIME_INVALID")
    if expires - issued > MAX_SNAPSHOT_TTL:
        raise SnapshotValidationError("SNAPSHOT_TTL_EXCEEDED")
    if not isinstance(tool_contract_revisions, Mapping):
        raise SnapshotValidationError("SNAPSHOT_CONTRACT_REVISIONS_INVALID")
    revisions: dict[str, int] = {}
    for tool_name, revision in tool_contract_revisions.items():
        if (
            not isinstance(tool_name, str)
            or not tool_name
            or not isinstance(revision, int)
            or isinstance(revision, bool)
            or revision <= 0
        ):
            raise SnapshotValidationError("SNAPSHOT_CONTRACT_REVISIONS_INVALID")
        revisions[tool_name] = revision
    payload = {
        "tenant_id": tenant_id,
        "control_plane_tenant_id": control_plane_tenant_id,
        "user_id": user_id,
        "session_id": session_id,
        "assistant_profile": assistant_profile.strip(),
        "object_refs": _sorted_unique(object_refs),
        "access_roles": _sorted_unique(access_roles),
        "allowed_capability_ids": _sorted_unique(allowed_capability_ids),
        "tool_contract_revisions": dict(sorted(revisions.items())),
        "projection_digest": projection_digest,
        "policy_revision": policy_revision,
        "issued_at": _utc_z(issued),
        "expires_at": _utc_z(expires),
    }
    canonical_json = _canonical_json(payload)
    return CapabilitySnapshot(
        tenant_id=tenant_id,
        control_plane_tenant_id=control_plane_tenant_id,
        user_id=user_id,
        session_id=session_id,
        assistant_profile=payload["assistant_profile"],
        object_refs=tuple(payload["object_refs"]),
        access_roles=tuple(payload["access_roles"]),
        allowed_capability_ids=tuple(payload["allowed_capability_ids"]),
        tool_contract_revisions=payload["tool_contract_revisions"],
        projection_digest=projection_digest,
        policy_revision=policy_revision,
        issued_at=issued,
        expires_at=expires,
        canonical_json=canonical_json,
        snapshot_digest=hashlib.sha256(canonical_json.encode("utf-8")).hexdigest(),
    )


def validate_snapshot_context(
    snapshot: CapabilitySnapshot,
    *,
    tenant_id: int,
    control_plane_tenant_id: str | None,
    user_id: int,
    session_id: int | None,
    assistant_profile: str,
    now: datetime,
) -> None:
    """Reject a snapshot when it is replayed by a different shadow subject."""
    subject = (tenant_id, control_plane_tenant_id, user_id, session_id, assistant_profile)
    recorded = (
        snapshot.tenant_id,
        snapshot.control_plane_tenant_id,
        snapshot.user_id,
        snapshot.session_id,
        snapshot.assistant_profile,
    )
    if subject != recorded:
        raise SnapshotValidationError("SNAPSHOT_SUBJECT_DRIFT")
    if now.tzinfo is None:
        raise SnapshotValidationError("SNAPSHOT_TIME_INVALID")
    if now.astimezone(UTC) > snapshot.expires_at:
        raise SnapshotValidationError("SNAPSHOT_EXPIRED")
