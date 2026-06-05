"""TDD: CORE_TOOL_NAMES + split_core_deferred primitives."""
from app.ai_chat.tools import CORE_TOOL_NAMES, split_core_deferred


def _fake_schemas(names):
    return [
        {
            "type": "function",
            "function": {
                "name": n,
                "description": n + " desc",
                "parameters": {"type": "object", "properties": {}},
            },
        }
        for n in names
    ]


def test_core_names_include_base_and_search():
    assert "search_tools" in CORE_TOOL_NAMES
    assert "read_attachment" in CORE_TOOL_NAMES      # base local tool
    assert "write_artifact" in CORE_TOOL_NAMES
    assert "list_apaas_app_models" in CORE_TOOL_NAMES  # a CORE_HOT read


def test_split_core_deferred():
    schemas = _fake_schemas([
        "read_attachment",
        "search_tools",
        "list_apaas_app_models",
        "update_apaas_model_field",
        "obscure_tool_x",
    ])
    core, deferred = split_core_deferred(schemas)
    core_names = {s["function"]["name"] for s in core}
    assert "read_attachment" in core_names and "search_tools" in core_names
    assert "list_apaas_app_models" in core_names
    assert "update_apaas_model_field" in deferred and "obscure_tool_x" in deferred
    assert "update_apaas_model_field" not in core_names
    assert isinstance(deferred, dict) and deferred["obscure_tool_x"]["function"]["name"] == "obscure_tool_x"
