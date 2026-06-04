import pytest

from app.services.config_converter import convert_analysis_to_app_config
from app.step_executor import execute_configure_permissions, execute_create_form


def _find_component(config, form_code, label):
    form = next(item for item in config["forms"] if item["code"] == form_code)
    return next(item for item in form["components"] if item["label"] == label)


def test_converter_keeps_business_form_names_and_field_metadata():
    config = convert_analysis_to_app_config({
        "app_info": {"name": "产品上市退市管理系统", "code": "prod_lifecycle"},
        "roles": [{"role_code": "product_manager", "role_name": "产品经理"}],
        "data_dictionary": [],
        "tables": [
            {
                "table_code": "customer_profile",
                "table_name": "客户档案",
                "table_type": "主表",
                "fields": [
                    {"field_code": "customer_name", "field_name": "客户名称", "data_type": "VARCHAR"},
                ],
            },
            {
                "table_code": "delisting_apply",
                "table_name": "用户表",
                "form_name": "退市申请表",
                "form_code": "delisting_apply_form",
                "table_type": "主表",
                "fields": [
                    {
                        "field_code": "apply_status",
                        "field_name": "申请状态",
                        "data_type": "VARCHAR",
                        "enum_values": ["待提交", "审核中", "已通过", "已驳回"],
                    },
                    {"field_code": "customer_id", "field_name": "客户", "data_type": "VARCHAR"},
                    {"field_code": "applicant", "field_name": "申请人", "data_type": "VARCHAR"},
                    {"field_code": "apply_dept", "field_name": "申请部门", "data_type": "VARCHAR"},
                ],
            },
        ],
    })

    form_names = [form["name"] for form in config["forms"]]
    assert len(form_names) == len(set(form_names))
    assert "用户表" not in form_names
    assert "退市申请表" in form_names

    status_field = next(field for model in config["models"] for field in model["fields"] if field["code"] == "apply_status")
    assert status_field["type"] == "下拉单选"
    assert status_field.get("dict")
    assert any(item["code"] == status_field["dict"] for item in config["dicts"])

    status_component = _find_component(config, "delisting_apply_form", "申请状态")
    assert status_component["dict"] == status_field["dict"]
    assert status_component["dictionarySelectConfig"]["dictionaryCode"] == status_field["dict"]

    customer_component = _find_component(config, "delisting_apply_form", "客户")
    assert customer_component["componentType"] == "FORM_DATA_SELECTOR_SINGLE"
    assert customer_component["ref_model_code"] == "customer_profile"
    assert customer_component["ref_display_field_code"] == "customer_name"

    assert _find_component(config, "delisting_apply_form", "申请人")["componentType"] == "FORM_PEOPLE_SELECT"
    assert _find_component(config, "delisting_apply_form", "申请部门")["componentType"] == "FORM_DEPARTMENT_SELECT"


@pytest.mark.asyncio
async def test_execute_create_form_finalizes_detail_config_after_create():
    class FakeClient:
        def __init__(self):
            self.calls = []
            self.saved = None

        async def create_form_config(self, app_id, payload):
            self.calls.append(("create_form_config", payload))
            return [{"id": "form-1", "formCode": "delisting_apply_form", "menuId": "menu-1"}]

        async def create_menu(self, *args, **kwargs):
            self.calls.append(("create_menu", args, kwargs))
            return {"ok": True}

        async def query_detail_page_config(self, app_id, form_id):
            self.calls.append(("query_detail_page_config", form_id))
            return {
                "id": form_id,
                "formName": "我的待办",
                "formCode": "old_form",
                "detailPage": {"formComponents": []},
            }

        async def save_form_config(self, app_id, form_config):
            self.calls.append(("save_form_config", form_config))
            self.saved = form_config
            return {"code": "ok"}

    client = FakeClient()
    result = await execute_create_form(
        client,
        app_id="app-1",
        form={
            "name": "退市申请表",
            "code": "delisting_apply_form",
            "modelCode": "delisting_apply",
            "components": [
                {"label": "申请名称", "code": "apply_name", "componentType": "FORM_TEXT_INPUT", "modelField": "delisting_apply.apply_name"},
            ],
        },
        form_index=0,
        dict_codes={},
        model_info={"0": {"name": "退市申请", "code": "delisting_apply", "fields": {"申请名称": "apply_name"}}},
        all_models=[],
        all_forms=[],
        form_results=[],
    )

    methods = [call[0] for call in client.calls]
    assert result["formId"] == "form-1"
    assert methods.index("save_form_config") > methods.index("create_form_config")
    assert client.saved["formName"] == "退市申请表"
    assert client.saved["formCode"] == "delisting_apply_form"
    assert client.saved["appId"] == "app-1"
    assert client.saved["menuId"] == "menu-1"
    assert client.saved["detailPage"]["formName"] == "退市申请表"
    assert client.saved["detailPage"]["formCode"] == "delisting_apply_form"


@pytest.mark.asyncio
async def test_execute_configure_permissions_syncs_form_config_by_form_code():
    class FakeClient:
        def __init__(self):
            self.permission_payloads = []
            self.saved_configs = []

        async def create_form_permissions(self, app_id, payloads):
            self.permission_payloads.append(payloads)
            return {"ok": True}

        async def query_detail_page_config(self, app_id, form_id):
            return {"id": form_id, "formName": "同名表单", "detailPage": {}}

        async def save_form_config(self, app_id, form_config):
            self.saved_configs.append(form_config)
            return {"code": "ok"}

    client = FakeClient()
    result = await execute_configure_permissions(
        client,
        app_id="app-1",
        permissions=[
            {"formCode": "target_form", "rules": [{"role": "product_manager", "op": "all", "data": "ALL"}]},
            {"form": "同名表单", "rules": [{"role": "all", "op": "view", "data": "SELF"}]},
        ],
        form_results=[
            {"formId": "form-a", "formName": "同名表单", "formCode": "other_form", "modelCode": "other"},
            {"formId": "form-b", "formName": "同名表单", "formCode": "target_form", "modelCode": "target"},
        ],
        role_codes={"product_manager": {"id": "role-1", "roleCode": "product_manager", "roleName": "产品经理"}},
        all_forms=[],
    )

    assert result["permissions_count"] == 2
    target_payload = next(item for item in client.permission_payloads[0] if item["formCode"] == "target_form")
    assert target_payload["dataPermissionGroups"][0]["permissionObjects"][0]["permissionObjectType"] == "ROLE"
    saved_target = next(item for item in client.saved_configs if item["formCode"] == "target_form")
    assert saved_target["advancedPermissionGroups"][0]["permissionObjects"][0]["permissionObjectType"] == "ROLE_USER"
    assert saved_target["detailPage"]["advancedPermissionGroups"][0]["permissionObjects"][0]["permissionObjectType"] == "ROLE_USER"
