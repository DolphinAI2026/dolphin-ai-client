from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.system_assistant.access_adapter import evaluate_access, evaluate_shadow_access
from app.system_assistant.capability_snapshot import build_capability_snapshot
from app.system_assistant.governance_dispatcher import evaluate_shadow_decision
from app.system_assistant.object_references import resolve_object_ref


def _snapshot(*, user_id=11, access_roles=(), projection_digest="projection-digest"):
    issued_at = datetime(2026, 8, 11, tzinfo=UTC)
    return build_capability_snapshot(
        tenant_id=7,
        control_plane_tenant_id="cp-tenant-7",
        user_id=user_id,
        session_id=19,
        assistant_profile="system_assistant",
        object_refs=["workspace:ws-a"],
        object_revisions={"workspace:ws-a": "rev-1"},
        access_roles=access_roles,
        allowed_capability_ids=["cap-read", "cap-write"],
        tool_contract_revisions={"read_tool": 1, "write_tool": 1},
        projection_digest=projection_digest,
        policy_revision=3,
        issued_at=issued_at,
        expires_at=issued_at + timedelta(minutes=15),
    )


def _context(*, owner_ref="user:11", project_source_status="ready", revision="rev-1"):
    return {
        "tenant_id": 7,
        "control_plane_tenant_id": "cp-tenant-7",
        "user_id": 11,
        "session_id": 19,
        "assistant_profile": "system_assistant",
        "object_catalog": {
            "workspace:ws-a": {
                "object_type": "workspace",
                "tenant_id": 7,
                "control_plane_tenant_id": "cp-tenant-7",
                "stable_id": "ws-a",
                "revision": revision,
                "owner_ref": owner_ref,
                "environment_ref": "runtime:dev",
                "metadata": {"project_source_status": project_source_status},
            }
        },
    }


def _resolved(**kwargs):
    return resolve_object_ref("workspace:ws-a", _context(**kwargs))


def test_legacy_allow_is_compare_only_and_never_authorizes_member_without_permission():
    compared = evaluate_shadow_access(
        snapshot=_snapshot(user_id=12),
        object_ref=_resolved(),
        action="write",
        runtime_binding={"status": "ready"},
        legacy_decision="allow",
    )

    assert compared.legacy_decision == "allow"
    assert compared.decision.decision == "deny"
    assert compared.decision.reason_code == "ACCESS_PERMISSION_REQUIRED"
    assert compared.result == "mismatch"


@pytest.mark.parametrize("action, expected", [("read", "allow"), ("write", "allow"), ("task", "allow_if_sandbox_ready"), ("preview", "allow_if_sandbox_ready")])
def test_creator_has_action_aware_access(action, expected):
    decision = evaluate_access(
        snapshot=_snapshot(), object_ref=_resolved(), action=action, runtime_binding={"status": "ready"}
    )

    assert decision.decision == expected
    assert decision.allowed is True


@pytest.mark.parametrize("roles", [("tenant_admin",), ("platform_admin",)])
def test_admin_has_action_aware_access(roles):
    decision = evaluate_access(
        snapshot=_snapshot(user_id=12, access_roles=roles),
        object_ref=_resolved(),
        action="write",
        runtime_binding={"status": "ready"},
    )

    assert decision.decision == "allow"
    assert decision.allowed is True


@pytest.mark.parametrize(
    "roles, action, expected",
    [
        (("workspace:view",), "read", "allow"),
        (("application:view",), "read", "allow"),
        (("workspace:edit",), "write", "allow"),
        (("application:edit",), "preview", "allow_if_sandbox_ready"),
        (("*",), "task", "allow_if_sandbox_ready"),
    ],
)
def test_explicit_permissions_are_the_member_authority(roles, action, expected):
    decision = evaluate_access(
        snapshot=_snapshot(user_id=12, access_roles=roles),
        object_ref=_resolved(),
        action=action,
        runtime_binding={"status": "ready"},
    )

    assert decision.decision == expected
    assert decision.allowed is True


@pytest.mark.parametrize(
    "binding, reason",
    [
        (None, "SANDBOX_NOT_BOUND"),
        ({"status": "stale"}, "SANDBOX_STALE"),
        ({"status": "unavailable"}, "SANDBOX_READINESS_UNAVAILABLE"),
    ],
)
def test_task_and_preview_require_ready_runtime_binding(binding, reason):
    decision = evaluate_access(
        snapshot=_snapshot(), object_ref=_resolved(), action="task", runtime_binding=binding
    )

    assert decision.decision == "deny"
    assert decision.reason_code == reason
    assert decision.allowed is False


