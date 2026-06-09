from __future__ import annotations

import pytest

import app.mcp_server as mcp_server
from app.mcp_server import _normalize_apaas_process_edge, _resolve_process_binding_from_raw


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
