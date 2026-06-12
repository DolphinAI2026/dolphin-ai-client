from __future__ import annotations

import copy
import re

from app.process_translator import build_apaas_bpmn_xml, translate_definition_to_apaas_schema


def _branch_definition() -> dict:
    return {
        "process_name": "漏洞整改闭环流程",
        "process_code": "vuln_fix_flow",
        "nodes": [
            {"id": "START", "type": "start", "label": "开始", "position": {"x": 320, "y": 40}, "props": {}},
            {
                "id": "gw-risk",
                "type": "condition",
                "label": "漏洞分类判断",
                "position": {"x": 320, "y": 140},
                "props": {"conditionExpression": "vuln_category == 'info_disclosure'"},
            },
            {
                "id": "manager",
                "type": "assignee_approval",
                "label": "上级领导审批",
                "position": {"x": 120, "y": 240},
                "props": {
                    "approvers": [
                        {"type": "ROLE", "value": "role-leader", "displayData": {"id": "role-leader", "label": "上级领导"}}
                    ]
                },
            },
            {
                "id": "fix-owner",
                "type": "assignee_approval",
                "label": "整改负责人处理",
                "position": {"x": 480, "y": 240},
                "props": {
                    "approvers": [
                        {"type": "ROLE", "value": "role-owner", "displayData": {"id": "role-owner", "label": "整改负责人"}}
                    ]
                },
            },
            {"id": "END", "type": "end", "label": "结束", "position": {"x": 320, "y": 360}, "props": {}},
        ],
        "edges": [
            {"id": "e-start-gw", "source": "START", "target": "gw-risk"},
            {
                "id": "e-gw-leader",
                "source": "gw-risk",
                "target": "manager",
                "label": "信息泄露",
                "condition": "vuln_category == 'info_disclosure'",
            },
            {"id": "e-gw-owner", "source": "gw-risk", "target": "fix-owner", "label": "其他", "condition": "default"},
            {"id": "e-leader-owner", "source": "manager", "target": "fix-owner"},
            {"id": "e-owner-end", "source": "fix-owner", "target": "END"},
        ],
    }


def test_branch_definition_translates_to_full_save_payload_with_condition_edges():
    payload, warnings = translate_definition_to_apaas_schema(
        _branch_definition(),
        apaas_app_id="app-1",
        menu_id="menu-1",
        form_id="form-1",
        process_name="漏洞整改闭环流程",
        process_code="vuln_fix_flow",
        form_components=[
            {
                "label": "漏洞分类",
                "bo_code": "sec_vuln~vuln_category",
                "choose_options": [{"id": "info_disclosure", "label": "信息泄露"}],
            }
        ],
    )

    assert warnings == []
    assert payload["appId"] == "app-1"
    assert payload["formId"] == "form-1"
    assert payload["menuId"] == "menu-1"
    assert payload["processName"] == "漏洞整改闭环流程"
    assert payload["processCode"] == "vuln_fix_flow"
    assert payload["status"] == "ENABLE"
    assert payload["engine"] == "VERSION_1.1"
    assert payload["processDataSource"] == {"sourceType": "SOURCE_TYPE_BO", "objectId": "boc_code_form-1"}

    assert not any(n["id"] == "gw-risk" for n in payload["nodes"])

    condition_edges = {e["id"]: e for e in payload["edges"]}
    assert condition_edges["e-start-gw__e-gw-leader"]["sourceNodeKey"] == "START"
    assert condition_edges["e-start-gw__e-gw-leader"]["targetNodeKey"] == "manager"
    assert condition_edges["e-start-gw__e-gw-leader"]["conditionExpression"] == "vuln_category == 'info_disclosure'"
    assert condition_edges["e-start-gw__e-gw-leader"]["lineName"] == "信息泄露"
    assert condition_edges["e-start-gw__e-gw-owner"]["sourceNodeKey"] == "START"
    assert condition_edges["e-start-gw__e-gw-owner"]["targetNodeKey"] == "fix-owner"
    assert condition_edges["e-start-gw__e-gw-owner"]["data"]["defaultFlow"] is True

    rule_key = condition_edges["e-start-gw__e-gw-leader"]["data"]["id"]
    assert payload["processRule"][rule_key]["ruleType"] == "simple"
    simple_rule = payload["processRule"][rule_key]["simpleRuleConfig"]
    assert simple_rule["express"] == "(((xdap.invoke('componentvalue','sec_vuln~vuln_category'))  == ('info_disclosure')))"
    assert simple_rule["formFieldRuleList"] == [
        {
            "connectOperation": "or",
            "fieldRuleList": [
                {
                    "type": "string",
                    "boCode": "sec_vuln~vuln_category",
                    "op": "eq",
                    "values": ["info_disclosure"],
                    "transValues": [],
                }
            ],
        }
    ]


