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


# ─────────────────────── build_deferred_manifest ───────────────────────

from app.ai_chat.tools import build_deferred_manifest


def test_manifest_lists_each_deferred_with_desc():
    deferred = {"update_apaas_model_field": {"function": {"name": "update_apaas_model_field", "description": "改模型字段必填/类型"}}}
    m = build_deferred_manifest(deferred)
    assert "update_apaas_model_field" in m and "改模型字段" in m
    assert "search_tools" in m  # 引导句提到先 search


def test_manifest_empty_when_no_deferred():
    assert build_deferred_manifest({}) == ""


# ─────────────────────── search_tools handler (Task 4) ───────────────────────

import json
import pytest


@pytest.mark.asyncio
async def test_search_tools_handler_returns_activated():
    import app.ai_chat.tools as t
    t._LAST_TOOL_SCHEMAS = [
        {"type":"function","function":{"name":"update_apaas_model_field","description":"改模型字段","parameters":{"type":"object","properties":{}}}},
        {"type":"function","function":{"name":"read_attachment","description":"读附件","parameters":{"type":"object","properties":{}}}},
    ]
    res = await t._handle_search_tools({"query":"select:update_apaas_model_field"}, session=None, db=None)
    data = json.loads(res)
    assert data["ok"] is True and "update_apaas_model_field" in data["activated"]


@pytest.mark.asyncio
async def test_search_tools_no_match():
    import app.ai_chat.tools as t
    t._LAST_TOOL_SCHEMAS = [{"type":"function","function":{"name":"foo_tool","description":"bar","parameters":{}}}]
    res = await t._handle_search_tools({"query":"完全无关xyz"}, session=None, db=None)
    data = json.loads(res)
    assert data["ok"] is True and data["activated"] == []


@pytest.mark.asyncio
async def test_system_assistant_search_tools_cannot_expose_local_skill_cache():
    from types import SimpleNamespace
    import app.ai_chat.tools as t

    t._LAST_TOOL_SCHEMAS = [
        {"type": "function", "function": {"name": "list_skills", "description": "列出本地技能", "parameters": {}}},
        {"type": "function", "function": {"name": "list_system_assets", "description": "列出远端系统资产", "parameters": {}}},
    ]
    session = SimpleNamespace(assistant_profile="system_assistant")

    local = json.loads(await t._handle_search_tools({"query": "select:list_skills"}, session=session, db=None))
    remote = json.loads(await t._handle_search_tools({"query": "select:list_system_assets"}, session=session, db=None))

    assert local["activated"] == []
    assert remote["activated"] == ["list_system_assets"]


def test_search_tools_in_base_schemas():
    from app.ai_chat.tools import TOOL_SCHEMAS
    names = {s["function"]["name"] for s in TOOL_SCHEMAS}
    assert "search_tools" in names


def test_per_turn_tools_rebuild_only_includes_active_deferred():
    from app.ai_chat.tools import split_core_deferred
    schemas = [
        {"type": "function", "function": {"name": "read_attachment", "description": "d", "parameters": {}}},      # core
        {"type": "function", "function": {"name": "search_tools", "description": "d", "parameters": {}}},          # core
        {"type": "function", "function": {"name": "list_apaas_app_models", "description": "d", "parameters": {}}}, # core (hot read)
        {"type": "function", "function": {"name": "update_apaas_model_field", "description": "d", "parameters": {}}}, # deferred
        {"type": "function", "function": {"name": "add_apaas_dict_option", "description": "d", "parameters": {}}},  # deferred
    ]
    core, deferred = split_core_deferred(schemas)
    active = {"update_apaas_model_field"}  # only one activated
    tools = core + [deferred[n] for n in active if n in deferred]
    names = {t["function"]["name"] for t in tools}
    assert "read_attachment" in names and "search_tools" in names and "list_apaas_app_models" in names
    assert "update_apaas_model_field" in names          # activated deferred → included
    assert "add_apaas_dict_option" not in names         # not activated → excluded
