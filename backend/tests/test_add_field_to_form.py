"""TDD for app.mcp_tools.apaas_form_tools._add_field_to_form_core

根因: aPaaS 模型字段与表单 formComponents 两套独立, add_apaas_model_field 只到模型层,
缺增量铺表单工具 → 对话加字段只建了模型、没出现在表单上。本核心函数一步做完
「加模型字段(若不存在) + 把字段作为组件追加到表单详情页(可选上列表页)」。

设计见 docs/superpowers/specs/2026-06-18-add-field-to-form-design.md。
"""
from __future__ import annotations

import asyncio
import copy

import pytest

from app.mcp_tools.apaas_form_tools import _add_field_to_form_core


class FakeClient:
    """假 apaas client: 持有一份 form_config + 记录 add_model_field 调用, 可注入错误。"""

    def __init__(self, form_config=None, add_field_error=None, save_error=None):
        self._form_config = form_config if form_config is not None else {"detailPage": {"formComponents": []}}
        self._add_field_error = add_field_error
        self._save_error = save_error
        self.add_model_field_calls = []
        self.saved_config = None

    async def add_model_field(self, app_id, model_id, model_code, field_code, field_name,
                              field_type="STRING", max_length=255, comment="", **kw):
        self.add_model_field_calls.append({
            "model_code": model_code, "field_code": field_code,
            "field_name": field_name, "field_type": field_type,
        })
        if self._add_field_error is not None:
            raise self._add_field_error
        return {"code": "ok"}

    async def query_form_config(self, app_id, form_id):
        return copy.deepcopy(self._form_config)

    async def save_form_config(self, app_id, form_config):
        if self._save_error is not None:
            raise self._save_error
        self.saved_config = form_config
        return {"code": "ok"}


def _run(coro):
    return asyncio.run(coro)


def _kw(**over):
    base = dict(apaas_app_id="app1", model_id="m1", model_code="customer",
                field_code="phone", field_name="手机号", field_type="STRING",
                max_length=20, comment="", form_id="f1", show_in_list=False)
    base.update(over)
    return base


def test_new_field_added_to_model_and_form():
    client = FakeClient({"detailPage": {"formComponents": []}})
    res = _run(_add_field_to_form_core(client, **_kw()))
    assert res["ok"] is True and not res.get("skipped")
    assert client.add_model_field_calls == [
        {"model_code": "customer", "field_code": "phone", "field_name": "手机号", "field_type": "STRING"}
    ]
    comps = client.saved_config["detailPage"]["formComponents"]
    assert any(c["modelField"] == "customer.phone" for c in comps)
    assert "customer" in client.saved_config["allModelCodes"]


def test_component_type_derived_from_field_type():
    client = FakeClient({"detailPage": {"formComponents": []}})
    res = _run(_add_field_to_form_core(client, **_kw(field_code="amount", field_name="金额", field_type="NUM")))
    assert res["component_type"] == "FORM_NUMBER_INPUT"
    comps = client.saved_config["detailPage"]["formComponents"]
    assert any(c["modelField"] == "customer.amount" and c["componentType"] == "FORM_NUMBER_INPUT" for c in comps)


def test_idempotent_when_field_already_on_form():
    preset = {"detailPage": {"formComponents": [
        {"componentType": "FORM_TEXT_INPUT", "modelField": "customer.phone", "label": "手机号"}
    ]}}
    client = FakeClient(preset)
    res = _run(_add_field_to_form_core(client, **_kw()))
    assert res["ok"] is True and res["skipped"] is True
    assert res["reason"] == "FIELD_ALREADY_ON_FORM"
    assert client.saved_config is None


def test_tolerates_field_already_on_model():
    client = FakeClient({"detailPage": {"formComponents": []}}, add_field_error=Exception("字段编码已存在"))
    res = _run(_add_field_to_form_core(client, **_kw()))
    assert res["ok"] is True
    comps = client.saved_config["detailPage"]["formComponents"]
    assert any(c["modelField"] == "customer.phone" for c in comps)


def test_add_field_real_failure_aborts_before_form():
    client = FakeClient({"detailPage": {"formComponents": []}}, add_field_error=Exception("模型不存在"))
    res = _run(_add_field_to_form_core(client, **_kw()))
    assert res["ok"] is False and res["error_code"] == "ADD_FIELD_FAILED"
    assert client.saved_config is None


def test_token_error_on_add_propagates():
    client = FakeClient({"detailPage": {"formComponents": []}},
                        add_field_error=Exception("Client error 401 token 失效"))
    with pytest.raises(Exception) as ei:
        _run(_add_field_to_form_core(client, **_kw()))
    assert "401" in str(ei.value)


def test_show_in_list_does_not_inject_listpageview():
    # 真机扒出 listPageView 不在 formConfigDetail payload 里; 凭空注入会致 500。
    # show_in_list=True 不再往 detailPage 注入 listPageView, 只在结果里标注列表列需另配。
    client = FakeClient({"detailPage": {"formComponents": []}})
    res = _run(_add_field_to_form_core(client, **_kw(show_in_list=True)))
    assert res["ok"] is True and res["show_in_list"] is True
    assert "listPageView" not in client.saved_config["detailPage"]


def test_default_does_not_touch_query_list():
    client = FakeClient({"detailPage": {"formComponents": []}})
    _run(_add_field_to_form_core(client, **_kw(show_in_list=False)))
    detail = client.saved_config["detailPage"]
    assert "listPageView" not in detail


def test_partial_failure_when_form_save_fails():
    client = FakeClient({"detailPage": {"formComponents": []}}, save_error=Exception("平台拒绝保存表单"))
    res = _run(_add_field_to_form_core(client, **_kw()))
    assert res["ok"] is False and res["error_code"] == "FORM_SAVE_FAILED"
    assert res["field_on_model"] is True and res["field_on_form"] is False
    assert len(client.add_model_field_calls) == 1


def test_reserved_field_code_rejected_before_client():
    client = FakeClient({"detailPage": {"formComponents": []}})
    res = _run(_add_field_to_form_core(client, **_kw(field_code="approval_status")))
    assert res["ok"] is False and res["error_code"] == "RESERVED_FIELD_CODE"
    assert client.add_model_field_calls == []


def test_missing_required_params_rejected():
    client = FakeClient({"detailPage": {"formComponents": []}})
    res = _run(_add_field_to_form_core(client, **_kw(form_id="")))
    assert res["ok"] is False and res["error_code"] == "INVALID_PARAMS"
    assert client.add_model_field_calls == []
