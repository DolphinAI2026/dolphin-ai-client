"""
MCP 工具元数据 single source of truth — load 模块.

SPEC v2 §5.1 / §5.2:
- 真相在 backend/tool_registry.yaml (跟代码同 commit, 部署时一起走)
- backend (FastAPI) + mcp_server (独立进程) 两边各自 load 同一份 yaml
- CI 测试保证 yaml 跟 mcp_server.py 真实 @mcp.tool() 一致

派生视图 (按 SPEC v2 §5.2 接口):
- tools_for_section(s)  affinity 软引导工具列表 (含 global)
- tools_for_agent(a)    agent prompt 白名单 (硬过滤)
- all_tool_names()      全工具名集合
- tool_meta(name)       单工具完整元数据 dict
- valid_sections() / valid_agents()  允许取值
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from threading import RLock
from types import MappingProxyType
from typing import Any, Mapping

import yaml

# yaml 文件位置 = backend/tool_registry.yaml (跟 app/ 平级)
_YAML_PATH = Path(__file__).parent.parent / "tool_registry.yaml"
_REGISTRY_LOCK = RLock()

VALID_SECTIONS: frozenset[str] = frozenset(
    {"data", "ui", "logic", "permission", "extension", "global"}
)
VALID_AGENTS: frozenset[str] = frozenset({"builder", "coding", "config"})

_SUPPORTED_VERSIONS = frozenset({1, 2})
_BASE_TOOL_FIELDS = frozenset({
    "sections",
    "agents",
    "category",
    "description",
    "search_hint",
    "read_only",
    "writes_workspace",
    "writes_apaas",
    "deploys_or_publishes",
    "requires_confirmation",
})
_V2_GOVERNANCE_FIELDS = frozenset({
    "capability_code",
    "contract_revision",
    "object_type",
    "action",
    "risk_level",
    "workspace_action",
    "confirmation_policy",
    "audit_policy",
    "environment_scope",
})
_V2_TOOL_FIELDS = _BASE_TOOL_FIELDS | _V2_GOVERNANCE_FIELDS


def _freeze_snapshot(value: Any) -> Any:
    """Copy mutable cache data into an immutable governance-view value."""
    if isinstance(value, Mapping):
        return MappingProxyType({key: _freeze_snapshot(item) for key, item in value.items()})
    if isinstance(value, list):
        return tuple(_freeze_snapshot(item) for item in value)
    if isinstance(value, tuple):
        return tuple(_freeze_snapshot(item) for item in value)
    return value


@dataclass(frozen=True)
class GovernanceRegistryView:
    """One immutable v2 registry generation for governance consumers."""

    registry: Mapping[str, Any]
    tool_contracts: Mapping[str, Mapping[str, Any]]
    capability_projection: Mapping[str, Mapping[str, str]]

    def tool_meta(self, name: str) -> Mapping[str, Any]:
        """Return this generation's tool metadata or raise ``KeyError``."""
        return self.registry["tools"][name]

    def tool_contract(self, name: str) -> Mapping[str, Any]:
        """Return this generation's derived tool contract or raise ``KeyError``."""
        return self.tool_contracts[name]


def _has_complete_v2_contract(meta: Mapping[str, Any]) -> bool:
    """Return whether a tool opts into the complete v2 governance contract."""
    return _V2_GOVERNANCE_FIELDS.issubset(meta)


def _validate_v2_contract(name: str, meta: Mapping[str, Any]) -> None:
    """Validate one complete v2 contract without inferring missing metadata."""
    unknown = set(meta) - _V2_TOOL_FIELDS
    if unknown:
        raise ValueError(f"{name} contains unknown v2 fields: {sorted(unknown)}")
    for field in _V2_GOVERNANCE_FIELDS:
        if not isinstance(meta[field], str) or not meta[field].strip():
            raise ValueError(f"{name}.{field} must be a non-empty string")

    risk_level = meta["risk_level"]
    workspace_action = meta["workspace_action"]
    confirmation_policy = meta["confirmation_policy"]
    expected_confirmation = {
        "L0": "none",
        "L1": "same_operator",
        "L2": "control_plane_approval",
    }
    if risk_level not in expected_confirmation:
        raise ValueError(f"{name}.risk_level is invalid: {risk_level!r}")
    if (
        confirmation_policy != expected_confirmation[risk_level]
        or (risk_level == "L0" and workspace_action != "read")
    ):
        raise ValueError(f"{name} has an invalid governance combination")
    if risk_level == "L0":
        # Use the execution contract's real side-effect derivation. Metadata must
        # not be able to label a category-derived write as a read-only capability.
        from app.services.tool_contract_service import _derive_contract

        side_effects = _derive_contract(name, dict(meta))
        if any(
            side_effects[field]
            for field in ("writes_workspace", "writes_apaas", "deploys_or_publishes")
        ):
            raise ValueError(f"{name} L0 contract has a write side effect")


