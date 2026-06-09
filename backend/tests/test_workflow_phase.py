"""Phase 5：workflow → payload 装配 + 非致命建流程循环。"""
from __future__ import annotations

import pytest

from app import workflow_phase
from app.step_executor import execute_create_workflow
from app.routes.generation_steps import _critical_step_keys


FORM_RESULTS = [
    {"formId": "F_report", "formCode": "test_report", "formName": "检测报告", "menuId": "M_report"},
]
ROLE_MAP = {
    "role_team_leader": {"roleCode": "role_team_leader", "roleName": "班组长", "id": "RID_1"},
    "role_quality_mgr": {"roleCode": "role_quality_mgr", "roleName": "质量经理", "id": "RID_2"},
}
WF = {
    "name": "检测报告审批流",
    "form_code": "test_report",
    "nodes": [
        {"name": "班组长审批", "role_code": "role_team_leader"},
        {"name": "质量经理审批", "role_code": "role_quality_mgr"},
    ],
}


def test_build_payload_binds_form_and_role_ids():
    payload, reason = workflow_phase.build_workflow_payload(WF, FORM_RESULTS, ROLE_MAP, app_id="app1")
    assert reason is None
    assert payload["processDataSource"]["objectId"] == "boc_code_F_report"
    assert payload["formId"] == "F_report"
    assert payload["menuId"] == "M_report"
    approve_nodes = [n for n in payload["nodes"] if n["id"] not in ("START", "END")]
    assert approve_nodes[0]["data"]["approvers"][0]["value"] == "RID_1"  # 角色 id 不是 code
    assert approve_nodes[1]["data"]["approvers"][0]["value"] == "RID_2"


def test_build_payload_missing_form_returns_reason():
    payload, reason = workflow_phase.build_workflow_payload(
        {**WF, "form_code": "nope"}, FORM_RESULTS, ROLE_MAP, app_id="app1"
    )
    assert payload is None
    assert reason and "nope" in reason


def test_build_payload_missing_role_returns_reason():
    wf = {**WF, "nodes": [{"name": "审批", "role_code": "role_unknown"}]}
    payload, reason = workflow_phase.build_workflow_payload(wf, FORM_RESULTS, ROLE_MAP, app_id="app1")
    assert payload is None
    assert reason and "role_unknown" in reason


@pytest.mark.asyncio
async def test_create_workflows_calls_save_and_is_non_fatal():
    saved = []

    class _FakeClient:
        async def save_process_config(self, app_id, payload):
            saved.append((app_id, payload))
            return {"code": "ok"}

    good = WF
    bad_form = {**WF, "name": "坏的", "form_code": "missing_form"}
    events = []
    async for ev in workflow_phase.create_workflows(
        _FakeClient(), "app1", [good, bad_form], FORM_RESULTS, ROLE_MAP
    ):
        events.append(ev)

    assert len(saved) == 1
    assert saved[0][1]["processName"] == "检测报告审批流"
    assert any(e.get("stage") == 5 for e in events)
    assert any("坏的" in (e.get("step") or "") for e in events)


@pytest.mark.asyncio
async def test_create_workflows_save_failure_does_not_raise():
    class _BoomClient:
        async def save_process_config(self, app_id, payload):
            raise RuntimeError("platform 500")

    events = []
    async for ev in workflow_phase.create_workflows(
        _BoomClient(), "app1", [WF], FORM_RESULTS, ROLE_MAP
    ):
        events.append(ev)
    assert any(e.get("stage") == 5 for e in events)


@pytest.mark.asyncio
async def test_step_executor_workflow_accepts_standard_form_and_role_codes():
    saved = []

    class _FakeClient:
        async def save_process_config(self, app_id, payload):
            saved.append((app_id, payload))
            return {"code": "ok"}

    result = await execute_create_workflow(
        _FakeClient(),
        "app1",
        {
            "name": "订单审批",
            "form_code": "order_form",
            "nodes": [{"name": "经理审批", "role_code": "manager"}],
        },
        [{"formId": "F1", "formCode": "order_form", "formName": "订单", "menuId": "M1"}],
        {"manager": {"roleCode": "manager_x", "roleName": "经理"}},
    )

    assert result["message"].startswith("流程创建成功")
    assert saved[0][1]["menuId"] == "M1"
    approve_nodes = [node for node in saved[0][1]["nodes"] if node["id"].startswith("UserTask_")]
    assert approve_nodes[0]["data"]["approvers"][0]["approverCode"] == "manager_x"


def test_generation_step_keys_include_workflows():
    keys = _critical_step_keys({
        "data": {
            "roles": [],
            "dicts": [],
            "models": [],
            "forms": [{"code": "order_form"}],
            "workflows": [{"name": "订单审批", "form_code": "order_form", "nodes": []}],
        }
    })

    assert "create_form:0" in keys
    assert "create_workflow:0" in keys
