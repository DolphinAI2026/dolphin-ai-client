import asyncio

import pytest

from app.step_executor import execute_create_workflow
from app.workflow_phase import build_workflow_payload


FORM_RESULTS = [
    {
        "formId": "form_1",
        "formCode": "leave_request",
        "formName": "请假申请",
        "menuId": "menu_1",
    }
]

ROLE_CODES = {
    "dept_manager": {
        "id": "role_id_1",
        "roleCode": "dept_manager_abc",
        "roleName": "部门经理",
    }
}


def test_build_workflow_payload_accepts_legacy_form_and_role_keys():
    workflow = {
        "name": "请假审批",
        "form": "请假申请",
        "nodes": [
            {"name": "发起申请", "role": "", "type": "start"},
            {"name": "部门经理审批", "role": "dept_manager", "type": "approve"},
            {"name": "结束", "role": "", "type": "end"},
        ],
    }

    payload, reason = build_workflow_payload(
        workflow,
        FORM_RESULTS,
        ROLE_CODES,
        app_id="app_1",
    )

    assert reason is None
    assert payload is not None
    approve_nodes = [
        node for node in payload["nodes"]
        if node.get("data", {}).get("type") == "APPROVE"
    ]
    assert len(approve_nodes) == 1
    approver = approve_nodes[0]["data"]["approvers"][0]
    assert approver["type"] == "ROLE"
    assert approver["value"] == "role_id_1"
    assert payload["processCode"] == "proc_leave_request"
    assert "START_HIDDEN" in payload["bpmn"]


def test_build_workflow_payload_rejects_workflow_without_real_approval_nodes():
    workflow = {
        "name": "空流程",
        "form_code": "leave_request",
        "nodes": [
            {"name": "发起申请", "type": "start"},
            {"name": "结束", "type": "end"},
        ],
    }

    payload, reason = build_workflow_payload(
        workflow,
        FORM_RESULTS,
        ROLE_CODES,
        app_id="app_1",
    )

    assert payload is None
    assert "无有效审批节点" in reason


def test_execute_create_workflow_raises_instead_of_marking_skipped_as_done():
    class DummyClient:
        async def save_process_config(self, app_id, payload):  # pragma: no cover
            raise AssertionError("empty workflow must not be saved")

    workflow = {"name": "空流程", "form": "请假申请", "nodes": []}

    with pytest.raises(ValueError, match="无有效审批节点"):
        asyncio.run(
            execute_create_workflow(
                DummyClient(),
                "app_1",
                workflow,
                FORM_RESULTS,
                ROLE_CODES,
            )
        )


def test_execute_create_workflow_saves_unified_payload():
    class DummyClient:
        def __init__(self):
            self.saved = None

        async def save_process_config(self, app_id, payload):
            self.saved = (app_id, payload)

    client = DummyClient()
    workflow = {
        "name": "请假审批",
        "form": "请假申请",
        "nodes": [
            {"name": "部门经理审批", "role": "dept_manager", "type": "approve"},
        ],
    }

    result = asyncio.run(
        execute_create_workflow(
            client,
            "app_1",
            workflow,
            FORM_RESULTS,
            ROLE_CODES,
        )
    )

    assert result["nodes_count"] == 3
    assert result["edges_count"] == 2
    assert result["process_code"] == "proc_leave_request"
    assert client.saved[0] == "app_1"
    assert client.saved[1]["processDataSource"]["objectId"] == "boc_code_form_1"
