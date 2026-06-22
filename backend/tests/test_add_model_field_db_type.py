"""TDD: add_model_field 按 field_type 推导 databaseFieldType。

Bug(2026-06-22 真机扒出): 对话加字段时 add_model_field 默认 databaseFieldType="VARCHAR",
两个调用方(add_apaas_field_to_form / add_apaas_model_field)都不传它 →
field_type="BIG_TEXT" 被 aPaaS 建成 VARCHAR 字符串(平台字段编辑器类型显示空、
原生设计器渲染成「单行输入」)。修复: 不传 database_field_type 时按 field_type 推导,
复用 canonical normalize_database_field_type(它能正确处理 STRING/TEXT/BIG_TEXT/DATE/
DATETIME/BOOLEAN,只漏认 aPaaS 逻辑码 "NUM" → 在此补 decimal)。
"""
from __future__ import annotations

import asyncio
import json

import httpx

from app.apaas_client import (
    APaaSClient,
    _db_type_for_field_type,
    _normalize_apaas_field_type,
)


def test_normalize_field_type_aliases_to_platform_codes():
    # 平台只认 STRING/NUM/BIG_TEXT/DATE/DATETIME/BOOLEAN; agent 常传同义词。
    assert _normalize_apaas_field_type("TEXT") == "BIG_TEXT"
    assert _normalize_apaas_field_type("LONGTEXT") == "BIG_TEXT"
    assert _normalize_apaas_field_type("NUMBER") == "NUM"
    assert _normalize_apaas_field_type("INT") == "NUM"
    assert _normalize_apaas_field_type("BIG_TEXT") == "BIG_TEXT"
    assert _normalize_apaas_field_type("STRING") == "STRING"
    assert _normalize_apaas_field_type("") == "STRING"


def test_add_model_field_normalizes_text_to_bigtext(monkeypatch):
    # agent 传 "TEXT" → 平台不认 → 字段类型为空(真机 bug)。归一成 BIG_TEXT + db=text。
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json={"code": "ok"})

    _patch_transport(monkeypatch, handler)
    client = APaaSClient(base_url="http://test", tenant_id="t1", token="tok")
    asyncio.run(client.add_model_field(
        "app1", "m1", "warehouse_area", "area_remark", "备注",
        field_type="TEXT", max_length=500,
    ))
    assert captured["body"]["fieldType"] == "BIG_TEXT"
    assert captured["body"]["databaseFieldType"] == "text"


def test_db_type_for_field_type_maps_apaas_logical_types():
    assert _db_type_for_field_type("BIG_TEXT") == "text"
    assert _db_type_for_field_type("TEXT") == "text"
    assert _db_type_for_field_type("STRING") == "varchar"
    # NUM→double: 真机实测平台 NUM 字段 databaseFieldType 全是 double
    assert _db_type_for_field_type("NUM") == "double"
    assert _db_type_for_field_type("DATE") == "date"
    assert _db_type_for_field_type("DATETIME") == "datetime"
    assert _db_type_for_field_type("") == "varchar"


def _patch_transport(monkeypatch, handler):
    transport = httpx.MockTransport(handler)
    orig = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: orig(transport=transport, **kw))


def test_add_model_field_derives_text_db_type_for_big_text(monkeypatch):
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json={"code": "ok"})

    _patch_transport(monkeypatch, handler)
    client = APaaSClient(base_url="http://test", tenant_id="t1", token="tok")
    asyncio.run(client.add_model_field(
        "app1", "m1", "score_result", "tl_evaluation", "TL评价",
        field_type="BIG_TEXT", max_length=1000,
    ))
    assert captured["body"]["fieldType"] == "BIG_TEXT"
    # 修复前: databaseFieldType 默认 "VARCHAR" → 平台把大文本建成字符串
    assert captured["body"]["databaseFieldType"] == "text"


def test_update_model_field_syncs_db_type_on_type_change(monkeypatch):
    # 改字段类型(update/fromApp)也要同步 databaseFieldType, 否则同样建坏(类型显示空)。
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json={"code": "ok"})

    _patch_transport(monkeypatch, handler)
    client = APaaSClient(base_url="http://test", tenant_id="t1", token="tok")
    asyncio.run(client.update_model_field(
        "app1", "m1", "fid1", "tl_evaluation", "TL评价",
        field_type="BIG_TEXT", max_length=1000,
    ))
    assert captured["body"]["fieldType"] == "BIG_TEXT"
    assert captured["body"]["databaseFieldType"] == "text"


def test_update_model_field_no_db_type_when_type_unchanged(monkeypatch):
    # 仅改名/长度(field_type=None)时不应注入 databaseFieldType。
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json={"code": "ok"})

    _patch_transport(monkeypatch, handler)
    client = APaaSClient(base_url="http://test", tenant_id="t1", token="tok")
    asyncio.run(client.update_model_field(
        "app1", "m1", "fid1", "phone", "手机号", max_length=30,
    ))
    assert "databaseFieldType" not in captured["body"]
    assert "fieldType" not in captured["body"]


def test_add_model_field_respects_explicit_db_type(monkeypatch):
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json={"code": "ok"})

    _patch_transport(monkeypatch, handler)
    client = APaaSClient(base_url="http://test", tenant_id="t1", token="tok")
    asyncio.run(client.add_model_field(
        "app1", "m1", "c", "f", "F",
        field_type="STRING", database_field_type="varchar", max_length=20,
    ))
    assert captured["body"]["databaseFieldType"] == "varchar"
