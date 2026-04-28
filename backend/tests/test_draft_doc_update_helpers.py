import pytest
from types import SimpleNamespace

from app.routes import requirements
from app.routes.applications.docs import (
    _build_update_context_summary,
    _classify_update_request_with_llm,
    _extract_add_field_names,
    _is_broad_feature_request,
    _is_trivial_non_update_message,
    _try_apply_simple_add_field_update,
)
from app.routes.applications._helpers import _resolve_builder_llm_cfg


def test_extract_add_field_names_from_update_instruction():
    assert _extract_add_field_names("给配额申请表单新增审批备注字段") == ["审批备注"]
    assert _extract_add_field_names("新增字段：审批意见、审批附件") == ["审批意见", "审批附件"]
    assert _extract_add_field_names("帮我增加一个会议成员管理的功能") == []
    assert _is_broad_feature_request("帮我增加一个会议成员管理的功能") is True
    assert _is_trivial_non_update_message("hello") is True
    assert _is_trivial_non_update_message("帮我给会议主表新增备注字段") is False


def test_update_context_summary_does_not_embed_full_document():
    config = {
        "appName": "会议报名管理系统",
        "appCode": "meeting-reg",
        "models": [{"code": "meeting", "name": "会议"}],
        "forms": [{"formCode": "meeting_form", "formName": "会议表单"}],
    }
    huge_doc = "# 标题\n" + ("正文内容" * 5000) + "\n## 模型\n" + ("更多正文" * 5000)

    summary = _build_update_context_summary(config, huge_doc)

    assert summary["appName"] == "会议报名管理系统"
    assert summary["counts"]["models"] == 1
    assert summary["doc_headings"] == ["# 标题", "## 模型"]
    assert "正文内容" not in str(summary)


def test_simple_add_field_update_adds_model_field_and_form_component():
    config = {
        "appName": "配额管理",
        "appCode": "PEGL",
        "models": [{
            "code": "quota_apply",
            "name": "配额申请",
            "fields": [{"code": "apply_no", "name": "申请编号", "type": "单行输入"}],
        }],
        "forms": [{
            "formCode": "quota_apply_form",
            "formName": "配额申请表单",
            "modelCode": "quota_apply",
            "components": [{"code": "apply_no", "label": "申请编号"}],
        }],
    }

    result = _try_apply_simple_add_field_update(config, "给配额申请表单新增审批备注字段")

    assert result is not None
    updated, added = result
    assert added == ["审批备注"]
    assert any(field["name"] == "审批备注" for field in updated["models"][0]["fields"])
    assert any(component["label"] == "审批备注" for component in updated["forms"][0]["components"])
    assert next(component for component in updated["forms"][0]["components"] if component["label"] == "审批备注")["componentType"] == "FORM_TEXTAREA_INPUT"


def test_simple_add_field_update_honors_explicit_model_code_target():
    config = {
        "appName": "配额管理",
        "appCode": "PEGL",
        "models": [
            {
                "code": "quota_apply",
                "name": "配额申请",
                "fields": [{"code": "apply_no", "name": "申请编号", "type": "单行输入"}],
            },
            {
                "code": "industry",
                "name": "行业",
                "fields": [{"code": "company_type", "name": "行业类型", "type": "下拉单选"}],
            },
        ],
        "forms": [
            {
                "formCode": "quota_apply_form",
                "formName": "配额申请表单",
                "modelCode": "quota_apply",
                "components": [{"code": "apply_no", "label": "申请编号"}],
            },
            {
                "formCode": "industry_form",
                "formName": "行业表单",
                "modelCode": "industry",
                "components": [{"code": "company_type", "label": "行业类型"}],
            },
        ],
    }

    result = _try_apply_simple_add_field_update(config, "industry增加一个备注字段")

    assert result is not None
    updated, added = result
    assert added == ["备注"]
    quota_model, industry_model = updated["models"]
    assert not any(field["name"] == "备注" for field in quota_model["fields"])
    assert any(field["name"] == "备注" for field in industry_model["fields"])
    assert not any(component["label"] == "备注" for component in updated["forms"][0]["components"])
    assert any(component["label"] == "备注" for component in updated["forms"][1]["components"])


def test_simple_add_field_update_honors_explicit_form_name_target():
    config = {
        "models": [
            {"code": "quota_apply", "name": "配额申请", "fields": []},
            {"code": "industry", "name": "行业", "fields": []},
        ],
        "forms": [
            {"formCode": "quota_apply_form", "formName": "配额申请表单", "modelCode": "quota_apply", "components": []},
            {"formCode": "industry_form", "formName": "行业表单", "modelCode": "industry", "components": []},
        ],
    }

    result = _try_apply_simple_add_field_update(config, "给行业表单新增备注字段")

    assert result is not None
    updated, _ = result
    assert not updated["models"][0]["fields"]
    assert updated["models"][1]["fields"][0]["name"] == "备注"


@pytest.mark.asyncio
async def test_update_intent_classification_uses_llm_response(monkeypatch):
    async def fake_complete_with_config(cfg, messages, **kwargs):
        assert "用户消息" in messages[-1]["content"]
        return '{"action":"answer","actionable_update":false,"normalized_instruction":"","assistant_reply":"我在，可以继续说要改哪里。","confidence":0.91}'

    monkeypatch.setattr(requirements, "_complete_with_config", fake_complete_with_config)

    result = await _classify_update_request_with_llm(
        {"api_key": "test", "base_url": "http://example.test/v1", "model": "test"},
        app_name="配额管理",
        instruction="hello",
        current_doc="",
        current_config={"appName": "配额管理", "models": []},
    )

    assert result["actionable_update"] is False
    assert result["assistant_reply"] == "我在，可以继续说要改哪里。"


@pytest.mark.asyncio
async def test_resolve_builder_llm_cfg_uses_selected_model_without_conversation(monkeypatch):
    async def fake_resolve_llm_config(db, tenant_id, *, purpose, selected_config_id=None):
        assert tenant_id == 123
        assert purpose == "builder"
        assert selected_config_id == 9
        return SimpleNamespace(
            api_key="key",
            base_url="https://llm.example/v1",
            model="qwen3.6-plus",
            max_tokens=7424,
            provider="qwen",
        )

    monkeypatch.setattr("app.harness.llm_resolver.resolve_llm_config", fake_resolve_llm_config)

    result = await _resolve_builder_llm_cfg(
        db=object(),
        tenant_id=123,
        conversation_id=464,
        selected_config_id=9,
    )

    assert result == {
        "api_key": "key",
        "base_url": "https://llm.example/v1",
        "model": "qwen3.6-plus",
        "max_tokens": 7424,
        "provider": "qwen",
    }
