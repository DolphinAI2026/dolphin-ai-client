from __future__ import annotations

import copy

import pytest

import app.mcp_server as mcp_server
from app.mcp_server import (
    _find_process_transition_edge,
    _normalize_apaas_process_edge,
    _resolve_process_binding_from_raw,
)


def test_resolve_process_binding_uses_menu_id_when_called_with_platform_process_id():
    binding = _resolve_process_binding_from_raw(
        [
            {
                "id": "process-1",
                "menuId": "menu-1",
                "formId": "form-1",
                "processName": "漏洞整改闭环流程",
                "processCode": "vuln_flow",
            }
        ],
        "process-1",
    )

    assert binding == {
        "process_id": "process-1",
        "menu_id": "menu-1",
        "form_id": "form-1",
        "process_name": "漏洞整改闭环流程",
        "process_code": "vuln_flow",
    }


def test_resolve_process_binding_also_accepts_menu_id_or_process_code():
    raw = [
        {
            "id": "process-1",
            "menuId": "menu-1",
            "formId": "form-1",
            "processName": "漏洞整改闭环流程",
            "processCode": "vuln_flow",
        }
    ]

    assert _resolve_process_binding_from_raw(raw, "menu-1")["menu_id"] == "menu-1"
    assert _resolve_process_binding_from_raw(raw, "vuln_flow")["process_id"] == "process-1"


def test_normalize_apaas_process_edge_accepts_platform_line_keys():
    edge = _normalize_apaas_process_edge(
        {
            "id": "edge-1",
            "sourceNodeKey": "gw-risk",
            "targetNodeKey": "manager",
            "lineName": "信息泄露",
            "data": {"conditionExpression": "vuln_category == 'info_disclosure'"},
        }
    )

    assert edge == {
        "id": "edge-1",
        "source": "gw-risk",
        "target": "manager",
        "label": "信息泄露",
        "condition": "vuln_category == 'info_disclosure'",
    }


def test_normalize_apaas_process_edge_hides_default_slash_label():
    edge = _normalize_apaas_process_edge(
        {
            "id": "edge-1",
            "source": "START",
            "target": "approve-1",
            "data": {"title": "\\"},
        }
    )

    assert edge["label"] == ""


def test_find_process_transition_edge_matches_edge_data_id():
    edge = {
        "id": "cell-edge-1",
        "source": "START",
        "target": "approve-1",
        "data": {"id": "BPMN_rule_edge", "title": "项目类型=客户交付"},
    }

    found = _find_process_transition_edge([edge], {"edge_id": "BPMN_rule_edge"}, [])

    assert found is edge


def test_find_process_transition_edge_matches_target_node_title_and_line_name():
    nodes = [
        {"id": "START", "data": {"title": "开始"}},
        {"id": "approve-maintain", "data": {"title": "项目经理审批"}},
    ]
    edge = {
        "id": "cell-edge-1",
        "source": "START",
        "target": "approve-maintain",
        "lineName": "维护优化",
        "data": {"id": "BPMN_rule_edge", "title": "维护优化"},
    }

    found = _find_process_transition_edge(
        [edge],
        {"target_node_title": "项目经理审批", "line_name": "维护优化"},
        nodes,
    )

    assert found is edge


@pytest.mark.asyncio
async def test_get_process_detail_prefers_full_config_edges_over_list_inference(monkeypatch):
    list_process = {
        "id": "process-1",
        "menuId": "menu-1",
        "formId": "form-1",
        "processName": "漏洞整改闭环流程",
        "processCode": "vuln_flow",
        "nodes": [
            {"id": "START", "x": 372, "y": 20, "data": {"type": "START", "title": "开始", "nodeId": "START"}},
            {"id": "cell-2", "x": 348, "y": 170, "data": {"type": "APPROVE", "title": "安全管理员确认", "nodeId": "cell-2"}},
            {"id": "cell-8", "x": 200, "y": 170, "data": {"type": "APPROVE", "title": "上级领导审批", "nodeId": "BPMN_leader"}},
        ],
    }
    full_process = {
        **list_process,
        "edges": [
            {
                "id": "cell-9",
                "source": "START",
                "target": "cell-8",
                "data": {"id": "BPMN_rule_edge", "title": "信息泄露", "defaultFlow": False},
            },
            {
                "id": "START->cell-2",
                "source": "START",
                "target": "cell-2",
                "data": {"id": "BPMN_default_edge", "title": "\\\\", "defaultFlow": True},
            },
            {
                "id": "cell-10",
                "source": "cell-8",
                "target": "cell-2",
                "data": {"id": "BPMN_join_edge", "title": "\\\\", "defaultFlow": True},
            },
        ],
        "processRule": {
            "BPMN_rule_edge": {
                "ruleType": "simple",
                "simpleRuleConfig": {
                    "formFieldRuleList": [
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
                    ],
                },
            }
        },
    }

    async def fake_cached_list_processes(env_id, apaas_app_id):
        return [list_process]

    async def fake_load_role_labels(env_id, apaas_app_id):
        return {}

    async def fake_with_client(env_id, op, fn):
        class Client:
            async def query_process_config(self, app_id, process_id):
                return {"ok": True, "data": full_process}

        return True, await fn(Client())

    monkeypatch.setattr(mcp_server, "_cached_list_processes", fake_cached_list_processes)
    monkeypatch.setattr(mcp_server, "_load_process_role_labels", fake_load_role_labels)
    monkeypatch.setattr(mcp_server, "_with_client", fake_with_client)

    detail = await mcp_server.get_apaas_process_detail(63, "app-1", "process-1")

    assert detail["ok"] is True
    edges = {(edge["source"], edge["target"]): edge for edge in detail["edges"]}
    assert set(edges) == {
        ("START", "cell-8"),
        ("START", "cell-2"),
        ("cell-8", "cell-2"),
    }
    assert edges[("START", "cell-8")]["label"] == "信息泄露"
    assert detail["edge_count"] == 3
    assert all(not edge.get("_inferred") for edge in detail["edges"])