def _validate_registry(registry: dict[str, Any]) -> None:
    """Validate v2-only governance invariants while retaining legacy entries."""
    if registry["version"] != 2:
        return

    capability_codes: set[str] = set()
    for name, meta in registry["tools"].items():
        if not isinstance(meta, dict):
            raise ValueError(f"{name} metadata must be a dict")
        if not _has_complete_v2_contract(meta):
            continue
        _validate_v2_contract(name, meta)
        capability_code = meta["capability_code"]
        if capability_code in capability_codes:
            raise ValueError(f"duplicate capability_code: {capability_code}")
        capability_codes.add(capability_code)


def _freeze_registry(registry: dict[str, Any]) -> Mapping[str, Any]:
    """把 load 出来的 registry 包成 read-only view (递归 proxy tools 字典).

    PR1 reviewer #2 (round2-p2 state hygiene):
    原 lru_cache 返回的是 dict 引用, 任何调用方都能改 load()['tools'] 污染整个进程 cache —
    一次手贱写 `load()['tools']['__hacker__'] = ...` 就让所有后续读到的工具集都带这条脏数据.
    用 types.MappingProxyType 包成只读, 任何 mutate 操作直接 raise TypeError. 双层 proxy
    (outer registry + inner tools dict) — 否则 load()['tools'] 拿到的仍是可写 dict.

    注: meta_dict 自身的 list (sections / agents) 还可改 — 但调用方都用 list comprehension
    复制后用, 没有 in-place mutate, 风险可控. 真要彻底冻可改 tuple, 但侵入测试太多.
    """
    tools_proxy = MappingProxyType(registry["tools"])
    return MappingProxyType({**registry, "tools": tools_proxy})


@contextmanager
def registry_read_lock():
    """Protect a multi-layer registry read from an in-progress reload."""
    with _REGISTRY_LOCK:
        yield


@lru_cache(maxsize=1)
def _load() -> Mapping[str, Any]:
    """读 tool_registry.yaml, 缓存 (LRU size=1).

    返回 read-only Mapping: {"version": 1|2, "tools": {tool_name: meta_dict, ...}}
    顶层 + tools 字典都是 MappingProxyType, 调用方写入会 raise TypeError.

    若 yaml 缺失 / 解析失败, 抛 FileNotFoundError / yaml.YAMLError —
    fail fast 比兜底空 dict 安全 (静默漏工具会导致 ConfigAssistant 失能).
    """
    with open(_YAML_PATH, encoding="utf-8") as f:
        registry = yaml.safe_load(f)
    if not isinstance(registry, dict):
        raise ValueError(f"tool_registry.yaml 顶层必须是 dict, 实际 {type(registry).__name__}")
    if registry.get("version") not in _SUPPORTED_VERSIONS:
        raise ValueError(f"tool_registry.yaml version 不支持: {registry.get('version')}")
    tools = registry.get("tools")
    if not isinstance(tools, dict) or not tools:
        raise ValueError("tool_registry.yaml tools 字段必须是非空 dict")
    _validate_registry(registry)
    return _freeze_registry(registry)


def load() -> Mapping[str, Any]:
    """Read the current registry generation under the reload coordinator lock."""
    with _REGISTRY_LOCK:
        return _load()


def _clear_load_cache() -> None:
    with _REGISTRY_LOCK:
        _load.cache_clear()


# Preserve the pre-v2 cache control API used by tests and hot-reload callers.
load.cache_clear = _clear_load_cache  # type: ignore[attr-defined]


def _reload_locked() -> Mapping[str, Any]:
    """Invalidate every registry-derived cache while holding the coordinator lock."""
    _load.cache_clear()
    _capability_projection.cache_clear()
    # Import lazily to avoid the service's normal ``from app.tool_registry`` cycle.
    from app.services.tool_contract_service import clear_cache as clear_contract_cache

    clear_contract_cache()
    return _load()


