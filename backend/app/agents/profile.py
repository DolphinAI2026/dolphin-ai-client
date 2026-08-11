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


_SYSTEM_ASSISTANT_SYSTEM_PROMPT = """你是睿鲸 AI 的 Dolphin Code 系统助手，只处理代码工程和软件开发任务。

工作边界：
- 以用户本轮请求、上传文件和当前会话明确绑定的 Code 工作区为唯一上下文来源。
- 没有明确绑定 ws_id 时，不发现、枚举、猜测、绑定或创建工作区，也不沿用历史会话中的工程身份。
- 未绑定工作区时，可以分析代码与技术问题、处理上传文件、生成会话产物；需要真实工程才能继续时，直接说明当前会话尚未绑定 Code 工作区。
- 只有会话已经明确绑定唯一 Code 工作区时，才读取、修改、运行和验证该工作区；不得枚举、切换或创建其他工作区。
- 先读取现有代码和配置，再做最小范围修改；修改后执行与风险相称的构建、测试或运行验证。
- 不声称已经读取、修改、运行或验证任何未通过工具实际访问的内容。

回答简洁、面向结果。具体任务直接处理；缺少必要输入时只说明真正的阻断。
"""


_SYSTEM_ASSISTANT_SESSION_TOOLS: tuple[str, ...] = (
    "read_attachment",
    "run_python",
    "write_artifact",
    "read_artifact",
    "edit_artifact",
    "create_artifact_from_attachment",
    "ask_clarifying_question",
    "save_binary_artifact",
)

_SYSTEM_ASSISTANT_BOUND_WORKSPACE_TOOLS: tuple[str, ...] = (
    "get_dev_workspace_status",
    "glob_workspace",
    "grep_workspace",
    "read_workspace_file",
    "edit_workspace_files",
    "write_workspace_files",
    "run_workspace_command",
)


def _system_assistant_tool_names() -> tuple[str, ...]:
    """Return the default session-scoped system-assistant tools."""
    return _SYSTEM_ASSISTANT_SESSION_TOOLS


_PROFILE_BUILDERS = {
    "dev-apaas": lambda: AgentProfile(
        name="dev-apaas",
        system_prompt=_DEV_APAAS_SYSTEM_PROMPT,
        tool_names=_dev_apaas_tool_names(),
        skill_pack=(),
        use_mcp=True,
        max_turns=30,
    ),
    "system_assistant": lambda: AgentProfile(
        name="system_assistant",
        system_prompt=_SYSTEM_ASSISTANT_SYSTEM_PROMPT,
        tool_names=_system_assistant_tool_names(),
        skill_pack=(),
        use_mcp=True,
        max_turns=30,
    ),
}


def resolve_profile(name: str | object) -> AgentProfile:
    """按 profile 名或会话解析 AgentProfile。未知值抛 KeyError。"""
    if not isinstance(name, str):
        assistant_profile = getattr(name, "assistant_profile", None)
        if assistant_profile not in (None, "", "entry_agent", "system_assistant"):
            raise KeyError(f"未知 assistant_profile: {assistant_profile!r}")
        if assistant_profile == "system_assistant":
            name = "system_assistant"
        elif getattr(name, "mode", None) == "code":
            name = "dev-apaas"
        else:
            raise KeyError("会话没有可解析的 agent profile")
    if name not in _PROFILE_BUILDERS:
        raise KeyError(
            f"未知 agent profile: {name!r}(已知:{sorted(_PROFILE_BUILDERS)})"
        )
    return _PROFILE_BUILDERS[name]()


# ── 单工作区锁定时按 ws_id 收窄工具(原 coding.py._cutover_tool_names,抽来两边复用)──

# Code 单工作区锁定时砍掉的"工作区发现/新建"工具:Code 模式已绑定打开的工作区,
# agent 不该枚举/新建别的工作区。实测 list_dev_workspaces(include_unbound=true)
# 会让 agent 列出全部工作区、挑错一个去读代码(读了"工厂孪生"而非用户打开的"访客")。
_WS_LOCK_DROP_TOOLS = frozenset({"list_dev_workspaces", "create_dev_workspace"})

# Code 模式砍掉的"需要 app/env 绑定的 apaas 应用级 / 应用管理工具":
# Code 会话不绑 app(env_id=0)→ 这些必失败,agent 会死循环(实测 get_apaas_app_overview
# 反复 platform_env_id=0 失败)。Code 是工作区代码编辑,二开 grounding 改读工作区自己的
# apaas.json + skill 包,不靠 live apaas 查询。保留:工作区代码工具 + 文件 + skill +
# lint/doctor/init 后端工作区 + start_serve。
_WS_LOCK_DROP_APP_TOOLS = frozenset({
    "get_apaas_app_overview", "get_apaas_form_detail", "get_apaas_user_name",
    "list_apaas_app_dev_kits", "list_apaas_app_dicts", "list_apaas_app_menus",
    "list_apaas_app_models", "list_apaas_app_roles", "list_apaas_apps_in_env",
    "list_apaas_form_components", "list_apaas_form_permissions", "list_apaas_form_views",
    "list_apaas_models_in_env", "list_apaas_resource_pool_kits", "query_apaas_business_data",
    "attach_dev_packages_to_apaas_app", "bind_apaas_form_field_to_dict",
    "build_apaas_feature_from_spec", "enable_apaas_self_dev_config",
    "rename_apaas_menu", "upload_external_zip_to_apaas",
    "get_application", "list_my_applications", "list_platform_envs",
    "compute_app_health", "check_app_code_conflict", "get_role_resource_matrix",
    "get_dev_scene_full_workflow", "get_dev_scene_spec", "list_dev_scenes", "save_dev_spec",
})


