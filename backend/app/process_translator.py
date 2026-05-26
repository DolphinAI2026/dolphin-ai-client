"""ProcessDefinition → apaas 平台 schema 翻译器 (design-v4 I4).

把前端 ProcessDesignerPanel 序列化的应用层 JSON (24 节点类型) 转换为
apaas 平台 /xdap-app/process/save/processConfig 接收的 payload.

apaas 平台节点类型 (实测来自 step_executor.execute_create_workflow):
- START / END             — 圆形入口出口
- APPROVE                 — 审批 (UserTask)
- 其他 EVENT_* / 多分支等  — P6 todo

前端 24 节点 (frontend/src/components/v3/processNodeRegistry.ts):
  entry:    start / end / timer / webhook
  approval: assignee_approval / role_approval / manager_approval / parallel_approval / cc
  logic:    condition / multi_branch / parallel_gateway / merge / wait
  action:   fill_form / write_data / read_data / ai_judge / ai_generate

翻译策略 (basic 实现, 覆盖审批主链路):
- start/end          → START / END (apaas 原生支持)
- *_approval         → APPROVE
- cc                 → APPROVE (apaas 不区分抄送, 用单 SUBMITTER 占位)
- fill_form          → APPROVE (作为发起或填表占位)
- condition/...      → 跳过 + 标 P6 todo (apaas process schema 对网关支持复杂)
- timer/webhook      → 跳过 + 标 P6 todo (apaas 业务事件 + 流程触发是分开的)
- write_data/read_data/ai_* → 跳过 + 标 P6 todo

不被翻译的节点会被收集到 unsupported 列表里, 一并返给调用方,
让前端可以提示用户"X 类型节点暂未上 apaas — 留 P6 实现".

参考: step_executor.execute_create_workflow (现 SPEC 走的 BPMN platform_nodes 构造).
"""
from __future__ import annotations

import logging
import uuid
from typing import Any, Optional

logger = logging.getLogger(__name__)


# --- 节点类型映射: frontend 24 → apaas type ---
APAAS_NODE_TYPE_MAP: dict[str, str] = {
    # entry — apaas 流程必须有 START + END
    "start": "START",
    "end": "END",
    # approval — 5 个都翻成 APPROVE; 内部 approverType 由 props.assignee/role 决定
    "assignee_approval": "APPROVE",
    "role_approval": "APPROVE",
    "manager_approval": "APPROVE",
    "parallel_approval": "APPROVE",
    "cc": "APPROVE",  # apaas 不区分抄送, 用单 SUBMITTER 占位 (P6 加 CC 类型)
    # action - fill_form 在 apaas 里是 START_HIDDEN 等价物
    "fill_form": "APPROVE",
}


# --- 不支持的节点类型 → P6 todo ---
UNSUPPORTED_NODE_TYPES: set[str] = {
    "timer", "webhook",
    "condition", "multi_branch", "parallel_gateway", "merge", "wait",
    "write_data", "read_data", "ai_judge", "ai_generate",
}


# --- 标准按钮模板 (复用 step_executor.execute_create_workflow) ---
_APPROVE_BUTTONS = [
    {"buttonCode": "APPROVE", "buttonName": "同意", "buttonLabel": "同意", "buttonStatus": True, "buttonStyle": "primary", "buttonLabelI18nAssociated": False},
    {"buttonCode": "REJECT", "buttonName": "拒绝", "buttonLabel": "拒绝", "buttonStatus": True, "buttonStyle": "primary", "buttonLabelI18nAssociated": False},
]
_START_BUTTONS = [
    {"buttonCode": "NORMAL_TERMINATE", "buttonName": "终止", "buttonLabel": "终止", "buttonStatus": False, "buttonStyle": "primary", "buttonLabelI18nAssociated": False},
    {"buttonCode": "RESTART", "buttonName": "重新提交", "buttonLabel": "重新提交", "buttonStatus": False, "buttonStyle": "primary", "buttonLabelI18nAssociated": False},
    {"buttonCode": "WITHDRAW", "buttonName": "撤回", "buttonLabel": "撤回", "buttonStatus": False, "buttonStyle": "primary", "buttonLabelI18nAssociated": False, "withdrawalType": "NEXT_NODE", "withdrawalList": []},
]
_COMMENT_CONFIG = {"required": False, "attachmentUpload": True, "requiredBtns": [], "show": True}
_PHRASE_CONFIG = {"handleType": "INPUT_TYPE", "phrase": "", "status": False}

_MINIMAL_BPMN = (
    '<?xml version="1.0" encoding="UTF-8"?>'
    '<definitions xmlns="http://www.omg.org/spec/BPMN/20100524/MODEL" '
    'xmlns:activiti="http://activiti.org/bpmn" id="Definitions_1" '
    'targetNamespace="http://bpmn.io/schema/bpmn">'
    '<process id="Process_1" isExecutable="true">'
    '<startEvent id="START" name="开始"/>'
    '<endEvent id="END" name="结束"/>'
    '</process>'
    '</definitions>'
)


