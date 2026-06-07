from app.form_component_sanitizer import sync_form_components_with_model_fields
from app.generator_v2 import _sort_forms_by_data_selector_dependencies


def _stale_selector_config():
    return {
        "models": [
            {
                "code": "industry",
                "name": "行业表单",
                "fields": [
                    {"code": "company_type", "name": "行业", "type": "单行输入"},
                ],
            }
        ],
        "forms": [
            {
                "code": "industry_form",
                "name": "行业表单",
                "modelCode": "industry",
                "components": [
                    {
                        "code": "company_type",
                        "label": "行业",
                        "componentType": "FORM_DATA_SELECTOR",
                        "modelField": "industry.company_type",
                        "description": "选择后赋值签发单位",
                    }
                ],
            }
        ],
    }


def test_sync_form_components_uses_latest_model_field_type():
    config = _stale_selector_config()

    changes = sync_form_components_with_model_fields(config)

    component = config["forms"][0]["components"][0]
    assert len(changes) == 1
    assert component["componentType"] == "FORM_TEXT_INPUT"
    assert "ref" not in component
    assert "selector_form_code" not in component


def test_synced_stale_selector_no_longer_blocks_dependency_sort():
    config = _stale_selector_config()
    sync_form_components_with_model_fields(config)

    _, issues = _sort_forms_by_data_selector_dependencies(config["forms"], {})

    assert issues == []


def test_sync_does_not_downgrade_non_reference_components():
    config = {
        "models": [
            {
                "code": "industry",
                "name": "行业表单",
                "fields": [
                    {"code": "approval_type", "name": "批准书类型", "type": "单行输入"},
                ],
            }
        ],
        "forms": [
            {
                "code": "industry_form",
                "name": "行业表单",
                "modelCode": "industry",
                "components": [
                    {
                        "code": "approval_type",
                        "label": "批准书类型",
                        "componentType": "FORM_SELECT_INPUT_SINGLE",
                        "modelField": "industry.approval_type",
                        "dict": "approval_type",
                    }
                ],
            }
        ],
    }

    changes = sync_form_components_with_model_fields(config)

    assert changes == []
    assert config["forms"][0]["components"][0]["componentType"] == "FORM_SELECT_INPUT_SINGLE"
