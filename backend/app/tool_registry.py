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

from functools import lru_cache
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping

import yaml

# yaml 文件位置 = backend/tool_registry.yaml (跟 app/ 平级)
_YAML_PATH = Path(__file__).parent.parent / "tool_registry.yaml"

VALID_SECTIONS: frozenset[str] = frozenset(
    {"data", "ui", "logic", "permission", "extension", "global"}
)
VALID_AGENTS: frozenset[str] = frozenset({"builder", "coding", "vibe", "config"})


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


@lru_cache(maxsize=1)
def load() -> Mapping[str, Any]:
    """读 tool_registry.yaml, 缓存 (LRU size=1).

    返回 read-only Mapping: {"version": 1, "tools": {tool_name: meta_dict, ...}}
    顶层 + tools 字典都是 MappingProxyType, 调用方写入会 raise TypeError.

    若 yaml 缺失 / 解析失败, 抛 FileNotFoundError / yaml.YAMLError —
    fail fast 比兜底空 dict 安全 (静默漏工具会导致 ConfigAssistant 失能).
    """
    with open(_YAML_PATH, encoding="utf-8") as f:
        registry = yaml.safe_load(f)
    if not isinstance(registry, dict):
        raise ValueError(f"tool_registry.yaml 顶层必须是 dict, 实际 {type(registry).__name__}")
    if registry.get("version") != 1:
        raise ValueError(f"tool_registry.yaml version 不支持: {registry.get('version')}")
    tools = registry.get("tools")
    if not isinstance(tools, dict) or not tools:
        raise ValueError("tool_registry.yaml tools 字段必须是非空 dict")
    return _freeze_registry(registry)


def reload() -> Mapping[str, Any]:
    """显式清缓存重新 load (测试 / 热替场景用)."""
    load.cache_clear()
    return load()


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


def valid_sections() -> frozenset[str]:
    """允许的 section 取值."""
    return VALID_SECTIONS


def valid_agents() -> frozenset[str]:
    """允许的 agent 取值."""
    return VALID_AGENTS
