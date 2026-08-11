"""Canonical local merge and bounded in-memory cache for capability projection."""
from __future__ import annotations

import hashlib
import json
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from threading import RLock
from typing import Any, Mapping

from app.config import settings

PROJECTION_TTL_SECONDS = 300.0
MAX_CACHE_ENTRIES = 256


@dataclass(frozen=True)
class ProjectionCacheEntry:
    items: list[dict[str, Any]]
    revision: str
    etag: str
    stored_at: float


@dataclass(frozen=True)
class CapabilityProjection:
    status: str
    items: list[dict[str, Any]] = field(default_factory=list)
    projection_digest: str | None = None
    control_plane_revision: str | None = None
    etag: str | None = None
    excluded: list[dict[str, str]] = field(default_factory=list)
    reason: str | None = None
    policy_revision: int | str | None = None
    stored_at: float | None = None
    registry_digest: str | None = None

    @property
    def capabilities(self) -> list[dict[str, Any]]:
        return self.items


class ProjectionCache:
    """Bounded cache containing only complete batches."""

    def __init__(self, *, ttl_seconds: float = PROJECTION_TTL_SECONDS, max_entries: int = MAX_CACHE_ENTRIES) -> None:
        self.ttl_seconds = float(ttl_seconds)
        self.max_entries = max(1, int(max_entries))
        self._items: OrderedDict[str, ProjectionCacheEntry | Any] = OrderedDict()
        self._lock = RLock()

    def get_entry(self, key: str) -> ProjectionCacheEntry | None:
        with self._lock:
            value = self._items.get(str(key))
            if value is None or not self._fresh(value):
                return None
            self._items.move_to_end(str(key))
            return value

    def get(self, key: str) -> Any | None:
        entry = self.get_entry(key)
        return entry

    def is_fresh(self, key: str) -> bool:
        with self._lock:
            value = self._items.get(str(key))
            return value is not None and self._fresh(value)

    def swap(self, key: str, value: Any) -> None:
        with self._lock:
            self._items[str(key)] = value
            self._items.move_to_end(str(key))
            while len(self._items) > self.max_entries:
                self._items.popitem(last=False)

    def invalidate(self, key: str | None = None) -> None:
        with self._lock:
            if key is None:
                self._items.clear()
            else:
                self._items.pop(str(key), None)

    def _fresh(self, value: Any) -> bool:
        stored_at = getattr(value, "stored_at", None)
        if stored_at is None:
            return True
        return isinstance(stored_at, (int, float)) and time.monotonic() - stored_at < self.ttl_seconds


projection_cache = ProjectionCache(ttl_seconds=settings.system_assistant_projection_cache_seconds)


def invalidate_projection_cache(key: str | None = None) -> None:
    projection_cache.invalidate(key)


def _value(item: Mapping[str, Any], *names: str, default: Any = None) -> Any:
    for name in names:
        if name in item:
            return item[name]
    return default