def narrow_tools_for_locked_ws(tool_names, ws_id: str | None) -> tuple[str, ...]:
    """绑定了工作区(Code 单工作区)→ 砍掉枚举/新建工具 + app/env 级 apaas 工具,
    把 agent 锁死在这个 ws_id、专注工作区代码。没绑定 → 保留全集。

    返回去重后的 tuple(确定性顺序:保留原 tool_names 顺序),供 coding.py harness 老路
    与 run_agent 引擎推导两边复用。原 coding.py._cutover_tool_names 抽来,行为等价。
    """
    if not ws_id:
        # 去重保序
        seen: set[str] = set()
        return tuple(t for t in tool_names if not (t in seen or seen.add(t)))
    drop = _WS_LOCK_DROP_TOOLS | _WS_LOCK_DROP_APP_TOOLS
    seen = set()
    return tuple(
        t for t in tool_names
        if t not in drop and not (t in seen or seen.add(t))
    )


# ── mode → profile 映射 + 按会话推导 override(SP2a)──

MODE_PROFILE: dict[str, str] = {"code": "dev-apaas"}


def ws_bind_view_context(ws_id: str | None) -> str | None:
    """code 会话单工作区硬绑 view_context:告诉 agent 当前 ws_id 并锁死所有工作区工具到它。

    供 run_agent 引擎推导(统一外壳从 /ai-chat 发 code 会话、调用方不传 view_context 时)
    与 harness 老路复用 —— **文本单一来源**,防两处漂移。
    缺这段 → agent 拿到 dev-apaas 提示词(说「上下文会给你 ws_id」)却没 ws_id →
    反问用户「请把 ws_id 发我」(2026-06-25 修复的 bug)。
    """
    if not ws_id:
        return None
    return (
        f"【硬性约束·单工作区锁定】你正在唯一指定的代码工作区 ws_id='{ws_id}' 内做二次开发,"
        f"右侧面板正显示它。用户说的「代码 / 最新代码 / 这个项目 / 这个页面」都**只**指 ws_id='{ws_id}'。"
        f"所有 read_workspace_file / write_workspace_files / edit_workspace_files / "
        f"glob_workspace / grep_workspace / run_workspace_command 的 ws_id 参数**必须**填 '{ws_id}';"
        f"**严禁**填任何其它 ws_id、严禁枚举或切换到别的工作区、严禁 create_dev_workspace 新建。"
    )


def resolve_overrides_for_session(session) -> tuple[str | None, set[str] | None, str | None]:
    """按 session.mode 推导 run_agent 的 (system_prompt, tool_names_set, locked_ws_id)。

    entry_agent + mode='code' → dev-apaas 提示词 + 按 session.workspace_id 收窄工具集 + 该 ws_id;
    system_assistant + mode='code' → 系统助手提示词 + 按 session.workspace_id 收窄工具集 + 该 ws_id;
    其它 / 未知 mode → (None, None, None)(走 run_agent 默认通用 Builder 行为,零变化)。

    纯函数:不碰 DB、不改 session。run_agent 在调用方未显式传 override 时调它。
    """
    assistant_profile = getattr(session, "assistant_profile", None) or "entry_agent"
    if assistant_profile == "system_assistant":
        profile = resolve_profile("system_assistant")
        ws_id = getattr(session, "workspace_id", None)
        tool_names = set(profile.tool_names)
        if ws_id:
            tool_names.update(_SYSTEM_ASSISTANT_BOUND_WORKSPACE_TOOLS)
            tool_names = set(narrow_tools_for_locked_ws(tool_names, ws_id))
        return (profile.system_prompt, tool_names, ws_id or None)
    if assistant_profile != "entry_agent":
        raise ValueError(f"未知 assistant_profile: {assistant_profile!r}")

    mode = getattr(session, "mode", None)
    profile_name = MODE_PROFILE.get(mode or "")
    if profile_name is None:
        return (None, None, None)
    profile = resolve_profile(profile_name)
    ws_id = getattr(session, "workspace_id", None)
    tool_names = set(narrow_tools_for_locked_ws(profile.tool_names, ws_id))
    return (profile.system_prompt, tool_names, ws_id or None)
