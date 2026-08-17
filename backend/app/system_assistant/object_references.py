"""Authority-only object reference resolution for shadow governance."""
from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Mapping


_OBJECT_PART = re.compile(r"^[A-Za-z0-9_.-]+$")


class ObjectReferenceError(ValueError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class ResolvedObjectRef:
    object_type: str
    tenant_id: int
    stable_id: str
    revision: str
    owner_ref: str
    environment_ref: str | None
    metadata_digest: str
    stable_id_digest: str
    metadata: Mapping[str, Any]

    @property
    def canonical_ref(self) -> str:
        return f"{self.object_type}:{self.stable_id}"


def _parse_ref(raw_ref: Any) -> tuple[str, str, str | None]:
    if not isinstance(raw_ref, str):
        raise ObjectReferenceError("OBJECT_REF_INVALID")
    base, separator, expected_revision = raw_ref.partition("@")
    if separator and (not expected_revision or "@" in expected_revision):
        raise ObjectReferenceError("OBJECT_REF_INVALID")
    object_type, separator, stable_id = base.partition(":")
    if not separator or not _OBJECT_PART.fullmatch(object_type) or not _OBJECT_PART.fullmatch(stable_id):
        raise ObjectReferenceError("OBJECT_REF_INVALID")
    return object_type, stable_id, expected_revision or None


def _metadata_digest(metadata: Mapping[str, Any]) -> str:
    payload = json.dumps(_json_value(metadata), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        if any(not isinstance(key, str) for key in value):
            raise ObjectReferenceError("OBJECT_MAPPING_UNRESOLVED")
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if isinstance(value, list):
        return tuple(_freeze(item) for item in value)
    if isinstance(value, tuple):
        return tuple(_freeze(item) for item in value)
    if isinstance(value, (set, frozenset, bytes, bytearray, memoryview)):
        raise ObjectReferenceError("OBJECT_MAPPING_UNRESOLVED")
    if value is None or type(value) is bool:
        return value
    if isinstance(value, int):
        return int.__int__(value)
    if isinstance(value, float):
        frozen_float = float.__float__(value)
        if not math.isfinite(frozen_float):
            raise ObjectReferenceError("OBJECT_MAPPING_UNRESOLVED")
        return frozen_float
    if isinstance(value, str):
        return str.__str__(value)
    raise ObjectReferenceError("OBJECT_MAPPING_UNRESOLVED")


def _json_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _json_value(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_json_value(item) for item in value]
    return value


def _not_found(candidate: Any, auth_context: Mapping[str, Any]) -> bool:
    if not isinstance(candidate, Mapping):
        return False
    if candidate.get("tenant_id") != auth_context.get("tenant_id"):
        return True
    expected_control_tenant = auth_context.get("control_plane_tenant_id")
    return (
        expected_control_tenant is not None
        and candidate.get("control_plane_tenant_id") != expected_control_tenant
    )


def resolve_object_ref(raw_ref: Any, auth_context: Mapping[str, Any]) -> ResolvedObjectRef:
    """Resolve from the supplied authoritative catalog without tenant information leaks."""
    object_type, stable_id, expected_revision = _parse_ref(raw_ref)
    catalog = auth_context.get("object_catalog") if isinstance(auth_context, Mapping) else None
    if not isinstance(catalog, Mapping):
        raise ObjectReferenceError("OBJECT_MAPPING_UNRESOLVED")
    candidate = catalog.get(f"{object_type}:{stable_id}")
    if candidate is None:
        raise ObjectReferenceError("OBJECT_NOT_FOUND")
    candidates = candidate if isinstance(candidate, (list, tuple)) else [candidate]
    authorized_candidates = [
        item for item in candidates
        if isinstance(item, Mapping) and not _not_found(item, auth_context)
    ]
    if not authorized_candidates:
        raise ObjectReferenceError("OBJECT_NOT_FOUND")
    if len(authorized_candidates) != 1:
        raise ObjectReferenceError("OBJECT_MAPPING_UNRESOLVED")
    candidate = authorized_candidates[0]
    if not isinstance(candidate, Mapping):
        raise ObjectReferenceError("OBJECT_MAPPING_UNRESOLVED")
    required = ("object_type", "tenant_id", "stable_id", "revision", "owner_ref")
    if any(not candidate.get(key) for key in required):
        raise ObjectReferenceError("OBJECT_MAPPING_UNRESOLVED")
    if candidate["object_type"] != object_type or candidate["stable_id"] != stable_id:
        raise ObjectReferenceError("OBJECT_MAPPING_UNRESOLVED")
    revision = str(candidate["revision"])
    if expected_revision is not None and expected_revision != revision:
        raise ObjectReferenceError("OBJECT_REVISION_CONFLICT")
    metadata = candidate.get("metadata") or {}
    if not isinstance(metadata, Mapping):
        raise ObjectReferenceError("OBJECT_MAPPING_UNRESOLVED")
    frozen_metadata = _freeze(metadata)
    return ResolvedObjectRef(
        object_type=object_type,
        tenant_id=int(candidate["tenant_id"]),
        stable_id=stable_id,
        revision=revision,
        owner_ref=str(candidate["owner_ref"]),
        environment_ref=(str(candidate["environment_ref"]) if candidate.get("environment_ref") else None),
        metadata_digest=_metadata_digest(frozen_metadata),
        stable_id_digest=hashlib.sha256(stable_id.encode("utf-8")).hexdigest(),
        metadata=frozen_metadata,
    )
