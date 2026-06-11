"""AIChat app-locked self-dev workspace reuse guard.

When the embedded app assistant is locked to an existing application, asking to
modify an existing self-dev page should not silently create another workspace
with the same name.
"""

import json

import pytest

from app.models.ai_chat import AIChatSession


@pytest.mark.asyncio
async def test_create_dev_workspace_reuses_existing_locked_app_workspace(monkeypatch):
    import app.ai_chat.tools as tools

    async def _fake_find_existing(args, session, db):
        return {
            "id": "1_existing",
            "project_name": "form-page-project-dashboard",
            "display_name": "项目驾驶舱",
            "project_type": "form-page",
            "project_id": None,
        }

    async def _fail_mcp_call(*args, **kwargs):
        raise AssertionError("create_dev_workspace should be blocked before MCP call")

    monkeypatch.setattr(tools, "_find_existing_app_workspace_for_create", _fake_find_existing, raising=False)
    monkeypatch.setattr("app.ai_chat.mcp_bridge.list_mcp_tool_names_cached", lambda: ["create_dev_workspace"])
    monkeypatch.setattr("app.ai_chat.mcp_bridge.call_tool", _fail_mcp_call)

    session = AIChatSession(id=1, tenant_id=7, user_id=3, app_id=5)
    result = await tools.execute_tool(
        "create_dev_workspace",
        {
            "scene_type": "form-page",
            "project_name": "form-page-project-dashboard",
            "display_name": "项目驾驶舱",
        },
        session,
        db=object(),
    )

    data = json.loads(result)
    assert data["ok"] is False
    assert data["error_code"] == "WORKSPACE_ALREADY_EXISTS"
    assert data["existing_workspace"]["ws_id"] == "1_existing"
    assert any("edit_workspace_files" in step for step in data["next_steps"])


@pytest.mark.asyncio
async def test_create_dev_workspace_in_locked_app_injects_project_id(monkeypatch):
    import app.ai_chat.tools as tools

    captured = {}

    async def _fake_find_existing(args, session, db):
        return None

    async def _fake_mcp_call(name, args, tenant_id=0, user_id=0):
        captured["name"] = name
        captured["args"] = dict(args)
        return json.dumps({"ok": True, "ws_id": "1_new"}, ensure_ascii=False)

    monkeypatch.setattr(tools, "_find_existing_app_workspace_for_create", _fake_find_existing, raising=False)
    monkeypatch.setattr("app.ai_chat.mcp_bridge.list_mcp_tool_names_cached", lambda: ["create_dev_workspace"])
    monkeypatch.setattr("app.ai_chat.mcp_bridge.call_tool", _fake_mcp_call)

    session = AIChatSession(id=1, tenant_id=7, user_id=3, app_id=5)
    result = await tools.execute_tool(
        "create_dev_workspace",
        {
            "scene_type": "form-page",
            "project_name": "form-page-project-dashboard-v2",
            "display_name": "项目驾驶舱 V2",
        },
        session,
        db=object(),
    )

    assert json.loads(result)["ok"] is True
    assert captured["name"] == "create_dev_workspace"
    assert captured["args"]["project_id"] == 5
