import pytest

from app import mcp_server


@pytest.mark.asyncio
async def test_spec_builder_rejects_select_without_dictionary():
    result = await mcp_server.build_apaas_feature_from_spec(
        env_id=1,
        apaas_app_id="app_1",
        feature_name="退市项目申请",
        feature_code="delisting_apply",
        fields=[
            {
                "name": "申请状态",
                "code": "apply_status",
                "type": "下拉单选",
            },
        ],
    )

    assert result["ok"] is False
    assert result["error_code"] == "SELECT_FIELD_NEEDS_DICTIONARY"
    assert "dict_options" in result["message"]


@pytest.mark.asyncio
async def test_spec_builder_rejects_data_selector_without_ref():
    result = await mcp_server.build_apaas_feature_from_spec(
        env_id=1,
        apaas_app_id="app_1",
        feature_name="退市项目申请",
        feature_code="delisting_apply",
        fields=[
            {
                "name": "客户",
                "code": "customer_id",
                "type": "数据单选",
            },
        ],
    )

    assert result["ok"] is False
    assert result["error_code"] == "DATA_SELECTOR_NEEDS_REF"
    assert "ref.model" in result["message"]


@pytest.mark.asyncio
async def test_post_configure_binds_dropdown_selector_and_permissions():
    class FakeClient:
        def __init__(self):
            self.simple_form = {
                "id": "form_apply",
                "detailPage": {
                    "formComponents": [
                        {
                            "uuid": "cmp_status",
                            "componentType": "FORM_SELECT_INPUT_SINGLE",
                            "label": "申请状态",
                            "modelField": "delisting_apply.apply_status",
                        }
                    ]
                },
            }
            self.current_detail = {
                "id": "form_apply",
                "formName": "退市项目申请",
                "modelCode": "delisting_apply",
                "detailPage": {
                    "formComponents": [
                        {
                            "uuid": "cmp_customer",
                            "componentType": "FORM_DATA_SELECTOR_SINGLE",
                            "label": "客户",
                            "modelField": "delisting_apply.customer_id",
                            "dataSelectorConfig": {"otherModelCode": "customer_profile"},
                        }
                    ]
                },
            }
            self.target_detail = {
                "id": "form_customer",
                "formName": "客户档案",
                "modelCode": "customer_profile",
                "detailPage": {
                    "formComponents": [
                        {
                            "uuid": "cmp_customer_name",
                            "componentType": "FORM_TEXT_INPUT",
                            "label": "客户名称",
                            "modelField": "customer_profile.customer_name",
                        }
                    ]
                },
            }
            self.saved_forms = []
            self.permission_payloads = []

        async def query_dicts(self, app_id):
            return [{"id": "dict_1", "dictionaryCode": "apply_status_dict"}]

        async def query_dict_options(self, app_id, dict_id):
            return [
                {"optionCode": "draft", "optionName": "草稿", "displayOrder": 1},
                {"optionCode": "submitted", "optionName": "已提交", "displayOrder": 2},
            ]

        async def query_form_config(self, app_id, form_id):
            return self.simple_form

        async def save_form_config(self, app_id, form_config):
            self.saved_forms.append(form_config)
            return {"ok": True}

        async def list_form_menus_for_event(self, app_id):
            return [{"form_id": "form_customer", "menu_name": "客户档案"}]

        async def query_detail_page_config(self, app_id, form_id):
            return self.target_detail if form_id == "form_customer" else self.current_detail

        async def query_roles(self, app_id):
            return [{"id": "role_admin_id", "roleCode": "admin", "roleName": "管理员"}]

        async def create_form_permissions(self, app_id, payload):
            self.permission_payloads.append(payload)
            return {"ok": True}

    fake = FakeClient()
    result = await mcp_server._post_configure_feature_form_quality(
        fake,
        app_id="app_1",
        form_id="form_apply",
        form_code="delisting_apply_form",
        fields=[
            {
                "name": "申请状态",
                "code": "apply_status",
                "type": "下拉单选",
                "dict_code": "apply_status_dict",
            },
            {
                "name": "客户",
                "code": "customer_id",
                "type": "数据单选",
                "ref": {"model": "customer_profile", "field": "customer_name"},
            },
        ],
        field_to_dict_code={},
    )

    assert result["dict_bound"] == 1
    assert result["data_selector_bound"] == 1
    assert result["permissions_configured"] is True
    select = fake.simple_form["detailPage"]["formComponents"][0]
    assert select["source"] == {"type": "DICTIONARY_TYPE", "id": "dict_1"}
    assert [item["label"] for item in select["chooseOptions"]] == ["草稿", "已提交"]
    selector = fake.current_detail["detailPage"]["formComponents"][0]
    assert selector["dataSelector"]["otherFormId"] == "form_customer"
    assert selector["dataSelector"]["otherComponent"] == "cmp_customer_name"
    assert "dataSelectorConfig" not in selector
    payload = fake.permission_payloads[0][0]
    assert payload["formCode"] == "delisting_apply_form"
    assert len(payload["dataPermissionGroups"]) == 2
    assert len(payload["operationPermissionGroups"]) == 2
