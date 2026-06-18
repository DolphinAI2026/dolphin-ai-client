"""
test_tool_registry.py — SPEC v2 PR1.

锁住三件事:
  1) yaml 能 load, schema 合法
  2) 每个工具有 sections / agents 字段, 取值合法
  3) tools_for_agent("config") 跟 PR1 之前的硬编码白名单 byte-equal (行为不变)
  4) tools_for_section() 软引导正确返回 affinity 工具
  5) tool_registry.yaml 全量工具 == MCP source files @mcp.tool() 真实注册 (无 drift)
"""
from __future__ import annotations

import ast
import re
from collections.abc import Mapping
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
# Expected ConfigAssistant whitelist — post-PR1+PR3 current state.
#
# **NOT** PR1-之前的硬编码 baseline (那个是 61 工具). 这个集合包含后续加入
# config agent 的工具, 所以总数会随 registry 同步更新。命名特意从 _OLD_* 改成 _EXPECTED_*, 防止
# 误读为 "PR1 落地前的 baseline" — round2-p2 reviewer #1 报的标签混淆.
#
# 测试用途: tool_registry.yaml 派生白名单必须 byte-equal 本集合 — 任何 yaml drift
# (新工具忘加 agent='config' / 老工具被误删) CI 拦.
# ─────────────────────────────────────────────────────
# N2(2026-06-01): 摘掉 codegen/自开发工具(15 个) — Builder 不做 codegen, 引导去 AI Coding.
# 摘掉: attach_dev_packages_to_apaas_app / create_apaas_self_dev_menu / create_dev_workspace /
#        edit_workspace_files / get_dev_workspace_status / glob_workspace / grep_workspace /
#        import_zip_to_workspace / list_dev_scenes / publish_dev_workspace / read_workspace_file /
#        republish_apaas_app / run_workspace_command / save_dev_spec / write_workspace_files
_EXPECTED_CONFIG_WHITELIST: frozenset[str] = frozenset({
    "add_apaas_dict_option",
    "add_apaas_model_field",
    "attach_dev_packages_to_apaas_app",
    "bind_apaas_form_field_to_dict",
    "build_apaas_feature_from_spec",
    "check_app_code_conflict",
    "compute_app_health",
    "create_apaas_app_dict",
    "create_apaas_app_roles",
    "create_apaas_business_event",
    "create_apaas_form_menu",
    "create_apaas_menu_group",
    "create_apaas_value_change_assignment_event",
    "create_form_event_with_python_code",
    "create_time_event_with_python_code",
    "delete_apaas_app_menu",
    "delete_apaas_app_role",
    "delete_apaas_business_event",
    "delete_config_skill",
    "deploy_process_to_apaas",
    "disable_apaas_app_dict",
    "disable_apaas_dict_option",
    "disable_apaas_model_field",
    "get_apaas_app_overview",
    "get_apaas_business_event_detail",
    "get_apaas_form_detail",
    "get_apaas_process_detail",
    "get_apaas_user_name",
    "get_config_skill",
    "get_dev_fix_policy",
    "get_role_resource_matrix",
    "list_apaas_app_dev_kits",
    "list_apaas_app_dicts",
    "list_apaas_app_menus",
    "list_apaas_app_models",
    "list_apaas_app_processes",
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
    "list_dev_workspaces",
    "list_product_issues",
    "query_apaas_business_event_trees",
    "repair_empty_apaas_form_from_model",
    "rename_apaas_menu",
    "republish_apaas_app",
    "record_product_issue",
    "record_support_triage",
    "save_apaas_business_event",
    "save_config_skill",
    "set_apaas_app_process",
    "set_apaas_process_transition_rules",
    "set_apaas_form_component_behavior",
    "set_apaas_form_component_default",
    "set_apaas_form_component_document_number_rules",
    "set_apaas_form_component_options",
    "set_apaas_form_component_style",
    "set_apaas_form_component_validation",
    "set_apaas_form_permissions",
    "set_apaas_menu_parent",
    "set_role_resource_permission",
    "update_apaas_app_dict",
    "update_apaas_app_info",
    "update_apaas_app_role",
    "update_apaas_dict_option",
    "update_apaas_form_component",
    "update_apaas_model_field",
    "upload_external_zip_to_apaas",
})


# ─────────────────────── 1. Load / schema ───────────────────────


