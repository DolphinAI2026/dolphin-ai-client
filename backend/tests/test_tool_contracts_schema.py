"""
test_tool_contracts_schema.py — Phase 2C 工具副作用契约验证.

验证:
  a) 每个 yaml 工具都能解析出完整契约(派生或显式)
  b) 代表性工具契约字段正确
     - 至少 1 个 read_only(introspection)
     - 至少 1 个 writes_apaas(create/update)
     - 至少 1 个 deploys_or_publishes + requires_confirmation(deploy 类)
  c) deploys_or_publishes 蕴含 requires_confirmation 铁律对全工具成立
  d) yaml 显式副作用字段类型合法(bool)
  e) read_only=True 时写副作用字段必须为 False
"""
from __future__ import annotations

import pytest

from app.tool_registry import load, all_tool_names
from app.services.tool_contract_service import (
    SIDE_EFFECT_FIELDS,
    all_contracts,
    contracts_by_flag,
    is_read_only,
    requires_confirmation,
    tool_contract,
    clear_cache,
)


# ─────────────────────── 辅助 ───────────────────────

def _all_tool_metas() -> dict:
    return dict(load()["tools"])


# ─────────────────────── a) 全量解析 ───────────────────────


def test_all_tools_parse_to_complete_contract():
    """每个 yaml 工具都能解析出含全部5字段的契约, 不抛异常."""
    required_fields = {
        "name", "category",
        "read_only", "writes_workspace", "writes_apaas",
        "deploys_or_publishes", "requires_confirmation",
    }
    names = all_tool_names()
    assert names, "工具集不能为空"

    for name in names:
        contract = tool_contract(name)
        missing = required_fields - set(contract.keys())
        assert not missing, f"{name} 契约缺字段: {sorted(missing)}"


def test_contract_fields_are_bool():
    """契约所有副作用字段必须是 bool 类型."""
    bool_fields = {
        "read_only", "writes_workspace", "writes_apaas",
        "deploys_or_publishes", "requires_confirmation",
    }
    for name, c in all_contracts().items():
        for field in bool_fields:
            assert isinstance(c[field], bool), (
                f"{name}.{field} 应是 bool, 实际 {type(c[field]).__name__!r}"
            )


def test_contract_name_matches_key():
    """契约 name 字段与工具名键一致."""
    for name, c in all_contracts().items():
        assert c["name"] == name, f"契约 name={c['name']!r} 与工具键 {name!r} 不符"


def test_all_tools_queryable_via_service():
    """通过 tool_contract() 查每个工具不抛异常."""
    for name in all_tool_names():
        contract = tool_contract(name)  # should not raise
        assert contract["name"] == name


def test_unknown_tool_raises_key_error():
    """tool_contract 传不存在工具名应抛 KeyError."""
    with pytest.raises(KeyError):
        tool_contract("__nonexistent_ghost_tool__")


# ─────────────────────── b) 代表性工具契约正确性 ───────────────────────


def test_introspection_tool_is_read_only():
    """introspection 类工具 read_only=True (示例: list_apaas_app_models)."""
    c = tool_contract("list_apaas_app_models")
    assert c["read_only"] is True, f"list_apaas_app_models 应 read_only, 实际 {c}"
    assert c["writes_apaas"] is False
    assert c["writes_workspace"] is False
    assert c["deploys_or_publishes"] is False
    assert c["requires_confirmation"] is False


def test_get_application_is_read_only():
    """get_application(introspection) 应 read_only=True."""
    c = tool_contract("get_application")
    assert c["read_only"] is True


def test_list_apaas_apps_is_read_only():
    """list_apaas_apps_in_env(introspection) 应 read_only=True."""
    c = tool_contract("list_apaas_apps_in_env")
    assert c["read_only"] is True


def test_create_tool_writes_apaas():
    """create 类工具 writes_apaas=True (示例: create_apaas_app_dict)."""
    c = tool_contract("create_apaas_app_dict")
    assert c["read_only"] is False
    assert c["writes_apaas"] is True, f"create_apaas_app_dict 应 writes_apaas, 实际 {c}"
    assert c["deploys_or_publishes"] is False


def test_update_tool_writes_apaas():
    """update 类工具 writes_apaas=True (示例: update_apaas_model_field)."""
    c = tool_contract("update_apaas_model_field")
    assert c["read_only"] is False
    assert c["writes_apaas"] is True


