"""抽出的流程 payload builder 契约 —— 护住已抓包验证的字段，保证抽取不改行为。"""
from __future__ import annotations

import pytest

from app.process_payload import build_process_payload


def _fixed_stages():
    return [
        {"name": "班组长审批", "approver_type": "ROLE", "approver_value": "role_id_1", "approver_label": "班组长"},
        {"name": "质量经理审批", "approver_type": "ROLE", "approver_value": "role_id_2", "approver_label": "质量经理"},
    ]


def test_payload_has_verified_critical_fields():
    p = build_process_payload(
        app_id="app1", form_id="F123", menu_id="M9",
        process_name="检测报告审批流", process_code="proc_test_report",
        stages_with_role=_fixed_stages(),
    )
    # ★ 最致命字段：流程绑哪张表
    assert p["processDataSource"] == {"sourceType": "SOURCE_TYPE_BO", "objectId": "boc_code_F123"}
    assert p["appId"] == "app1"
    assert p["formId"] == "F123"
    assert p["menuId"] == "M9"
    assert p["processName"] == "检测报告审批流"
    assert p["processCode"] == "proc_test_report"
    assert p["status"] == "ENABLE"
    assert p["engine"] == "VERSION_1.1"
    assert p["boExist"] is True
    assert isinstance(p["bpmn"], str) and "<" in p["bpmn"]  # 真 BPMN XML
    # START + END + 2 审批节点 = 4
    assert len(p["nodes"]) == 4
    assert p["nodes"][0]["id"] == "START"
    assert p["nodes"][1]["id"] == "END"
    # 边：START→stage1, stage1→stage2, stage2→END = 3
    assert len(p["edges"]) == 3


def test_approver_is_role_id_not_code():
    p = build_process_payload(
        app_id="a", form_id="F", menu_id="M",
        process_name="n", process_code="c", stages_with_role=_fixed_stages(),
    )
    approve_nodes = [n for n in p["nodes"] if n["id"] not in ("START", "END")]
    approvers = approve_nodes[0]["data"]["approvers"]
    assert approvers[0]["type"] == "ROLE"
    assert approvers[0]["value"] == "role_id_1"  # 雪花 id，不是 role_code
    assert approvers[0]["displayData"]["label"] == "班组长"
