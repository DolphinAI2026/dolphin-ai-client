"""TDD: CORE_TOOL_NAMES + split_core_deferred + search_deferred_tools primitives."""
from app.ai_chat.tools import CORE_TOOL_NAMES, split_core_deferred, search_deferred_tools


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


# ─────────────────────── search_deferred_tools ───────────────────────

def test_search_select_exact():
    deferred = {"update_apaas_model_field":{"function":{"name":"update_apaas_model_field","description":"改模型字段"}},
                "add_apaas_dict_option":{"function":{"name":"add_apaas_dict_option","description":"加字典选项"}}}
    assert search_deferred_tools("select:update_apaas_model_field", deferred) == ["update_apaas_model_field"]

def test_search_keyword_tokenizes_name():
    deferred = {"update_apaas_model_field":{"function":{"name":"update_apaas_model_field","description":"修改模型字段属性"}}}
    hits = search_deferred_tools("模型 字段", deferred)
    assert "update_apaas_model_field" in hits

def test_search_uses_hint(monkeypatch):
    import app.ai_chat.tools as t
    monkeypatch.setattr(t, "_search_hint_for", lambda n: "发布 上线 go-live" if n=="republish_apaas_app" else "")
    deferred = {"republish_apaas_app":{"function":{"name":"republish_apaas_app","description":"重新发布版本"}}}
    assert "republish_apaas_app" in search_deferred_tools("上线", deferred)

def test_search_no_match_returns_empty():
    deferred = {"foo_tool":{"function":{"name":"foo_tool","description":"bar"}}}
    assert search_deferred_tools("完全不相关的词xyz", deferred) == []
