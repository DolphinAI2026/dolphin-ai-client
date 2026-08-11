from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone

import pytest

from app.system_assistant.capability_snapshot import (
    SnapshotValidationError,
    build_capability_snapshot,
    validate_snapshot_context,
)


def _snapshot(**overrides):
    issued_at = overrides.pop("issued_at", datetime(2026, 8, 11, 8, 0, tzinfo=timezone(timedelta(hours=8))))
    expires_at = overrides.pop("expires_at", issued_at.astimezone(UTC) + timedelta(minutes=15))
    values = {
        "tenant_id": 7,
        "control_plane_tenant_id": "cp-tenant-7",
        "user_id": 11,
        "session_id": 19,
        "assistant_profile": "system_assistant",
        "object_refs": {"workspace:ws-b", "workspace:ws-a", "workspace:ws-a"},
        "object_revisions": {"workspace:ws-a": "rev-1", "workspace:ws-b": "rev-2"},
        "access_roles": {"workspace:edit", "tenant_admin", "workspace:edit"},
        "allowed_capability_ids": {"cap-b", "cap-a", "cap-a"},
        "tool_contract_revisions": {"tool-b": 2, "tool-a": 1},
        "projection_digest": "projection-digest",
        "policy_revision": 3,
        "issued_at": issued_at,
        "expires_at": expires_at,
    }
    values.update(overrides)
    return build_capability_snapshot(**values)


def test_snapshot_uses_canonical_utc_json_and_stable_digest():
    first = _snapshot()
    second = _snapshot(
        object_refs=["workspace:ws-a", "workspace:ws-b", "workspace:ws-a"],
        access_roles=["tenant_admin", "workspace:edit"],
        allowed_capability_ids=["cap-a", "cap-b"],
        tool_contract_revisions={"tool-a": 1, "tool-b": 2},
    )

    assert first.snapshot_digest == second.snapshot_digest
    assert first.canonical_json == second.canonical_json
    assert first.to_dict()["issued_at"] == "2026-08-11T00:00:00Z"
    assert first.to_dict()["object_refs"] == ["workspace:ws-a", "workspace:ws-b"]
    assert first.to_dict()["access_roles"] == ["tenant_admin", "workspace:edit"]
    assert first.to_dict()["allowed_capability_ids"] == ["cap-a", "cap-b"]


def test_snapshot_writes_missing_optional_values_as_null():
    snapshot = _snapshot(control_plane_tenant_id=None, session_id=None)

    assert snapshot.to_dict()["control_plane_tenant_id"] is None
    assert snapshot.to_dict()["session_id"] is None
    assert '"control_plane_tenant_id":null' in snapshot.canonical_json


def test_snapshot_rejects_expiry_longer_than_one_agent_run_limit():
    issued_at = datetime(2026, 8, 11, 0, 0, tzinfo=UTC)

    with pytest.raises(SnapshotValidationError, match="SNAPSHOT_TTL_EXCEEDED"):
        _snapshot(issued_at=issued_at, expires_at=issued_at + timedelta(minutes=15, seconds=1))


def test_snapshot_context_rejects_subject_drift_and_expiry():
    snapshot = _snapshot()

    with pytest.raises(SnapshotValidationError, match="SNAPSHOT_SUBJECT_DRIFT"):
        validate_snapshot_context(
            snapshot,
            tenant_id=7,
            control_plane_tenant_id="cp-tenant-7",
            user_id=12,
            session_id=19,
            assistant_profile="system_assistant",
            now=datetime(2026, 8, 11, 0, 1, tzinfo=UTC),
        )
    with pytest.raises(SnapshotValidationError, match="SNAPSHOT_EXPIRED"):
        validate_snapshot_context(
            snapshot,
            tenant_id=7,
            control_plane_tenant_id="cp-tenant-7",
            user_id=11,
            session_id=19,
            assistant_profile="system_assistant",
            now=datetime(2026, 8, 11, 0, 16, tzinfo=UTC),
        )


def test_snapshot_captures_object_revisions_and_freezes_contract_revisions():
    contract_revisions = {"tool-a": 1, "tool-b": 2}
    snapshot = _snapshot(tool_contract_revisions=contract_revisions)
    digest = snapshot.snapshot_digest

    assert snapshot.object_revisions == {"workspace:ws-a": "rev-1", "workspace:ws-b": "rev-2"}
    contract_revisions["tool-a"] = 99
    assert snapshot.tool_contract_revisions["tool-a"] == 1
    with pytest.raises(TypeError):
        snapshot.tool_contract_revisions["tool-a"] = 99
    assert snapshot.snapshot_digest == digest


def test_snapshot_treats_expiry_boundary_as_expired():
    snapshot = _snapshot()

    with pytest.raises(SnapshotValidationError, match="SNAPSHOT_EXPIRED"):
        validate_snapshot_context(
            snapshot,
            tenant_id=7,
            control_plane_tenant_id="cp-tenant-7",
            user_id=11,
            session_id=19,
            assistant_profile="system_assistant",
            now=snapshot.expires_at,
        )
