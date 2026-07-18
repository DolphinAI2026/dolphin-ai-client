"""Control Plane tenant identifiers mapped onto Builder tenant rows."""
from __future__ import annotations

from typing import Any


def mapped_control_plane_tenant_id(tenant: Any) -> str | None:
    tenant_code = str(getattr(tenant, "tenant_code", "") or "").strip()
    if tenant_code == "default":
        return "default"
    if tenant_code.startswith("workspace-"):
        value = tenant_code.removeprefix("workspace-").strip()
        return value or None
    return None


def is_unbound_control_plane_account(user: Any) -> bool:
    return (
        str(getattr(user, "account_source", "") or "").strip() == "control_plane"
        and not getattr(user, "apaas_user_id", None)
        and bool(str(getattr(user, "coding_tenant_id", "") or "").strip())
    )


def matches_current_control_plane_tenant(user: Any, tenant: Any) -> bool:
    current_tenant_id = str(getattr(user, "coding_tenant_id", "") or "").strip()
    return bool(current_tenant_id) and mapped_control_plane_tenant_id(tenant) == current_tenant_id
