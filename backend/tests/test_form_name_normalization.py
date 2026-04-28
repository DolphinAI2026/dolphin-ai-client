from app.routes.applications._helpers import _compact_preview_payload
from app.routes.generation_steps import _build_steps
from app.step_executor import (
    _build_create_form_payload,
    _resolve_form_code,
    _resolve_form_main_model,
)


def test_compact_preview_preserves_standard_doc_form_name_fields():
    compact = _compact_preview_payload({
        "data": {
            "forms": [{
                "form_name": "配额申请表单",
                "form_code": "quota_apply_form",
                "main_model_code": "quota_apply",
                "all_model_codes": ["quota_apply", "quota_detail"],
                "components": [],
            }],
        }
    })

    assert compact["forms"] == [{
        "code": "quota_apply_form",
        "name": "配额申请表单",
        "formCode": "quota_apply_form",
        "formName": "配额申请表单",
        "modelCode": "quota_apply",
        "components": [],
        "allModelCodes": ["quota_apply", "quota_detail"],
    }]


def test_create_form_payload_uses_standard_doc_form_name():
    form = {
        "form_name": "配额申请表单",
        "form_code": "quota_apply_form",
        "main_model_code": "quota_apply",
        "all_model_codes": ["quota_apply", "quota_detail"],
        "components": [],
    }
    model_info = {
        "0": {"name": "配额申请", "code": "quota_apply", "fields": {"申请编号": "apply_no"}},
    }

    form_name, main_model_code, all_model_codes, model = _resolve_form_main_model(form, model_info)
    form_code = _resolve_form_code(form, form_name)
    payload = _build_create_form_payload(form_name, form_code, all_model_codes, [], [], [])

    assert form_name == "配额申请表单"
    assert main_model_code == "quota_apply"
    assert all_model_codes == ["quota_apply", "quota_detail"]
    assert model["code"] == "quota_apply"
    assert payload[0]["formName"] == "配额申请表单"
    assert payload[0]["formCode"] == "quota_apply_form"


def test_generation_step_label_uses_standard_doc_form_name():
    steps = _build_steps(
        {
            "data": {
                "models": [{"name": "配额申请", "code": "quota_apply", "fields": []}],
                "forms": [{
                    "form_name": "配额申请表单",
                    "form_code": "quota_apply_form",
                    "main_model_code": "quota_apply",
                    "components": [],
                }],
            }
        },
        {"steps_completed": ["create_app"], "step_errors": {}},
        apaas_app_id="app-1",
    )

    form_step = next(step for step in steps if step.key == "create_form:0")
    assert form_step.label == "创建表单: 配额申请表单"
    assert form_step.model_index == 0
