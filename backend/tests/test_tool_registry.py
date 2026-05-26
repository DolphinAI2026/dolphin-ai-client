"""
test_tool_registry.py — SPEC v2 PR1.

锁住三件事:
  1) yaml 能 load, schema 合法
  2) 每个工具有 sections / agents 字段, 取值合法
  3) tools_for_agent("config") 跟 PR1 之前的硬编码白名单 byte-equal (行为不变)
  4) tools_for_section() 软引导正确返回 affinity 工具
  5) tool_registry.yaml 全量工具 == mcp_server.py @mcp.tool() 真实注册 (无 drift)
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

from app.tool_registry import (
    VALID_AGENTS,
    VALID_SECTIONS,
    all_tool_names,
    load,
    reload,
    tool_meta,
    tools_for_agent,
    tools_for_section,
    valid_agents,
    valid_sections,
)


# ─────────────────────────────────────────────────────
# Baseline: PR1 落地前的硬编码 _CONFIG_CHAT_TOOL_WHITELIST.
# 这是从 backend/app/routes/applications/__init__.py 2026-05-25 HEAD
# (commit b7dc145 "加 bind_apaas_form_field_to_dict") 抓出来的 61 工具.
# 2026-05-26 PR3 加 update_apaas_app_info → snapshot 升 62.
# tool_registry.yaml 派生白名单必须 byte-equal 这个集合, 否则 ConfigAssistant 行为变了.
# ─────────────────────────────────────────────────────
_OLD_CONFIG_WHITELIST: frozenset[str] = frozenset({
    "add_apaas_dict_option",
    "add_apaas_model_field",
    "bind_apaas_form_field_to_dict",
    "update_apaas_app_info",  # PR3 (SPEC v2 顶部 breadcrumb 编辑)
    "browser_click",
    "browser_list_pages",
    "browser_navigate",
    "browser_press_key",
    "browser_screenshot",
    "browser_select_page",
    "browser_snapshot",
    "browser_start_recording",
    "browser_stop_recording",
    "browser_type",
    "browser_wait_for_text",
    "build_apaas_feature_from_spec",
    "check_app_code_conflict",
    "create_apaas_app_dict",
    "create_apaas_app_roles",
    "create_apaas_business_event",
    "create_apaas_form_menu",
    "create_apaas_menu_group",
    "create_apaas_self_dev_menu",
    "create_apaas_value_change_assignment_event",
    "create_form_event_with_python_code",
    "create_time_event_with_python_code",
    "delete_apaas_app_menu",
    "delete_apaas_app_role",
    "delete_apaas_business_event",
    "delete_config_skill",
    "disable_apaas_app_dict",
    "disable_apaas_dict_option",
    "disable_apaas_model_field",
    "get_apaas_app_overview",
    "get_apaas_business_event_detail",
    "get_config_skill",
    "list_apaas_app_dicts",
    "list_apaas_app_menus",
    "list_apaas_app_models",
    "list_apaas_app_roles",
    "list_apaas_apps_in_env",
    "list_apaas_business_event_execution_history",
    "list_apaas_business_events",
    "list_apaas_business_events_in_tenant",
    "list_apaas_form_components",
    "list_apaas_form_menus_for_event",
    "list_apaas_form_permissions",
    "list_apaas_form_views",
    "list_apaas_models_in_env",
    "list_config_skills",
    "query_apaas_business_event_trees",
    "rename_apaas_menu",
    "save_apaas_business_event",
    "save_config_skill",
    "set_apaas_app_process",
    "set_apaas_form_permissions",
    "set_apaas_menu_parent",
    "update_apaas_app_dict",
    "update_apaas_app_role",
    "update_apaas_dict_option",
    "update_apaas_form_component",
    "update_apaas_model_field",
})


# ─────────────────────── 1. Load / schema ───────────────────────


def test_registry_loadable():
    """yaml 文件能 load, version=1, tools 非空."""
    r = load()
    assert r["version"] == 1, "version 必须是 1 (后续升级走 v2)"
    assert isinstance(r["tools"], dict)
    assert len(r["tools"]) > 100, f"工具数应远大于 100, 实际 {len(r['tools'])}"


def test_reload_clears_cache():
    """reload() 显式清缓存 — 用于测试 / 热替."""
    r1 = load()
    r2 = reload()
    assert r1 is not r2, "reload 必须返回新 dict object"


def test_valid_sections_and_agents_are_immutable():
    """VALID_SECTIONS / VALID_AGENTS 是 frozenset, 不能改."""
    assert isinstance(valid_sections(), frozenset)
    assert isinstance(valid_agents(), frozenset)
    assert valid_sections() == VALID_SECTIONS
    assert valid_agents() == VALID_AGENTS
    with pytest.raises(AttributeError):
        VALID_SECTIONS.add("hacker")  # type: ignore[attr-defined]


# ─────────────────────── 2. 字段完整性 ───────────────────────


def test_every_tool_has_required_fields():
    """每个工具必须有 sections + agents 字段."""
    for name, meta in load()["tools"].items():
        assert "sections" in meta, f"{name} 缺 sections"
        assert "agents" in meta, f"{name} 缺 agents"
        assert isinstance(meta["sections"], list), f"{name} sections 必须是 list"
        assert isinstance(meta["agents"], list), f"{name} agents 必须是 list"


def test_section_values_are_legal():
    """sections 字段取值必须在 VALID_SECTIONS 内."""
    for name, meta in load()["tools"].items():
        for s in meta["sections"]:
            assert s in VALID_SECTIONS, (
                f"{name}.sections 含非法值 {s!r}, "
                f"合法: {sorted(VALID_SECTIONS)}"
            )


def test_agent_values_are_legal():
    """agents 字段取值必须在 VALID_AGENTS 内."""
    for name, meta in load()["tools"].items():
        for a in meta["agents"]:
            assert a in VALID_AGENTS, (
                f"{name}.agents 含非法值 {a!r}, "
                f"合法: {sorted(VALID_AGENTS)}"
            )


def test_section_partition_complete():
    """每个工具至少有一个 section (含 global) — 不能全空."""
    for name, meta in load()["tools"].items():
        assert meta["sections"], f"{name} sections 不能为空"


def test_tool_meta_lookup():
    """tool_meta(name) 拿单工具完整元数据, 含 sections/agents/category."""
    meta = tool_meta("list_apaas_app_models")
    assert "data" in meta["sections"]
    assert "config" in meta["agents"]
    assert meta["category"] == "introspection"


def test_tool_meta_unknown_raises():
    """tool_meta 未知工具抛 KeyError."""
    with pytest.raises(KeyError):
        tool_meta("nonexistent_tool_xyz")


# ─────────────────────── 3. 派生白名单 byte-equal 现状 ───────────────────────


def test_config_whitelist_unchanged():
    """tool_registry.yaml 派生的 config 白名单 == snapshot (PR1 61 + PR3 1 = 62)."""
    new = set(tools_for_agent("config"))
    diff = new ^ _OLD_CONFIG_WHITELIST
    assert not diff, (
        f"配置助手白名单 diff = {len(diff)} 个 (行为变了!)\n"
        f"  only in new (yaml 派生): {sorted(new - _OLD_CONFIG_WHITELIST)}\n"
        f"  only in old (硬编码): {sorted(_OLD_CONFIG_WHITELIST - new)}"
    )
    assert len(new) == 62, f"config 白名单总数应是 62 (PR3 加 update_apaas_app_info), 实际 {len(new)}"


def test_builder_whitelist_count():
    """builder 白名单非空 (锁数量, 防止误删)."""
    # 现状 46 工具 (prompt 文档写 "37" stale, 实际 list 46)
    tools = tools_for_agent("builder")
    assert len(tools) >= 40, f"builder 白名单 >= 40, 实际 {len(tools)}"


def test_coding_whitelist_count():
    """coding 白名单 >= 35 (锁数量)."""
    tools = tools_for_agent("coding")
    assert len(tools) >= 35, f"coding 白名单 >= 35, 实际 {len(tools)}"


def test_vibe_whitelist_is_vibe_prefixed():
    """vibe 白名单全是 vibe_ 开头 — 严格隔离."""
    tools = tools_for_agent("vibe")
    assert tools, "vibe 白名单不能空"
    for t in tools:
        assert t.startswith("vibe_"), f"{t} 不是 vibe_ 前缀, 不该归 vibe agent"


# ─────────────────────── 4. Section affinity ───────────────────────


def test_section_filter_ui_includes_build_feature():
    """ui section 软引导应含 build_apaas_feature_from_spec."""
    ui_tools = set(tools_for_section("ui"))
    assert "build_apaas_feature_from_spec" in ui_tools


def test_section_filter_ui_includes_browser_tools():
    """ui section 软引导应含 browser_* 工具."""
    ui_tools = set(tools_for_section("ui"))
    assert "browser_snapshot" in ui_tools
    assert "browser_click" in ui_tools


def test_section_filter_data_includes_model_field():
    """data section 软引导应含字段管理工具."""
    data_tools = set(tools_for_section("data"))
    assert "add_apaas_model_field" in data_tools
    assert "list_apaas_app_models" in data_tools
    assert "list_apaas_app_dicts" in data_tools


def test_section_filter_logic_includes_business_event():
    """logic section 软引导应含业务事件工具."""
    logic_tools = set(tools_for_section("logic"))
    assert "create_apaas_business_event" in logic_tools
    assert "save_apaas_business_event" in logic_tools
    assert "set_apaas_app_process" in logic_tools


def test_section_filter_permission_includes_role():
    """permission section 软引导应含角色工具."""
    perm_tools = set(tools_for_section("permission"))
    assert "create_apaas_app_roles" in perm_tools
    assert "set_apaas_form_permissions" in perm_tools


def test_section_filter_extension_includes_workspace():
    """extension section 软引导应含 workspace / vibe / dev_scene 工具."""
    ext_tools = set(tools_for_section("extension"))
    assert "create_dev_workspace" in ext_tools
    assert "vibe_create_workspace" in ext_tools
    assert "list_dev_scenes" in ext_tools


def test_section_filter_global_includes_lifecycle():
    """global section 应含部署生命周期工具."""
    g_tools = set(tools_for_section("global"))
    assert "deploy_application" in g_tools
    assert "publish_application" in g_tools
    assert "list_deploy_records" in g_tools
    assert "rollback_application" in g_tools


def test_section_filter_includes_global_when_not_global():
    """非 global section 调 tools_for_section() 应含 global 工具
    (SPEC v2 §1.2: global 工具任何 section 都看得到)."""
    ui_tools = set(tools_for_section("ui"))
    # deploy_application 是 global, ui section 也应见
    assert "deploy_application" in ui_tools


def test_section_filter_global_only_global():
    """tools_for_section('global') 只返 global section 工具."""
    g_tools = tools_for_section("global")
    for t in g_tools:
        meta = tool_meta(t)
        assert "global" in meta["sections"], (
            f"{t} 在 global section 返回但 yaml sections={meta['sections']}"
        )


def test_section_filter_rejects_invalid():
    """tools_for_section 传非法 section 抛 ValueError."""
    with pytest.raises(ValueError):
        tools_for_section("hacker")


def test_agent_filter_rejects_invalid():
    """tools_for_agent 传非法 agent 抛 ValueError."""
    with pytest.raises(ValueError):
        tools_for_agent("hacker")


# ─────────────────────── 5. Drift detection — yaml vs mcp_server.py ───────────────────────


def _extract_mcp_tool_names_from_source() -> set[str]:
    """从 backend/app/mcp_server.py AST 提取所有 @mcp.tool() 装饰的 async def 名."""
    mcp_path = Path(__file__).parent.parent / "app" / "mcp_server.py"
    src = mcp_path.read_text(encoding="utf-8")
    tree = ast.parse(src)
    names: set[str] = set()
    for node in tree.body:
        if not isinstance(node, ast.AsyncFunctionDef):
            continue
        for deco in node.decorator_list:
            # @mcp.tool() 或 @mcp.tool(description="...")
            if (
                isinstance(deco, ast.Call)
                and isinstance(deco.func, ast.Attribute)
                and deco.func.attr == "tool"
            ):
                names.add(node.name)
                break
    return names


def test_yaml_matches_mcp_server_source():
    """tool_registry.yaml 全量工具 == mcp_server.py 真实注册.

    SPEC v2 §5.3: 加新工具忘了在 yaml 里加 entry, 或反过来 yaml 列了源码没注册的
    工具, CI 都拦. 这是 single source of truth 的硬契约.
    """
    yaml_tools = all_tool_names()
    src_tools = _extract_mcp_tool_names_from_source()

    only_yaml = yaml_tools - src_tools
    only_src = src_tools - yaml_tools

    msg_parts = []
    if only_yaml:
        msg_parts.append(
            f"yaml 列了但 mcp_server.py 没注册的工具: {sorted(only_yaml)} "
            f"(yaml 删 entry 或源码补 @mcp.tool() async def)"
        )
    if only_src:
        msg_parts.append(
            f"mcp_server.py 注册了但 yaml 缺 entry 的工具: {sorted(only_src)} "
            f"(请在 backend/tool_registry.yaml 加 entry)"
        )
    if msg_parts:
        pytest.fail("\n".join(msg_parts))


# ─────────────────────── 6. 完整性 sanity ───────────────────────


def test_all_tool_names_count_sensible():
    """总数 sanity check."""
    count = len(all_tool_names())
    assert 100 <= count <= 200, f"工具总数 {count} 不在 100-200 区间, 可能 yaml drift"


def test_each_section_has_some_tools():
    """每个 section (除特殊情况) 至少有几个工具 — 防 yaml 全归到 global."""
    for s in ("data", "ui", "logic", "permission", "extension"):
        direct_tools = [
            n for n, m in load()["tools"].items() if s in (m.get("sections") or [])
        ]
        assert len(direct_tools) >= 3, (
            f"section={s!r} 直接 affinity 工具只有 {len(direct_tools)} 个, "
            f"可能 yaml 分类太狭窄"
        )
