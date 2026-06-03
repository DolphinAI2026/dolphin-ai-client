from app.services.config_converter import convert_analysis_to_app_config


def _base_doc(tables, dicts=None):
    return {
        "app_info": {"name": "质量管理系统", "code": "quality-mgmt"},
        "roles": [],
        "data_dictionary": dicts or [],
        "tables": tables,
        "flows": [],
        "role_table_mapping": [],
    }


def test_business_reference_field_becomes_data_selector_with_target_model():
    config = convert_analysis_to_app_config(_base_doc([
        {
            "table_code": "customer_profile",
            "table_name": "客户档案",
            "fields": [
                {"field_code": "customer_name", "field_name": "客户名称", "data_type": "VARCHAR"},
                {"field_code": "customer_no", "field_name": "客户编号", "data_type": "VARCHAR"},
            ],
        },
        {
            "table_code": "contract_apply",
            "table_name": "合同申请",
            "fields": [
                {"field_code": "customer_id", "field_name": "客户", "data_type": "VARCHAR"},
                {"field_code": "contract_amount", "field_name": "合同金额", "data_type": "DECIMAL"},
            ],
        },
    ]))

    contract = next(model for model in config["models"] if model["code"] == "contract_apply")
    customer_field = next(field for field in contract["fields"] if field["code"] == "customer_id")
    assert customer_field["type"] == "数据单选"
    assert customer_field["ref"] == {"model": "customer_profile", "field": "customer_name"}

    contract_form = next(form for form in config["forms"] if form["modelCode"] == "contract_apply")
    customer_component = next(component for component in contract_form["components"] if component["label"] == "客户")
    assert customer_component["componentType"] == "FORM_DATA_SELECTOR_SINGLE"
    assert customer_component["ref_model_code"] == "customer_profile"
    assert customer_component["ref_display_field_code"] == "customer_name"


def test_select_field_with_inline_options_gets_dictionary_binding():
    config = convert_analysis_to_app_config(_base_doc([
        {
            "table_code": "launch_apply",
            "table_name": "上市申请",
            "fields": [
                {
                    "field_code": "apply_status",
                    "field_name": "申请状态",
                    "data_type": "VARCHAR",
                    "options": ["草稿", "已提交", "已审批"],
                },
            ],
        },
    ]))

    status = config["models"][0]["fields"][0]
    assert status["type"] == "下拉单选"
    assert status["dict"] == "launch_apply_apply_status_dict"
    assert config["dicts"] == [{
        "name": "申请状态选项",
        "code": "launch_apply_apply_status_dict",
        "options": [
            {"name": "草稿", "code": "option_1"},
            {"name": "已提交", "code": "option_2"},
            {"name": "已审批", "code": "option_3"},
        ],
    }]

    component = config["forms"][0]["components"][0]
    assert component["componentType"] == "FORM_SELECT_INPUT_SINGLE"
    assert component["dict"] == "launch_apply_apply_status_dict"


def test_generic_or_duplicate_form_names_are_made_identifiable_and_unique():
    config = convert_analysis_to_app_config(_base_doc([
        {
            "table_code": "project_apply",
            "table_name": "立项申请",
            "form_name": "新增表单",
            "fields": [{"field_code": "title", "field_name": "标题", "data_type": "VARCHAR"}],
        },
        {
            "table_code": "project_review",
            "table_name": "立项评审",
            "form_name": "新增表单",
            "fields": [{"field_code": "title", "field_name": "标题", "data_type": "VARCHAR"}],
        },
    ]))

    names = [form["formName"] for form in config["forms"]]
    assert names == ["立项申请-新增表单", "立项评审-新增表单"]
    assert len(names) == len(set(names))
