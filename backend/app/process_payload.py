"""aPaaS 流程 payload builder（抓包验证过的 schema）。

从 mcp_server 抽出共享：set_apaas_app_process（MCP 工具）和 generator_v2 Phase 5 都用这一份。
线性多级审批链 → 平台 /xdap-app/process/save/processConfig 接受的完整 payload。
**只动文件位置，不改任何逻辑**（行为由 tests/test_process_payload.py 锁定）。
"""
from __future__ import annotations

# ── 以下 7 个函数从 mcp_server.py:~5624-5977 原样搬入（逻辑零改动）──


def _bpmn_random_id() -> str:
    """生成平台风格的 BPMN_xxx id (16 hex chars)."""
    import secrets
    return "BPMN_" + secrets.token_hex(8)


# 2026-05-25: 平台审批节点完整 data 模板 — 抓包 docs/captures/process-* 实证.
# data.title / data.approvers / data.nodeId 需要每节点 swap, 其他默认.
def _approve_node_data_template(title: str, bpmn_id: str, approvers: list) -> dict:
    """返一个 APPROVE 节点的完整 data 字段 (含 10 个默认 button + voteConfig 等)."""
    return {
        "type": "APPROVE",
        "title": title,
        "approveType": "SINGLE",
        "chooseApprovalMethod": "STAY_AT_THE_NODE",
        "voteConfig": {
            "passMode": "PASS_NUMBER",
            "passNumber": 100,
            "passRate": "100",
            "passRateCalcMode": "INCLUDE_ABSTAIN",
            "oneVoteVeto": False,
            "flowMode": "ALL",
        },
        "sequentialApprover": {
            "approverSource": "", "approverValue": "", "appointType": "",
            "approverType": "APPROVER", "personType": "", "roleId": [],
            "approvalSequenceType": "",
            "appointValue": "", "xdapDepartments": None, "xdapUsers": [],
            "xdapRoles": None,
        },
        "approvers": approvers,
        "enableComponentPermission": True,
        "icon": "approve-icon",
        "remindList": [], "nodeRemindList": [], "approveRemindList": [],
        "approveRemindStatus": False, "nodeTriggerRemindStatus": False,
        "processEventStatus": False, "rejectRemindList": [],
        "rejectRemindStatus": False, "approveIsApplicantSkip": False,
        "approveButtons": [
            {"buttonCode": "APPROVE", "buttonName": "同意", "buttonLabel": "同意", "buttonStatus": True, "buttonStyle": "primary"},
            {"buttonCode": "REJECT", "buttonName": "拒绝", "buttonLabel": "拒绝", "buttonStatus": True},
            {"buttonCode": "INQUIRE", "buttonName": "征询", "buttonLabel": "征询", "buttonStyle": "primary"},
            {"buttonCode": "REASSIGN", "buttonName": "转交", "buttonLabel": "转交", "buttonStyle": "primary", "operatorScope": [], "index": 3},
            {"buttonCode": "ADDONE", "buttonName": "加签", "buttonLabel": "加签", "buttonStyle": "primary"},
            {"buttonCode": "FRONTADDONE", "buttonName": "前加签", "buttonLabel": "前加签", "buttonStyle": "primary"},
            {"buttonCode": "ANDCOUNTERSIGN", "buttonName": "并加签", "buttonLabel": "并加签", "buttonStyle": "primary"},
            {"buttonCode": "OVERRULE", "buttonName": "驳回", "buttonLabel": "驳回", "buttonStyle": "primary", "approveButtonConfigList": [], "overruleType": "any_node", "overruleReapprovalMethodAppoint": "DEFAULT", "overruleReapprovalMethod": "LEVEL_BY_LEVEL_APPROVAL", "modified": False},
            {"buttonCode": "WITHDRAW", "buttonName": "支持撤回", "buttonLabel": "撤回", "buttonStatus": False, "buttonStyle": "primary", "withdrawalType": "NEXT_NODE", "withdrawalList": []},
            {"buttonCode": "ABSTAIN", "buttonName": "保留意见", "buttonLabel": "保留意见", "buttonStatus": False, "buttonStyle": "primary"},
        ],
        "initiatorButtons": [
            {"buttonCode": "INITIATOR_TERMINATE", "buttonName": "终止", "buttonLabel": "终止", "buttonStatus": False, "buttonStyle": "primary"},
        ],
        "operationButtons": [
            {"buttonCode": "INFORM", "buttonName": "知会", "buttonLabel": "知会", "buttonStatus": False, "buttonStyle": "primary"},
            {"buttonCode": "STAGING", "buttonName": "暂存", "buttonLabel": "暂存", "buttonStatus": False, "buttonStyle": "primary"},
        ],
        "overtimeHandleConfig": {"status": False, "handleType": "RECOMMEND_DEAL_TIME", "timeUnit": "H"},
        "approveSkipConfig": False,
        "approvePhraseConfig": {"handleType": "INPUT_TYPE", "phrase": "", "status": False},
        "approveCommentConfig": {"required": False, "attachmentUpload": True, "requiredBtns": [], "show": True},
        "signatureConfig": {"required": False},
        "externalSystemApproval": {"status": False, "linkUrl": "", "linkMobileUrl": ""},
        "nodeId": bpmn_id,
        "timeoutRemindList": [],
        "supportBatchApprove": True,
        "supportBatchReject": True,
    }


