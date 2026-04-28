from app.doc_standard_parser import parse
from app.routes.requirements import json_to_markdown, normalize_doc_result
from app.services.design_doc_preflight import validate_design_doc_preflight


def _base_doc() -> dict:
    return {
        "app_info": {
            "code": "expense_app",
            "name": "报销管理系统",
            "description": "管理员工报销申请、审核和付款归档。",
        },
        "roles": [
            {"role_code": "employee", "role_name": "员工", "description": "提交报销申请"},
            {"role_code": "finance", "role_name": "财务", "description": "复核票据并登记付款"},
        ],
        "data_dictionary": [
            {
                "dict_code": "expense_type",
                "dict_name": "报销类型",
                "items": [
                    {"item_code": "travel", "item_name": "差旅"},
                    {"item_code": "office", "item_name": "办公用品"},
                ],
            },
            {
                "dict_code": "request_status",
                "dict_name": "报销状态",
                "items": [
                    {"item_code": "draft", "item_name": "草稿"},
                    {"item_code": "submitted", "item_name": "已提交"},
                ],
            },
        ],
        "tables": [
            {
                "table_code": "t_expense_request",
                "table_name": "报销申请",
                "table_type": "主表",
                "parent_table": "",
                "description": "员工发起的一次报销申请。",
                "fields": [
                    {"field_code": "request_no", "field_name": "申请编号", "data_type": "VARCHAR", "length": "64", "nullable": False},
                    {"field_code": "applicant_name", "field_name": "申请人", "data_type": "VARCHAR", "length": "64", "nullable": False},
                    {"field_code": "department_name", "field_name": "所属部门", "data_type": "VARCHAR", "length": "64", "nullable": False},
                    {"field_code": "expense_type", "field_name": "报销类型", "data_type": "VARCHAR", "length": "32", "nullable": False, "dict_code": "expense_type"},
                    {"field_code": "amount_total", "field_name": "报销金额", "data_type": "DECIMAL", "length": "18,2", "nullable": False},
                    {"field_code": "request_status", "field_name": "报销状态", "data_type": "VARCHAR", "length": "32", "nullable": False, "dict_code": "request_status"},
                ],
            }
        ],
        "forms": [
            {
                "form_code": "expense_request_form",
                "form_name": "报销申请表",
                "model_code": "t_expense_request",
                "components": [
                    {"field_code": "request_no", "field_name": "申请编号", "component_type": "FORM_TEXT_INPUT", "required": True, "show_in_list": True},
                    {"field_code": "applicant_name", "field_name": "申请人", "component_type": "FORM_TEXT_INPUT", "required": True, "show_in_list": True},
                    {"field_code": "department_name", "field_name": "所属部门", "component_type": "FORM_TEXT_INPUT", "required": True, "show_in_list": True},
                    {"field_code": "expense_type", "field_name": "报销类型", "component_type": "FORM_SELECT", "required": True, "show_in_list": True, "dict_code": "expense_type"},
                    {"field_code": "amount_total", "field_name": "报销金额", "component_type": "FORM_NUMBER_INPUT", "required": True, "show_in_list": True},
                    {"field_code": "request_status", "field_name": "报销状态", "component_type": "FORM_SELECT", "required": True, "show_in_list": True, "dict_code": "request_status"},
                ],
            }
        ],
        "modules": [
            {
                "module_code": "expense",
                "module_name": "报销管理",
                "description": "报销申请和财务复核。",
                "features": [],
            }
        ],
        "flows": [
            {
                "flow_code": "expense_approval",
                "flow_name": "报销审批流程",
                "description": "员工提交后由财务复核。",
                "steps": [
                    {"step": 1, "action": "提交申请", "role": "employee", "status": "已提交"},
                    {"step": 2, "action": "财务复核", "role": "finance", "status": "已复核"},
                ],
            }
        ],
        "role_table_mapping": [
            {
                "table_code": "t_expense_request",
                "table_name": "报销申请表",
                "permissions": [
                    {"role_code": "employee", "role_name": "员工", "operations": ["新增", "查看", "编辑"], "data_scope": "self"},
                    {"role_code": "finance", "role_name": "财务", "operations": ["查看", "编辑", "导出"], "data_scope": "all"},
                ],
            }
        ],
    }


def test_preflight_blocks_duplicate_model_code():
    doc = _base_doc()
    doc["tables"].append({
        **doc["tables"][0],
        "table_name": "重复报销模型",
    })

    result = validate_design_doc_preflight(doc)

    assert not result.ok
    assert any(issue.code == "model_code_conflict" for issue in result.blocking_issues)
    assert "请给这个模型一个新的英文编码" in result.assistant_message


def test_preflight_blocks_reserved_field_code():
    doc = _base_doc()
    doc["tables"][0]["fields"][5]["field_code"] = "status"

    result = validate_design_doc_preflight(doc)

    assert not result.ok
    assert any(issue.code == "field_code_reserved" for issue in result.blocking_issues)
    assert "状态字段用 request_status" in result.assistant_message


def test_standard_markdown_is_parseable_and_omits_custom_development():
    normalized = normalize_doc_result(_base_doc(), [])
    preflight = validate_design_doc_preflight(normalized)
    assert preflight.ok

    markdown = json_to_markdown(normalized)
    parsed = parse(markdown)

    assert "## 七、权限定义" in markdown
    assert "## 七、自开发定义" not in markdown
    assert parsed.config["appName"] == "报销管理系统"
    assert parsed.config["models"]
    assert parsed.config["forms"]
    assert not parsed.has_critical_failure
