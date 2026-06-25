"""工具层单工作区强制锁:防 Code cutover 下 agent 读错工作区。

真机实测:agent 从 list_dev_workspaces / app_context 拿到别的 ws_id,
软提示绑定堵不死 → 在 execute_tool 入口把 ws_id 参数强制换成绑定的那个。
"""
from __future__ import annotations

from unittest.mock import MagicMock

from app.ai_chat import tools


def test_force_overrides_agent_ws_id_when_session_locked(monkeypatch):
    # read_workspace_file 声明了 ws_id 参数
    monkeypatch.setattr(tools, "_tool_declares_param", lambda name, param: param == "ws_id")
    session = MagicMock()
    session._locked_ws_id = "1_3c274b2f"  # 绑定的(用户打开的访客工作区)
    # agent 自传了别的(工厂孪生)→ 必须被强制换回绑定的
    out = tools._force_locked_ws_id(
        "read_workspace_file",
        {"ws_id": "1_88d4df89", "file_path": "src/page.vue"},
        session,
    )
    assert out["ws_id"] == "1_3c274b2f"
    assert out["file_path"] == "src/page.vue"  # 其它参数不动


def test_noop_when_session_not_locked(monkeypatch):
    monkeypatch.setattr(tools, "_tool_declares_param", lambda name, param: param == "ws_id")
    session = MagicMock(spec=[])  # 无 _locked_ws_id(Builder 会话)
    args = {"ws_id": "agent-picked"}
    assert tools._force_locked_ws_id("read_workspace_file", args, session) == args


def test_noop_when_tool_has_no_ws_id_param(monkeypatch):
    monkeypatch.setattr(tools, "_tool_declares_param", lambda name, param: False)
    session = MagicMock()
    session._locked_ws_id = "1_3c274b2f"
    args = {"foo": "bar"}
    assert tools._force_locked_ws_id("deploy_application", args, session) == args