def test_branch_condition_translates_chinese_is_operator_and_option_label_to_rule():
    definition = copy.deepcopy(_branch_definition())
    branch_edge = next(edge for edge in definition["edges"] if edge["id"] == "e-gw-leader")
    branch_edge["label"] = "项目类型=客户交付"
    branch_edge["condition"] = "项目类型 是 客户交付"

    payload, warnings = translate_definition_to_apaas_schema(
        definition,
        apaas_app_id="app-1",
        menu_id="menu-1",
        form_id="form-1",
        process_name="项目立项审批流",
        process_code="project_init_flow",
        form_components=[
            {
                "label": "项目类型",
                "bo_code": "project_main~project_type",
                "choose_options": [{"id": "custom_delivery", "label": "客户交付"}],
            }
        ],
    )

    assert warnings == []
    condition_edge = next(edge for edge in payload["edges"] if edge["id"] == "e-start-gw__e-gw-leader")
    rule_key = condition_edge["data"]["id"]
    simple_rule = payload["processRule"][rule_key]["simpleRuleConfig"]
    assert simple_rule["express"] == "(((xdap.invoke('componentvalue','project_main~project_type'))  == ('custom_delivery')))"
    assert simple_rule["formFieldRuleList"][0]["fieldRuleList"][0] == {
        "type": "string",
        "boCode": "project_main~project_type",
        "op": "eq",
        "values": ["custom_delivery"],
        "transValues": [],
    }


def test_branch_label_condition_translates_to_process_rule_when_condition_field_missing():
    definition = copy.deepcopy(_branch_definition())
    branch_edge = next(edge for edge in definition["edges"] if edge["id"] == "e-gw-leader")
    branch_edge["label"] = "项目类型=产品研发"
    branch_edge.pop("condition", None)

    payload, warnings = translate_definition_to_apaas_schema(
        definition,
        apaas_app_id="app-1",
        menu_id="menu-1",
        form_id="form-1",
        process_name="项目立项审批流",
        process_code="project_init_flow",
        form_components=[
            {
                "label": "项目类型",
                "bo_code": "project_main~project_type",
                "choose_options": [{"id": "product_rd", "label": "产品研发"}],
            }
        ],
    )

    assert warnings == []
    condition_edge = next(edge for edge in payload["edges"] if edge["id"] == "e-start-gw__e-gw-leader")
    assert condition_edge["lineName"] == "项目类型=产品研发"
    assert condition_edge["conditionExpression"] == "项目类型=产品研发"
    rule_key = condition_edge["data"]["id"]
    simple_rule = payload["processRule"][rule_key]["simpleRuleConfig"]
    assert simple_rule["express"] == "(((xdap.invoke('componentvalue','project_main~project_type'))  == ('product_rd')))"
    assert simple_rule["formFieldRuleList"][0]["fieldRuleList"][0]["boCode"] == "project_main~project_type"
    assert simple_rule["formFieldRuleList"][0]["fieldRuleList"][0]["values"] == ["product_rd"]


