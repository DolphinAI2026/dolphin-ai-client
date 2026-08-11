"""Composition boundary for B0 shadow decisions; it never issues a ticket."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Mapping

from app.system_assistant.access_adapter import ShadowAccessComparison, evaluate_shadow_access
from app.system_assistant.capability_snapshot import (
    CapabilitySnapshot,
    SnapshotValidationError,
    validate_snapshot_context,
)
from app.system_assistant.governance_policy import projection_failure_reason, shadow_policy_status
from app.system_assistant.object_references import ObjectReferenceError, resolve_object_ref


@dataclass(frozen=True)
class ShadowDecision:
    status: str
    reason_code: str | None
    snapshot_digest: str
    ticket_issued: bool = False
    access_compare: ShadowAccessComparison | None = None


def _projection_item(projection: Any, capability_id: str) -> Mapping[str, Any] | None:
    for item in getattr(projection, "items", []) or []:
        if isinstance(item, Mapping) and item.get("capability_id") == capability_id:
            return item
    return None


def evaluate_shadow_decision(
    *,
    policy: str,
    snapshot: CapabilitySnapshot,
    raw_object_ref: Any,
    auth_context: Mapping[str, Any],
    action: str,
    capability_id: str,
    projection: Any,
    governance_view: Any,
    runtime_binding: Mapping[str, Any] | None,
    legacy_decision: str,
    minimum_policy_revision: int = 1,
    now: datetime | None = None,
) -> ShadowDecision:
    """Build the shadow verdict from TASK-003 projection/view inputs only."""
    policy_status = shadow_policy_status(policy)
    if policy_status == "not_needed":
        return ShadowDecision("not_needed", "POLICY_LEGACY", snapshot.snapshot_digest)
    if policy_status != "active" or governance_view is None:
        return ShadowDecision("not_enforceable", "POLICY_UNAVAILABLE", snapshot.snapshot_digest)
    projection_reason = projection_failure_reason(projection)
    if projection_reason:
        return ShadowDecision("not_enforceable", projection_reason, snapshot.snapshot_digest)
    if (
        not isinstance(minimum_policy_revision, int)
        or isinstance(minimum_policy_revision, bool)
        or minimum_policy_revision <= 0
        or snapshot.policy_revision < minimum_policy_revision
    ):
        return ShadowDecision("deny", "POLICY_REVISION_STALE", snapshot.snapshot_digest)
    required_subject_fields = {
        "tenant_id", "control_plane_tenant_id", "user_id", "session_id", "assistant_profile"
    }
    if not required_subject_fields.issubset(auth_context):
        return ShadowDecision("deny", "SNAPSHOT_SUBJECT_DRIFT", snapshot.snapshot_digest)
    try:
        validate_snapshot_context(
            snapshot,
            tenant_id=int(auth_context.get("tenant_id", 0)),
            control_plane_tenant_id=auth_context.get("control_plane_tenant_id"),
            user_id=int(auth_context["user_id"]),
            session_id=auth_context["session_id"],
            assistant_profile=str(auth_context["assistant_profile"]),
            now=now or datetime.now(UTC),
        )
        resolved = resolve_object_ref(raw_object_ref, auth_context)
    except SnapshotValidationError as error:
        return ShadowDecision("deny", str(error), snapshot.snapshot_digest)
    except ObjectReferenceError as error:
        return ShadowDecision("deny", error.code, snapshot.snapshot_digest)
    if resolved.canonical_ref not in snapshot.object_refs:
        return ShadowDecision("deny", "SNAPSHOT_OBJECT_REF_MISSING", snapshot.snapshot_digest)
    item = _projection_item(projection, capability_id)
    if item is None or capability_id not in snapshot.allowed_capability_ids:
        return ShadowDecision("deny", "CAPABILITY_NOT_ALLOWED", snapshot.snapshot_digest)
    if snapshot.projection_digest != getattr(projection, "projection_digest", None):
        return ShadowDecision("deny", "SNAPSHOT_PROJECTION_DRIFT", snapshot.snapshot_digest)
    if item.get("object_type") != resolved.object_type or item.get("action") != action:
        return ShadowDecision("deny", "CAPABILITY_CONTRACT_MISMATCH", snapshot.snapshot_digest)
    if snapshot.tool_contract_revisions.get(item.get("tool_name")) != item.get("tool_contract_revision"):
        return ShadowDecision("deny", "SNAPSHOT_CONTRACT_REVISION_DRIFT", snapshot.snapshot_digest)
    compared = evaluate_shadow_access(
        snapshot=snapshot,
        object_ref=resolved,
        action=action,
        runtime_binding=runtime_binding,
        legacy_decision=legacy_decision,
    )
    if not compared.decision.allowed:
        return ShadowDecision("deny", compared.decision.reason_code, snapshot.snapshot_digest, access_compare=compared)
    if item.get("risk_level") in {"L1", "L2"}:
        return ShadowDecision("not_enforceable", "RISK_NOT_ENFORCEABLE", snapshot.snapshot_digest, access_compare=compared)
    return ShadowDecision("allow", None, snapshot.snapshot_digest, access_compare=compared)