@pytest.mark.asyncio
async def test_set_process_transition_rules_saves_simple_rule_and_process_rule(monkeypatch):
    list_process = {
        "id": "process-1",
        "menuId": "menu-1",
        "formId": "form-1",
        "processName": "项目立项审批流",
        "processCode": "project_init_flow",
    }
    full_process = {
        **list_process,
        "appId": "app-1",
        "status": "ENABLE",
        "engine": "VERSION_1.1",
        "nodes": [
            {"id": "START", "x": 372, "y": 20, "data": {"type": "START", "title": "开始", "nodeId": "START"}},
            {
                "id": "approve-delivery",
                "x": 240,
                "y": 170,
                "data": {"type": "APPROVE", "title": "交付负责人审批", "nodeId": "approve-delivery", "approvers": []},
            },
            {"id": "END", "x": 372, "y": 300, "data": {"type": "END", "title": "结束", "nodeId": "END"}},
        ],
        "edges": [
            {
                "id": "edge-1",
                "source": "START",
                "target": "approve-delivery",
                "lineName": "客户交付",
                "data": {"id": "BPMN_rule_edge", "title": "客户交付", "defaultFlow": True},
            },
            {
                "id": "edge-2",
                "source": "approve-delivery",
                "target": "END",
                "data": {"id": "BPMN_end_edge", "title": "\\\\", "defaultFlow": True},
            },
        ],
        "processRule": {},
        "globalSettings": {},
        "processGlobalConfig": {},
    }
    captured_payload = {}

    async def fake_cached_list_processes(env_id, apaas_app_id):
        return [list_process]

    async def fake_with_client(env_id, op, fn):
        class Client:
            async def query_process_config(self, app_id, process_id):
                return {"ok": True, "data": copy.deepcopy(full_process)}

            async def query_form_components(self, app_id, form_id):
                return [
                    {
                        "label": "项目类型",
                        "boCode": "project_main~project_type",
                        "chooseOptions": [{"id": "custom_delivery", "label": "客户交付"}],
                    }
                ]

            async def save_simple_rule(self, app_id, menu_id, cfg):
                return {**copy.deepcopy(cfg), "id": "rule-123"}

            async def save_process_config(self, app_id, payload):
                captured_payload.update(copy.deepcopy(payload))
                return {"code": "ok"}

        return True, await fn(Client())

    monkeypatch.setattr(mcp_server, "_cached_list_processes", fake_cached_list_processes)
    monkeypatch.setattr(mcp_server, "_with_client", fake_with_client)

    result = await mcp_server.set_apaas_process_transition_rules(
        env_id=63,
        apaas_app_id="app-1",
        process_id="process-1",
        rules=[
            {
                "line_name": "客户交付",
                "target_node_title": "交付负责人审批",
                "condition": {"fieldCode": "project_type", "operator": "eq", "value": "custom_delivery"},
            }
        ],
    )

    assert result["ok"] is True
    assert result["process_rule_count"] == 1
    assert captured_payload["processRule"]["BPMN_rule_edge"]["simpleRuleId"] == "rule-123"
    assert captured_payload["edges"][0]["data"]["defaultFlow"] is False
    assert "executeSimpleProcRule(processId, documentId, 'rule-123', outcome)" in captured_payload["bpmn"]
