"""锁住 BPMN ID/IDREF 自洽 —— 防多级审批链把图节点 id 'cell-N' 漏进 BPMN sourceRef。

实测 bug：set_apaas_app_process 三级审批链 → apaas 存流程 500
  {"code":"error","message":"cvc-id.1: There is no ID/IDREF binding for IDREF 'cell-2'."}
根因：_build_process_payload_v2 给 BPMN 边的 source 用了 prev_node_id（被设成图节点
'cell-N'），而 BPMN userTask 的 id 是随机 bpmn_id —— sequenceFlow sourceRef 引用了
不存在的 'cell-2'，apaas BPMN schema 校验直接拒。单级链 source='START' 合法侥幸过，
多级必崩。
"""
from __future__ import annotations

import re

from app.process_payload import build_process_payload


def test_bpmn_sequenceflow_refs_resolve_to_defined_ids():
    p = build_process_payload(
        app_id="app1", form_id="F123", menu_id="M9",
        process_name="多级审批", process_code="multi",
        stages_with_role=[
            {"name": "一级", "approver_type": "ROLE", "approver_value": "r1", "approver_label": "一级"},
            {"name": "二级", "approver_type": "ROLE", "approver_value": "r2", "approver_label": "二级"},
            {"name": "三级", "approver_type": "ROLE", "approver_value": "r3", "approver_label": "三级"},
        ],
    )
    bpmn = p["bpmn"]
    defined = set(re.findall(r'<(?:startEvent|endEvent|userTask)\s+id="([^"]+)"', bpmn))
    refs = re.findall(r'<sequenceFlow[^>]*\ssourceRef="([^"]+)"[^>]*\stargetRef="([^"]+)"', bpmn)
    assert refs, "BPMN 里应有 sequenceFlow"

    dangling = []
    for src, tgt in refs:
        if src not in defined:
            dangling.append(("sourceRef", src))
        if tgt not in defined:
            dangling.append(("targetRef", tgt))
    assert not dangling, (
        f"BPMN sequenceFlow 引用了未定义的 id（cvc-id.1 根因）: {dangling}; defined={sorted(defined)}"
    )
    approve_bpmn_node_ids = [
        node["data"]["nodeId"]
        for node in p["nodes"]
        if isinstance(node.get("data"), dict) and node["data"].get("type") == "APPROVE"
    ]
    assert approve_bpmn_node_ids
    assert all(node_id in defined for node_id in approve_bpmn_node_ids)

    approve_canvas_ids = [
        node["id"]
        for node in p["nodes"]
        if isinstance(node.get("data"), dict) and node["data"].get("type") == "APPROVE"
    ]
    start_node = next(node for node in p["nodes"] if node["data"]["type"] == "START")
    end_node = next(node for node in p["nodes"] if node["data"]["type"] == "END")
    assert start_node["id"] == "START"
    assert end_node["id"] == "END"
    assert all(node_id.startswith("cell-") for node_id in approve_canvas_ids)
    assert all(node_id.startswith("BPMN_") for node_id in approve_bpmn_node_ids)
    assert not set(approve_canvas_ids) & set(approve_bpmn_node_ids)


def test_bpmn_uses_hidden_start_task_for_runtime_flow_image():
    p = build_process_payload(
        app_id="app1", form_id="F123", menu_id="M9",
        process_name="审批", process_code="approval",
        stages_with_role=[
            {"name": "一级", "approver_type": "ROLE", "approver_value": "r1", "approver_label": "一级"},
        ],
    )
    bpmn = p["bpmn"]
    defined = set(re.findall(r'<(?:startEvent|endEvent|userTask)\s+id="([^"]+)"', bpmn))
    refs = re.findall(r'<sequenceFlow[^>]*\ssourceRef="([^"]+)"[^>]*\stargetRef="([^"]+)"', bpmn)

    assert "START_HIDDEN" in defined
    assert ("START", "START_HIDDEN") in refs
    assert not any(src == "START" and tgt != "START_HIDDEN" for src, tgt in refs)
    assert any(src == "START_HIDDEN" and tgt.startswith("BPMN_") for src, tgt in refs)
    assert "processUsers(processId,&apos;START_HIDDEN&apos;,documentId,submitter)" in bpmn
