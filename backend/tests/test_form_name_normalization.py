import pytest

from app.routes.applications._helpers import _compact_preview_payload
from app.routes.generation_steps import _build_steps, _upsert_form_result
from app.step_executor import (
    _apply_form_identity_to_form_config,
    _apply_dictionary_binding_to_component,
    _build_create_form_payload,
    _collect_component_dict_lookup,
    _lookup_component_dict_code,
    _merge_existing_form_components,
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


def test_apply_form_identity_overwrites_platform_default_form_name():
    config = {
        "formName": "我的待办",
        "formCode": "old_form",
        "allModelCodes": [],
        "simpleFormConfig": {
            "formName": "我的待办",
            "formCode": "old_form",
            "allModelCodes": [],
        },
    }

    changed = _apply_form_identity_to_form_config(
        config,
        form_name="员工档案",
        form_code="t_employee_profile",
        all_model_codes=["t_employee_profile"],
    )

    assert changed is True
    assert config["formName"] == "员工档案"
    assert config["formCode"] == "t_employee_profile"
    assert config["allModelCodes"] == ["t_employee_profile"]
    assert config["simpleFormConfig"]["formName"] == "员工档案"
    assert config["simpleFormConfig"]["formCode"] == "t_employee_profile"
    assert config["simpleFormConfig"]["allModelCodes"] == ["t_employee_profile"]


def test_upsert_form_result_deduplicates_by_form_id_and_model_code():
    state = {
        "form_results": [
            {"formId": "form-1", "formName": "我的待办", "modelCode": "t_employee_profile"},
        ]
    }

    _upsert_form_result(
        state,
        {
            "formId": "form-1",
            "formName": "员工档案",
            "formCode": "t_employee_profile",
            "modelCode": "t_employee_profile",
        },
    )
    _upsert_form_result(
        state,
        {
            "formId": "",
            "formName": "员工档案",
            "formCode": "t_employee_profile",
            "modelCode": "t_employee_profile",
            "menuId": "menu-1",
        },
    )

    assert state["form_results"] == [
        {
            "formId": "form-1",
            "formName": "员工档案",
            "formCode": "t_employee_profile",
            "modelCode": "t_employee_profile",
            "menuId": "menu-1",
        }
    ]


def test_form_dict_binding_uses_model_field_when_component_lacks_dict():
    all_models = [{
        "name": "员工档案",
        "code": "t_employee_profile",
        "fields": [{
            "name": "员工状态",
            "code": "employee_profile_status",
            "type": "下拉单选",
            "dict": "employee_status",
        }],
    }]
    model_info = {
        "0": {
            "name": "员工档案",
            "code": "t_employee_profile",
            "fields": {"员工状态": "employee_profile_status"},
        }
    }
    component = {
        "componentType": "FORM_SELECT_INPUT_SINGLE",
        "label": "员工状态",
        "modelField": "t_employee_profile.employee_profile_status",
    }

    lookup = _collect_component_dict_lookup(
        form_components=[component],
        all_models=all_models,
        model_info=model_info,
        dict_codes={"employee_status": "employee_status"},
    )
    dict_code = _lookup_component_dict_code(component, lookup)
    changed = _apply_dictionary_binding_to_component(
        component,
        dict_code,
        "dict-id-1",
        [{"valueCode": "active", "valueName": "在职", "displayOrder": 1}],
    )

    assert dict_code == "employee_status"
    assert changed is True
    assert component["componentType"] == "FORM_SELECT_INPUT"
    assert component["source"] == {"type": "DICTIONARY_TYPE", "id": "dict-id-1"}
    assert component["chooseType"] == "SINGLE"
    assert component["dictionarySelectConfig"]["dictionaryCode"] == "employee_status"
    assert component["dictionaryChooseOptions"][0]["label"] == "在职"


@pytest.mark.asyncio
async def test_reused_form_syncs_component_flags_and_list_view():
    class FakeClient:
        def __init__(self):
            self.form_config = {
                "formName": "我的待办",
                "components": [{
                    "componentType": "FORM_TEXT_INPUT",
                    "label": "旧名称",
                    "modelField": "t_employee_profile.name",
                    "showInList": False,
                    "searchable": False,
                }],
                "listPageView": {
                    "queryConditions": [],
                    "queryList": [],
                },
            }
            self.saved = None

        async def query_form_config(self, _app_id, _form_id):
            return self.form_config

        async def save_form_config(self, _app_id, form_config):
            self.saved = form_config
            return {"code": "ok"}

    client = FakeClient()
    desired_components = [
        {
            "componentType": "FORM_TEXT_INPUT",
            "label": "姓名",
            "modelField": "t_employee_profile.name",
            "required": True,
            "hidden": False,
            "readonly": False,
            "showInList": True,
            "searchable": True,
        },
        {
            "componentType": "FORM_SELECT_INPUT_SINGLE",
            "label": "员工状态",
            "modelField": "t_employee_profile.employee_status",
            "dict": "employee_status",
            "showInList": True,
            "searchable": True,
        },
    ]

    changed_count = await _merge_existing_form_components(
        client,
        "app-1",
        "form-1",
        "员工档案",
        desired_components,
        ["t_employee_profile.name"],
        ["t_employee_profile.name", "t_employee_profile.employee_status"],
    )

    assert changed_count == 2
    assert client.saved["formName"] == "员工档案"
    assert client.saved["components"][0]["label"] == "姓名"
    assert client.saved["components"][0]["required"] is True
    assert client.saved["components"][0]["showInList"] is True
    assert client.saved["components"][0]["searchable"] is True
    assert client.saved["components"][1]["label"] == "员工状态"
    assert client.saved["components"][1]["dict"] == "employee_status"
    assert client.saved["listPageView"]["queryConditions"] == ["t_employee_profile.name"]
    assert client.saved["listPageView"]["queryList"] == [
        "t_employee_profile.name",
        "t_employee_profile.employee_status",
    ]


@pytest.mark.asyncio
async def test_reused_form_syncs_select_binding_props_for_existing_component():
    class FakeClient:
        def __init__(self):
            self.form_config = {
                "formName": "客户档案",
                "components": [{
                    "componentType": "FORM_TEXT_INPUT",
                    "label": "客户等级",
                    "modelField": "customer_profile.customer_level",
                }],
            }
            self.saved = None

        async def query_form_config(self, _app_id, _form_id):
            return self.form_config

        async def save_form_config(self, _app_id, form_config):
            self.saved = form_config
            return {"code": "ok"}

    choose_options = [{
        "id": "A",
        "label": "A级",
        "labelI18nAssociated": False,
        "color": "#027AFF",
        "status": "ENABLE",
        "checked": False,
        "displayOrder": 0,
    }]
    desired_components = [{
        "componentType": "FORM_SELECT_INPUT",
        "label": "客户等级",
        "modelField": "customer_profile.customer_level",
        "dict": "customer_level",
        "source": {"type": "DICTIONARY_TYPE", "id": "dict-id-1"},
        "chooseType": "SINGLE",
        "chooseOptions": choose_options,
        "dictionaryChooseOptions": choose_options,
        "dictionarySelectConfig": {
            "dictionaryCode": "customer_level",
            "dictionarySelectOptions": choose_options,
        },
        "multicolor": True,
        "dictionaryMulticolorStatus": "ENABLE",
    }]

    client = FakeClient()
    changed_count = await _merge_existing_form_components(
        client,
        "app-1",
        "form-1",
        "客户档案",
        desired_components,
    )

    assert changed_count == 1
    component = client.saved["components"][0]
    assert component["componentType"] == "FORM_SELECT_INPUT"
    assert component["source"] == {"type": "DICTIONARY_TYPE", "id": "dict-id-1"}
    assert component["chooseType"] == "SINGLE"
    assert component["chooseOptions"] == choose_options
    assert component["dictionaryChooseOptions"] == choose_options
    assert component["dictionarySelectConfig"]["dictionaryCode"] == "customer_level"
