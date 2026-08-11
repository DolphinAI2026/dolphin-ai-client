from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.system_assistant.capability_projection import (
    ProjectionCache,
    build_capability_projection,
    load_capability_projection,
)


def _view(*contracts):
    tools = {}
    projection = {}
    for name, code, risk, revision in contracts:
        tools[name] = {
            "capability_code": code,
            "contract_revision": revision,
            "object_type": "workspace",
            "action": "read",
            "risk_level": risk,
            "workspace_action": "read",
            "confirmation_policy": "none",
            "audit_policy": "record",
            "environment_scope": "workspace",
        }
        projection[code] = {
            "tool_name": name,
            "contract_revision": revision,
            "object_type": "workspace",
            "action": "read",
        }
    return SimpleNamespace(registry={"tools": tools}, capability_projection=projection)


def _remote(code="workspace.read", *, risk="L0", status="ENABLED", number=1):
    return {
        "capabilityId": f"remote-{number}",
        "code": code,
        "objectVersionNumber": number,
        "status": status,
        "riskLevel": risk,
    }


def test_merge_joins_by_exact_capability_code_and_publishes_digest():
    result = build_capability_projection(
        [_remote()],
        governance_view=_view(("read_tool", "workspace.read", "L0", 1)),
        control_plane_revision="rev-1",
        etag="rev-1",
    )

    assert result.status == "ready"
    assert result.projection_digest
    assert result.items == [
        {
            "capability_id": "remote-1",
            "capability_code": "workspace.read",
            "control_plane_object_version": 1,
            "tool_name": "read_tool",
            "tool_contract_revision": 1,
            "object_type": "workspace",
            "action": "read",
            "risk_level": "L0",
            "workspace_action": "read",
            "confirmation_policy": "none",
            "audit_policy": "record",
            "environment_scope": "workspace",
        }
    ]


@pytest.mark.parametrize(
    "remote,local",
    [
        ([_remote(code="workspace.missing")], ("read_tool", "workspace.read", "L0", 1)),
        ([_remote(risk="L1")], ("read_tool", "workspace.read", "L0", 1)),
        ([_remote(status="DISABLED")], ("read_tool", "workspace.read", "L0", 1)),
        ([_remote()], ("read_tool", "workspace.read", "L0", 0)),
    ],
)
def test_invalid_or_unmatched_entries_are_excluded(remote, local):
    result = build_capability_projection(
        remote,
        governance_view=_view(local),
        control_plane_revision="rev-1",
        etag="rev-1",
    )

    assert result.status == "ready"
    assert result.items == []


def test_merge_mixed_remote_id_types_make_the_batch_unavailable():
    invalid = _remote()
    invalid["capabilityId"] = 7

    result = build_capability_projection(
        [invalid],
        governance_view=_view(("read_tool", "workspace.read", "L0", 1)),
        control_plane_revision="rev-1",
        etag="rev-1",
    )

    assert result.status == "unavailable"
    assert result.items == []


def test_cache_swap_is_atomic_and_invalidation_removes_complete_batch():
    cache = ProjectionCache(ttl_seconds=300)
    old = SimpleNamespace(projection_digest="old")
    new = SimpleNamespace(projection_digest="new")
    cache.swap("tenant-1", old)
    cache.swap("tenant-1", new)
    assert cache.get("tenant-1") is new
    cache.invalidate("tenant-1")
    assert cache.get("tenant-1") is None


@pytest.mark.asyncio
async def test_legacy_never_loads_remote_projection():
    class UnexpectedClient:
        async def load(self, **_kwargs):
            raise AssertionError("legacy must not call Control Plane")

    result = await load_capability_projection(
        tenant_id="tenant-1",
        policy="legacy",
        policy_revision=1,
        client=UnexpectedClient(),
    )

    assert result.status == "not_needed"


@pytest.mark.asyncio
async def test_fresh_local_projection_still_checks_remote_etag():
    from app.system_assistant.capability_projection import projection_cache

    projection_cache.invalidate("tenant-etag")
    calls = []

    class Client:
        async def load(self, **_kwargs):
            calls.append(True)
            return type(
                "Loaded",
                (),
                {
                    "available": True,
                    "items": [_remote()],
                    "projection_revision": "rev-1",
                    "etag": "rev-1",
                },
            )()

    view = _view(("read_tool", "workspace.read", "L0", 1))
    first = await load_capability_projection(
        tenant_id="tenant-etag", policy="shadow", policy_revision=1,
        client=Client(), governance_view=view,
    )
    second = await load_capability_projection(
        tenant_id="tenant-etag", policy="shadow", policy_revision=1,
        client=Client(), governance_view=view,
    )

    assert first.status == second.status == "ready"
    assert len(calls) == 2
