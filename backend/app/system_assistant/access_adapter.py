"""Action-aware, diagnostic-only access checks for B0 shadow execution."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, Mapping

from app.system_assistant.capability_snapshot import CapabilitySnapshot
from app.system_assistant.object_references import ResolvedObjectRef
from app.system_assistant.telemetry import governance_telemetry


AccessOutcome = Literal["allow", "deny", "allow_if_sandbox_ready"]
_ACTIONS = frozenset({"read", "write", "task", "preview"})
_ADMIN_ROLES = frozenset({"tenant_admin", "platform_admin", "admin"})


@dataclass(frozen=True)
class AccessDecision:
    action: str
    decision: AccessOutcome
    reason_code: str | None = None

    @property
    def allowed(self) -> bool:
        return self.decision != "deny"


@dataclass(frozen=True)
class ShadowAccessComparison:
    legacy_decision: str
    decision: AccessDecision
    result: Literal["match", "mismatch"]


def _permissions(snapshot: CapabilitySnapshot) -> frozenset[str]:
    return frozenset(snapshot.access_roles)


def _has_base_access(snapshot: CapabilitySnapshot, object_ref: ResolvedObjectRef, action: str) -> bool:
    roles = _permissions(snapshot)
    if object_ref.owner_ref == f"user:{snapshot.user_id}" or roles & _ADMIN_ROLES or "*" in roles:
        return True
    if action == "read":
        return bool(roles & {"workspace:view", "application:view", "workspace:edit", "application:edit"})
    return bool(roles & {"workspace:edit", "application:edit"})


def _sandbox_decision(runtime_binding: Mapping[str, Any] | None, action: str) -> AccessDecision:
    if not runtime_binding or not runtime_binding.get("status"):
        return AccessDecision(action, "deny", "SANDBOX_NOT_BOUND")
    if runtime_binding.get("status") == "ready":
        return AccessDecision(action, "allow_if_sandbox_ready")
    if runtime_binding.get("status") == "stale":
        return AccessDecision(action, "deny", "SANDBOX_STALE")
    return AccessDecision(action, "deny", "SANDBOX_READINESS_UNAVAILABLE")


def evaluate_access(
    *,
    snapshot: CapabilitySnapshot,
    object_ref: ResolvedObjectRef,
    action: str,
    runtime_binding: Mapping[str, Any] | None = None,
) -> AccessDecision:
    """Evaluate only canonical snapshot roles and resolved authority metadata."""
    if action not in _ACTIONS:
        return AccessDecision(action, "deny", "ACCESS_ACTION_UNSUPPORTED")
    if object_ref.tenant_id != snapshot.tenant_id:
        return AccessDecision(action, "deny", "OBJECT_NOT_FOUND")
    if object_ref.metadata.get("project_source_status") in {"incomplete", "unavailable"}:
        if action == "read":
            return AccessDecision(action, "allow")
        return AccessDecision(action, "deny", "ACCESS_SOURCE_INCOMPLETE")
    if not _has_base_access(snapshot, object_ref, action):
        return AccessDecision(action, "deny", "ACCESS_PERMISSION_REQUIRED")
    if action in {"task", "preview"}:
        return _sandbox_decision(runtime_binding, action)
    return AccessDecision(action, "allow")


def evaluate_shadow_access(
    *,
    snapshot: CapabilitySnapshot,
    object_ref: ResolvedObjectRef,
    action: str,
    runtime_binding: Mapping[str, Any] | None,
    legacy_decision: str,
) -> ShadowAccessComparison:
    """Compare an explicitly supplied legacy result without consuming legacy authority."""
    decision = evaluate_access(
        snapshot=snapshot,
        object_ref=object_ref,
        action=action,
        runtime_binding=runtime_binding,
    )
    normalized_legacy = str(legacy_decision).strip().lower()
    result: Literal["match", "mismatch"] = (
        "match" if normalized_legacy == decision.decision else "mismatch"
    )
    governance_telemetry.record_access_compare(normalized_legacy, decision.decision, result)
    return ShadowAccessComparison(normalized_legacy, decision, result)
