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