def test_registry_loadable():
    """yaml 文件能 load, version=1, tools 非空."""
    r = load()
    assert r["version"] == 1, "version 必须是 1 (后续升级走 v2)"
    # PR1 round2-p2 #2: load() 返 MappingProxyType (read-only view) — 不是 dict
    # 但接受任意 Mapping 实现 (dict / MappingProxyType 都通).
    assert isinstance(r["tools"], Mapping)
    assert len(r["tools"]) > 100, f"工具数应远大于 100, 实际 {len(r['tools'])}"


def test_reload_clears_cache():
    """reload() 显式清缓存 — 用于测试 / 热替.

    PR1 reviewer #3 (round2-p2) 留: 这个测试只验 object identity,
    见下面 test_reload_actually_rereads_disk 验真 disk re-read.
    """
    r1 = load()
    r2 = reload()
    assert r1 is not r2, "reload 必须返回新 Mapping object"


def test_reload_actually_rereads_disk(monkeypatch, tmp_path):
    """PR1 round2-p2 #3: reload() 必须真 re-read disk, 不只是返新 object.

    老 test_reload_clears_cache 只验 `r1 is not r2` (object identity) — 这不足以
    证明 disk 真被 re-read. monkeypatch _YAML_PATH 指向临时 yaml, 改文件内容后
    reload() 应看到新内容. 老 test 保留作 sanity check.

    流程:
      1. 写一份只含 N 工具的临时 yaml
      2. monkeypatch _YAML_PATH 指过去 + reload() 让 cache 失效并读临时文件
      3. 改临时 yaml 增加一个工具
      4. load() 再调 — cache 命中, 应是 N (proves cache 有效)
      5. reload() — 应是 N+1 (proves 真 re-read disk)
    """
    import app.tool_registry as tr

    fake_yaml = tmp_path / "fake_tool_registry.yaml"
    base_yaml = """\
version: 1
tools:
  fake_tool_a:
    sections: [data]
    agents: [builder]
    category: introspection
    description: test fixture
  fake_tool_b:
    sections: [ui]
    agents: [config]
    category: ui
    description: test fixture
"""
    fake_yaml.write_text(base_yaml, encoding="utf-8")

    # 注入临时路径 + 清缓存让首次 load 读临时文件
    monkeypatch.setattr(tr, "_YAML_PATH", fake_yaml)
    try:
        first = tr.reload()
        assert set(first["tools"].keys()) == {"fake_tool_a", "fake_tool_b"}, (
            f"首次 reload 后应读到临时 yaml 2 工具, 实际 {sorted(first['tools'].keys())}"
        )

        # 改 disk 加一条 — 但不 reload, cache 应仍是 2 工具
        fake_yaml.write_text(
            base_yaml + """\
  fake_tool_c:
    sections: [logic]
    agents: [config]
    category: event
    description: added after first load
""",
            encoding="utf-8",
        )
        cached = tr.load()
        assert set(cached["tools"].keys()) == {"fake_tool_a", "fake_tool_b"}, (
            "load() cache 命中应仍返老 2 工具 (proves cache 生效)"
        )

        # reload — 应看到 3 工具 (proves 真 re-read disk)
        fresh = tr.reload()
        assert set(fresh["tools"].keys()) == {"fake_tool_a", "fake_tool_b", "fake_tool_c"}, (
            f"reload() 后应 re-read disk 看到 3 工具, 实际 {sorted(fresh['tools'].keys())}"
        )
    finally:
        # 退出前再清一次, 避免后续测试用到 cache 里临时 yaml 数据
        tr.load.cache_clear()


def test_load_returns_readonly_view():
    """PR1 round2-p2 #2: load() 返 MappingProxyType — 调用方 mutate 必须 raise TypeError.

    历史教训: 老 dict 返回让调用方一次手贱写 `load()['tools']['__hacker__'] = ...`
    就污染整个进程 lru_cache, 后续所有读到的工具集都带这条脏数据 + 难复现.
    """
    r = load()

    # 顶层 immutable
    with pytest.raises(TypeError):
        r["version"] = 999  # type: ignore[index]
    with pytest.raises(TypeError):
        r["new_field"] = "x"  # type: ignore[index]
    with pytest.raises(TypeError):
        del r["version"]  # type: ignore[arg-type]

    # 二级 (tools 字典本身) immutable — 这是最重要那层
    with pytest.raises(TypeError):
        r["tools"]["__hacker__"] = {  # type: ignore[index]
            "sections": ["data"],
            "agents": ["builder"],
        }
    with pytest.raises(TypeError):
        del r["tools"]["list_apaas_apps_in_env"]  # type: ignore[arg-type]


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