def test_delete_tool_writes_apaas():
    """delete 类工具 writes_apaas=True (示例: delete_apaas_app_menu)."""
    c = tool_contract("delete_apaas_app_menu")
    assert c["read_only"] is False
    assert c["writes_apaas"] is True


def test_deploy_application_is_deploy_and_requires_confirmation():
    """deploy_application: deploys_or_publishes=True + requires_confirmation=True."""
    c = tool_contract("deploy_application")
    assert c["deploys_or_publishes"] is True, f"deploy_application 应 deploys_or_publishes, 实际 {c}"
    assert c["requires_confirmation"] is True, f"deploy_application 应 requires_confirmation, 实际 {c}"
    assert c["writes_apaas"] is True  # lifecycle default + explicit deploy


def test_publish_application_is_deploy_and_requires_confirmation():
    """publish_application: deploys_or_publishes=True + requires_confirmation=True."""
    c = tool_contract("publish_application")
    assert c["deploys_or_publishes"] is True
    assert c["requires_confirmation"] is True


def test_republish_apaas_app_requires_confirmation():
    """republish_apaas_app: deploys_or_publishes=True + requires_confirmation=True (契约文档重点工具)."""
    c = tool_contract("republish_apaas_app")
    assert c["deploys_or_publishes"] is True, f"republish_apaas_app 应 deploys_or_publishes, 实际 {c}"
    assert c["requires_confirmation"] is True, f"republish_apaas_app 应 requires_confirmation, 实际 {c}"


def test_rollback_application_requires_confirmation():
    """rollback_application: deploys_or_publishes=True + requires_confirmation=True."""
    c = tool_contract("rollback_application")
    assert c["deploys_or_publishes"] is True
    assert c["requires_confirmation"] is True


def test_publish_dev_workspace_requires_confirmation():
    """publish_dev_workspace(dev_workspace): deploys_or_publishes=True + requires_confirmation=True."""
    c = tool_contract("publish_dev_workspace")
    assert c["deploys_or_publishes"] is True
    assert c["requires_confirmation"] is True
    assert c["writes_workspace"] is True


def test_upload_external_zip_requires_confirmation():
    """upload_external_zip_to_apaas: deploys_or_publishes=True + requires_confirmation=True."""
    c = tool_contract("upload_external_zip_to_apaas")
    assert c["deploys_or_publishes"] is True
    assert c["requires_confirmation"] is True


def test_deploy_process_requires_confirmation():
    """deploy_process_to_apaas: deploys_or_publishes=True + requires_confirmation=True."""
    c = tool_contract("deploy_process_to_apaas")
    assert c["deploys_or_publishes"] is True
    assert c["requires_confirmation"] is True


def test_generate_app_from_doc_is_deploy():
    """generate_app_from_doc(doc_pipeline): writes_apaas=True + deploys_or_publishes=True."""
    c = tool_contract("generate_app_from_doc")
    assert c["writes_apaas"] is True
    assert c["deploys_or_publishes"] is True
    assert c["requires_confirmation"] is True


# ─────────────────────── b) dev_workspace 工具契约 ───────────────────────


def test_workspace_write_tools_have_writes_workspace():
    """writes_workspace 类工作区写工具 (示例: write_workspace_files, edit_workspace_files)."""
    for tool_name in ("write_workspace_files", "edit_workspace_files", "init_apaas_backend_workspace"):
        c = tool_contract(tool_name)
        assert c["writes_workspace"] is True, f"{tool_name} 应 writes_workspace, 实际 {c}"
        assert c["read_only"] is False


def test_workspace_read_tools_are_read_only():
    """工作区只读工具应 read_only=True (glob/grep/read)."""
    for tool_name in ("glob_workspace", "grep_workspace", "read_workspace_file",
                      "get_dev_workspace_status", "lint_apaas_backend_workspace",
                      "doctor_apaas_backend_workspace"):
        c = tool_contract(tool_name)
        assert c["read_only"] is True, f"{tool_name} 应 read_only, 实际 {c}"


def test_list_dev_workspaces_read_only():
    """list_dev_workspaces 应 read_only=True."""
    c = tool_contract("list_dev_workspaces")
    assert c["read_only"] is True


# ─────────────────────── b) business_event 契约 ───────────────────────


