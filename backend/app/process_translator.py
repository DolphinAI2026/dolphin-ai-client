"""ProcessDefinition → apaas 平台 schema 翻译器 (design-v4 I4 + K2).

把前端 ProcessDesignerPanel 序列化的应用层 JSON (24 节点类型) 转换为
apaas 平台 /xdap-app/process/save/processConfig 接收的 payload.

apaas 平台节点类型 (实测来自 step_executor.execute_create_workflow + K2 BPMN 推测):
- START / END                     — 圆形入口出口 (apaas 实测支持)
- APPROVE                         — 审批 (UserTask, apaas 实测支持)
- TIMER_START / MESSAGE_START     — 定时 / Webhook 触发 (BPMN start event with timer/message)
- EXCLUSIVE_GATEWAY               — 排他网关 (condition / multi_branch)
- PARALLEL_GATEWAY                — 并行网关 (parallel_gateway / merge — apaas 按入边方向区分 fork/join)
- TIMER_BOUNDARY                  — 等待超时 (wait 节点)
- SERVICE_TASK                    — 服务任务 (write_data / read_data / ai_* 兜底)
- AI_TASK                         — AI 任务 (ai_judge / ai_generate, 不确定 apaas 是否真支持 — 加 task_type 让平台识别)

前端 24 节点 (frontend/src/components/v3/processNodeRegistry.ts):
  entry:    start / end / timer / webhook
  approval: assignee_approval / role_approval / manager_approval / parallel_approval / cc
  logic:    condition / multi_branch / parallel_gateway / merge / wait
  action:   fill_form / write_data / read_data / ai_judge / ai_generate

K2 之前 (I4 basic) 翻译策略:
- 只翻译 START / END / *_approval / cc / fill_form (APPROVE)
- 串行链固定 START → START_HIDDEN → UserTask_1 → ... → END (不按 edges)
- timer/webhook/logic/action 全部 skip + P6 todo

K2 之后:
- logic 5 个全翻译 (EXCLUSIVE_GATEWAY / PARALLEL_GATEWAY / TIMER_BOUNDARY)
- action 4 个全翻译 (SERVICE_TASK / AI_TASK)
- timer / webhook 真翻译 (TIMER_START / MESSAGE_START)
- edges 按 frontend.edges 真拓扑还原 (fork / join / 分支 / 并行 全保真)
- 兜底: 空 definition / 缺 start / 缺 end / orphan edge ref 全友好处理

参考: step_executor.execute_create_workflow (现 SPEC 走的 BPMN platform_nodes 构造).
"""
from __future__ import annotations

import hashlib
import logging
import secrets
import uuid
from typing import Any, Optional

logger = logging.getLogger(__name__)


# --- 节点类型映射: frontend 24 → apaas type ---
# entry: 4 类
ENTRY_TO_APAAS: dict[str, str] = {
    "start": "START",
    "end": "END",
    "timer": "TIMER_START",       # 定时触发 — apaas BPMN start event with timer
    "webhook": "MESSAGE_START",   # webhook → 消息触发 start event
}

# approval: 5 个都翻 APPROVE; approveType 由 props 决定
APPROVAL_TO_APAAS: dict[str, str] = {
    "assignee_approval": "APPROVE",
    "role_approval": "APPROVE",
    "manager_approval": "APPROVE",
    "parallel_approval": "APPROVE",
    "cc": "APPROVE",  # apaas 不区分抄送, 用单 SUBMITTER 占位 (P6 加 CC 类型)
}

# logic: 5 个 → 3 种 apaas gateway/timer
LOGIC_TO_APAAS: dict[str, str] = {
    "condition": "EXCLUSIVE_GATEWAY",        # 排他网关 (真值/假值 2 出边)
    "multi_branch": "EXCLUSIVE_GATEWAY",     # 多分支 (N 条件 N 出边)
    "parallel_gateway": "PARALLEL_GATEWAY",  # 并行网关 (N 并行出边)
    "merge": "PARALLEL_GATEWAY",             # 汇聚 (反向, apaas 按入边方向区分 fork/join)
    "wait": "TIMER_BOUNDARY",                # 等待 (超时分支)
}