def test_config_whitelist_matches_current_expected():
    """tool_registry.yaml 派生的 config 白名单 == 当前期望集合。"""
    new = set(tools_for_agent("config"))
    diff = new ^ _EXPECTED_CONFIG_WHITELIST
    assert not diff, (
        f"配置助手白名单 diff = {len(diff)} 个 (yaml drift vs expected snapshot!)\n"
        f"  only in yaml (registered): {sorted(new - _EXPECTED_CONFIG_WHITELIST)}\n"
        f"  only in expected (yaml 漏): {sorted(_EXPECTED_CONFIG_WHITELIST - new)}"
    )
    # N2(2026-06-01): 82 → 67，摘掉 15 个 codegen/workspace 工具
    # 2026-06-03: +4 自开发工具(upload_external_zip / republish / list_dev_kits / attach)进 config → 71
    # 2026-06-04: +1 空表单修复工具 → 72
    # 2026-06-05+: 问题助手 / 自开发等后续工具累计后现状 → 76
    # 2026-06-09: +1 平台用户名称反查工具 → 77
    # 2026-06-11: +6 表单组件结构化调整工具 → 83
    # 2026-06-12: +1 已有流程连线规则调整工具 → 84
    # 2026-06-12: +1 自开发 workspace 反查工具 → 85
    # 2026-06-12: -11 退役 browser_* / Chrome extension POC → 74
    # 2026-06-16: +1 应用健康体检引擎 compute_app_health (46a53beb 注册漏同步快照) → 75
    assert len(new) == 75, f"config 白名单总数应是 75, 实际 {len(new)}"


def test_builder_whitelist_count():
    """builder 白名单非空 (锁数量, 防止误删)."""
    # 现状 46 工具 (prompt 文档写 "37" stale, 实际 list 46)
    tools = tools_for_agent("builder")
    assert len(tools) >= 40, f"builder 白名单 >= 40, 实际 {len(tools)}"


def test_coding_whitelist_count():
    """coding 白名单 >= 35 (锁数量)."""
    tools = tools_for_agent("coding")
    assert len(tools) >= 35, f"coding 白名单 >= 35, 实际 {len(tools)}"


# ─────────────────────── 4. Section affinity ───────────────────────


def test_section_filter_ui_includes_build_feature():
    """ui section 软引导应含 build_apaas_feature_from_spec."""
    ui_tools = set(tools_for_section("ui"))
    assert "build_apaas_feature_from_spec" in ui_tools


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
    assert "set_apaas_process_transition_rules" in logic_tools


def test_section_filter_permission_includes_role():
    """permission section 软引导应含角色工具."""
    perm_tools = set(tools_for_section("permission"))
    assert "create_apaas_app_roles" in perm_tools
    assert "set_apaas_form_permissions" in perm_tools


def test_section_filter_extension_includes_workspace():
    """extension section 软引导应含 workspace / dev_scene 工具."""
    ext_tools = set(tools_for_section("extension"))
    assert "create_dev_workspace" in ext_tools
    assert "list_dev_workspaces" in ext_tools
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


# ─────────────────────── 5. Drift detection — yaml vs MCP source files ───────────────────────


def _mcp_source_paths() -> list[Path]:
    app_dir = Path(__file__).parent.parent / "app"
    tool_dir = app_dir / "mcp_tools"
    paths = [app_dir / "mcp_server.py"]
    if tool_dir.exists():
        paths.extend(sorted(p for p in tool_dir.glob("*.py") if p.name != "__init__.py"))
    return paths


def _is_mcp_tool_decorator(deco: ast.expr) -> bool:
    # @mcp.tool() 或 @mcp.tool(description="...")
    return (
        isinstance(deco, ast.Call)
        and isinstance(deco.func, ast.Attribute)
        and deco.func.attr == "tool"
    )


def _extract_mcp_tool_names_from_source() -> set[str]:
    """从 backend/app/mcp_server.py 与 app/mcp_tools/*.py AST 提取 @mcp.tool() 函数名."""
    names: set[str] = set()
    for mcp_path in _mcp_source_paths():
        src = mcp_path.read_text(encoding="utf-8")
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if not isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef)):
                continue
            if any(_is_mcp_tool_decorator(deco) for deco in node.decorator_list):
                names.add(node.name)
    return names