def _start_node_data() -> dict:
    """START 节点 data — 用户发起表单填报阶段, 含 终止/重新提交/撤回 3 个表单按钮.
    capture 实证模板. 平台后端 deserialize 所有 node.data 成 NodeXxxConfig, 不给
    data 字段会 NPE (Cannot invoke ... because newData is null)."""
    return {
        "type": "START", "nodeId": "START", "title": "开始",
        "enableComponentPermission": True,
        "remindList": [], "processEventStatus": False,
        "approvePhraseConfig": {"handleType": "INPUT_TYPE", "phrase": "", "status": False},
        "approveCommentConfig": {"required": False, "attachmentUpload": True, "requiredBtns": [], "show": True},
        "formButtons": [
            {"buttonCode": "NORMAL_TERMINATE", "buttonName": "终止", "buttonLabel": "终止", "buttonStatus": False, "buttonStyle": "primary"},
            {"buttonCode": "RESTART", "buttonName": "重新提交", "buttonLabel": "重新提交", "buttonStatus": True, "buttonStyle": "primary"},
            {"buttonCode": "WITHDRAW", "buttonName": "撤回", "buttonLabel": "撤回", "buttonStatus": False, "buttonStyle": "primary", "withdrawalType": "SPECIFY_NODES", "withdrawalList": []},
        ],
        "externalSystemApproval": {"status": False, "linkUrl": "", "linkMobileUrl": ""},
    }


def _end_node_data() -> dict:
    """END 节点 data — 流程结束阶段, 含知会按钮. capture 实证模板."""
    return {
        "type": "END", "nodeId": "END", "title": "结束",
        "enableComponentPermission": False,
        "operationButtons": [
            {"buttonCode": "INFORM", "buttonName": "知会", "buttonLabel": "知会", "buttonStatus": False, "buttonStyle": "primary"},
        ],
        "externalSystemApproval": {"status": False, "linkUrl": "", "linkMobileUrl": ""},
    }


def _process_edge_template(edge_cell_id: str, source: str, target: str) -> dict:
    """返一条 edge — 平台 BPMN 渲染必填一堆视觉配置."""
    return {
        "id": edge_cell_id,
        "data": {
            "title": "\\", "type": "EDGE", "defaultFlow": True,
            "id": _bpmn_random_id(),
        },
        "align": "center", "bendable": True, "editable": False, "endArrow": "classic",
        "fontColor": "rgba(0, 0, 0, 1)", "labelBackgroundColor": "#f8f9fa",
        "movable": True, "orthogonal": True, "rounded": True, "shape": "connector",
        "sourceAnchorDx": "0", "stroke": "#313133", "edge": "orth",
        "sourceAnchorX": "0.5", "sourceAnchorY": "1",
        "targetAnchorX": "0.5", "targetAnchorY": "0", "targetAnchorDx": "0",
        "targetAnchorDy": "0",
        "label": "\\", "x": 0, "y": 0, "width": 0, "height": 0,
        "relative": True, "translateControlPoints": True, "verticalAlign": "middle",
        "schema": {
            "configurators": ["BpmnConfigTitle", "BpmnConfigDefaultFlow"], "hooks": {},
        },
        "visible": True, "source": source, "target": target,
    }


_MIN_BPMN_XML = (
    '<?xml version="1.0" encoding="UTF-8"?>\n'
    '<definitions xmlns:bpmndi="http://www.omg.org/spec/BPMN/20100524/DI" '
    'xmlns:omgdc="http://www.omg.org/spec/DD/20100524/DC" '
    'xmlns:omgdi="http://www.omg.org/spec/DD/20100524/DI" '
    'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" '
    'xmlns="http://www.omg.org/spec/BPMN/20100524/MODEL" typeLanguage="http://www.w3.org/2001/XMLSchema" '
    'expressionLanguage="http://www.w3.org/1999/XPath" targetNamespace="http://www.activiti.org/processdef"/>'
)