def test_business_event_read_tools_are_read_only():
    """business_event 类读工具: list/get 操作应 read_only=True."""
    read_tools = (
        "list_apaas_business_events",
        "list_apaas_business_events_in_tenant",
        "list_apaas_business_event_execution_history",
        "get_apaas_business_event_detail",
        "query_apaas_business_event_trees",
    )
    for name in read_tools:
        c = tool_contract(name)
        assert c["read_only"] is True, f"{name} 应 read_only, 实际 {c}"


def test_business_event_write_tools_write_apaas():
    """business_event 类写工具: create/save/delete 应 writes_apaas=True."""
    write_tools = (
        "create_apaas_business_event",
        "create_apaas_value_change_assignment_event",
        "create_form_event_with_python_code",
        "create_time_event_with_python_code",
        "save_apaas_business_event",
        "delete_apaas_business_event",
    )
    for name in write_tools:
        c = tool_contract(name)
        assert c["writes_apaas"] is True, f"{name} 应 writes_apaas, 实际 {c}"
        assert c["read_only"] is False


# ─────────────────────── b) other 类工具覆盖 ───────────────────────


def test_check_app_code_conflict_is_read_only():
    """check_app_code_conflict(other) 显式覆盖 read_only=True."""
    c = tool_contract("check_app_code_conflict")
    assert c["read_only"] is True


def test_query_apaas_business_data_is_read_only():
    """query_apaas_business_data(other) 应 read_only=True."""
    c = tool_contract("query_apaas_business_data")
    assert c["read_only"] is True


def test_other_write_tools_have_writes_apaas():
    """other 类写工具 (attach/bind/build/rename/enable) 应 writes_apaas=True."""
    for name in (
        "attach_dev_packages_to_apaas_app",
        "bind_apaas_form_field_to_dict",
        "build_apaas_feature_from_spec",
        "rename_apaas_menu",
        "enable_apaas_self_dev_config",
    ):
        c = tool_contract(name)
        assert c["writes_apaas"] is True, f"{name} 应 writes_apaas, 实际 {c}"


# ─────────────────────── b) doc_pipeline 契约 ───────────────────────


def test_doc_pipeline_read_tools_are_read_only():
    """doc_pipeline 类纯读工具应 read_only=True."""
    for name in (
        "parse_design_doc",
        "get_apaas_doc_template_spec",
        "validate_apaas_builder_doc",
        "validate_builder_doc",
        "get_change_plan",
    ):
        c = tool_contract(name)
        assert c["read_only"] is True, f"{name} 应 read_only, 实际 {c}"


def test_execute_change_plan_writes_apaas():
    """execute_change_plan(doc_pipeline) 显式覆盖 writes_apaas=True."""
    c = tool_contract("execute_change_plan")
    assert c["writes_apaas"] is True
    assert c["read_only"] is False


# ─────────────────────── b) lifecycle 工具 ───────────────────────


def test_list_deploy_records_is_read_only():
    """list_deploy_records(lifecycle) 显式覆盖 read_only=True."""
    c = tool_contract("list_deploy_records")
    assert c["read_only"] is True


# ─────────────────────── c) 铁律: deploys → requires_confirmation ───────────────────────


def test_deploys_implies_requires_confirmation_for_all_tools():
    """铁律: 全量工具中 deploys_or_publishes=True → requires_confirmation=True 必须成立."""
    violations = []
    for name, c in all_contracts().items():
        if c["deploys_or_publishes"] and not c["requires_confirmation"]:
            violations.append(name)
    assert not violations, (
        f"铁律违反: 以下工具 deploys_or_publishes=True 但 requires_confirmation=False: "
        f"{sorted(violations)}"
    )


def test_read_only_implies_no_write_side_effects():
    """语义一致性: read_only=True → 所有写副作用字段为 False."""
    violations = []
    for name, c in all_contracts().items():
        if c["read_only"]:
            if c["writes_workspace"] or c["writes_apaas"] or c["deploys_or_publishes"]:
                violations.append(name)
    assert not violations, (
        f"语义矛盾: 以下工具 read_only=True 但含写副作用字段: {sorted(violations)}"
    )


def test_read_only_implies_no_requires_confirmation():
    """read_only=True → requires_confirmation=False (只读无需确认)."""
    violations = []
    for name, c in all_contracts().items():
        if c["read_only"] and c["requires_confirmation"]:
            violations.append(name)
    assert not violations, (
        f"语义矛盾: 以下工具 read_only=True 但 requires_confirmation=True: {sorted(violations)}"
    )


# ─────────────────────── d) yaml 显式副作用字段类型校验 ───────────────────────