def test_yaml_matches_mcp_server_source():
    """tool_registry.yaml 全量工具 == MCP source files 真实注册.

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
            f"yaml 列了但 MCP source files 没注册的工具: {sorted(only_yaml)} "
            f"(yaml 删 entry 或源码补 @mcp.tool() async def)"
        )
    if only_src:
        msg_parts.append(
            f"MCP source files 注册了但 yaml 缺 entry 的工具: {sorted(only_src)} "
            f"(请在 backend/tool_registry.yaml 加 entry)"
        )
    if msg_parts:
        pytest.fail("\n".join(msg_parts))


# ─────────────────────── 5b. Runtime drift detection (mcp_server.py) ───────────────────────


def test_runtime_drift_check_passes_in_clean_state(caplog):
    """启动时 yaml ↔ FastMCP 实际注册工具集应一致 (无 drift, 不出 warning).

    PR1 reviewer #4 round2-p2: 静态 AST 对比 (test_yaml_matches_mcp_server_source)
    管不到 runtime 真注册情况, drift check 跑 mcp._tool_manager.list_tools() 才准.
    """
    import logging
    from app.mcp_server import _assert_yaml_vs_registered_tools

    with caplog.at_level(logging.WARNING, logger="app.mcp_server"):
        only_yaml, only_registered = _assert_yaml_vs_registered_tools()

    assert not only_yaml, f"yaml 多余工具 (FastMCP 未注册): {sorted(only_yaml)}"
    assert not only_registered, (
        f"FastMCP 注册了但 yaml 缺 entry: {sorted(only_registered)}"
    )
    # 没 drift 时不应有 WARNING level 日志
    drift_warnings = [
        r for r in caplog.records
        if r.levelname == "WARNING" and "tool-registry drift" in r.message
    ]
    assert not drift_warnings, (
        f"无 drift 时不应 warning, 实际 {len(drift_warnings)} 条: "
        f"{[r.message for r in drift_warnings]}"
    )


def test_runtime_drift_check_warns_when_yaml_has_extra(monkeypatch, caplog):
    """模拟 yaml 多列了一条 FastMCP 没注册的工具 → 应 log warning."""
    import logging
    import app.tool_registry as tr
    from app import mcp_server

    real_names = tr.all_tool_names()
    fake_names = real_names | {"__fake_ghost_tool_only_in_yaml__"}
    monkeypatch.setattr(mcp_server, "_yaml_tool_names", lambda: fake_names, raising=False)
    # 直接 monkeypatch tr.all_tool_names 让 mcp_server 内 import 后调用读到 fake
    monkeypatch.setattr(tr, "all_tool_names", lambda: fake_names)

    with caplog.at_level(logging.WARNING, logger="app.mcp_server"):
        only_yaml, only_registered = mcp_server._assert_yaml_vs_registered_tools()

    assert "__fake_ghost_tool_only_in_yaml__" in only_yaml
    assert not only_registered
    drift_warnings = [
        r for r in caplog.records
        if r.levelname == "WARNING" and "yaml 列了但 FastMCP 未注册" in r.message
    ]
    assert len(drift_warnings) == 1, (
        f"应 log 1 条 yaml-only warning, 实际 {len(drift_warnings)}"
    )


def test_runtime_drift_check_warns_when_registered_has_extra(monkeypatch, caplog):
    """模拟 yaml 漏一条 FastMCP 已注册工具 → 应 log warning."""
    import logging
    import app.tool_registry as tr
    from app import mcp_server

    real_names = tr.all_tool_names()
    # 拿一个真实注册的工具名, 从 yaml fake 集合里删
    sample_tool = next(iter(real_names))
    fake_names = real_names - {sample_tool}
    monkeypatch.setattr(tr, "all_tool_names", lambda: fake_names)

    with caplog.at_level(logging.WARNING, logger="app.mcp_server"):
        only_yaml, only_registered = mcp_server._assert_yaml_vs_registered_tools()

    assert not only_yaml
    assert sample_tool in only_registered
    drift_warnings = [
        r for r in caplog.records
        if r.levelname == "WARNING" and "FastMCP 注册了但 yaml 缺 entry" in r.message
    ]
    assert len(drift_warnings) == 1, (
        f"应 log 1 条 registered-only warning, 实际 {len(drift_warnings)}"
    )


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
