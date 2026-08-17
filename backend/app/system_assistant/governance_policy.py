"""Small B0 policy boundary for diagnostic shadow decisions."""
from __future__ import annotations


def shadow_policy_status(policy: str) -> str:
    normalized = str(policy).strip().lower()
    if normalized == "legacy":
        return "not_needed"
    if normalized == "shadow":
        return "active"
    return "invalid"


def projection_failure_reason(projection: object) -> str | None:
    if str(getattr(projection, "status", "unavailable")) != "ready":
        return "PROJECTION_UNAVAILABLE"
    return None