def reload() -> Mapping[str, Any]:
    """Atomically invalidate registry-derived caches and re-read the registry."""
    with _REGISTRY_LOCK:
        return _reload_locked()


@lru_cache(maxsize=1)
def _capability_projection() -> dict[str, dict[str, str]]:
    """Build the cacheable v2 capability view used by projection consumers."""
    projection: dict[str, dict[str, str]] = {}
    for name, meta in load()["tools"].items():
        if not _has_complete_v2_contract(meta) or meta.get("deploys_or_publishes"):
            continue
        projection[meta["capability_code"]] = {
            "tool_name": name,
            "contract_revision": meta["contract_revision"],
            "object_type": meta["object_type"],
            "action": meta["action"],
        }
    return projection


def capability_projection() -> dict[str, dict[str, str]]:
    """Return a copy of the v2 capability projection, excluding publish tools."""
    with _REGISTRY_LOCK:
        if load()["version"] != 2:
            return {}
        return {code: dict(contract) for code, contract in _capability_projection().items()}


def governance_view() -> GovernanceRegistryView:
    """Capture registry, contracts and projection from one immutable v2 generation.

    Consumers that combine tool metadata, derived contracts and projection data
    must use this API instead of composing the legacy single-layer functions.
    """
    with _REGISTRY_LOCK:
        current_registry = load()
        if current_registry["version"] != 2:
            raise ValueError("governance_view requires a version 2 registry")
        from app.services.tool_contract_service import all_contracts

        return GovernanceRegistryView(
            registry=_freeze_snapshot(current_registry),
            tool_contracts=_freeze_snapshot(all_contracts()),
            capability_projection=_freeze_snapshot(_capability_projection()),
        )


def all_tool_names() -> set[str]:
    """全工具名集合."""
    return set(load()["tools"].keys())


def tool_meta(name: str) -> dict[str, Any]:
    """单工具完整元数据 dict (sections / agents / category / description).

    若 name 不存在, 抛 KeyError.
    """
    return load()["tools"][name]


def tools_for_section(section: str) -> list[str]:
    """affinity 工具列表 (软引导, SPEC v2 §1.2).

    返回顺序: 先 section 直接命中的工具, 再 global 工具 (global 永远可见).
    若传入 "global", 只返 global 工具.

    用法: ConfigAssistant 切到 ui section 时,
          system prompt 注入 "优先用以下工具: {tools_for_section('ui')}"
    """
    if section not in VALID_SECTIONS:
        raise ValueError(
            f"section 必须是 {sorted(VALID_SECTIONS)} 之一, 实际 {section!r}"
        )
    direct: list[str] = []
    global_pool: list[str] = []
    for name, meta in load()["tools"].items():
        sects = meta.get("sections") or []
        if section in sects:
            direct.append(name)
        elif section != "global" and "global" in sects:
            global_pool.append(name)
    return direct + global_pool


def tools_for_agent(agent: str) -> list[str]:
    """agent prompt 白名单 — 决定哪些 agent 能看到本工具.

    用法: dolphin agent 工具白名单从这里派生:
          _CONFIG_CHAT_TOOL_WHITELIST = set(tools_for_agent("config"))
    """
    if agent not in VALID_AGENTS:
        raise ValueError(
            f"agent 必须是 {sorted(VALID_AGENTS)} 之一, 实际 {agent!r}"
        )
    return [
        name
        for name, meta in load()["tools"].items()
        if agent in (meta.get("agents") or [])
    ]


def search_hints() -> dict[str, str]:
    """name -> search_hint (tool_registry.yaml 可选字段); 缺省空串。

    search_hint 是给 search_deferred_tools 用的额外关键词索引：
    用于工具名/描述不直观、用户会用不同词搜索的场景。
    例如 republish_apaas_app → "发布 上线 release 重新发布"。
    """
    reg = load()
    return {name: (meta.get("search_hint") or "") for name, meta in (reg.get("tools") or {}).items()}


def valid_sections() -> frozenset[str]:
    """允许的 section 取值."""
    return VALID_SECTIONS


def valid_agents() -> frozenset[str]:
    """允许的 agent 取值."""
    return VALID_AGENTS
