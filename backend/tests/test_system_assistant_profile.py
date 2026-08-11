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
from app.ai_chat.agent import (
    _SYSTEM_ASSISTANT_INTRO_RESPONSE,
    _apply_session_overrides,
    _is_system_assistant_intro_request,
)


def test_system_assistant_profile_exposes_workspace_runtime_and_diagnostics_only():
    profile = resolve_profile("system_assistant")
    tools = set(profile.tool_names)

    assert profile.name == "system_assistant"
    assert "先诊断" in profile.system_prompt
    assert "read_workspace_file" in tools
    assert "write_workspace_files" in tools
    assert "run_workspace_command" in tools
    assert "list_dev_workspaces" in tools
    assert "create_dev_workspace" in tools
    assert "init_apaas_backend_workspace" in tools
    assert "doctor_apaas_backend_workspace" in tools
    assert "lint_apaas_backend_workspace" in tools
    assert {"use_skill", "read_knowledge", "search_knowledge"}.issubset(tools)
    assert "read_attachment" in tools
    assert "write_artifact" in tools

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
    ):
        assert forbidden not in tools


def test_system_assistant_prompt_describes_seed_workspace_and_bound_workspace_contract():
    prompt = resolve_profile("system_assistant").system_prompt

    assert "内置 dev scene/seed scaffold" in prompt
    assert "create_dev_workspace" in prompt
    assert "不是创建 Builder/aPaaS 应用" in prompt
    assert "生成开发规格或工程草稿" in prompt
    assert "初始化 aPaaS 后端骨架" in prompt
    assert "doctor、lint 和验证" in prompt
    assert "生成和迭代工作区内的 user Skill 草稿" in prompt
    assert "不写共享 Skill 库" in prompt
    assert "单工作区锁" in prompt
    assert "数字员工能力" in prompt


def test_system_assistant_intro_reports_four_compact_real_capability_directions():
    numbered_directions = [
        line for line in _SYSTEM_ASSISTANT_INTRO_RESPONSE.splitlines()
        if line[:2] in {"1.", "2.", "3.", "4.", "5."}
    ]

    assert len(numbered_directions) == 4
    assert "种子工程/工作区" in _SYSTEM_ASSISTANT_INTRO_RESPONSE
    assert "生成或迭代工作区 Skill 草稿" in _SYSTEM_ASSISTANT_INTRO_RESPONSE
    assert "平台配置、部署发布和数字员工能力暂不开放" in _SYSTEM_ASSISTANT_INTRO_RESPONSE


def test_system_assistant_profile_does_not_require_a_bound_workspace():
    prompt, tools, locked_ws_id = resolve_overrides_for_session(
        SimpleNamespace(mode="chat", assistant_profile="system_assistant")
    )

    assert prompt == resolve_profile("system_assistant").system_prompt
    assert tools
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
    assert tools == set(narrow_tools_for_locked_ws(profile.tool_names, "ws-system"))
    assert "list_dev_workspaces" not in tools
    assert "create_dev_workspace" not in tools
    assert locked_ws_id == "ws-system"
    assert "ws-system" in (ws_bind_view_context(locked_ws_id) or "")

    applied_prompt, applied_tools, view_context = _apply_session_overrides(session, None, None)
    assert applied_prompt == prompt
    assert applied_tools == tools
    assert getattr(session, "_locked_ws_id", None) == "ws-system"
    assert "ws-system" in (view_context or "")


def test_system_assistant_code_session_without_workspace_can_discover_one():
    session = SimpleNamespace(
        mode="code", assistant_profile="system_assistant", workspace_id=None
    )

    _prompt, tools, locked_ws_id = resolve_overrides_for_session(session)
    profile = resolve_profile("system_assistant")

    assert tools == set(profile.tool_names)
    assert "list_dev_workspaces" in tools
    assert "create_dev_workspace" in tools
    assert locked_ws_id is None
    assert ws_bind_view_context(locked_ws_id) is None


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