def _resolve_approvers_from_props(node_type: str, props: dict[str, Any], role_codes: Optional[dict[str, dict]] = None) -> list[dict[str, Any]]:
    """从 ProcessDefinition.props 解析 apaas approvers 数组.

    - assignee_approval → approvers=[{type:USER, code/name}]
    - role_approval     → approvers=[{type:ROLE, code/name}]  (role_codes 查 platform code)
    - manager_approval  → approvers=[{type:LEADER, code/name}] (apaas 支持上级直接路由)
    - parallel_approval → approvers=[{type:USER, code/name}, ...]; approveType=ALL/ANY
    - cc / fill_form    → SUBMITTER 占位
    """
    role_codes = role_codes or {}

    if node_type == "assignee_approval":
        # props.assignee / props.approvers — backend node JSON
        assignees = props.get("approvers") or ([props["assignee"]] if props.get("assignee") else [])
        if not isinstance(assignees, list):
            assignees = [assignees]
        out = []
        for a in assignees:
            code = str(a or "").strip()
            if code:
                out.append({"approverType": "USER", "approverName": code, "approverCode": code})
        if not out:
            out = [{"approverType": "SUBMITTER", "approverName": "表单提交人", "approverCode": "SUBMITTER"}]
        return out

    if node_type == "role_approval":
        role_code = ""
        # 支持 props.role (单角色) 或 props.approvers (兼容 list)
        role_keys = props.get("approvers")
        if isinstance(role_keys, list) and role_keys:
            role_code = str(role_keys[0])
        else:
            role_code = str(props.get("role") or "")
        if role_code:
            role_info = role_codes.get(role_code, {})
            platform_code = role_info.get("roleCode", role_code)
            platform_name = role_info.get("roleName", role_code)
            return [{"approverType": "ROLE", "approverName": platform_name, "approverCode": platform_code}]
        return [{"approverType": "SUBMITTER", "approverName": "表单提交人", "approverCode": "SUBMITTER"}]

    if node_type == "manager_approval":
        return [{"approverType": "LEADER", "approverName": "上级", "approverCode": "LEADER"}]

    if node_type == "parallel_approval":
        assignees = props.get("approvers") or []
        if not isinstance(assignees, list):
            assignees = [assignees]
        out = []
        for a in assignees:
            code = str(a or "").strip()
            if code:
                out.append({"approverType": "USER", "approverName": code, "approverCode": code})
        if not out:
            out = [{"approverType": "SUBMITTER", "approverName": "表单提交人", "approverCode": "SUBMITTER"}]
        return out

    if node_type in ("cc", "fill_form"):
        return [{"approverType": "SUBMITTER", "approverName": "表单提交人", "approverCode": "SUBMITTER"}]

    return [{"approverType": "SUBMITTER", "approverName": "表单提交人", "approverCode": "SUBMITTER"}]


def _make_apaas_node(
    node_id: str,
    title: str,
    apaas_type: str,
    y: float,
    approvers: Optional[list[dict[str, Any]]] = None,
    approve_type: str = "SINGLE",
) -> dict[str, Any]:
    """构造 apaas 平台 process 节点 dict (参考 step_executor._make_node).

    apaas_type ∈ {'START', 'END', 'APPROVE'}.
    approve_type ∈ {'SINGLE', 'ANY', 'ALL', 'MAJORITY'} — 仅 APPROVE 用.
    """
    n: dict[str, Any] = {
        "id": node_id,
        "nodeId": node_id,
        "timeBoudries": [],  # 注: 平台拼写就是 'Boudries', 不是 'Boundaries'
        "width": "64.0" if apaas_type in ("START", "END") else "122.0",
        "height": "64.0" if apaas_type in ("START", "END") else "48.0",
        "x": 372.0,
        "y": y,
        "data": {
            "nodeId": node_id,
            "title": title,
            "type": apaas_type,
            "enableComponentPermission": True,
            "titleI18nAssociated": False,
            "approveCommentConfig": _COMMENT_CONFIG,
            "approvePhraseConfig": _PHRASE_CONFIG,
            "remindList": [],
            "processEventStatus": False,
            "saveFlag": True,
        },
    }
    if apaas_type == "START":
        n["data"]["formButtons"] = _START_BUTTONS
    elif apaas_type == "APPROVE":
        n["data"]["approveType"] = approve_type
        n["data"]["approveButtons"] = _APPROVE_BUTTONS
        n["data"]["approvers"] = approvers or []
    return n


