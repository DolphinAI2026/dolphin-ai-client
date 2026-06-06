"""get_apaas_form_detail：普通下拉/单选/复选组件必须透出选项（choose_options），
否则只读表单设计器里下拉永远空（绑了字典也拉不到）。
直接调 MCP 工具函数，monkeypatch _with_client 喂 apaas detailPageConfig 结构。
"""
from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_form_detail_exposes_dropdown_choose_options(monkeypatch):
    from app import mcp_server

    raw = {
        "modelWithFieldVoList": [],
        "detailPage": {
            "formComponents": [
                {
                    "uuid": "c1", "label": "状态", "componentType": "FORM_SELECT_INPUT_SINGLE",
                    "boCode": "m~status", "chooseType": "SINGLE", "dictionaryCode": "STATUS_DICT",
                    "dictionaryChooseOptions": [
                        {"value": "OPEN", "label": "进行中", "code": "1"},
                        {"value": "DONE", "label": "已完成", "code": "2"},
                    ],
                },
            ],
        },
        "modelCode": "m",
        "listPageViews": [],
    }

    async def fake_with_client(env_id, op, fn):
        return True, raw

    monkeypatch.setattr(mcp_server, "_with_client", fake_with_client)

    out = await mcp_server.get_apaas_form_detail(1, "AP1", "F1")

    assert out["ok"] is True
    comp = next(c for c in out["components"] if c["uuid"] == "c1")
    assert comp.get("choose_options") == [
        {"code": "OPEN", "name": "进行中"},
        {"code": "DONE", "name": "已完成"},
    ], "下拉选项必须透出为 {code,name} 给前端渲染"
    assert comp.get("choose_type") == "SINGLE"
    assert comp.get("dictionary_code") == "STATUS_DICT"


@pytest.mark.asyncio
async def test_form_detail_plain_choose_options_without_dict(monkeypatch):
    """没绑字典、用固定 chooseOptions 的下拉也要透出选项。"""
    from app import mcp_server

    raw = {
        "modelWithFieldVoList": [],
        "detailPage": {
            "formComponents": [
                {
                    "uuid": "c2", "label": "优先级", "componentType": "FORM_SELECT_INPUT",
                    "boCode": "m~prio", "chooseType": "MULTIPLE",
                    "chooseOptions": [
                        {"value": "H", "label": "高"},
                        {"value": "L", "label": "低"},
                    ],
                },
            ],
        },
        "modelCode": "m",
        "listPageViews": [],
    }

    async def fake_with_client(env_id, op, fn):
        return True, raw

    monkeypatch.setattr(mcp_server, "_with_client", fake_with_client)

    out = await mcp_server.get_apaas_form_detail(1, "AP1", "F1")
    comp = next(c for c in out["components"] if c["uuid"] == "c2")
    assert comp.get("choose_options") == [{"code": "H", "name": "高"}, {"code": "L", "name": "低"}]
