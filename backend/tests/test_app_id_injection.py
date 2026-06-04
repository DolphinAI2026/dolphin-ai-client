"""Task A4: 应用上下文注入护栏测试

锁定 app 时 execute_tool 必须把 session.app_id → (env_id, apaas_app_id) 强制注入声明了这两参数的工具，
覆盖 LLM 给的值；自由态会话不注入。
"""
import pytest
from app.ai_chat import tools as t
from app.models.ai_chat import AIChatSession


@pytest.mark.asyncio
async def test_locked_app_ctx_overrides_llm_values(monkeypatch):
    captured = {}
    async def _fake_mcp_call(name, args, tenant_id=0, user_id=0):
        captured["args"] = args
        return "ok"
    monkeypatch.setattr("app.ai_chat.mcp_bridge.call_tool", _fake_mcp_call)
    monkeypatch.setattr("app.ai_chat.mcp_bridge.list_mcp_tool_names_cached", lambda: ["list_apaas_app_models"])
    monkeypatch.setattr(t, "_tool_declares_param", lambda name, p: p in ("env_id", "apaas_app_id"))
    async def _fake_resolve(session, db):
        return (5, "APAAS_APP_99")
    monkeypatch.setattr(t, "_resolve_locked_app_ctx", _fake_resolve)

    s = AIChatSession(id=1, tenant_id=7, user_id=3, app_id=42)
    await t.execute_tool("list_apaas_app_models", {"env_id": 999, "apaas_app_id": "WRONG"}, s, db=object())
    assert captured["args"]["env_id"] == 5
    assert captured["args"]["apaas_app_id"] == "APAAS_APP_99"


@pytest.mark.asyncio
async def test_free_session_no_injection(monkeypatch):
    captured = {}
    async def _fake_mcp_call(name, args, tenant_id=0, user_id=0):
        captured["args"] = dict(args)
        return "ok"
    monkeypatch.setattr("app.ai_chat.mcp_bridge.call_tool", _fake_mcp_call)
    monkeypatch.setattr("app.ai_chat.mcp_bridge.list_mcp_tool_names_cached", lambda: ["list_apaas_app_models"])
    monkeypatch.setattr(t, "_tool_declares_param", lambda name, p: p in ("env_id", "apaas_app_id"))
    s = AIChatSession(id=1, tenant_id=7, user_id=3, app_id=None)  # 自由态
    await t.execute_tool("list_apaas_app_models", {"env_id": 999, "apaas_app_id": "WRONG"}, s, db=object())
    assert captured["args"]["env_id"] == 999
    assert captured["args"]["apaas_app_id"] == "WRONG"