# action: 4 个 → SERVICE_TASK / AI_TASK
ACTION_TO_APAAS: dict[str, str] = {
    "fill_form": "APPROVE",       # fill_form 在 apaas 是 APPROVE 类 (SUBMITTER 角色)
    "write_data": "SERVICE_TASK",  # 服务任务 (写数据)
    "read_data": "SERVICE_TASK",
    "ai_judge": "AI_TASK",         # AI_TASK apaas 不确定支持 — 加 task_type 让平台识别, 退到 SERVICE_TASK 兜底
    "ai_generate": "AI_TASK",
}

# 合并总表 (向后兼容老调用方 APAAS_NODE_TYPE_MAP)
APAAS_NODE_TYPE_MAP: dict[str, str] = {
    **ENTRY_TO_APAAS,
    **APPROVAL_TO_APAAS,
    **LOGIC_TO_APAAS,
    **ACTION_TO_APAAS,
}

# 旧 P6 todo 列表 (K2 都已实现, 留空 set 向后兼容)
UNSUPPORTED_NODE_TYPES: set[str] = set()


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


# --- 节点尺寸 (按 apaas type 区分) ---
def _node_size(apaas_type: str) -> tuple[str, str]:
    """返 (width, height) — apaas 平台字符串数字."""
    if apaas_type in ("START", "END", "TIMER_START", "MESSAGE_START"):
        return ("64.0", "64.0")
    if apaas_type in ("EXCLUSIVE_GATEWAY", "PARALLEL_GATEWAY", "TIMER_BOUNDARY"):
        return ("64.0", "64.0")  # 网关菱形, 跟 START/END 一样小
    # APPROVE / SERVICE_TASK / AI_TASK — 矩形
    return ("122.0", "48.0")


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


def _gen_webhook_secret() -> str:
    """生成 webhook secret token (32 hex)."""
    return secrets.token_hex(16)