def _canonical_digest(items: list[dict[str, Any]]) -> str:
    payload = json.dumps(items, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _registry_digest(view: Any) -> str:
    registry = getattr(view, "registry", {}) or {}
    tools = registry.get("tools", {}) if isinstance(registry, Mapping) else {}
    payload = json.dumps(tools, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _local_contracts(view: Any) -> dict[str, dict[str, Any]]:
    """Read complete v2 contracts from one captured ``governance_view``."""
    contracts: dict[str, dict[str, Any]] = {}
    registry = getattr(view, "registry", {}) or {}
    tools = registry.get("tools", {}) if isinstance(registry, Mapping) else {}
    for tool_name, metadata in tools.items():
        if not isinstance(metadata, Mapping):
            continue
        code = metadata.get("capability_code")
        required = ("contract_revision", "object_type", "action", "risk_level", "workspace_action", "confirmation_policy")
        if not code or any(key not in metadata for key in required):
            continue
        if code in contracts:
            contracts[code] = {"_duplicate": True}
            continue
        contracts[code] = {"tool_name": tool_name, **{key: metadata[key] for key in required}}
    return contracts


def build_capability_projection(
    remote_items: list[Mapping[str, Any]],
    *,
    governance_view: Any,
    control_plane_revision: str,
    etag: str,
    policy_revision: int | str | None = None,
    registry_digest: str | None = None,
) -> CapabilityProjection:
    """Merge remote capabilities with one immutable local registry generation."""
    contracts = _local_contracts(governance_view)
    remote_by_code: dict[str, Mapping[str, Any]] = {}
    duplicate_codes: set[str] = set()
    seen_ids: set[str] = set()
    duplicate_ids: set[str] = set()
    for remote in remote_items:
        if not isinstance(remote, Mapping):
            continue
        code = _value(remote, "code", "capabilityCode", "capability_code")
        capability_id = _value(remote, "capabilityId", "capability_id")
        capability_id = str(capability_id or "")
        if not code or not capability_id or code in remote_by_code or capability_id in seen_ids:
            duplicate_codes.add(str(code or ""))
            if capability_id:
                duplicate_ids.add(str(capability_id))
        remote_by_code[str(code)] = remote
        seen_ids.add(capability_id)

    merged: list[dict[str, Any]] = []
    excluded: list[dict[str, str]] = []
    for code, contract in contracts.items():
        remote = remote_by_code.get(code)
        if not remote:
            excluded.append({"capability_code": code, "reason": "remote_missing"})
            continue
        remote_id = str(_value(remote, "capabilityId", "capability_id"))
        if contract.get("_duplicate") or code in duplicate_codes or remote_id in duplicate_ids:
            excluded.append({"capability_code": code, "reason": "duplicate"})
            continue
        status = str(_value(remote, "status", default=""))
        if status != "ENABLED":
            excluded.append({"capability_code": code, "reason": "disabled"})
            continue
        revision = contract.get("contract_revision")
        if isinstance(revision, bool) or not isinstance(revision, int) or revision <= 0:
            excluded.append({"capability_code": code, "reason": "invalid_contract_revision"})
            continue
        risk = _value(remote, "riskLevel", "risk_level")
        if risk != contract.get("risk_level"):
            excluded.append({"capability_code": code, "reason": "risk_mismatch"})
            continue
        if (
            contract.get("workspace_action") == "read" and contract.get("confirmation_policy") != "none"
        ) or (
            contract.get("workspace_action") != "read" and contract.get("confirmation_policy") not in {"same_operator", "control_plane_approval"}
        ):
            excluded.append({"capability_code": code, "reason": "invalid_combination"})
            continue
        merged.append({
            "capability_id": str(_value(remote, "capabilityId", "capability_id")),
            "capability_code": code,
            "control_plane_object_version": _value(remote, "objectVersionNumber", "object_version_number"),
            "tool_name": contract["tool_name"],
            "tool_contract_revision": revision,
            "object_type": contract["object_type"],
            "action": contract["action"],
            "risk_level": risk,
        })
    merged.sort(key=lambda item: (item["capability_code"], item["capability_id"]))
    return CapabilityProjection(
        status="ready",
        items=merged,
        projection_digest=_canonical_digest(merged),
        control_plane_revision=control_plane_revision,
        etag=etag,
        excluded=excluded,
        policy_revision=policy_revision,
        registry_digest=registry_digest,
    )


merge_capability_projection = build_capability_projection


async def load_capability_projection(
    *,
    tenant_id: str | int,
    policy: str,
    policy_revision: int | str,
    client: Any | None = None,
    governance_view: Any | None = None,
) -> CapabilityProjection:
    """Load then merge a tenant projection without exposing partial data."""
    from dataclasses import replace

    from .policy import validate_governance_policy

    mode = validate_governance_policy(policy, policy_revision=int(policy_revision))
    if mode == "legacy":
        return CapabilityProjection(status="not_needed", policy_revision=policy_revision)
    key = str(tenant_id)
    if governance_view is None:
        from app.tool_registry import governance_view as capture_governance_view

        governance_view = capture_governance_view()
    current_registry_digest = _registry_digest(governance_view)
    cached = projection_cache.get_entry(key)
    if (
        isinstance(cached, CapabilityProjection)
        and cached.policy_revision == policy_revision
        and cached.registry_digest == current_registry_digest
    ):
        return cached
    if client is None:
        from .control_plane_capabilities import ControlPlaneCapabilityClient

        client = ControlPlaneCapabilityClient(tenant_id=tenant_id)
    loaded = await client.load(tenant_id=tenant_id)
    if not loaded.available:
        return CapabilityProjection(
            status="unavailable",
            reason=loaded.reason or "control_plane_unavailable",
            policy_revision=policy_revision,
        )
    result = build_capability_projection(
        loaded.items,
        governance_view=governance_view,
        control_plane_revision=str(loaded.projection_revision or ""),
        etag=str(loaded.etag or ""),
        policy_revision=policy_revision,
        registry_digest=current_registry_digest,
    )
    complete = replace(result, stored_at=time.monotonic())
    projection_cache.swap(key, complete)
    return complete


def projection_status_for_policy(policy: str, load_result: Any | None) -> str:
    """Expose shadow diagnostics without changing legacy tool visibility."""
    from .policy import validate_governance_policy

    mode = validate_governance_policy(policy)
    if mode == "legacy":
        return "not_needed"
    return str(getattr(load_result, "status", "unavailable") or "unavailable")