def test_branch_structured_condition_string_translates_to_process_rule():
    definition = copy.deepcopy(_branch_definition())
    branch_edge = next(edge for edge in definition["edges"] if edge["id"] == "e-gw-leader")
    branch_edge["label"] = "项目类型=客户交付"
    branch_edge["condition"] = (
        "{'field': 'project_type', 'fieldCode': 'project_type', 'operator': 'eq', "
        "'value': 'custom_delivery', 'valueLabel': '客户交付', 'dictCode': 'project_type_dict'}"
    )

    payload, warnings = translate_definition_to_apaas_schema(
        definition,
        apaas_app_id="app-1",
        menu_id="menu-1",
        form_id="form-1",
        process_name="项目立项审批流",
        process_code="project_init_flow",
        form_components=[
            {
                "label": "项目类型",
                "bo_code": "project_main~project_type",
                "choose_options": [{"id": "custom_delivery", "label": "客户交付"}],
            }
        ],
    )

    assert warnings == []
    condition_edge = next(edge for edge in payload["edges"] if edge["id"] == "e-start-gw__e-gw-leader")
    rule_key = condition_edge["data"]["id"]
    simple_rule = payload["processRule"][rule_key]["simpleRuleConfig"]
    assert simple_rule["express"] == "(((xdap.invoke('componentvalue','project_main~project_type'))  == ('custom_delivery')))"
    assert simple_rule["formFieldRuleList"][0]["fieldRuleList"][0]["boCode"] == "project_main~project_type"
    assert simple_rule["formFieldRuleList"][0]["fieldRuleList"][0]["op"] == "eq"
    assert simple_rule["formFieldRuleList"][0]["fieldRuleList"][0]["values"] == ["custom_delivery"]


def test_branch_structured_not_equal_condition_translates_to_process_rule():
    definition = copy.deepcopy(_branch_definition())
    branch_edge = next(edge for edge in definition["edges"] if edge["id"] == "e-gw-leader")
    branch_edge["label"] = "其他项目类型"
    branch_edge["condition"] = {
        "field": "project_type",
        "fieldCode": "project_type",
        "operator": "neq",
        "value": "custom_delivery",
        "valueLabel": "非客户交付",
        "dictCode": "project_type_dict",
    }

    payload, warnings = translate_definition_to_apaas_schema(
        definition,
        apaas_app_id="app-1",
        menu_id="menu-1",
        form_id="form-1",
        process_name="项目立项审批流",
        process_code="project_init_flow",
        form_components=[
            {
                "label": "项目类型",
                "bo_code": "project_main~project_type",
                "choose_options": [{"id": "custom_delivery", "label": "客户交付"}],
            }
        ],
    )

    assert warnings == []
    condition_edge = next(edge for edge in payload["edges"] if edge["id"] == "e-start-gw__e-gw-leader")
    rule_key = condition_edge["data"]["id"]
    simple_rule = payload["processRule"][rule_key]["simpleRuleConfig"]
    assert simple_rule["express"] == "(((xdap.invoke('componentvalue','project_main~project_type'))  != ('custom_delivery')))"
    assert simple_rule["formFieldRuleList"][0]["fieldRuleList"][0]["op"] == "neq"
    assert simple_rule["formFieldRuleList"][0]["fieldRuleList"][0]["values"] == ["custom_delivery"]


def test_branch_definition_accepts_exclusive_gateway_alias_from_tool_input():
    definition = copy.deepcopy(_branch_definition())
    gateway = next(n for n in definition["nodes"] if n["id"] == "gw-risk")
    gateway["type"] = "exclusive_gateway"

    payload, warnings = translate_definition_to_apaas_schema(
        definition,
        apaas_app_id="app-1",
        menu_id="menu-1",
        form_id="form-1",
        process_name="漏洞整改闭环流程",
        process_code="vuln_fix_flow",
    )

    assert warnings == []
    assert not any(n["id"] == "gw-risk" for n in payload["nodes"])

    condition_edges = {e["id"]: e for e in payload["edges"]}
    assert condition_edges["e-start-gw__e-gw-leader"]["sourceNodeKey"] == "START"
    assert condition_edges["e-start-gw__e-gw-leader"]["targetNodeKey"] == "manager"
    assert condition_edges["e-start-gw__e-gw-leader"]["conditionExpression"] == "vuln_category == 'info_disclosure'"
    assert condition_edges["e-start-gw__e-gw-owner"]["data"]["defaultFlow"] is True