def test_yaml_explicit_side_effect_fields_are_bool():
    """yaml 中显式设置的副作用字段必须是 bool 类型(非字符串'true'/'false')."""
    for name, meta in _all_tool_metas().items():
        for field in SIDE_EFFECT_FIELDS:
            if field in meta:
                assert isinstance(meta[field], bool), (
                    f"{name}.{field} yaml 显式值应是 bool, "
                    f"实际 {type(meta[field]).__name__!r}: {meta[field]!r}"
                )


# ─────────────────────── contracts_by_flag 辅助 API ───────────────────────


def test_contracts_by_flag_read_only():
    """contracts_by_flag(read_only=True) 应返回非空工具列表, 且全部 read_only."""
    read_tools = contracts_by_flag(read_only=True)
    assert len(read_tools) >= 10, f"read_only 工具应至少 10 个, 实际 {len(read_tools)}"
    for name in read_tools:
        assert is_read_only(name), f"{name} 在 read_only 列表但 is_read_only() 返 False"


def test_contracts_by_flag_deploys():
    """contracts_by_flag(deploys_or_publishes=True) 应包含已知发布工具."""
    deploy_tools = set(contracts_by_flag(deploys_or_publishes=True))
    expected = {
        "deploy_application",
        "publish_application",
        "republish_apaas_app",
        "rollback_application",
        "publish_dev_workspace",
        "upload_external_zip_to_apaas",
        "deploy_process_to_apaas",
        "generate_app_from_doc",
    }
    missing = expected - deploy_tools
    assert not missing, f"以下发布工具未在 deploys_or_publishes=True 列表中: {sorted(missing)}"


def test_contracts_by_flag_requires_confirmation_matches_deploys():
    """requires_confirmation=True 的工具集 ⊇ deploys_or_publishes=True 的工具集."""
    confirm_set = set(contracts_by_flag(requires_confirmation=True))
    deploy_set = set(contracts_by_flag(deploys_or_publishes=True))
    missing = deploy_set - confirm_set
    assert not missing, f"deploys 工具应在 requires_confirmation 列表中, 缺失: {sorted(missing)}"


def test_contracts_by_flag_writes_workspace():
    """contracts_by_flag(writes_workspace=True) 包含已知工作区写工具."""
    ws_write = set(contracts_by_flag(writes_workspace=True))
    expected = {
        "create_dev_workspace",
        "edit_workspace_files",
        "write_workspace_files",
        "init_apaas_backend_workspace",
        "run_workspace_command",
        "save_dev_spec",
        "publish_dev_workspace",
    }
    missing = expected - ws_write
    assert not missing, f"以下工作区写工具未在 writes_workspace=True 列表: {sorted(missing)}"


# ─────────────────────── service API 快捷方法 ───────────────────────


def test_requires_confirmation_shortcut():
    """requires_confirmation() 快捷方法与 tool_contract()['requires_confirmation'] 一致."""
    for name in ("deploy_application", "list_apaas_app_models", "republish_apaas_app"):
        expected = tool_contract(name)["requires_confirmation"]
        assert requires_confirmation(name) == expected, (
            f"{name}: requires_confirmation() 快捷方法结果不一致"
        )


def test_is_read_only_shortcut():
    """is_read_only() 快捷方法与 tool_contract()['read_only'] 一致."""
    for name in ("get_application", "create_apaas_app_dict", "deploy_application"):
        expected = tool_contract(name)["read_only"]
        assert is_read_only(name) == expected, (
            f"{name}: is_read_only() 快捷方法结果不一致"
        )


def test_skill_learning_category_profile():
    """skill_learning 工具: read_only=False, 无写 apaas/workspace/deploy."""
    c = tool_contract("list_config_skills")  # list is read → introspection? No, skill_learning category
    # Actually list_config_skills category is skill_learning, but list operations...
    # Let's test save_config_skill which clearly writes
    c = tool_contract("save_config_skill")
    assert c["read_only"] is False
    assert c["writes_apaas"] is False
    assert c["writes_workspace"] is False
    assert c["deploys_or_publishes"] is False


def test_all_contracts_returns_all_tools():
    """all_contracts() 应包含 yaml 全量工具."""
    contracts = all_contracts()
    yaml_names = all_tool_names()
    assert set(contracts.keys()) == yaml_names, (
        f"all_contracts() 工具数 {len(contracts)} 与 yaml 工具数 {len(yaml_names)} 不符"
    )
