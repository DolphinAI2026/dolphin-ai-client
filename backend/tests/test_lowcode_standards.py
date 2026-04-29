from app.lowcode_standards import normalize_preview_config
from app.step_executor import _build_model_field_payload


def test_preview_config_normalizes_db_types_components_and_reserved_field_codes():
    config = {
        "type": "preview",
        "data": {
            "models": [
                {
                    "name": "招聘需求",
                    "code": "t_job_requisition",
                    "fields": [
                        {"name": "岗位名称", "code": "title", "type": "text"},
                        {"name": "需求部门", "code": "department", "type": "department"},
                        {"name": "招聘人数", "code": "headcount", "type": "number"},
                        {"name": "招聘状态", "code": "status", "type": "dict", "dict": "job_status"},
                        {"name": "岗位职责", "code": "job_description", "type": "textarea"},
                    ],
                }
            ],
            "forms": [
                {
                    "name": "招聘需求",
                    "code": "t_job_requisition",
                    "modelCode": "t_job_requisition",
                    "components": [
                        {"code": "title", "componentType": "text", "modelField": "t_job_requisition.title"},
                        {"code": "department", "componentType": "department", "modelField": "t_job_requisition.department"},
                        {"code": "status", "componentType": "dict", "modelField": "t_job_requisition.status"},
                    ],
                }
            ],
        },
    }

    normalized, changed, meta = normalize_preview_config(config)

    assert changed is True
    assert meta["field_code_map"]["t_job_requisition"] == {
        "title": "job_requisition_title",
        "department": "job_requisition_department",
        "status": "job_requisition_status",
    }
    fields = normalized["data"]["models"][0]["fields"]
    assert [(f["code"], f["type"], f["databaseFieldType"]) for f in fields] == [
        ("job_requisition_title", "单行输入", "varchar"),
        ("job_requisition_department", "部门选择", "varchar"),
        ("headcount", "数字", "int"),
        ("job_requisition_status", "下拉单选", "varchar"),
        ("job_description", "多行输入", "text"),
    ]
    components = normalized["data"]["forms"][0]["components"]
    assert components[0]["modelField"] == "t_job_requisition.job_requisition_title"
    assert components[1]["componentType"] == "FORM_DEPARTMENT_SELECT"
    assert components[2]["componentType"] == "FORM_SELECT_INPUT_SINGLE"
    assert components[2]["dict"] == "job_status"
    assert components[2]["dict_code"] == "job_status"


def test_preview_config_infers_form_component_dict_from_model_field():
    config = {
        "data": {
            "models": [{
                "name": "员工档案",
                "code": "t_employee_profile",
                "fields": [{
                    "name": "员工状态",
                    "code": "employee_profile_status",
                    "type": "下拉单选",
                    "dict": "employee_status",
                }],
            }],
            "forms": [{
                "name": "员工档案",
                "modelCode": "t_employee_profile",
                "components": [{
                    "label": "员工状态",
                    "code": "employee_profile_status",
                    "modelField": "t_employee_profile.employee_profile_status",
                    "componentType": "FORM_SELECT_INPUT_SINGLE",
                }],
            }],
        },
    }

    normalized, changed, _meta = normalize_preview_config(config)

    component = normalized["data"]["forms"][0]["components"][0]
    assert changed is True
    assert component["dict"] == "employee_status"
    assert component["dict_code"] == "employee_status"
    assert component["componentType"] == "FORM_SELECT_INPUT_SINGLE"


def test_preview_config_backfills_standard_form_component_flags():
    config = {
        "data": {
            "models": [{
                "name": "招聘需求",
                "code": "t_job_requisition",
                "fields": [
                    {"name": "岗位名称", "code": "job_title", "type": "单行输入", "required": True},
                    {"name": "招聘状态", "code": "job_status", "type": "下拉单选", "dict": "job_status"},
                    {"name": "岗位职责", "code": "job_description", "type": "多行输入"},
                ],
            }],
            "forms": [{
                "name": "招聘需求",
                "modelCode": "t_job_requisition",
                "components": [
                    {"label": "岗位名称", "code": "job_title", "modelField": "t_job_requisition.job_title"},
                    {"label": "招聘状态", "code": "job_status", "modelField": "t_job_requisition.job_status"},
                    {"label": "岗位职责", "code": "job_description", "modelField": "t_job_requisition.job_description"},
                ],
            }],
        },
    }

    normalized, changed, _meta = normalize_preview_config(config)

    components = normalized["data"]["forms"][0]["components"]
    assert changed is True
    assert components[0]["required"] is True
    assert components[0]["hidden"] is False
    assert components[0]["readonly"] is False
    assert components[0]["showInList"] is True
    assert components[0]["searchable"] is True
    assert components[1]["dictCode"] == "job_status"
    assert components[1]["showInList"] is True
    assert components[1]["searchable"] is True
    assert components[2]["componentType"] == "FORM_TEXTAREA_INPUT"
    assert components[2]["showInList"] is False
    assert components[2]["searchable"] is False


def test_preview_config_preserves_explicit_false_form_flags():
    config = {
        "data": {
            "models": [{
                "name": "员工档案",
                "code": "t_employee_profile",
                "fields": [{"name": "姓名", "code": "name", "type": "单行输入", "required": True}],
            }],
            "forms": [{
                "name": "员工档案",
                "modelCode": "t_employee_profile",
                "components": [{
                    "label": "姓名",
                    "code": "name",
                    "modelField": "t_employee_profile.name",
                    "showInList": False,
                    "searchable": False,
                }],
            }],
        },
    }

    normalized, _changed, _meta = normalize_preview_config(config)

    component = normalized["data"]["forms"][0]["components"][0]
    assert component["required"] is True
    assert component["showInList"] is False
    assert component["searchable"] is False


def test_preview_config_updates_ref_targets_after_field_code_normalization():
    config = {
        "data": {
            "models": [
                {
                    "name": "招聘需求",
                    "code": "t_job_requisition",
                    "fields": [{"name": "岗位名称", "code": "title", "type": "单行输入"}],
                },
                {
                    "name": "候选人",
                    "code": "t_candidate",
                    "fields": [{
                        "name": "应聘岗位",
                        "code": "applied_job",
                        "type": "数据单选",
                        "ref": {"model": "t_job_requisition", "field": "title"},
                    }],
                },
            ],
            "forms": [{
                "name": "候选人",
                "modelCode": "t_candidate",
                "components": [{
                    "label": "应聘岗位",
                    "code": "applied_job",
                    "modelField": "t_candidate.applied_job",
                }],
            }],
        },
    }

    normalized, changed, meta = normalize_preview_config(config)

    candidate_field = normalized["data"]["models"][1]["fields"][0]
    candidate_component = normalized["data"]["forms"][0]["components"][0]
    assert changed is True
    assert meta["field_code_map"]["t_job_requisition"] == {"title": "job_requisition_title"}
    assert candidate_field["ref"]["field"] == "job_requisition_title"
    assert candidate_component["ref"]["field"] == "job_requisition_title"
    assert candidate_component["componentType"] == "FORM_DATA_SELECTOR_SINGLE"


def test_model_payload_uses_safe_field_code_and_standard_database_type():
    payload = _build_model_field_payload(
        {
            "name": "招聘状态",
            "code": "status",
            "type": "dict",
            "_model_code": "t_job_requisition",
        }
    )

    assert payload["fieldCode"] == "job_requisition_status"
    assert payload["fieldType"] == "STRING"
    assert payload["databaseFieldType"] == "varchar"
