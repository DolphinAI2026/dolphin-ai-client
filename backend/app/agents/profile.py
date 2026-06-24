"""AgentProfile — 一套 BaseAgent 引擎的「场景配置」对象。

引擎对场景无知:它只消费 AgentProfile 字段。每个场景(dev-apaas / builder-config /
dev-fullcode)= 一份 profile。详见
docs/superpowers/specs/2026-06-24-unified-agent-engine-design.md
"""
from __future__ import annotations

from dataclasses import dataclass

from app.coding.tools import TOOL_DEFINITIONS
from app.tool_registry import load as _load_registry, tools_for_agent


@dataclass(frozen=True)
class AgentProfile:
    name: str
    system_prompt: str
    tool_names: tuple[str, ...]
    skill_pack: tuple[str, ...] = ()
    use_mcp: bool = True
    max_turns: int = 30


# ── 本地执行工具(非 MCP,经 app/coding/tools.py execute_tool 跑)──
BASE_LOCAL_TOOLS: tuple[str, ...] = tuple(
    d["function"]["name"]
    for d in TOOL_DEFINITIONS
    if d.get("function", {}).get("name")
)


def _paused_tool_names() -> set[str]:
    """当前暂停、不暴露给任何 agent 的工具(business_event,见 ai_chat/tools.py 注释)。"""
    reg = _load_registry()
    paused = {
        n for n, m in reg["tools"].items()
        if m.get("category") == "business_event"
    }
    paused.add("list_apaas_form_menus_for_event")  # 只为建事件服务的 helper
    return paused


def _dev_apaas_tool_names() -> tuple[str, ...]:
    """dev-apaas 工具集 = run_agent 现有并集(builder∪coding∪config)∪ 本地工具 − 暂停。

    复刻 ai_chat/tools.py 现在跑通的并集,保证迁移时行为不退化。
    """
    allow = (
        set(tools_for_agent("builder"))
        | set(tools_for_agent("coding"))
        | set(tools_for_agent("config"))
    )
    allow |= set(BASE_LOCAL_TOOLS)
    allow -= _paused_tool_names()
    # 稳定顺序:本地工具在前,其余按名排序(确定性,便于测试/diff)
    local = [t for t in BASE_LOCAL_TOOLS if t in allow]
    rest = sorted(allow - set(local))
    return tuple(local + rest)


_PROFILE_BUILDERS = {
    "dev-apaas": lambda: AgentProfile(
        name="dev-apaas",
        system_prompt="",  # Phase 1 接入瘦提示词 + skill 包,这里先留空占位
        tool_names=_dev_apaas_tool_names(),
        skill_pack=(),
        use_mcp=True,
        max_turns=30,
    ),
}


def resolve_profile(name: str) -> AgentProfile:
    """按场景名解析 AgentProfile。未知 name 抛 KeyError。"""
    if name not in _PROFILE_BUILDERS:
        raise KeyError(
            f"未知 agent profile: {name!r}(已知:{sorted(_PROFILE_BUILDERS)})"
        )
    return _PROFILE_BUILDERS[name]()
