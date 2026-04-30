from __future__ import annotations

import os
import sys

os.environ.setdefault("LLM_API_KEY", "test-key")
os.environ.setdefault("JWT_SECRET_KEY", "test-secret")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from app.routes.applications._doc_helpers import is_valid_doc_result, normalize_doc_result


def test_normalize_doc_result_completes_missing_spec_sections():
    raw = {
        "app_info": {
            "name": "日常巡检管理",
            "code": "app_mgmt",
            "description": "用于巡检记录和异常处理。",
        },
        "roles": [
            {"role_code": "employee", "role_name": "员工"},
            {"role_code": "supervisor", "role_name": "直属上级"},
        ],
        "data_dictionary": [],
        "tables": [
            {
                "table_code": "inspection_record",
                "table_name": "巡检记录",
                "fields": [
                    {"field_code": "id", "field_name": "主键ID", "is_pk": True},
                    {"field_code": "location", "field_name": "巡检位置", "data_type": "VARCHAR"},
                ],
            }
        ],
        "role_table_mapping": [],
    }

    normalized = normalize_doc_result(raw)

    assert is_valid_doc_result(normalized) is True
    assert normalized["roles"][0]["role_code"] == "business_admin"
    assert normalized["tables"][0]["table_code"] == "t_inspection_record"
    field_codes = [field["field_code"] for field in normalized["tables"][0]["fields"]]
    assert "id" not in field_codes
    assert len(field_codes) >= 6
    assert normalized["modules"]
    assert normalized["flows"]
    assert normalized["forms"]
    assert normalized["role_table_mapping"][0]["permissions"][0]["role_code"] == "all_employee"
    assert normalized["custom_development"][0]["type"] == "none"


def test_normalize_doc_result_preserves_actionable_custom_development():
    raw = {
        "app_info": {"name": "会议报名管理系统", "code": "meeting_req", "description": "会议报名。"},
        "roles": [{"role_code": "meeting_admin", "role_name": "会议管理员"}],
        "tables": [{"table_code": "meeting_apply", "table_name": "会议报名", "fields": []}],
        "custom_development": [
            {
                "type": "backend_api",
                "name": "会议名额校验接口",
                "trigger": "报名提交时需要实时校验会议名额和冲突规则",
                "scope": "提供名额校验 Hook 和接口",
                "acceptance": "重复报名和超额报名会被拦截",
            }
        ],
    }

    normalized = normalize_doc_result(raw)

    assert is_valid_doc_result(normalized) is True
    assert normalized["custom_development"][0]["type"] == "backend_api"
    assert normalized["forms"][0]["formName"] == "会议报名"