def translate_definition_to_apaas_schema(
    definition: dict[str, Any],
    apaas_app_id: str,
    menu_id: str,
    role_codes: Optional[dict[str, dict]] = None,
) -> tuple[dict[str, Any], list[dict[str, str]]]:
    """把本地 ProcessDefinition JSON 翻译成 apaas /process/save/processConfig payload.

    入参:
        definition: 本地 JSON, shape = {process_name, nodes:[...], edges:[...]}
            nodes: [{id, type, label, position, props}]
            edges: [{id, source, target, label, condition}]
        apaas_app_id: 平台 appId (传给 save API)
        menu_id: 表单菜单 ID (apaas 流程必须挂在表单 menu 下)
        role_codes: 可选, 角色 code → {roleCode, roleName} 反查 (role_approval 用)

    返回:
        (payload, unsupported_nodes)
            payload: 可直接传给 client.save_process_config
            unsupported_nodes: 没翻译的节点 [{id, type, reason}]

    限制 (P6 todo):
        - condition/multi_branch/parallel_gateway/merge — apaas process schema
          对 GATEWAY 类型有特殊支持, 当前简化串行链不走分支
        - timer/webhook — apaas 流程触发是表单提交, 定时/Webhook 是业务事件分开配
        - write_data/read_data/ai_* — apaas 流程节点不直接执行 DAO/AI, 需配业务事件
    """
    role_codes = role_codes or {}

    if not isinstance(definition, dict):
        raise ValueError("definition 必须是 dict")
    raw_nodes = definition.get("nodes") or []
    if not isinstance(raw_nodes, list):
        raise ValueError("definition.nodes 必须是 list")

    # 收集翻译信息
    unsupported: list[dict[str, str]] = []
    approvable_nodes: list[dict[str, Any]] = []  # 中间审批节点 (除 start/end 外)
    has_start = False
    has_end = False

    for raw_node in raw_nodes:
        if not isinstance(raw_node, dict):
            continue
        node_type = str(raw_node.get("type") or "")
        node_id = str(raw_node.get("id") or "") or uuid.uuid4().hex
        node_label = str(raw_node.get("label") or node_type)
        node_props = raw_node.get("props") or {}
        if not isinstance(node_props, dict):
            node_props = {}

        if node_type == "start":
            has_start = True
            continue
        if node_type == "end":
            has_end = True
            continue

        if node_type in UNSUPPORTED_NODE_TYPES:
            unsupported.append({
                "id": node_id,
                "type": node_type,
                "label": node_label,
                "reason": f"P6 todo: apaas process schema 暂未实现 {node_type} 类型翻译",
            })
            continue

        if node_type not in APAAS_NODE_TYPE_MAP:
            unsupported.append({
                "id": node_id,
                "type": node_type,
                "label": node_label,
                "reason": f"未知节点类型 {node_type}",
            })
            continue

        # 进入 APPROVE 翻译
        approvers = _resolve_approvers_from_props(node_type, node_props, role_codes)
        approve_type = "ALL" if node_type == "parallel_approval" else "SINGLE"
        approvable_nodes.append({
            "raw_id": node_id,
            "label": node_label,
            "approvers": approvers,
            "approve_type": approve_type,
        })

    # 构造 apaas platform_nodes
    # 固定结构: START → START_HIDDEN(发起申请) → APPROVE_1 → APPROVE_2 → ... → END
    platform_nodes: list[dict[str, Any]] = [
        _make_apaas_node("START", "开始", "START", 32.0),
        _make_apaas_node(
            "START_HIDDEN", "发起申请", "APPROVE", 128.0,
            [{"approverType": "SUBMITTER", "approverName": "表单提交人", "approverCode": "SUBMITTER"}],
        ),
    ]

    y_pos = 224.0
    for idx, ap in enumerate(approvable_nodes, start=1):
        platform_nodes.append(
            _make_apaas_node(
                f"UserTask_{idx}", ap["label"], "APPROVE", y_pos,
                approvers=ap["approvers"],
                approve_type=ap["approve_type"],
            )
        )
        y_pos += 96.0

    platform_nodes.append(_make_apaas_node("END", "结束", "END", y_pos))

    # 构造串行边 (P6: 真按 frontend edges 拓扑还原 — 当前只走串行链)
    platform_edges: list[dict[str, Any]] = []
    for i in range(len(platform_nodes) - 1):
        src = platform_nodes[i]["id"]
        tgt = platform_nodes[i + 1]["id"]
        platform_edges.append({
            "id": f"SequenceFlow_{tgt}",
            "source": src,
            "target": tgt,
            "data": {"titleI18nAssociated": False},
        })

    payload = {
        "appId": apaas_app_id,
        "menuId": menu_id,
        "bpmn": _MINIMAL_BPMN,
        "nodes": platform_nodes,
        "edges": platform_edges,
    }

    # 如果连 start/end 都没 → 当作 warning, 但仍构造 (apaas 平台会自动加)
    if not has_start or not has_end:
        missing = []
        if not has_start:
            missing.append("start")
        if not has_end:
            missing.append("end")
        logger.warning(
            "translate_definition_to_apaas_schema: 本地 definition 缺 %s — apaas 平台会自动补齐",
            "/".join(missing),
        )

    return payload, unsupported
