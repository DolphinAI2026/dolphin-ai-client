from __future__ import annotations

import pytest

from app.mcp_server import (
    _apply_form_component_updates,
    _build_component_behavior_updates,
    _find_form_component,
    _normalize_select_component_options,
    _validate_component_default_value,
)


def _sample_components() -> list[dict]:
    return [
        {
            "uuid": "cmp-name",
            "label": "项目名称",
            "boCode": "project_form.project_name",
            "componentType": "FORM_INPUT",
            "required": True,
        },
        {
            "uuid": "cmp-status",
            "label": "项目状态",
            "boCode": "project_form.project_status",
            "componentType": "FORM_SELECT_INPUT_SINGLE",
            "defaultValue": "draft",
            "chooseOptions": [
                {"id": "draft", "label": "草稿"},
                {"id": "approved", "label": "已立项"},
            ],
            "dictionaryChooseOptions": [
                {"id": "draft", "label": "草稿"},
                {"id": "approved", "label": "已立项"},
            ],
        },
    ]


def test_find_form_component_prefers_uuid_then_bo_code_then_label():
    comps = _sample_components()

    found, match_by = _find_form_component(comps, component_uuid="cmp-status", component_label="项目名称")
    assert found["label"] == "项目状态"
    assert match_by == "uuid"

    found, match_by = _find_form_component(comps, bo_code="project_form.project_name")
    assert found["uuid"] == "cmp-name"
    assert match_by == "bo_code"

    found, match_by = _find_form_component(comps, component_label="项目状态")
    assert found["uuid"] == "cmp-status"
    assert match_by == "label"


def test_apply_form_component_updates_returns_changed_field_diff_only():
    form_config = {"detailPage": {"formComponents": _sample_components()}}

    result = _apply_form_component_updates(
        form_config,
        {"required": False, "placeholder": "请输入项目名称"},
        component_label="项目名称",
    )

    assert result["component"]["required"] is False
    assert result["diff"] == {
        "required": {"before": True, "after": False},
        "placeholder": {"before": None, "after": "请输入项目名称"},
    }
    assert result["match_by"] == "label"


def test_build_component_behavior_updates_validates_width_values():
    updates = _build_component_behavior_updates(width=6, mobile_width=12, read_only=True)
    assert updates == {"width": 6, "mobileWidth": 12, "readOnly": True}

    with pytest.raises(ValueError, match="width"):
        _build_component_behavior_updates(width=5)

    with pytest.raises(ValueError, match="mobile_width"):
        _build_component_behavior_updates(mobile_width=9)


def test_validate_component_default_value_requires_existing_select_option():
    component = _sample_components()[1]

    _validate_component_default_value(component, "draft")

    with pytest.raises(ValueError, match="默认值"):
        _validate_component_default_value(component, "missing")


def test_normalize_select_component_options_builds_platform_option_shape():
    options = _normalize_select_component_options(
        [
            {"id": "draft", "label": "草稿", "color": "#2F80ED"},
            {"value": "approved", "name": "已立项"},
        ]
    )

    assert options == [
        {
            "id": "draft",
            "value": "draft",
            "code": "draft",
            "label": "草稿",
            "name": "草稿",
            "color": "#2F80ED",
            "displayOrder": 0,
            "labelI18nAssociated": False,
        },
        {
            "id": "approved",
            "value": "approved",
            "code": "approved",
            "label": "已立项",
            "name": "已立项",
            "color": "",
            "displayOrder": 1,
            "labelI18nAssociated": False,
        },
    ]
