from __future__ import annotations

import pytest

from app.system_assistant.object_references import (
    ObjectReferenceError,
    resolve_object_ref,
)


class MutableInt(int):
    pass


class MutableStr(str):
    pass


class MutableFloat(float):
    pass


def _context(*, tenant_id=7, objects=None):
    return {
        "tenant_id": tenant_id,
        "control_plane_tenant_id": f"cp-tenant-{tenant_id}",
        "object_catalog": objects
        if objects is not None
        else {
            "workspace:ws-a": {
                "object_type": "workspace",
                "tenant_id": 7,
                "control_plane_tenant_id": "cp-tenant-7",
                "stable_id": "ws-a",
                "revision": "rev-1",
                "owner_ref": "user:11",
                "environment_ref": "runtime:dev",
                "metadata": {"project_source_status": "ready"},
            }
        },
    }


def test_resolve_object_ref_returns_canonical_authoritative_identity():
    resolved = resolve_object_ref("workspace:ws-a", _context())

    assert resolved.object_type == "workspace"
    assert resolved.tenant_id == 7
    assert resolved.stable_id == "ws-a"
    assert resolved.revision == "rev-1"
    assert resolved.owner_ref == "user:11"
    assert resolved.environment_ref == "runtime:dev"
    assert len(resolved.metadata_digest) == 64
    assert len(resolved.stable_id_digest) == 64


def test_cross_tenant_object_is_indistinguishable_from_missing_object():
    foreign = {
        "workspace:ws-a": {
            **_context()["object_catalog"]["workspace:ws-a"],
            "tenant_id": 8,
            "control_plane_tenant_id": "cp-tenant-8",
        }
    }

    for catalog in ({}, foreign):
        with pytest.raises(ObjectReferenceError) as raised:
            resolve_object_ref("workspace:ws-a", _context(objects=catalog))
        assert raised.value.code == "OBJECT_NOT_FOUND"
        assert str(raised.value) == "OBJECT_NOT_FOUND"


def test_multiple_foreign_candidates_are_indistinguishable_from_missing_object():
    foreign = {
        **_context()["object_catalog"]["workspace:ws-a"],
        "tenant_id": 8,
        "control_plane_tenant_id": "cp-tenant-8",
    }

    with pytest.raises(ObjectReferenceError) as raised:
        resolve_object_ref("workspace:ws-a", _context(objects={"workspace:ws-a": [foreign, foreign]}))

    assert raised.value.code == "OBJECT_NOT_FOUND"


def test_resolved_object_metadata_is_deeply_immutable():
    context = _context()
    context["object_catalog"]["workspace:ws-a"]["metadata"] = {"nested": {"state": "ready"}}
    resolved = resolve_object_ref("workspace:ws-a", context)

    with pytest.raises(TypeError):
        resolved.metadata["nested"] = {}
    with pytest.raises(TypeError):
        resolved.metadata["nested"]["state"] = "stale"


def test_resolver_rejects_mutable_metadata_leaves_before_publishing_a_digest():
    context = _context()
    context["object_catalog"]["workspace:ws-a"]["metadata"] = {
        "payload": bytearray(b"ready")
    }

    with pytest.raises(ObjectReferenceError) as raised:
        resolve_object_ref("workspace:ws-a", context)

    assert raised.value.code == "OBJECT_MAPPING_UNRESOLVED"


@pytest.mark.parametrize(
    ("source_value", "expected_type"),
    [
        (MutableInt(7), int),
        (MutableStr("ready"), str),
        (MutableFloat(1.5), float),
    ],
)
def test_resolver_normalizes_mutable_metadata_scalar_subclasses(source_value, expected_type):
    source_value.mutable_state = {"status": "before"}
    context = _context()
    context["object_catalog"]["workspace:ws-a"]["metadata"] = {"payload": source_value}

    resolved = resolve_object_ref("workspace:ws-a", context)
    original_digest = resolved.metadata_digest

    assert type(resolved.metadata["payload"]) is expected_type
    assert not hasattr(resolved.metadata["payload"], "mutable_state")
    source_value.mutable_state["status"] = "after"
    assert resolved.metadata_digest == original_digest


def test_ambiguous_or_revision_drift_object_refs_have_typed_errors():
    duplicate = [_context()["object_catalog"]["workspace:ws-a"]] * 2

    with pytest.raises(ObjectReferenceError, match="OBJECT_MAPPING_UNRESOLVED"):
        resolve_object_ref("workspace:ws-a", _context(objects={"workspace:ws-a": duplicate}))
    with pytest.raises(ObjectReferenceError, match="OBJECT_REVISION_CONFLICT"):
        resolve_object_ref("workspace:ws-a@rev-2", _context())
    with pytest.raises(ObjectReferenceError, match="OBJECT_REF_INVALID"):
        resolve_object_ref("workspace", _context())