def test_branch_definition_accepts_branch_alias_from_tool_input():
    definition = copy.deepcopy(_branch_definition())
    gateway = next(n for n in definition["nodes"] if n["id"] == "gw-risk")
    gateway["type"] = "branch"

    payload, warnings = translate_definition_to_apaas_schema(
        definition,
        apaas_app_id="app-1",
        menu_id="menu-1",
        form_id="form-1",
        process_name="漏洞整改闭环流程",
        process_code="vuln_fix_flow",
    )

    assert warnings == []
    assert not any(n["id"] == "gw-risk" for n in payload["nodes"])

    condition_edges = {e["id"]: e for e in payload["edges"]}
    assert condition_edges["e-start-gw__e-gw-leader"]["conditionExpression"] == "vuln_category == 'info_disclosure'"
    assert condition_edges["e-start-gw__e-gw-owner"]["data"]["defaultFlow"] is True


def test_apaas_role_approver_dicts_are_preserved_when_translating_definition():
    payload, _warnings = translate_definition_to_apaas_schema(
        _branch_definition(),
        apaas_app_id="app-1",
        menu_id="menu-1",
        form_id="form-1",
        process_name="漏洞整改闭环流程",
        process_code="vuln_fix_flow",
    )

    leader = next(n for n in payload["nodes"] if n["id"] == "manager")
    approver = leader["data"]["approvers"][0]
    assert approver["type"] == "ROLE"
    assert approver["value"] == "role-leader"
    assert approver["displayData"]["label"] == "上级领导"


def test_bpmn_uses_saved_simple_rule_id_for_condition_edges():
    payload, _warnings = translate_definition_to_apaas_schema(
        _branch_definition(),
        apaas_app_id="app-1",
        menu_id="menu-1",
        form_id="form-1",
        process_name="漏洞整改闭环流程",
        process_code="vuln_fix_flow",
        form_components=[{"label": "漏洞分类", "bo_code": "sec_vuln~vuln_category"}],
    )
    condition_edge = next(e for e in payload["edges"] if e["id"] == "e-start-gw__e-gw-leader")
    rule_key = condition_edge["data"]["id"]
    payload["processRule"][rule_key]["simpleRuleId"] = "rule-123"
    payload["processRule"][rule_key]["simpleRuleConfig"]["id"] = "rule-123"

    bpmn = build_apaas_bpmn_xml(payload["nodes"], payload["edges"], payload["processRule"])

    assert "sourceRef=\"START_HIDDEN\"" in bpmn
    assert f'id="SequenceFlow_{rule_key}"' in bpmn
    assert "procRuleHandle.executeSimpleProcRule(processId, documentId, 'rule-123', outcome)" in bpmn
    assert "<exclusiveGateway" not in bpmn
    assert "<inclusiveGateway" not in bpmn


def test_start_and_end_node_ids_are_canonicalized_for_bpmn_refs():
    payload, warnings = translate_definition_to_apaas_schema(
        {
            "process_name": "任意节点 ID 流程",
            "process_code": "custom_ids",
            "nodes": [
                {"id": "node-start", "type": "start", "label": "开始", "position": {"x": 320, "y": 40}, "props": {}},
                {
                    "id": "approve-1",
                    "type": "assignee_approval",
                    "label": "审批",
                    "position": {"x": 320, "y": 160},
                    "props": {},
                },
                {"id": "node-end", "type": "end", "label": "结束", "position": {"x": 320, "y": 280}, "props": {}},
            ],
            "edges": [
                {"id": "e-start-approve", "source": "node-start", "target": "approve-1"},
                {"id": "e-approve-end", "source": "approve-1", "target": "node-end"},
            ],
        },
        apaas_app_id="app-1",
        menu_id="menu-1",
        form_id="form-1",
        process_name="任意节点 ID 流程",
        process_code="custom_ids",
    )

    assert warnings == []
    assert {node["id"] for node in payload["nodes"]} == {"START", "approve-1", "END"}
    assert [(edge["source"], edge["target"]) for edge in payload["edges"]] == [
        ("START", "approve-1"),
        ("approve-1", "END"),
    ]

    defined = set(re.findall(r'<(?:startEvent|endEvent|userTask)\s+id="([^"]+)"', payload["bpmn"]))
    refs = re.findall(r'<sequenceFlow[^>]*\ssourceRef="([^"]+)"[^>]*\stargetRef="([^"]+)"', payload["bpmn"])
    assert ("START_HIDDEN", "approve-1") in refs
    assert ("START", "approve-1") not in refs
    assert ("approve-1", "END") in refs
    assert all(src in defined and tgt in defined for src, tgt in refs)