def _build_executable_bpmn_xml(
    process_def_id: str,
    stages: list,  # [{bpmn_id, title, next_edge_bpmn_id?}, ...]
    edges_data: list,  # [{bpmn_id, source, target}]
) -> str:
    """生成可执行 BPMN XML — Activiti 引擎要 isExecutable=true + 完整 userTask.

    平台 capture 实证 BPMN 结构:
      <definitions ...>
        <process id="..." isExecutable="true">
          <startEvent id="START"/>
          <userTask id="START_HIDDEN" .../>
          <endEvent id="END">
            <extensionElements>...activiti:executionListener...</extensionElements>
          </endEvent>
          <userTask id="{bpmn_id}" name="{title}" activiti:assignee="${{assignee}}">
            <extensionElements>...</extensionElements>
            <multiInstanceLoopCharacteristics ...activiti:collection="...processUsers..."/>
          </userTask>
          ...
          <sequenceFlow id="SequenceFlow_{edge_bpmn_id}" sourceRef="..." targetRef="..."/>
        </process>
      </definitions>
    """
    parts = []
    parts.append('<?xml version="1.0" encoding="UTF-8"?>')
    parts.append('<definitions xmlns:bpmndi="http://www.omg.org/spec/BPMN/20100524/DI" '
                 'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" '
                 'xmlns:di="http://www.omg.org/spec/DD/20100524/DI" '
                 'xmlns:dc="http://www.omg.org/spec/DD/20100524/DC" '
                 'xmlns="http://www.omg.org/spec/BPMN/20100524/MODEL" '
                 'xmlns:activiti="http://activiti.org/bpmn" '
                 'id="Definitions_1z0losk" '
                 'targetNamespace="http://bpmn.io/schema/bpmn" '
                 'exporter="bpmn-js (https://demo.bpmn.io)" exporterVersion="5.0.0">')
    parts.append('<process id="Process_Process_" isExecutable="true">')
    # startEvent + hidden start task.
    #
    # aPaaS VERSION_1.1 runtime expects an executable task after START. Without
    # START_HIDDEN, saved flows pass schema validation but runtime
    # processImageInfo can hit "currentFlowNode is null" when drawing the
    # active instance.
    parts.append('<startEvent id="START" name="开始"/>')
    first_edge = next((e for e in edges_data if e.get("source") == "START"), None)
    first_edge_id = first_edge.get("bpmn_id") if isinstance(first_edge, dict) else ""
    hidden_default_attr = f' default="SequenceFlow_{first_edge_id}"' if first_edge_id else ""
    parts.append(
        f'<userTask id="START_HIDDEN" name="开始"{hidden_default_attr} activiti:assignee="${{assignee}}">'
        '<extensionElements>'
        '<activiti:executionListener xmlns:activiti="http://activiti.org/bpmn" event="start" delegateExpression="${executionListener}"/>'
        '<activiti:executionListener xmlns:activiti="http://activiti.org/bpmn" event="end" delegateExpression="${executionListener}"/>'
        '</extensionElements>'
        '<multiInstanceLoopCharacteristics isSequential="false" '
        'xmlns:activiti="http://activiti.org/bpmn" '
        "activiti:collection=\"${procPersonHandle.processUsers(processId,'START_HIDDEN',documentId,submitter)}\" "
        'activiti:elementVariable="assignee">'
        '</multiInstanceLoopCharacteristics>'
        '</userTask>'
    )
    # endEvent
    parts.append('<endEvent id="END" name="结束">'
                 '<extensionElements>'
                 '<activiti:executionListener xmlns:activiti="http://activiti.org/bpmn" event="start" delegateExpression="${executionListener}"/>'
                 '<activiti:executionListener xmlns:activiti="http://activiti.org/bpmn" event="end" delegateExpression="${executionListener}"/>'
                 '</extensionElements>'
                 '</endEvent>')
    # 每个审批 stage → userTask
    for s in stages:
        bid = s["bpmn_id"]
        title = (s.get("title") or "审批").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")
        next_edge = s.get("next_edge_bpmn_id", "")
        default_attr = f' default="SequenceFlow_{next_edge}"' if next_edge else ""
        parts.append(
            f'<userTask id="{bid}" name="{title}"{default_attr} activiti:assignee="${{assignee}}">'
            '<extensionElements>'
            '<activiti:executionListener xmlns:activiti="http://activiti.org/bpmn" event="start" delegateExpression="${executionListener}"/>'
            '<activiti:executionListener xmlns:activiti="http://activiti.org/bpmn" event="end" delegateExpression="${executionListener}"/>'
            '</extensionElements>'
            '<multiInstanceLoopCharacteristics isSequential="false" '
            'xmlns:activiti="http://activiti.org/bpmn" '
            f"activiti:collection=\"${{procPersonHandle.processUsers(processId,'{bid}',documentId,submitter)}}\" "
            'activiti:elementVariable="assignee">'
            '<completionCondition>${nrOfCompletedInstances &gt; 0 and multiIsComplete}</completionCondition>'
            '</multiInstanceLoopCharacteristics>'
            '</userTask>'
        )
    # sequenceFlows
    for e in edges_data:
        bid = e["bpmn_id"]
        src = "START_HIDDEN" if e["source"] == "START" else e["source"]
        tgt = e["target"]
        parts.append(
            f'<sequenceFlow id="SequenceFlow_{bid}" sourceRef="{src}" targetRef="{tgt}"/>'
        )
    parts.append('<sequenceFlow id="SequenceFlow_START_HIDDEN" sourceRef="START" targetRef="START_HIDDEN"/>')
    parts.append('</process>')
    parts.append('</definitions>')
    return "\n".join(parts)


