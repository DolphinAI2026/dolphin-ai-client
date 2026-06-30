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
    assert sorted(p.keys()) == [
        "appId",
        "bpmn",
        "edges",
        "engine",
        "formId",
        "globalSettings",
        "menuId",
        "nodes",
        "openProcessVersion",
        "processGlobalConfig",
        "processRule",
        "status",
    ]
    assert p["appId"] == "app1"
    assert p["formId"] == "F123"
    assert p["menuId"] == "M9"
    assert p["status"] == "ENABLE"
    assert p["engine"] == "VERSION_1.1"
    assert isinstance(p["bpmn"], str) and "<" in p["bpmn"]  # 真 BPMN XML
    # START + END + 2 审批节点 = 4
    assert len(p["nodes"]) == 4
    assert p["nodes"][0]["id"] == "cell-2"
    assert p["nodes"][1]["id"] == "cell-3"
    # 边：START→stage1, stage1→stage2, stage2→END = 3
    assert len(p["edges"]) == 3


def test_approver_is_role_id_not_code():
    p = build_process_payload(
        app_id="a", form_id="F", menu_id="M",
        process_name="n", process_code="c", stages_with_role=_fixed_stages(),
    )
    approve_nodes = [n for n in p["nodes"] if n["data"]["type"] == "APPROVE"]
    approvers = approve_nodes[0]["data"]["approvers"]
    assert approvers[0]["type"] == "ROLE"
    assert approvers[0]["value"] == "role_id_1"  # 雪花 id，不是 role_code
    assert approvers[0]["displayData"]["label"] == "班组长"


def test_process_global_config_matches_designer_save_defaults():
    p = build_process_payload(
        app_id="a",
        form_id="F",
        menu_id="M",
        process_name="n",
        process_code="c",
        stages_with_role=_fixed_stages(),
        form_components=[
            {"uuid": "u1", "label": "字段一", "componentType": "FORM_TEXT_INPUT"},
            {"uuid": "u2", "label": "字段二", "componentType": "FORM_NUMBER_INPUT"},
        ],
    )

    cfg = p["processGlobalConfig"]
    assert cfg["approveUiMobile"] == "MODAL"
    assert cfg["approveUiPc"] == "DETAIL"
    assert cfg["processViewDisplayField"] == "processStatus"
    assert "titleConfigListI18nAssociated" not in cfg
    assert cfg["processDisplayFieldList"] == [
        {"componentId": "u1", "componentName": "字段一", "componentType": "FORM_TEXT_INPUT"},
        {"componentId": "u2", "componentName": "字段二", "componentType": "FORM_NUMBER_INPUT"},
    ]


def test_bpmn_header_and_buttons_match_designer_save_payload():
    p = build_process_payload(
        app_id="a",
        form_id="F",
        menu_id="M",
        process_name="n",
        process_code="c",
        stages_with_role=_fixed_stages(),
    )

    assert 'id="Definitions_1z0losk"' in p["bpmn"]
    assert 'exporter="bpmn-js (https://demo.bpmn.io)" exporterVersion="5.0.0"' in p["bpmn"]
    assert '<process id="Process_Process_" isExecutable="true">' in p["bpmn"]

    approve_nodes = [
        n for n in p["nodes"]
        if isinstance(n.get("data"), dict) and n["data"].get("type") == "APPROVE"
    ]
    reassign = next(
        b for b in approve_nodes[0]["data"]["approveButtons"]
        if b.get("buttonCode") == "REASSIGN"
    )
    assert reassign["index"] == 3
    assert all(
        "buttonLabelI18nAssociated" not in b
        for b in approve_nodes[0]["data"]["approveButtons"]
    )
