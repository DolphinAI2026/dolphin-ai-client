"""TDD: add_apaas_field_to_form 铺组件时克隆同模型同类型的现有组件。

2026-06-22 真机(Claude in Chrome)扒出 formConfigDetail 真实 payload:
- 每个组件 ~75 字段(uuid 32-hex 前端 GUID / boId / boCode(model~field) / render /
  methods / modelCode / fieldFullName …);残缺组件(8 字段无 uuid)→ 平台 500。
- listPageView 不在 formConfigDetail payload 里(凭空注入 detailPage.listPageView → 错)。

修复: 读表单后克隆一个同模型同类型的现有组件(保留完整平台结构), 只换身份字段
(uuid/label/modelField/boCode/modelCode/fieldFullName), 同模型 → boId/render/methods 自动正确;
无可用模板时退化到旧的残缺构造(行为不比现状差)。并删除 listPageView 注入。
"""
from __future__ import annotations

import asyncio
import copy
import re

from app.mcp_tools.apaas_form_tools import (
    _add_field_to_form_core,
    _build_form_component_for_field,
    _clone_form_component_for_field,
    _gen_form_component_uuid,
)


def _sibling(**over):
    base = {
        "uuid": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6",
        "componentType": "FORM_TEXT_INPUT",
        "label": "队名",
        "modelField": "score_result.team_name",
        "boCode": "score_result~team_name",
        "boId": "856866633788868096",
        "modelCode": "score_result",
        "modelName": "评分结果",
        "modelFieldName": "队名",
        "fieldFullName": "评分结果-队名",
        "render": {"r": 1},
        "methods": {"m": 1},
        "width": 6,
        "value": "old",
        "defaultValue": "old",
        "validatorList": [{"x": 1}],
        "required": True,
    }
    base.update(over)
    return base


# ── 纯 helper 单测 ──────────────────────────────────────────────────────────

def test_gen_uuid_is_32_hex_no_dash():
    u = _gen_form_component_uuid()
    assert re.fullmatch(r"[a-f0-9]{32}", u)
    assert _gen_form_component_uuid() != u  # 每次不同


def test_clone_preserves_platform_fields_and_swaps_identity():
    tmpl = _sibling()
    c = _clone_form_component_for_field(
        tmpl, model_code="score_result", field_code="tl_evaluation",
        field_name="TL评价", comp_type="FORM_TEXTAREA_INPUT")
    # 平台结构字段保留(同模型 → boId 也对)
    assert c["render"] == {"r": 1} and c["methods"] == {"m": 1} and c["width"] == 6
    assert c["boId"] == "856866633788868096"
    # 身份换新
    assert c["componentType"] == "FORM_TEXTAREA_INPUT"
    assert c["label"] == "TL评价"
    assert c["modelField"] == "score_result.tl_evaluation"
    assert c["boCode"] == "score_result~tl_evaluation"
    assert c["modelCode"] == "score_result"
    assert c["fieldFullName"] == "评分结果-TL评价"
    assert c["modelFieldName"] == "TL评价"
    # 新 uuid, 与模板不同, 32-hex
    assert c["uuid"] != tmpl["uuid"] and re.fullmatch(r"[a-f0-9]{32}", c["uuid"])
    # 不继承模板字段的值/校验
    assert not c.get("value")
    assert not c.get("defaultValue")
    assert not c.get("validatorList")
    assert c["required"] is False
    # 模板未被原地改动
    assert tmpl["uuid"] == "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6" and tmpl["label"] == "队名"


def test_clone_clears_dict_binding():
    tmpl = _sibling(componentType="FORM_SELECT_INPUT_SINGLE",
                    dictionaryCode="sex", chooseOptions=[{"code": "m", "name": "男"}],
                    dictionarySelectConfig={"dictionaryCode": "sex"})
    c = _clone_form_component_for_field(
        tmpl, model_code="score_result", field_code="grade",
        field_name="等级", comp_type="FORM_SELECT_INPUT_SINGLE")
    assert not c.get("dictionaryCode")
    assert not c.get("chooseOptions")
    assert not c.get("dictionarySelectConfig")


def test_build_prefers_same_model_same_type_clone():
    existing = [_sibling()]  # FORM_TEXT_INPUT, score_result
    field = {"field_code": "tl_evaluation", "field_name": "TL评价", "data_type": "STRING",
             "max_length": 255, "dictionary_code": "", "required": False}
    c = _build_form_component_for_field(existing, field, "score_result", "TL评价", "FORM_TEXT_INPUT")
    assert c.get("render") == {"r": 1}  # 来自克隆
    assert c["modelField"] == "score_result.tl_evaluation"
    assert re.fullmatch(r"[a-f0-9]{32}", c["uuid"])


def test_build_falls_back_to_skeletal_without_sibling():
    field = {"field_code": "phone", "field_name": "手机号", "data_type": "STRING",
             "max_length": 20, "dictionary_code": "", "required": False}
    c = _build_form_component_for_field([], field, "customer", "手机号", "FORM_TEXT_INPUT")
    assert "render" not in c  # 无任何同模型组件 → 残缺兜底
    assert c["modelField"] == "customer.phone"
    assert c["componentType"] == "FORM_TEXT_INPUT"