def _process_display_fields(form_components: list | None, limit: int = 4) -> list[dict]:
    """Pick stable form fields for the process detail display area."""
    fields: list[dict] = []
    for component in form_components or []:
        if not isinstance(component, dict):
            continue
        component_id = str(component.get("uuid") or component.get("componentId") or "").strip()
        component_name = str(component.get("label") or component.get("componentName") or component.get("name") or "").strip()
        component_type = str(component.get("componentType") or component.get("type") or "").strip()
        if not component_id or not component_name or not component_type:
            continue
        fields.append({
            "componentId": component_id,
            "componentName": component_name,
            "componentType": component_type,
        })
        if len(fields) >= limit:
            break
    return fields


def _build_process_payload_v2(
    app_id: str, form_id: str, menu_id: str,
    process_name: str, process_code: str,
    stages_with_role: list,  # [{name, approver_type, approver_id_or_submitter, approver_label}]
    form_components: list | None = None,
) -> dict:
    """用 capture 实证 schema 构建平台流程 payload.

    每个 stage 期望:
      - name: 节点显示标题
      - approver_type: ROLE | SUBMITTER
      - approver_value: ROLE 时是 role_id (snowflake, 用 query_roles 反查 role_code 拿到的 id); SUBMITTER 时填 "SUBMITTER"
      - approver_label: 显示名 (角色名 / "申请人")
    """
    # START / END 节点 — 必须含完整 data 字段, 否则平台后端 deserialize 成
    # NodeStartConfig/NodeEndConfig 时为 null → 触发 NPE "newData is null".
    # 实证 docs/captures/process-*.json START/END 都有 type/formButtons/等完整 data.
    start_cell_id = "cell-2"
    end_cell_id = "cell-3"
    nodes = [
        {"id": start_cell_id, "x": 372, "y": 32, "height": 64, "width": 64,
         "timeBoudries": [], "data": _start_node_data(), "nodeId": "START"},
        {"id": end_cell_id, "x": 372, "y": 240 + 120 * max(1, len(stages_with_role)),
         "height": 64, "width": 64,
         "timeBoudries": [], "data": _end_node_data(), "nodeId": "END"},
    ]
    edges = []
    # 同时跟踪 stages 跟 edges 的 BPMN id, 给 BPMN XML 用
    stage_bpmn_meta = []  # [{bpmn_id, title, next_edge_bpmn_id}]
    edge_bpmn_meta = []   # [{bpmn_id, source, target}]
    prev_node_id = start_cell_id
    # 画布上的 START/END 也用 cell-*；运行态/BPMN nodeId 仍是 START/END。
    # 平台设计器保存的可运行流程就是这种形态：edges 连接 cell-*，
    # BPMN XML 连接 START_HIDDEN / BPMN_* / END。
    prev_bpmn_id = "START"
    cell_idx = 3
    edge_idx = len(stages_with_role) + 3
    y_pos = 150
    for stage_idx, stage in enumerate(stages_with_role, start=1):
        cell_idx += 1
        cell_id = f"cell-{cell_idx}"
        bpmn_id = _bpmn_random_id()
        approver_type = (stage.get("approver_type") or "ROLE").upper()
        if approver_type == "SUBMITTER":
            approvers = [{
                "type": "SUBMITTER", "value": "SUBMITTER",
                "displayData": {"label": "申请人"},
            }]
        else:
            value = str(stage.get("approver_value") or "")
            label = stage.get("approver_label") or "审批人"
            approvers = [{
                "type": approver_type, "value": value,
                "displayData": {"id": value, "label": label},
            }]
        title = stage.get("name") or f"审批 {stage_idx}"
        nodes.append({
            "id": cell_id, "x": 340, "y": y_pos, "height": 48, "width": 112,
            "timeBoudries": [],
            "data": _approve_node_data_template(
                title=title, bpmn_id=bpmn_id, approvers=approvers,
            ),
            "nodeId": bpmn_id,
        })
        edge_idx += 1
        # edge bpmn id 必须跟 BPMN XML 里 sequenceFlow id 对齐
        in_edge_bpmn_id = _bpmn_random_id()
        edge_obj = _process_edge_template(
            edge_cell_id=f"cell-{edge_idx}",
            source=prev_node_id, target=cell_id,
        )
        edge_obj["data"]["id"] = in_edge_bpmn_id
        edges.append(edge_obj)
        edge_bpmn_meta.append({"bpmn_id": in_edge_bpmn_id,
                                "source": prev_bpmn_id,
                                "target": bpmn_id})
        stage_bpmn_meta.append({"bpmn_id": bpmn_id, "title": title,
                                "next_edge_bpmn_id": ""})  # fill after we know next edge
        prev_node_id = cell_id
        prev_bpmn_id = bpmn_id  # 下一条 BPMN 边的 source 用本节点的 bpmn_id（非图 cell id）
        # 记录指向当前 cell 的 edge id (给上一个 stage 用作 default)
        if len(stage_bpmn_meta) >= 2:
            # 之前那个 stage 后的 edge 就是当前 in_edge
            stage_bpmn_meta[-2]["next_edge_bpmn_id"] = in_edge_bpmn_id
        y_pos += 96
    # 最后一条 edge 接 END
    edge_idx += 1
    last_edge_bpmn_id = _bpmn_random_id()
    last_edge_obj = _process_edge_template(
        edge_cell_id=f"cell-{edge_idx}",
        source=prev_node_id, target=end_cell_id,
    )
    last_edge_obj["data"]["id"] = last_edge_bpmn_id
    edges.append(last_edge_obj)
    # 最后一条 edge: BPMN sourceRef 用最后 stage 的 executable node id.
    last_stage_bpmn_id = stage_bpmn_meta[-1]["bpmn_id"] if stage_bpmn_meta else "START"
    edge_bpmn_meta.append({"bpmn_id": last_edge_bpmn_id,
                            "source": last_stage_bpmn_id, "target": "END"})
    if stage_bpmn_meta:
        stage_bpmn_meta[-1]["next_edge_bpmn_id"] = last_edge_bpmn_id

    # 生成可执行 BPMN XML (Activiti 引擎必需 isExecutable=true)
    bpmn_xml = _build_executable_bpmn_xml(
        process_def_id=_bpmn_random_id().replace("BPMN_", ""),
        stages=stage_bpmn_meta,
        edges_data=edge_bpmn_meta,
    )

    # processGlobalConfig 平台 UI 默认填的流程标题模板 (capture 实证)
    process_global_config = {
        "titleConfigList": [
            {"componentId": "submitter", "name": "发起人", "type": "COMPONENT"},
            {"value": "创建的", "type": "TEXT"},
            {"componentId": "formName", "name": "表单名称", "type": "COMPONENT"},
            {"value": "流程\n", "type": "TEXT"},
        ],
        "processDisplayFieldList": _process_display_fields(form_components),
        "approveUiMobile": "MODAL",
        "approveUiPc": "DETAIL",
        "processViewDisplayField": "processStatus",
    }
    return {
        "appId": app_id,
        "formId": form_id,
        "menuId": menu_id,
        "bpmn": bpmn_xml,
        "status": "ENABLE",
        "engine": "VERSION_1.1",
        "nodes": nodes,
        "edges": edges,
        "processRule": {},
        "globalSettings": {},
        "processGlobalConfig": process_global_config,
        "openProcessVersion": False,
    }


# 对外公开名（generator_v2 / 新代码用这个）
build_process_payload = _build_process_payload_v2
