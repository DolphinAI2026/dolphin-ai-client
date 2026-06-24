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


# dev-apaas(代码二次开发)要砍掉的工具类别:部署/发布/从文档生成应用 + 平台配置增删改。
# 这些是 Builder/配置侧的活,给 Code agent 会让它"跑偏"去部署整个应用、耗轮次(实测过)。
# 保留:introspection(只读查询)/dev_workspace(工作区读写跑)/dev_scene/skill_learning/other。
_DEV_APAAS_DROP_CATEGORIES = frozenset({
    "lifecycle",       # deploy/publish/republish — 部署是配置侧的事,不给 Code
    "doc_pipeline",    # generate_app_from_doc/update_app_from_doc — 重新生成整个应用,会跑偏
    "create", "update", "delete", "configure", "process",  # 平台配置增删改 = Builder 的活
    "business_event",  # 已暂停
    "issue_assistant",
})


def _dev_apaas_drop_by_category() -> set[str]:
    reg = _load_registry()
    return {
        n for n, m in reg["tools"].items()
        if m.get("category") in _DEV_APAAS_DROP_CATEGORIES
    }


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
    allow -= _dev_apaas_drop_by_category()  # 砍掉部署/生成/配置增删改,防 Code 跑偏
    # 稳定顺序:本地工具在前,其余按名排序(确定性,便于测试/diff)
    local = [t for t in BASE_LOCAL_TOOLS if t in allow]
    rest = sorted(allow - set(local))
    return tuple(local + rest)


_DEV_APAAS_SYSTEM_PROMPT = """你是睿鲸 AI 的代码开发助手,在一个【已有的代码工作区】里做 aPaaS 应用的二次开发(写/改自开发页面、组件、逻辑)。

核心工作方式:
- **确认即开干**:用户一旦选定/同意了目标应用或你提出的方案(哪怕只说"可以""好""就这个""按你说的来"),立刻进入开发——读工作区文件 → 改/写代码 → 构建验证。**不要再重复确认已经定下来的事。**
- **最多问一次,且只问真正卡住的关键信息**。能从上下文/工具查到的自己查,别反过来问用户;绝不重复问上一轮已回答过的问题。
- **在绑定的工作区里干活**:上下文会给你当前 ws_id,所有文件/命令工具都用这个 ws_id;工作区已存在,**不要 create_dev_workspace 新建**。
- 先 read/glob/grep 看清现有代码再动手;优先用 edit 局部修改,别整文件重写。
- aPaaS 只读工具(查应用/模型/菜单/数据)只用于**了解现状做参照**;你在这里**不部署、不改平台配置、不重新生成应用**——那是配置侧的事。
- 回答简洁,做完说清改了哪些文件/做了什么,不空喊。

记住:你的价值是把需求**落成代码**,不是反复确认和聊天。"""


_PROFILE_BUILDERS = {
    "dev-apaas": lambda: AgentProfile(
        name="dev-apaas",
        system_prompt=_DEV_APAAS_SYSTEM_PROMPT,
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
