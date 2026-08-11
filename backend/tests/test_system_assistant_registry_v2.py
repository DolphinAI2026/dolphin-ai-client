"""Registry v2 governance contract and reload invalidation tests."""
from __future__ import annotations

from pathlib import Path

import pytest

import app.tool_registry as registry
from app.services import tool_contract_service


def _write_registry(path: Path, tools: str, *, version: int = 2) -> None:
    path.write_text(f"version: {version}\ntools:\n{tools}", encoding="utf-8")


def _v2_tool(
    name: str,
    *,
    capability_code: str = "workspace.inspect",
    action: str = "inspect",
    risk_level: str = "L0",
    workspace_action: str = "read",
    confirmation_policy: str = "none",
    audit_policy: str = "record",
    environment_scope: str = "workspace",
    deploys_or_publishes: str = "false",
    extra: str = "",
) -> str:
    return f"""  {name}:
    sections: [global]
    agents: [builder]
    category: introspection
    description: test tool
    capability_code: {capability_code}
    contract_revision: r1
    object_type: workspace
    action: {action}
    risk_level: {risk_level}
    workspace_action: {workspace_action}
    confirmation_policy: {confirmation_policy}
    audit_policy: {audit_policy}
    environment_scope: {environment_scope}
    deploys_or_publishes: {deploys_or_publishes}
{extra}"""


@pytest.fixture(autouse=True)
def _isolated_registry(monkeypatch, tmp_path):
    fake_yaml = tmp_path / "tool_registry.yaml"
    monkeypatch.setattr(registry, "_YAML_PATH", fake_yaml)
    registry.load.cache_clear()
    tool_contract_service.clear_cache()
    yield fake_yaml
    registry.load.cache_clear()
    tool_contract_service.clear_cache()


def test_v1_registry_remains_loadable_with_legacy_contracts(_isolated_registry):
    _write_registry(
        _isolated_registry,
        """  legacy_tool:
    sections: [global]
    agents: [builder]
    category: introspection
    description: legacy tool
""",
        version=1,
    )

    loaded = registry.reload()

    assert loaded["version"] == 1
    assert registry.capability_projection() == {}
    assert registry.tool_meta("legacy_tool")["description"] == "legacy tool"


@pytest.mark.parametrize(
    ("risk_level", "workspace_action", "confirmation_policy"),
    [
        ("L0", "read", "none"),
        ("L1", "write", "same_operator"),
        ("L2", "write", "control_plane_approval"),
    ],
)
def test_valid_v2_governance_combinations_enter_capability_projection(
    _isolated_registry, risk_level, workspace_action, confirmation_policy
):
    _write_registry(
        _isolated_registry,
        _v2_tool(
            "governed_tool",
            risk_level=risk_level,
            workspace_action=workspace_action,
            confirmation_policy=confirmation_policy,
        ),
    )

    registry.reload()

    assert registry.capability_projection() == {
        "workspace.inspect": {
            "tool_name": "governed_tool",
            "contract_revision": "r1",
            "object_type": "workspace",
            "action": "inspect",
        }
    }
    contract = tool_contract_service.tool_contract("governed_tool")
    assert contract["capability_code"] == "workspace.inspect"
    assert contract["contract_revision"] == "r1"
    assert contract["action"] == "inspect"


@pytest.mark.parametrize(
    "overrides",
    [
        {"risk_level": "L0", "workspace_action": "write", "confirmation_policy": "none"},
        {"risk_level": "L1", "workspace_action": "write", "confirmation_policy": "none"},
        {"risk_level": "L2", "workspace_action": "write", "confirmation_policy": "same_operator"},
    ],
)
def test_invalid_risk_governance_combination_is_rejected(_isolated_registry, overrides):
    _write_registry(_isolated_registry, _v2_tool("invalid_tool", **overrides))

    with pytest.raises(ValueError, match="governance"):
        registry.reload()


@pytest.mark.parametrize(
    "field",
    [
        "capability_code",
        "contract_revision",
        "object_type",
        "action",
        "risk_level",
        "workspace_action",
        "confirmation_policy",
        "audit_policy",
        "environment_scope",
    ],
)
def test_partial_v2_fields_remain_legacy(_isolated_registry, field):
    lines = _v2_tool("partial_tool").splitlines()
    _write_registry(
        _isolated_registry,
        "\n".join(line for line in lines if not line.strip().startswith(f"{field}:")),
    )

    registry.reload()

    assert registry.capability_projection() == {}


def test_unknown_v2_field_is_rejected(_isolated_registry):
    _write_registry(_isolated_registry, _v2_tool("unknown_field_tool", extra="    unknown: value\n"))

    with pytest.raises(ValueError, match="unknown"):
        registry.reload()


def test_duplicate_capability_code_is_rejected(_isolated_registry):
    _write_registry(
        _isolated_registry,
        _v2_tool("first_tool") + _v2_tool("second_tool"),
    )

    with pytest.raises(ValueError, match="duplicate capability_code"):
        registry.reload()


def test_publish_tool_is_excluded_from_capability_projection(_isolated_registry):
    _write_registry(
        _isolated_registry,
        _v2_tool(
            "publish_tool",
            capability_code="workspace.publish",
            action="publish",
            risk_level="L2",
            workspace_action="write",
            confirmation_policy="control_plane_approval",
            deploys_or_publishes="true",
        ),
    )

    registry.reload()

    assert registry.capability_projection() == {}


def test_reload_clears_loader_contract_and_projection_caches(_isolated_registry):
    _write_registry(_isolated_registry, _v2_tool("old_tool", capability_code="workspace.old"))
    registry.reload()
    assert registry.tool_meta("old_tool")["capability_code"] == "workspace.old"
    assert tool_contract_service.tool_contract("old_tool")["name"] == "old_tool"
    assert set(registry.capability_projection()) == {"workspace.old"}

    _write_registry(_isolated_registry, _v2_tool("new_tool", capability_code="workspace.new"))
    registry.reload()

    with pytest.raises(KeyError):
        registry.tool_meta("old_tool")
    with pytest.raises(KeyError):
        tool_contract_service.tool_contract("old_tool")
    assert registry.capability_projection() == {
        "workspace.new": {
            "tool_name": "new_tool",
            "contract_revision": "r1",
            "object_type": "workspace",
            "action": "inspect",
        }
    }