def test_user_owned_workspace_owner_is_allowed_and_project_incomplete_is_read_only():
    owner = evaluate_access(
        snapshot=_snapshot(user_id=22), object_ref=_resolved(owner_ref="user:22"), action="write"
    )
    read = evaluate_access(
        snapshot=_snapshot(user_id=12), object_ref=_resolved(project_source_status="incomplete"), action="read"
    )
    write = evaluate_access(
        snapshot=_snapshot(user_id=12), object_ref=_resolved(project_source_status="incomplete"), action="write"
    )

    assert owner.decision == "allow"
    assert read.decision == "allow"
    assert write.decision == "deny"
    assert write.reason_code == "ACCESS_SOURCE_INCOMPLETE"


@pytest.mark.parametrize("risk_level", ["L1", "L2"])
def test_dispatcher_rejects_revision_drift_and_l1_l2_as_not_enforceable(risk_level):
    projection = type(
        "Projection",
        (),
        {
            "status": "ready",
            "projection_digest": "projection-digest",
            "items": [
                {
                    "capability_id": "cap-write",
                    "tool_name": "write_tool",
                    "tool_contract_revision": 1,
                    "object_type": "workspace",
                    "action": "write",
                    "risk_level": risk_level,
                }
            ],
        },
    )()
    drift = evaluate_shadow_decision(
        policy="shadow",
        snapshot=_snapshot(),
        raw_object_ref="workspace:ws-a@rev-2",
        auth_context=_context(),
        action="write",
        capability_id="cap-write",
        projection=projection,
        governance_view=object(),
        runtime_binding={"status": "ready"},
        legacy_decision="allow",
        now=datetime(2026, 8, 11, 0, 1, tzinfo=UTC),
    )
    l1 = evaluate_shadow_decision(
        policy="shadow",
        snapshot=_snapshot(),
        raw_object_ref="workspace:ws-a",
        auth_context=_context(),
        action="write",
        capability_id="cap-write",
        projection=projection,
        governance_view=object(),
        runtime_binding={"status": "ready"},
        legacy_decision="allow",
        now=datetime(2026, 8, 11, 0, 1, tzinfo=UTC),
    )

    assert drift.status == "deny"
    assert drift.reason_code == "OBJECT_REVISION_CONFLICT"
    assert l1.status == "not_enforceable"
    assert l1.ticket_issued is False


def test_dispatcher_rejects_missing_subject_fields_and_stale_policy_revision():
    projection = type(
        "Projection",
        (),
        {
            "status": "ready",
            "projection_digest": "projection-digest",
            "items": [
                {
                    "capability_id": "cap-read",
                    "tool_name": "read_tool",
                    "tool_contract_revision": 1,
                    "object_type": "workspace",
                    "action": "read",
                    "risk_level": "L0",
                }
            ],
        },
    )()
    missing_subject = evaluate_shadow_decision(
        policy="shadow",
        snapshot=_snapshot(),
        raw_object_ref="workspace:ws-a",
        auth_context={key: value for key, value in _context().items() if key != "user_id"},
        action="read",
        capability_id="cap-read",
        projection=projection,
        governance_view=object(),
        runtime_binding=None,
        legacy_decision="allow",
        now=datetime(2026, 8, 11, 0, 1, tzinfo=UTC),
    )
    stale_policy = evaluate_shadow_decision(
        policy="shadow",
        snapshot=_snapshot(),
        raw_object_ref="workspace:ws-a",
        auth_context={**_context(), "user_id": 11, "session_id": 19, "assistant_profile": "system_assistant"},
        action="read",
        capability_id="cap-read",
        projection=projection,
        governance_view=object(),
        runtime_binding=None,
        legacy_decision="allow",
        minimum_policy_revision=4,
        now=datetime(2026, 8, 11, 0, 1, tzinfo=UTC),
    )

    assert missing_subject.status == "deny"
    assert missing_subject.reason_code == "SNAPSHOT_SUBJECT_DRIFT"
    assert stale_policy.status == "deny"
    assert stale_policy.reason_code == "POLICY_REVISION_STALE"


def test_dispatcher_rejects_catalog_revision_drift_without_raw_revision():
    projection = type(
        "Projection",
        (),
        {
            "status": "ready",
            "projection_digest": "projection-digest",
            "items": [
                {
                    "capability_id": "cap-read",
                    "tool_name": "read_tool",
                    "tool_contract_revision": 1,
                    "object_type": "workspace",
                    "action": "read",
                    "risk_level": "L0",
                }
            ],
        },
    )()
    decision = evaluate_shadow_decision(
        policy="shadow",
        snapshot=_snapshot(),
        raw_object_ref="workspace:ws-a",
        auth_context=_context(revision="rev-2"),
        action="read",
        capability_id="cap-read",
        projection=projection,
        governance_view=object(),
        runtime_binding=None,
        legacy_decision="allow",
        now=datetime(2026, 8, 11, 0, 1, tzinfo=UTC),
    )

    assert decision.status == "deny"
    assert decision.reason_code == "OBJECT_REVISION_CONFLICT"