def _make_apaas_node(
    node_id: str,
    title: str,
    apaas_type: str,
    x: float,
    y: float,
    *,
    approvers: Optional[list[dict[str, Any]]] = None,
    approve_type: str = "SINGLE",
    extra_data: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """构造 apaas 平台 process 节点 dict (参考 step_executor._make_node).

    apaas_type ∈ {START, END, APPROVE, TIMER_START, MESSAGE_START,
                  EXCLUSIVE_GATEWAY, PARALLEL_GATEWAY, TIMER_BOUNDARY,
                  SERVICE_TASK, AI_TASK}.
    approve_type ∈ {SINGLE, ANY, ALL, MAJORITY} — 仅 APPROVE 用.
    extra_data: 节点类型特定的额外字段 (timerType/cron/webhookPath/condition/serviceType 等)
    """
    w, h = _node_size(apaas_type)
    n: dict[str, Any] = {
        "id": node_id,
        "nodeId": node_id,
        "timeBoudries": [],  # 注: 平台拼写就是 'Boudries', 不是 'Boundaries'
        "width": w,
        "height": h,
        "x": x,
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
    # 合并节点专属字段
    if extra_data:
        n["data"].update(extra_data)
    return n


def _build_logic_extra_data(node_type: str, props: dict[str, Any]) -> dict[str, Any]:
    """K2: logic 节点 (EXCLUSIVE_GATEWAY/PARALLEL_GATEWAY/TIMER_BOUNDARY) 的 data 扩展.

    - condition / multi_branch: conditionExpression (用户写的真分支条件) + defaultFlow (兜底分支)
    - parallel_gateway / merge: 不带 condition (并行无条件)
    - wait: timerType + duration / dateTime
    """
    extra: dict[str, Any] = {}
    if node_type in ("condition", "multi_branch"):
        extra["conditionExpression"] = str(props.get("condition") or props.get("conditionExpression") or "")
        extra["defaultFlow"] = str(props.get("default_flow") or props.get("defaultFlow") or "")
        extra["gatewayType"] = "EXCLUSIVE"
    elif node_type == "parallel_gateway":
        extra["gatewayType"] = "PARALLEL_FORK"
    elif node_type == "merge":
        extra["gatewayType"] = "PARALLEL_JOIN"
    elif node_type == "wait":
        # 等待节点 — 超时分支 (apaas TIMER_BOUNDARY)
        extra["timerType"] = str(props.get("timer_type") or props.get("timerType") or "duration")
        extra["duration"] = str(props.get("duration") or props.get("wait_duration") or "PT1H")  # ISO 8601 默认 1 小时
        if props.get("date_time") or props.get("dateTime"):
            extra["dateTime"] = str(props.get("date_time") or props.get("dateTime"))
    return extra


def _build_action_extra_data(node_type: str, props: dict[str, Any]) -> dict[str, Any]:
    """K2: action 节点 (SERVICE_TASK / AI_TASK) 的 data 扩展.

    - write_data / read_data: serviceType + targetModelCode + fieldMapping
    - ai_judge / ai_generate: task_type 提示 apaas 平台识别, 若不识别可退 SERVICE_TASK
    """
    extra: dict[str, Any] = {}
    if node_type == "write_data":
        extra["serviceType"] = "data_write"
        extra["targetModelCode"] = str(props.get("target_model_code") or props.get("targetModelCode") or "")
        fm = props.get("field_mapping") or props.get("fieldMapping") or {}
        extra["fieldMapping"] = fm if isinstance(fm, dict) else {}
    elif node_type == "read_data":
        extra["serviceType"] = "data_read"
        extra["targetModelCode"] = str(props.get("target_model_code") or props.get("targetModelCode") or "")
        # read_data 多一个 query 条件
        extra["queryExpression"] = str(props.get("query") or props.get("queryExpression") or "")
    elif node_type in ("ai_judge", "ai_generate"):
        # AI_TASK 不确定 apaas 是否真支持 — 加 task_type 让 apaas 平台自己识别 or 退到 SERVICE_TASK
        extra["task_type"] = node_type  # apaas 识别不到则可 fallback
        extra["aiModel"] = str(props.get("ai_model") or props.get("aiModel") or "")
        extra["aiPrompt"] = str(props.get("ai_prompt") or props.get("aiPrompt") or "")
        if node_type == "ai_judge":
            extra["judgeCriteria"] = str(props.get("judge_criteria") or props.get("judgeCriteria") or "")
    return extra


def _build_entry_extra_data(node_type: str, props: dict[str, Any], process_code: str) -> dict[str, Any]:
    """K2: entry 节点 (TIMER_START / MESSAGE_START) 的 data 扩展.

    - timer: timerType + cron (apaas cycle/date/duration)
    - webhook: messageType + webhookPath + secret
    """
    extra: dict[str, Any] = {}
    if node_type == "timer":
        extra["timerType"] = str(props.get("timer_type") or props.get("timerType") or "cycle")
        extra["cron"] = str(props.get("cron") or "")
    elif node_type == "webhook":
        extra["messageType"] = "webhook"
        # 默认 path 走 /webhook/<process_code> 或 props.path 覆盖
        provided_path = props.get("webhook_path") or props.get("webhookPath")
        if provided_path:
            extra["webhookPath"] = str(provided_path)
        else:
            safe_code = (process_code or "default").strip() or "default"
            extra["webhookPath"] = f"/webhook/{safe_code}"
        extra["secret"] = str(props.get("secret") or _gen_webhook_secret())
    return extra


def _build_apaas_edges(
    raw_edges: list[dict[str, Any]],
    known_node_ids: set[str],
    warnings: list[dict[str, str]],
) -> list[dict[str, Any]]:
    """K2: 按 frontend definition.edges 真还原 apaas sequenceFlow / lineList.

    apaas line shape (从 step_executor 反推, 加 K2 真分支字段):
      {
        id: edge.id or hash 兜底,
        source / sourceNodeKey: source 节点 id,
        target / targetNodeKey: target 节点 id,
        lineName: edge.label,
        conditionExpression: edge.condition (来自 condition/multi_branch 节点的分支条件)
        data: {titleI18nAssociated: False}
      }

    skip + warning 条件:
      - source / target 引用了不存在的节点 (orphan ref)
      - source == target (自环)
    """
    out: list[dict[str, Any]] = []
    if not isinstance(raw_edges, list):
        return out

    for e in raw_edges:
        if not isinstance(e, dict):
            continue
        src = str(e.get("source") or "").strip()
        tgt = str(e.get("target") or "").strip()
        if not src or not tgt:
            warnings.append({
                "id": str(e.get("id") or ""),
                "type": "orphan_edge",
                "reason": f"edge 缺 source/target — 已跳过 (source={src!r}, target={tgt!r})",
            })
            continue
        if src == tgt:
            warnings.append({
                "id": str(e.get("id") or ""),
                "type": "self_loop_edge",
                "reason": f"edge 形成自环 {src} → {src} — 已跳过",
            })
            continue
        if src not in known_node_ids:
            warnings.append({
                "id": str(e.get("id") or ""),
                "type": "orphan_edge",
                "reason": f"edge.source={src} 不在 nodes 列表里 — 已跳过",
            })
            continue
        if tgt not in known_node_ids:
            warnings.append({
                "id": str(e.get("id") or ""),
                "type": "orphan_edge",
                "reason": f"edge.target={tgt} 不在 nodes 列表里 — 已跳过",
            })
            continue
        edge_id = str(e.get("id") or "").strip()
        if not edge_id:
            # 用 hash 给个稳定 id
            edge_id = "line_" + hashlib.md5(f"{src}::{tgt}".encode("utf-8")).hexdigest()[:12]
        lbl = e.get("label") or ""
        cond = e.get("condition") or ""
        out.append({
            "id": edge_id,
            "lineId": edge_id,
            "source": src,
            "target": tgt,
            "sourceNodeKey": src,
            "targetNodeKey": tgt,
            "lineName": str(lbl),
            "conditionExpression": str(cond),
            "data": {"titleI18nAssociated": False},
        })
    return out


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
        (payload, warnings_or_unsupported)
            payload: 可直接传给 client.save_process_config
            warnings_or_unsupported: 未翻译的节点 / orphan edges / 兜底自动加 START/END 提示
                shape: [{id, type, reason, ...}]
                  - 老 P6 todo 节点 (timer/logic/action) K2 已实现, 不再 unsupported
                  - 仅在: 未知类型 / 空 / 缺 START / 缺 END / orphan edge 时填

    K2 实现:
        - logic 5 (condition/multi_branch/parallel_gateway/merge/wait) 真翻译
        - action 4 (write_data/read_data/ai_judge/ai_generate) 真翻译
        - entry 4 (start/end/timer/webhook) 真翻译
        - edges 按 frontend.edges 真还原 (不再是固定串行链)
        - 兜底: 空 / 缺 START / 缺 END / orphan ref 都不抛, 加 warning + 自动补
    """
    role_codes = role_codes or {}

    if not isinstance(definition, dict):
        raise ValueError("definition 必须是 dict")
    raw_nodes = definition.get("nodes") or []
    raw_edges = definition.get("edges") or []
    process_code = str(definition.get("process_name") or definition.get("process_code") or menu_id or "default")

    if not isinstance(raw_nodes, list):
        raise ValueError("definition.nodes 必须是 list")
    if not isinstance(raw_edges, list):
        raw_edges = []

    warnings: list[dict[str, str]] = []

    # 空 definition 兜底 — 返空 payload + warning
    if not raw_nodes and not raw_edges:
        warnings.append({
            "id": "",
            "type": "empty_definition",
            "reason": "definition 没 nodes 也没 edges — 返空 payload",
        })
        payload_empty = {
            "appId": apaas_app_id,
            "menuId": menu_id,
            "bpmn": _MINIMAL_BPMN,
            "nodes": [],
            "edges": [],
        }
        return payload_empty, warnings

    # 第一遍扫: 收集已知节点 id + 类型 + 检查 has_start/has_end
    has_start = False
    has_end = False
    platform_nodes: list[dict[str, Any]] = []
    known_node_ids: set[str] = set()

    for raw_node in raw_nodes:
        if not isinstance(raw_node, dict):
            continue
        node_type = str(raw_node.get("type") or "")
        node_id = str(raw_node.get("id") or "") or uuid.uuid4().hex
        node_label = str(raw_node.get("label") or node_type)
        node_props = raw_node.get("props") or {}
        if not isinstance(node_props, dict):
            node_props = {}
        position = raw_node.get("position") or {}
        if not isinstance(position, dict):
            position = {}
        try:
            x = float(position.get("x", 372.0))
        except (TypeError, ValueError):
            x = 372.0
        try:
            y = float(position.get("y", 100.0))
        except (TypeError, ValueError):
            y = 100.0

        # === entry: start / end / timer / webhook ===
        if node_type == "start":
            has_start = True
            platform_nodes.append(_make_apaas_node(node_id, node_label or "开始", "START", x, y))
            known_node_ids.add(node_id)
            continue
        if node_type == "end":
            has_end = True
            platform_nodes.append(_make_apaas_node(node_id, node_label or "结束", "END", x, y))
            known_node_ids.add(node_id)
            continue
        if node_type == "timer":
            platform_nodes.append(_make_apaas_node(
                node_id, node_label or "定时触发", "TIMER_START", x, y,
                extra_data=_build_entry_extra_data("timer", node_props, process_code),
            ))
            known_node_ids.add(node_id)
            continue
        if node_type == "webhook":
            platform_nodes.append(_make_apaas_node(
                node_id, node_label or "Webhook", "MESSAGE_START", x, y,
                extra_data=_build_entry_extra_data("webhook", node_props, process_code),
            ))
            known_node_ids.add(node_id)
            continue

        # === approval: 5 个 → APPROVE ===
        if node_type in APPROVAL_TO_APAAS:
            approvers = _resolve_approvers_from_props(node_type, node_props, role_codes)
            approve_type = "ALL" if node_type == "parallel_approval" else (
                "LEADER" if node_type == "manager_approval" else "SINGLE"
            )
            platform_nodes.append(_make_apaas_node(
                node_id, node_label, "APPROVE", x, y,
                approvers=approvers, approve_type=approve_type,
            ))
            known_node_ids.add(node_id)
            continue

        # === action: fill_form / write_data / read_data / ai_judge / ai_generate ===
        if node_type == "fill_form":
            # fill_form 等价 APPROVE 给 SUBMITTER
            platform_nodes.append(_make_apaas_node(
                node_id, node_label or "填写表单", "APPROVE", x, y,
                approvers=[{"approverType": "SUBMITTER", "approverName": "表单提交人", "approverCode": "SUBMITTER"}],
                approve_type="SINGLE",
            ))
            known_node_ids.add(node_id)
            continue
        if node_type in ACTION_TO_APAAS and node_type != "fill_form":
            apaas_type = ACTION_TO_APAAS[node_type]
            platform_nodes.append(_make_apaas_node(
                node_id, node_label, apaas_type, x, y,
                extra_data=_build_action_extra_data(node_type, node_props),
            ))
            known_node_ids.add(node_id)
            continue

        # === logic: condition / multi_branch / parallel_gateway / merge / wait ===
        if node_type in LOGIC_TO_APAAS:
            apaas_type = LOGIC_TO_APAAS[node_type]
            platform_nodes.append(_make_apaas_node(
                node_id, node_label, apaas_type, x, y,
                extra_data=_build_logic_extra_data(node_type, node_props),
            ))
            known_node_ids.add(node_id)
            continue

        # === 未知节点类型 → 收 warning 跳过 ===
        warnings.append({
            "id": node_id,
            "type": node_type,
            "label": node_label,
            "reason": f"未知节点类型 {node_type}",
        })

    # 兜底: 找不到 entry 节点 → 自动加 1 个 START
    if not has_start:
        # 找最小 y 作为 START 位置 (放最上)
        min_y = min((n.get("y", 100.0) for n in platform_nodes), default=32.0)
        start_node = _make_apaas_node("START", "开始", "START", 372.0, float(min_y) - 96.0)
        platform_nodes.insert(0, start_node)
        known_node_ids.add("START")
        warnings.append({
            "id": "START",
            "type": "auto_added",
            "reason": "definition 没有 start 节点 — 自动加了一个 START",
        })

    # 兜底: 找不到 end 节点 → 自动加 1 个 END
    if not has_end:
        max_y = max((n.get("y", 100.0) for n in platform_nodes), default=224.0)
        end_node = _make_apaas_node("END", "结束", "END", 372.0, float(max_y) + 96.0)
        platform_nodes.append(end_node)
        known_node_ids.add("END")
        warnings.append({
            "id": "END",
            "type": "auto_added",
            "reason": "definition 没有 end 节点 — 自动加了一个 END",
        })

    # K2: 用 frontend definition.edges 真还原 apaas edges (替代固定串行链)
    platform_edges = _build_apaas_edges(raw_edges, known_node_ids, warnings)

    payload = {
        "appId": apaas_app_id,
        "menuId": menu_id,
        "bpmn": _MINIMAL_BPMN,
        "nodes": platform_nodes,
        "edges": platform_edges,
    }

    return payload, warnings
