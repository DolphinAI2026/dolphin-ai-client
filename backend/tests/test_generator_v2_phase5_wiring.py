"""run_complete_generation 接上 Phase 5：config 带 workflows 时会调 save_process_config。

只验证「接线」——Phase 5 被调用、save_process_config 收到平台设计器同款 payload；
前 4 个 phase 用 mock client 各自跑过即可（不验证 1-4 的细节）。

方法名/返回结构按 run_complete_generation 实际调用对齐：
  - 角色: create_roles + query_roles（query_roles 必须回带 id 的角色，按 roleName 匹配，
    Phase 5 build_workflow_payload 反查节点审批人靠 role_code_map[code]["id"]）
  - 模型: query_models（先空=全新）→ create_models → _refresh_model_codes_from_platform 再 query_models
  - 表单: query_menus（_load_existing_form_menus，空）→ create_form_config（返 list，含 formCode/id/menuId）
    → create_menu
  - 权限: permissions=[] → 每个表单 user_perm=None → 不下发，Phase 4 仍 yield stage:4 done
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from app import generator_v2


@pytest.mark.asyncio
async def test_phase5_creates_workflow_from_config():
    client = MagicMock()
    client.create_roles = AsyncMock(return_value={"code": "ok"})
    # query_roles 回带 snowflake id；按 roleName 匹配（平台 roleCode 会被加随机后缀）
    client.query_roles = AsyncMock(
        return_value=[{"id": "RID_1", "roleCode": "role_a_x", "roleName": "审批角色"}]
    )
    # 模型查询：先空（全部当新建）；create_models 后的回查也用同一个 mock 返空，
    # 此时 model_info 里保留本地构建的 code/fields，足够 Phase 3 建表单。
    client.query_models = AsyncMock(return_value=[])
    client.create_models = AsyncMock(return_value=[])
    client.query_dicts = AsyncMock(return_value=[])
    client.create_dicts = AsyncMock(return_value={"code": "ok"})
    # _load_existing_form_menus → query_menus；空表示无已存在表单
    client.query_menus = AsyncMock(return_value=[])
    # create_form_config 返 list（真实形状），含 formCode 让 Phase 5 按 form_code 反查得到 formId
    client.create_form_config = AsyncMock(
        return_value=[{"id": "F1", "formCode": "order", "formName": "订单", "menuId": "M1"}]
    )
    client.create_menu = AsyncMock(return_value={"code": "ok"})
    client.save_process_config = AsyncMock(return_value={"code": "ok"})

    config = {
        "data": {
            "appName": "下单", "appCode": "order-app",
            "roles": [{"code": "role_a", "name": "审批角色"}],
            "dicts": [],
            "models": [{"code": "order", "name": "订单", "fields": [{"code": "amount", "name": "金额", "type": "金额"}]}],
            "forms": [{"code": "order", "name": "订单", "modelCode": "order"}],
            "permissions": [],
            "workflows": [{
                "name": "订单审批流", "form_code": "order",
                "nodes": [{"name": "审批", "role_code": "role_a"}],
            }],
        }
    }

    events = []
    async for ev in generator_v2.run_complete_generation(client, "app1", config):
        events.append(ev)

    assert any(e.get("stage") == 5 for e in events), f"Phase 5 没跑：{[e.get('stage') for e in events]}"
    client.save_process_config.assert_awaited()
    _app_id, payload = client.save_process_config.await_args.args
    assert "processName" not in payload
    assert "processDataSource" not in payload
    assert payload["formId"] == "F1"
