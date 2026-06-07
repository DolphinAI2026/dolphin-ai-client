import json

import pytest

from app.apaas_client import APaaSClient
from app.coding.apaas_tools import _validate_builder_doc


class FailingModelClient(APaaSClient):
    async def _post_resource(self, path, payload, app_id=None):
        raise Exception("字段编码与数据库关键字重复")


@pytest.mark.asyncio
async def test_create_models_diagnostic_does_not_flag_business_tokens():
    client = FailingModelClient(base_url="http://apaas.local")
    payload = {
        "dataModels": [
            {
                "modelName": "拜访计划",
                "modelCode": "visit_plan",
                "fields": [
                    {"fieldName": "关联客户", "fieldCode": "related_customer"},
                    {"fieldName": "拜访时间", "fieldCode": "visit_time"},
                    {"fieldName": "计划状态", "fieldCode": "plan_status"},
                    {"fieldName": "计划编号", "fieldCode": "plan_no"},
                ],
            },
            {
                "modelName": "拜访记录",
                "modelCode": "visit_record",
                "fields": [
                    {"fieldName": "关联计划", "fieldCode": "related_plan"},
                    {"fieldName": "跟进动作", "fieldCode": "follow_action"},
                    {"fieldName": "附件备注", "fieldCode": "attachment_note"},
                    {"fieldName": "客户ID", "fieldCode": "customer_id"},
                    {"fieldName": "实际拜访时间", "fieldCode": "actual_visit_time"},
                ],
            },
        ],
    }

    with pytest.raises(Exception) as exc_info:
        await client.create_models("app-1", payload)

    message = str(exc_info.value)
    assert "token 级扫描" not in message
    assert "含保留字 token" not in message
    assert "status/type/code/date/time/note/file/user/no/id" not in message
    assert "不要仅因字段编码包含 customer/id/time/status/no 等业务 token 就改写" in message


@pytest.mark.asyncio
async def test_create_models_diagnostic_still_flags_approval_prefix():
    client = FailingModelClient(base_url="http://apaas.local")
    payload = {
        "dataModels": [
            {
                "modelName": "审批扩展",
                "modelCode": "approval_ext",
                "fields": [
                    {"fieldName": "审批备注", "fieldCode": "approval_comment"},
                ],
            }
        ],
    }

    with pytest.raises(Exception) as exc_info:
        await client.create_models("app-1", payload)

    message = str(exc_info.value)
    assert "approval_*" in message
    assert "approval_comment" in message


@pytest.mark.asyncio
async def test_builder_doc_validation_allows_application_id_but_flags_workflow_fields():
    ok_result = await _validate_builder_doc(
        {
            "md_content": (
                "应用元数据\n角色定义\n数据字典\n数据模型\n表单与流程\n权限矩阵\n页面与导航\n"
                "| 字段名称 | 字段编码 |\n| 应用ID | application_id |\n"
            )
        },
        platform_env_id=1,
        db=None,
    )
    ok_payload = json.loads(ok_result)
    assert ok_payload["valid"] is True
    assert ok_payload["reserved_field_hits"] == []

    bad_result = await _validate_builder_doc(
        {
            "md_content": (
                "应用元数据\n角色定义\n数据字典\n数据模型\n表单与流程\n权限矩阵\n页面与导航\n"
                "| 字段名称 | 字段编码 |\n| 审批人 | approver_id |\n| 审批备注 | approval_comment |\n"
            )
        },
        platform_env_id=1,
        db=None,
    )
    bad_payload = json.loads(bad_result)
    assert bad_payload["valid"] is False
    assert set(bad_payload["reserved_field_hits"]) == {"approver_id", "approval_comment"}
