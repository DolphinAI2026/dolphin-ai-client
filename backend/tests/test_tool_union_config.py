import pytest
from app.tool_registry import tools_for_agent


def test_config_only_tools_in_union():
    builder = set(tools_for_agent("builder"))
    coding = set(tools_for_agent("coding"))
    config = set(tools_for_agent("config"))
    union = builder | coding | config
    assert "save_config_skill" in config
    assert "save_config_skill" in union
    assert config - (builder | coding), "config 应有专属工具，否则 union 无意义"


@pytest.mark.asyncio
async def test_get_all_tool_schemas_includes_config(monkeypatch):
    from app.ai_chat import tools as t
    from app.tool_registry import tools_for_agent as tfa
    config_tools = list(set(tfa("config")))
    fake = [{"type": "function", "function": {"name": n, "parameters": {}}} for n in config_tools]
    async def _fake_schemas():
        return fake
    monkeypatch.setattr("app.ai_chat.mcp_bridge.get_tool_schemas_openai", _fake_schemas)
    schemas = await t.get_all_tool_schemas()
    names = {s["function"]["name"] for s in schemas}
    assert "save_config_skill" in names