def test_build_clones_text_family_when_no_exact_type():
    # 表单只有单行文本(FORM_TEXT_INPUT), 加多行文本(FORM_TEXTAREA_INPUT) → 文本家族互借克隆,
    # 转成 textarea(覆盖"表单没有多行文本字段"的高频场景, 不再退化成残缺)。
    existing = [_sibling()]  # FORM_TEXT_INPUT
    field = {"field_code": "remark", "field_name": "备注", "data_type": "BIG_TEXT",
             "max_length": 500, "dictionary_code": "", "required": False}
    c = _build_form_component_for_field(existing, field, "score_result", "备注", "FORM_TEXTAREA_INPUT")
    assert c.get("render") == {"r": 1}  # 克隆了完整结构(非残缺)
    assert c["componentType"] == "FORM_TEXTAREA_INPUT"
    assert c["modelField"] == "score_result.remark"


def test_build_clones_any_same_model_when_no_text_family():
    # 加数字字段但表单无同类型/无文本家族 → 借任意同模型组件(保证完整水合), 转类型。
    existing = [_sibling(componentType="FORM_SELECT_INPUT_SINGLE")]
    field = {"field_code": "score", "field_name": "得分", "data_type": "NUM",
             "max_length": 0, "dictionary_code": "", "required": False}
    c = _build_form_component_for_field(existing, field, "score_result", "得分", "FORM_NUMBER_INPUT")
    assert c.get("render") == {"r": 1}  # 完整水合, 非残缺
    assert c["componentType"] == "FORM_NUMBER_INPUT"


# ── 集成: 通过 _add_field_to_form_core ────────────────────────────────────────

class _FakeClient:
    def __init__(self, form_config):
        self._fc = form_config
        self.saved_config = None

    async def add_model_field(self, *a, **k):
        return {"code": "ok"}

    async def query_form_config(self, app_id, form_id):
        return copy.deepcopy(self._fc)

    async def save_form_config(self, app_id, form_config):
        self.saved_config = form_config
        return {"code": "ok"}


def _core_kw(**over):
    base = dict(apaas_app_id="app1", model_id="m1", model_code="score_result",
                field_code="tl_evaluation", field_name="TL评价", field_type="BIG_TEXT",
                max_length=1000, comment="", form_id="f1", show_in_list=False)
    base.update(over)
    return base


def test_integration_clones_same_type_sibling_into_form():
    # BIG_TEXT → FORM_TEXTAREA_INPUT, 表单里有 textarea sibling(结果备注)可作模板。
    textarea_sibling = _sibling(componentType="FORM_TEXTAREA_INPUT", label="结果备注",
                                modelField="score_result.result_note", boCode="score_result~result_note",
                                modelFieldName="结果备注", fieldFullName="评分结果-结果备注",
                                render={"r": 2}, methods={"m": 2})
    fc = {"detailPage": {"formComponents": [_sibling(), textarea_sibling]},
          "allModelCodes": ["score_result"]}
    client = _FakeClient(fc)
    res = asyncio.run(_add_field_to_form_core(client, **_core_kw()))
    assert res["ok"] is True
    comps = client.saved_config["detailPage"]["formComponents"]
    new = next(c for c in comps if c["modelField"] == "score_result.tl_evaluation")
    # 克隆自同类型(textarea) sibling 的完整结构
    assert new["componentType"] == "FORM_TEXTAREA_INPUT"
    assert new.get("render") == {"r": 2} and new.get("methods") == {"m": 2}
    assert new.get("boId") == "856866633788868096"
    assert re.fullmatch(r"[a-f0-9]{32}", new["uuid"])


def test_integration_clones_text_family_when_no_textarea_sibling():
    # 表单只有单行文本(无多行文本), 加 BIG_TEXT(→TEXTAREA) → 文本家族互借克隆(非残缺)。
    # 这正是真机 WMS「仓库区域」表单的场景: 没有多行文本字段当同类型模板。
    fc = {"detailPage": {"formComponents": [_sibling()]}, "allModelCodes": ["score_result"]}
    client = _FakeClient(fc)
    res = asyncio.run(_add_field_to_form_core(client, **_core_kw()))
    assert res["ok"] is True
    comps = client.saved_config["detailPage"]["formComponents"]
    new = next(c for c in comps if c["modelField"] == "score_result.tl_evaluation")
    assert new.get("render") == {"r": 1}  # 文本家族克隆, 完整水合
    assert new["componentType"] == "FORM_TEXTAREA_INPUT"


def test_integration_show_in_list_does_not_inject_listpageview():
    fc = {"detailPage": {"formComponents": [_sibling()]}}
    client = _FakeClient(fc)
    res = asyncio.run(_add_field_to_form_core(client, **_core_kw(show_in_list=True)))
    assert res["ok"] is True
    assert "listPageView" not in client.saved_config.get("detailPage", {})
