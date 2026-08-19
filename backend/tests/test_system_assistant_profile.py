"""P0 system-assistant profile selection and tool boundary tests."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.agents.profile import (
    narrow_tools_for_locked_ws,
    resolve_overrides_for_session,
    resolve_profile,
    ws_bind_view_context,
)
from app.mcp_tools.system_assets import SYSTEM_ASSET_TOOL_NAMES
from app.ai_chat import tools as chat_tools
from app.ai_chat.agent import (
    _SYSTEM_ASSISTANT_INTRO_RESPONSE,
    _apply_session_overrides,
    _is_system_assistant_intro_request,
    _session_app_context_id,
)


def test_system_assistant_profile_exposes_system_asset_read_and_use_capabilities():
    profile = resolve_profile("system_assistant")
    tools = set(profile.tool_names)

    assert profile.name == "system_assistant"
    assert "read_attachment" in tools
    assert "write_artifact" in tools
    assert "run_python" in tools
    assert "search_tools" in tools
    assert SYSTEM_ASSET_TOOL_NAMES.issubset(tools)

    # System assets must be queried through the remote Builder AI Control Plane
    # MCP tools, never through the sidecar's local cache/skill directory.
    for local_query in (
        "use_skill", "read_knowledge", "search_knowledge", "list_skills", "read_skill_file",
    ):
        assert local_query not in tools

    for forbidden_local in ("write_file", "edit_file", "run_command", "start_serve"):
        assert forbidden_local not in tools

    for forbidden in (
        "generate_app_from_doc",
        "update_app_from_doc",
        "deploy_application",
        "publish_application",
        "publish_dev_workspace",
        "upload_external_zip_to_apaas",
        "create_apaas_app_dict",
        "set_apaas_form_permissions",
        "delete_config_skill",
        "save_config_skill",
        "create_skill",
        "write_skill_file",
        "update_skill_metadata",
        "list_dev_workspaces",
        "create_dev_workspace",
        "init_apaas_backend_workspace",
        "doctor_apaas_backend_workspace",
        "lint_apaas_backend_workspace",
        "list_dev_scenes",
        "get_dev_scene_spec",
        "get_dev_scene_full_workflow",
        "get_application",
        "list_my_applications",
        "list_platform_envs",
        "get_apaas_app_overview",
        "list_apaas_apps_in_env",
        "list_apaas_app_models",
        "list_apaas_app_menus",
        "list_apaas_app_roles",
        "list_apaas_form_permissions",
        "compute_app_health",
        "read_workspace_file",
        "write_workspace_files",
        "edit_workspace_files",
        "run_workspace_command",
        "glob_workspace",
        "grep_workspace",
        "get_dev_workspace_status",
    ):
        assert forbidden not in tools


@pytest.mark.asyncio
async def test_system_asset_tools_are_not_added_to_normal_tool_pool(monkeypatch):
    async def fake_mcp_schemas():
        return [
            {"type": "function", "function": {"name": "get_application"}},
            {"type": "function", "function": {"name": "list_system_assets"}},
        ]

    monkeypatch.setattr("app.ai_chat.mcp_bridge.get_tool_schemas_openai", fake_mcp_schemas)
    schemas = await chat_tools.get_all_tool_schemas()
    names = {schema.get("function", {}).get("name") for schema in schemas}

    assert "get_application" in names
    assert not (SYSTEM_ASSET_TOOL_NAMES & names)

    system_schemas = await chat_tools.get_system_asset_tool_schemas()
    assert [schema["function"]["name"] for schema in system_schemas] == ["list_system_assets"]


def test_system_assistant_prompt_targets_system_level_code_assets():
    prompt = resolve_profile("system_assistant").system_prompt
    normalized = prompt.lower()

    assert "系统级资产、标准与能力基线" in prompt
    assert "种子工程" in prompt
    assert "知识和 Skill" in prompt
    assert "具体应用工程里的日常开发助手" in prompt
    assert "修复某个应用的 bug" in prompt
    assert "对应应用的 Code 会话" in prompt
    assert "不发现、枚举、猜测、绑定或创建工作区" in prompt
    assert "不沿用历史会话中的工程身份" in prompt
    assert 'asset_type="mcp_server"' in prompt
    assert "不是 MCP 服务资产查询" in prompt
    assert "get_system_asset_schema" in prompt
    assert "get_system_assistant_mcp_contract" in prompt
    assert "allowed_values" in prompt
    assert "environmentInstanceSchema" in prompt
    assert "applicationEnvironmentInstanceSchema" in prompt
    assert "绝不能杜撰 `environment:` 段" in prompt
    assert "credentialRef / resolverRef" in prompt
    assert "create_system_capability_git_repository" in prompt
    assert "list_system_deployment_environments" in prompt
    assert "list_environment_infrastructure_schemas" in prompt
    assert "get_system_asset_creation_examples" in prompt
    assert "严禁复制其 Git 项目 ID" in prompt
    assert "create_system_asset_starter_repository" in prompt
    assert "reference_rules" in prompt
    assert "参考仓库 → 文件名 → 可复用规则" in prompt
    assert "Dolphin Code" in prompt
    assert "apaas" not in normalized
    assert "builder" not in normalized
    assert "form-page" not in normalized


def test_system_assistant_intro_reports_four_compact_real_capability_directions():
    numbered_directions = [
        line for line in _SYSTEM_ASSISTANT_INTRO_RESPONSE.splitlines()
        if line[:2] in {"1.", "2.", "3.", "4.", "5."}
    ]

    assert len(numbered_directions) == 4
    assert "系统级资产和标准能力建设" in _SYSTEM_ASSISTANT_INTRO_RESPONSE
    assert "种子工程" in _SYSTEM_ASSISTANT_INTRO_RESPONSE
    assert "知识与 Skill" in _SYSTEM_ASSISTANT_INTRO_RESPONSE
    assert "系统资产工作区" in _SYSTEM_ASSISTANT_INTRO_RESPONSE
    assert "对应应用的 Code 会话" in _SYSTEM_ASSISTANT_INTRO_RESPONSE
    assert "修 bug、写接口、改页面" in _SYSTEM_ASSISTANT_INTRO_RESPONSE
    assert "apaas" not in _SYSTEM_ASSISTANT_INTRO_RESPONSE.lower()
    assert "builder" not in _SYSTEM_ASSISTANT_INTRO_RESPONSE.lower()


def test_system_assistant_profile_does_not_require_a_bound_workspace():
    prompt, tools, locked_ws_id = resolve_overrides_for_session(
        SimpleNamespace(mode="chat", assistant_profile="system_assistant")
    )

    assert prompt == resolve_profile("system_assistant").system_prompt
    assert tools
    assert "read_attachment" in tools
    assert "write_artifact" in tools
    assert "list_system_assets" in tools
    assert "use_skill" not in tools
    assert "search_knowledge" not in tools
    assert "read_workspace_file" not in tools
    assert "write_workspace_files" not in tools
    assert "run_workspace_command" not in tools
    assert "list_dev_workspaces" not in tools
    assert "create_dev_workspace" not in tools
    assert locked_ws_id is None


@pytest.mark.parametrize("text", ["你好", "你能做什么？", "介绍一下自己"])
def test_system_assistant_intro_requests_use_the_bounded_reply(text: str):
    session = SimpleNamespace(assistant_profile="system_assistant")

    assert _is_system_assistant_intro_request(session, text) is True


def test_concrete_system_assistant_work_does_not_use_the_intro_reply():
    session = SimpleNamespace(assistant_profile="system_assistant")

    assert _is_system_assistant_intro_request(session, "帮我检查并修复当前工程的构建问题") is False


def test_builder_session_does_not_use_the_system_assistant_intro_reply():
    session = SimpleNamespace(assistant_profile="entry_agent")

    assert _is_system_assistant_intro_request(session, "你能做什么") is False


def test_system_assistant_code_session_locks_bound_workspace_and_context():
    session = SimpleNamespace(
        mode="code", assistant_profile="system_assistant", workspace_id="ws-system"
    )

    prompt, tools, locked_ws_id = resolve_overrides_for_session(session)
    profile = resolve_profile("system_assistant")

    assert prompt == profile.system_prompt
    assert set(profile.tool_names).issubset(tools)
    assert "list_dev_workspaces" not in tools
    assert "create_dev_workspace" not in tools
    assert "read_workspace_file" in tools
    assert "write_workspace_files" in tools
    assert "run_workspace_command" in tools
    assert locked_ws_id == "ws-system"
    assert "ws-system" in (ws_bind_view_context(locked_ws_id) or "")

    applied_prompt, applied_tools, view_context = _apply_session_overrides(session, None, None)
    assert applied_prompt == prompt
    assert applied_tools == tools
    assert getattr(session, "_locked_ws_id", None) == "ws-system"
    assert "ws-system" in (view_context or "")


def test_system_assistant_code_session_without_workspace_stays_session_scoped():
    session = SimpleNamespace(
        mode="code", assistant_profile="system_assistant", workspace_id=None
    )

    _prompt, tools, locked_ws_id = resolve_overrides_for_session(session)
    assert "read_attachment" in tools
    assert "write_artifact" in tools
    assert "read_workspace_file" not in tools
    assert "write_workspace_files" not in tools
    assert "run_workspace_command" not in tools
    assert "list_dev_workspaces" not in tools
    assert "create_dev_workspace" not in tools
    assert locked_ws_id is None
    assert ws_bind_view_context(locked_ws_id) is None


def test_system_assistant_never_inherits_application_context():
    session = SimpleNamespace(assistant_profile="system_assistant", app_id=99)

    assert _session_app_context_id(session) is None


def test_entry_agent_keeps_application_context():
    session = SimpleNamespace(assistant_profile="entry_agent", app_id=99)

    assert _session_app_context_id(session) == 99


def test_entry_agent_code_mode_keeps_existing_dev_apaas_resolution():
    session = SimpleNamespace(mode="code", assistant_profile="entry_agent", workspace_id="ws-1")

    prompt, tools, locked_ws_id = resolve_overrides_for_session(session)

    legacy = resolve_profile("dev-apaas")
    assert prompt == legacy.system_prompt
    assert tools == set(narrow_tools_for_locked_ws(legacy.tool_names, "ws-1"))
    assert locked_ws_id == "ws-1"


def test_resolve_profile_rejects_unknown_session_profile_even_in_code_mode():
    session = SimpleNamespace(
        mode="code", assistant_profile="system_assistant_v2", workspace_id="ws-1"
    )

    with pytest.raises(KeyError, match="system_assistant_v2"):
        resolve_profile(session)
