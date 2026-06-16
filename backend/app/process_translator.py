"""ProcessDefinition → apaas 平台 schema 翻译器 (design-v4 I4 + K2).

把前端 ProcessDesignerPanel 序列化的应用层 JSON (24 节点类型) 转换为
apaas 平台 /xdap-app/process/save/processConfig 接收的 payload.

apaas 平台节点/边结构 (实测来自低代码平台流程设计器 + processConfigDetail):
- START / END                     — 圆形入口出口 (apaas 实测支持)
- APPROVE                         — 审批 (UserTask, apaas 实测支持)
- TIMER_START / MESSAGE_START     — 定时 / Webhook 触发 (BPMN start event with timer/message)
- condition / multi_branch        — 不保存独立网关；折叠成条件连线 + processRule
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
- logic 5 个全翻译 (条件边 + processRule / PARALLEL_GATEWAY / TIMER_BOUNDARY)
- action 4 个全翻译 (SERVICE_TASK / AI_TASK)
- timer / webhook 真翻译 (TIMER_START / MESSAGE_START)
- edges 按 frontend.edges 真拓扑还原 (fork / join / 分支 / 并行 全保真)
- 兜底: 空 definition / 缺 start / 缺 end / orphan edge ref 全友好处理

参考: step_executor.execute_create_workflow (现 SPEC 走的 BPMN platform_nodes 构造).
"""
from __future__ import annotations

import ast
import hashlib
import logging
import re
import secrets
import uuid
from typing import Any, Optional

from app.process_payload import (
    _approve_node_data_template,
    _end_node_data,
    _process_edge_template,
    _start_node_data,
)

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

# logic: 5 个 → 平台流程结构
LOGIC_TO_APAAS: dict[str, str] = {
    # aPaaS 流程设计器的条件分支不保存独立 gateway 节点。UI 会把分支条件
    # 挂到 sequence edge 的 data.id 上, 再用 processRule[edge.data.id] 关联规则。
    # translator 会在建图前把 condition/multi_branch 节点折叠为条件边。
    "condition": "CONDITION_EDGE",
    "multi_branch": "CONDITION_EDGE",
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

NODE_TYPE_ALIASES: dict[str, str] = {
    # Agent/tool callers often use BPMN/platform terms instead of the
    # ProcessDesigner frontend type names. Normalize at the translator boundary
    # so branch edges still see a known gateway id.
    "branch": "condition",
    "condition_branch": "condition",
    "conditional_branch": "condition",
    "decision": "condition",
    "decision_gateway": "condition",
    "gateway": "condition",
    "exclusive_gateway": "condition",
    "exclusivegateway": "condition",
    "parallelgateway": "parallel_gateway",
    "approve": "assignee_approval",
    "approval": "assignee_approval",
    "user_task": "assignee_approval",
    "usertask": "assignee_approval",
    "service": "write_data",
    "service_task": "write_data",
    "servicetask": "write_data",
}


def normalize_process_node_type(value: Any) -> str:
    """Return the internal ProcessDesigner node type for frontend/BPMN/apaas aliases."""
    raw = str(value or "").strip()
    if not raw:
        return ""
    key = raw.replace("-", "_").lower()
    return NODE_TYPE_ALIASES.get(key, key)

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

_DEFAULT_CONDITION_VALUES = {"", "default", "else", "otherwise", "其他", "默认", "兜底"}
_EQUAL_OPERATORS = {"==", "=", "eq", "equals", "equal", "是", "为", "等于"}
_NOT_EQUAL_OPERATORS = {"!=", "<>", "≠", "ne", "neq", "not_eq", "not_equal", "not_equals", "不是", "不等于"}
# aPaaS simpleRule numeric comparison op codes — 抓包实证 (docs: /xdap-app/rule/save/simpleRule):
# ≥ → "ge", > → "gt", ≤ → "le", < → "lt" (与 eq/neq 同为 2 字母编码).
_GREATER_EQUAL_OPERATORS = {">=", "≥", "≧", "ge", "gte", "大于等于", "不小于", "不少于", "至少"}
_GREATER_OPERATORS = {">", "gt", "大于", "超过", "高于", "多于"}
_LESS_EQUAL_OPERATORS = {"<=", "≤", "≦", "le", "lte", "小于等于", "不大于", "不超过", "最多"}
_LESS_OPERATORS = {"<", "lt", "小于", "低于", "少于"}
# 数值比较 op → 平台 fieldRule.type 必须是 "number" (抓包实证), eq/neq 维持 "string".
_NUMERIC_OPERATORS = {"gt", "ge", "lt", "le"}


def _escape_xml_text(value: Any) -> str:
    text = str(value or "")
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _is_default_condition(value: Any) -> bool:
    return str(value or "").strip().lower() in _DEFAULT_CONDITION_VALUES


def _looks_like_condition_text(value: Any) -> bool:
    text = str(value or "").strip()
    if not text or _is_default_condition(text):
        return False
    if text.startswith("{") and ("field" in text or "fieldCode" in text or "operator" in text):
        return True
    return bool(
        re.search(
            r"(==|!=|<>|>=|<=|≥|≤|≧|≦|>|<|=|\beq\b|\bne\b|\bneq\b|\bgt\b|\bge\b|\blt\b|\ble\b"
            r"|是|为|等于|不等于|大于等于|小于等于|不小于|不大于|大于|小于|超过|低于|高于|至少|不超过|最多)",
            text,
            flags=re.IGNORECASE,
        )
    )


def _edge_label_value(edge: dict[str, Any]) -> str:
    props = edge.get("props") if isinstance(edge.get("props"), dict) else {}
    data = edge.get("data") if isinstance(edge.get("data"), dict) else {}
    return str(
        edge.get("label")
        or edge.get("lineName")
        or edge.get("title")
        or props.get("label")
        or props.get("lineName")
        or props.get("title")
        or data.get("label")
        or data.get("lineName")
        or data.get("title")
        or ""
    ).strip()


def _edge_condition_value(edge: dict[str, Any]) -> str:
    props = edge.get("props") if isinstance(edge.get("props"), dict) else {}
    data = edge.get("data") if isinstance(edge.get("data"), dict) else {}
    explicit = str(
        edge.get("condition")
        or edge.get("conditionExpression")
        or props.get("condition")
        or props.get("conditionExpression")
        or data.get("condition")
        or data.get("conditionExpression")
        or ""
    ).strip()
    if explicit:
        return explicit
    label = _edge_label_value(edge)
    if _looks_like_condition_text(label):
        return label
    return ""


def _component_value(component: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = component.get(key)
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return ""


def _component_lookup(form_components: Optional[list[dict[str, Any]]]) -> dict[str, dict[str, Any]]:
    lookup: dict[str, dict[str, Any]] = {}
    for component in form_components or []:
        if not isinstance(component, dict):
            continue
        bo_code = _component_value(component, "bo_code", "boCode", "bocode")
        model_field = _component_value(component, "modelField", "model_field")
        field_code = _component_value(component, "fieldCode", "field_code", "code")
        label = _component_value(component, "label", "componentName", "name", "widgetText")
        uuid_value = _component_value(component, "uuid", "id", "componentId")
        keys = [bo_code, model_field, field_code, label, uuid_value]
        for compound in (bo_code, model_field):
            if "~" in compound:
                keys.append(compound.split("~", 1)[1])
            if "." in compound:
                keys.append(compound.rsplit(".", 1)[1])
        for key in keys:
            if key:
                lookup[key] = component
    return lookup


def _component_bo_code(field_ref: str, lookup: dict[str, dict[str, Any]]) -> str:
    ref = str(field_ref or "").strip()
    if not ref:
        return ""
    if "~" in ref and ref not in lookup:
        return ref
    component = lookup.get(ref)
    if component:
        return _component_value(component, "bo_code", "boCode", "bocode", "modelField", "model_field") or ref
    return ref


def _resolve_option_value(bo_code: str, raw_value: str, lookup: dict[str, dict[str, Any]]) -> str:
    value = str(raw_value or "").strip()
    component = lookup.get(bo_code) or lookup.get(bo_code.split("~", 1)[-1])
    if not component:
        return value
    options = (
        component.get("choose_options")
        or component.get("chooseOptions")
        or component.get("dictionary_choose_options")
        or component.get("dictionaryChooseOptions")
        or []
    )
    if not isinstance(options, list):
        return value
    for option in options:
        if not isinstance(option, dict):
            continue
        option_id = _component_value(option, "id", "value", "code")
        option_label = _component_value(option, "label", "name", "text")
        if value and value in {option_id, option_label}:
            return option_id or value
    return value


# 人类可读连线名/标签里的操作符（符号 + 中文词）。长操作符在前，避免 ">=" 被 ">" 抢匹配。
_TEXT_OP_PATTERN = (
    r">=|<=|≥|≤|≧|≦|==|!=|<>|≠|>|<|="
    r"|大于等于|小于等于|不小于|不大于|不等于|不超过|大于|小于|超过|低于|高于|至少|最多|等于|不是|是|为"
)


def _search_condition_in_text(
    text: str,
    lookup: dict[str, dict[str, Any]],
) -> tuple[str, str, str] | None:
    """从带前缀的描述性连线名里抽 (field_ref, op, value)。

    例: "高预算：项目预算≥100000" → ("项目预算", "≥", "100000")。
    做法: 在文本里定位某个已知表单组件引用(字段名/编码, 长的优先), 再取其后的操作符+值。
    """
    keys = sorted(
        {k for k in lookup if k and len(str(k)) >= 2},
        key=lambda s: len(str(s)),
        reverse=True,
    )
    for key in keys:
        idx = text.find(key)
        if idx < 0:
            continue
        rest = text[idx + len(key):]
        match = re.match(
            r"\s*(?P<op>" + _TEXT_OP_PATTERN + r")\s*['\"]?(?P<value>[^'\"\s]+)",
            rest,
        )
        if match:
            value = match.group("value").strip().rstrip("。.,，、)）")
            if value:
                return key, match.group("op"), value
    return None


def _parse_simple_condition(
    condition: Any,
    lookup: dict[str, dict[str, Any]],
) -> tuple[str, str, str] | None:
    """把条件解析成 (bo_code, op, value)。op ∈ {eq, neq, gt, ge, lt, le}。"""
    mapping = _condition_mapping(condition)
    if mapping:
        field_ref = _first_text(
            mapping,
            "boCode",
            "bo_code",
            "fieldBoCode",
            "field_bo_code",
            "modelField",
            "model_field",
            "fieldCode",
            "field_code",
            "field",
        )
        raw_value = _first_condition_value(mapping, "value", "valueCode", "value_code", "optionId", "option_id")
        if raw_value == "":
            raw_value = _first_condition_value(mapping, "valueLabel", "value_label", "label")
        op = _normalize_rule_operator(mapping.get("operator") or mapping.get("op") or "eq")
        if not field_ref or not raw_value or not op:
            return None
        bo_code = _component_bo_code(field_ref, lookup)
        if not bo_code:
            return None
        # 数值比较 (gt/ge/lt/le) 的值是数字, 不走字典选项反查。
        value = raw_value if op in _NUMERIC_OPERATORS else _resolve_option_value(bo_code, raw_value, lookup)
        return bo_code, op, value

    text = str(condition or "").strip()
    if not text or _is_default_condition(text):
        return None

    field_ref = ""
    raw_value = ""
    op = ""

    invoke_match = re.search(
        r"componentvalue['\"]\s*,\s*['\"](?P<field>[^'\"]+)['\"][\s\S]*?(?:==|=)\s*\(?\s*['\"](?P<value>[^'\"]+)['\"]",
        text,
    )
    if invoke_match:
        field_ref = invoke_match.group("field")
        raw_value = invoke_match.group("value")
        op = "eq"
    else:
        simple_match = re.match(
            r"^\s*(?P<field>[\w.~一-龥]+?)\s*(?P<op>" + _TEXT_OP_PATTERN + r")\s*['\"]?(?P<value>[^'\"]+?)['\"]?\s*$",
            text,
            flags=re.IGNORECASE,
        )
        if simple_match:
            field_ref = simple_match.group("field")
            raw_value = simple_match.group("value")
            op = _normalize_rule_operator(simple_match.group("op"))
        else:
            # 描述性连线名(带前缀, 如 "高预算：项目预算≥100000")按已知组件引用搜索。
            searched = _search_condition_in_text(text, lookup)
            if searched:
                field_ref, raw_op, raw_value = searched
                op = _normalize_rule_operator(raw_op)

    if not field_ref or raw_value == "" or not op:
        return None

    bo_code = _component_bo_code(field_ref, lookup)
    if not bo_code:
        return None
    value = str(raw_value).strip() if op in _NUMERIC_OPERATORS else _resolve_option_value(bo_code, raw_value, lookup)
    return bo_code, op, value


def _condition_mapping(condition: Any) -> dict[str, Any] | None:
    if isinstance(condition, dict):
        return condition
    text = str(condition or "").strip()
    if not text.startswith("{") or "}" not in text:
        return None
    try:
        parsed = ast.literal_eval(text)
    except (SyntaxError, ValueError):
        return None
    return parsed if isinstance(parsed, dict) else None


def _first_text(mapping: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = mapping.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
        if value is not None and not isinstance(value, (dict, list, tuple, set)):
            text = str(value).strip()
            if text:
                return text
    return ""


def _first_condition_value(mapping: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = mapping.get(key)
        if isinstance(value, list) and value:
            value = value[0]
        if isinstance(value, dict):
            value = value.get("id") or value.get("value") or value.get("code") or value.get("label")
        text = str(value or "").strip()
        if text:
            return text
    return ""


def _normalize_rule_operator(value: Any) -> str:
    op = str(value or "").strip().lower()
    if op in _EQUAL_OPERATORS:
        return "eq"
    if op in _NOT_EQUAL_OPERATORS:
        return "neq"
    if op in _GREATER_EQUAL_OPERATORS:
        return "ge"
    if op in _GREATER_OPERATORS:
        return "gt"
    if op in _LESS_EQUAL_OPERATORS:
        return "le"
    if op in _LESS_OPERATORS:
        return "lt"
    return ""


def _build_simple_process_rule(
    condition: str,
    menu_id: str,
    lookup: dict[str, dict[str, Any]],
) -> dict[str, Any] | None:
    parsed = _parse_simple_condition(condition, lookup)
    if not parsed:
        return None
    bo_code, op, value = parsed
    # 抓包实证 (aPaaS /xdap-app/rule/save/simpleRule): 数值比较用 type="number",
    # eq/neq 用 type="string"; 平台前端不发 express/hasBoTrans, 但带 queryFieldType。
    field_type = "number" if op in _NUMERIC_OPERATORS else "string"
    simple_rule_config = {
        "ruleType": "simple",
        "menuId": menu_id,
        "queryFieldType": "businessObj",
        "formFieldRuleList": [
            {
                "connectOperation": "or",
                "fieldRuleList": [
                    {
                        "op": op,
                        "type": field_type,
                        "boCode": bo_code,
                        "values": [value],
                        "transValues": [],
                    }
                ],
            }
        ],
    }
    return {"ruleType": "simple", "simpleRuleConfig": simple_rule_config}


# --- 节点尺寸 (按 apaas type 区分) ---
def _node_size(apaas_type: str) -> tuple[str, str]:
    """返 (width, height) — apaas 平台字符串数字."""
    if apaas_type in ("START", "END", "TIMER_START", "MESSAGE_START"):
        return ("64.0", "64.0")
    if apaas_type in ("PARALLEL_GATEWAY", "TIMER_BOUNDARY"):
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

    def _platform_approver(kind: str, value: str, label: str = "") -> dict[str, Any]:
        kind = (kind or "USER").upper()
        value = str(value or "").strip()
        if kind == "ROLE":
            hit = role_codes.get(value) or {}
            value = str(hit.get("id") or hit.get("roleId") or hit.get("value") or value).strip()
            label = label or str(hit.get("roleName") or hit.get("name") or hit.get("roleCode") or value)
        elif kind == "SUBMITTER":
            value = "SUBMITTER"
            label = label or "申请人"
        elif kind in ("LEADER", "MANAGER"):
            value = value or "LEADER"
            label = label or "上级"
        else:
            label = label or value
        return {"type": kind, "value": value, "displayData": {"id": value, "label": label or value}}

    def _from_item(item: Any, default_kind: str = "USER") -> dict[str, Any] | None:
        if isinstance(item, dict):
            display = item.get("displayData") if isinstance(item.get("displayData"), dict) else {}
            kind = str(item.get("type") or item.get("approverType") or default_kind).upper()
            value = str(
                item.get("value")
                or item.get("approverValue")
                or item.get("approverCode")
                or item.get("roleId")
                or item.get("userId")
                or item.get("id")
                or ""
            ).strip()
            label = str(
                item.get("label")
                or item.get("name")
                or item.get("roleName")
                or item.get("userName")
                or display.get("label")
                or ""
            ).strip()
            if value or kind == "SUBMITTER":
                return _platform_approver(kind, value, label)
            return None
        value = str(item or "").strip()
        if value:
            return _platform_approver(default_kind, value)
        return None

    if node_type == "assignee_approval":
        # props.assignee / props.approvers — backend node JSON
        assignees = props.get("approvers") or ([props["assignee"]] if props.get("assignee") else [])
        if not isinstance(assignees, list):
            assignees = [assignees]
        out = []
        for a in assignees:
            item = _from_item(a, default_kind="USER")
            if item:
                out.append(item)
        if not out:
            out = [_platform_approver("SUBMITTER", "SUBMITTER", "表单提交人")]
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
            return [_platform_approver("ROLE", role_code)]
        return [_platform_approver("SUBMITTER", "SUBMITTER", "表单提交人")]

    if node_type == "manager_approval":
        return [_platform_approver("LEADER", "LEADER", "上级")]

    if node_type == "parallel_approval":
        assignees = props.get("approvers") or []
        if not isinstance(assignees, list):
            assignees = [assignees]
        out = []
        for a in assignees:
            item = _from_item(a, default_kind="USER")
            if item:
                out.append(item)
        if not out:
            out = [_platform_approver("SUBMITTER", "SUBMITTER", "表单提交人")]
        return out

    if node_type in ("cc", "fill_form"):
        return [_platform_approver("SUBMITTER", "SUBMITTER", "表单提交人")]

    return [_platform_approver("SUBMITTER", "SUBMITTER", "表单提交人")]


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
                  PARALLEL_GATEWAY, TIMER_BOUNDARY,
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
        n["data"] = _start_node_data()
    elif apaas_type == "APPROVE":
        n["data"] = _approve_node_data_template(title=title, bpmn_id=node_id, approvers=approvers or [])
        n["data"]["approveType"] = approve_type
    elif apaas_type == "END":
        n["data"] = _end_node_data()
    # 合并节点专属字段
    if extra_data:
        n["data"].update(extra_data)
    return n


def _build_logic_extra_data(node_type: str, props: dict[str, Any]) -> dict[str, Any]:
    """K2: logic 节点 (PARALLEL_GATEWAY/TIMER_BOUNDARY) 的 data 扩展.

    - condition / multi_branch: 已在建图前折叠成条件边, 不会进入这里
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


def _flatten_condition_nodes(
    raw_nodes: list[dict[str, Any]],
    raw_edges: list[dict[str, Any]],
    warnings: list[dict[str, str]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """把 ProcessDesigner 的 condition/multi_branch 节点折叠成 aPaaS 条件边.

    aPaaS 平台 UI 的真实保存结构是:
      upstream node --(default edge)--> default target
      upstream node --(conditional edge + processRule)--> branch target

    而不是保存独立 gateway 节点。因此本函数把 `A -> condition -> B/C`
    转成 `A -> B` 和 `A -> C`, 保留 outgoing edge 的 label/condition。
    """
    condition_node_ids: set[str] = set()
    for node in raw_nodes:
        if not isinstance(node, dict):
            continue
        node_type = normalize_process_node_type(node.get("type"))
        if node_type in {"condition", "multi_branch"}:
            node_id = str(node.get("id") or "").strip()
            if node_id:
                condition_node_ids.add(node_id)

    if not condition_node_ids:
        return raw_nodes, raw_edges

    passthrough_edges: list[dict[str, Any]] = [
        edge for edge in raw_edges
        if isinstance(edge, dict)
        and str(edge.get("source") or "").strip() not in condition_node_ids
        and str(edge.get("target") or "").strip() not in condition_node_ids
    ]

    for node_id in sorted(condition_node_ids):
        incoming = [
            edge for edge in raw_edges
            if isinstance(edge, dict) and str(edge.get("target") or "").strip() == node_id
        ]
        outgoing = [
            edge for edge in raw_edges
            if isinstance(edge, dict) and str(edge.get("source") or "").strip() == node_id
        ]
        if not incoming or not outgoing:
            warnings.append({
                "id": node_id,
                "type": "condition",
                "reason": "condition 节点缺入边或出边 — 已跳过该分支节点",
            })
            continue
        for in_edge in incoming:
            in_source = str(in_edge.get("source") or "").strip()
            if not in_source:
                continue
            for out_edge in outgoing:
                out_target = str(out_edge.get("target") or "").strip()
                if not out_target:
                    continue
                merged = dict(out_edge)
                in_id = str(in_edge.get("id") or in_source).strip()
                out_id = str(out_edge.get("id") or out_target).strip()
                merged["id"] = f"{in_id}__{out_id}"
                merged["source"] = in_source
                merged["target"] = out_target
                passthrough_edges.append(merged)

    flattened_nodes = [
        node for node in raw_nodes
        if isinstance(node, dict) and str(node.get("id") or "").strip() not in condition_node_ids
    ]
    return flattened_nodes, passthrough_edges


def _build_apaas_edges(
    raw_edges: list[dict[str, Any]],
    known_node_ids: set[str],
    warnings: list[dict[str, str]],
    *,
    menu_id: str = "",
    form_components: Optional[list[dict[str, Any]]] = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
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
    process_rules: dict[str, Any] = {}
    lookup = _component_lookup(form_components)
    if not isinstance(raw_edges, list):
        return out, process_rules

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
        lbl = _edge_label_value(e)
        cond = _edge_condition_value(e)
        edge = _process_edge_template(edge_id, src, tgt)
        edge["lineId"] = edge_id
        edge["sourceNodeKey"] = src
        edge["targetNodeKey"] = tgt
        edge["lineName"] = str(lbl)
        edge["conditionExpression"] = str(cond)
        edge["label"] = str(lbl) or edge.get("label") or "\\\\"
        edge["data"]["title"] = str(lbl) or edge["data"].get("title") or "\\\\"
        edge["data"]["conditionExpression"] = str(cond)
        if _is_default_condition(cond):
            edge["data"]["defaultFlow"] = True
        elif str(cond).strip():
            edge["data"]["defaultFlow"] = False
            rule = _build_simple_process_rule(str(cond), menu_id, lookup)
            if rule:
                process_rules[str(edge["data"]["id"])] = rule
            else:
                warnings.append({
                    "id": edge_id,
                    "type": "condition_rule",
                    "reason": f"条件表达式 {cond!r} 暂不能翻译成 aPaaS simpleRule — 已只保留条件文本",
                })
        out.append(edge)
    return out, process_rules


def _node_bpmn_id_by_cell(nodes: list[dict[str, Any]]) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for node in nodes or []:
        data = node.get("data") if isinstance(node.get("data"), dict) else {}
        cell_id = str(node.get("id") or "")
        bpmn_id = str(data.get("nodeId") or node.get("nodeId") or cell_id)
        if cell_id:
            mapping[cell_id] = bpmn_id
    return mapping


def _default_edge_sequence_id(edges: list[dict[str, Any]], source: str) -> str:
    source_edges = [edge for edge in edges or [] if str(edge.get("source") or "") == source]
    if not source_edges:
        return ""
    default_edge = next(
        (edge for edge in source_edges if (edge.get("data") or {}).get("defaultFlow") is True),
        source_edges[0],
    )
    edge_data_id = ((default_edge.get("data") or {}).get("id") or default_edge.get("id") or "")
    return f"SequenceFlow_{edge_data_id}" if edge_data_id else ""


def build_apaas_bpmn_xml(
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
    process_rule: Optional[dict[str, Any]] = None,
) -> str:
    """生成 aPaaS VERSION_1.1 可执行 BPMN XML.

    这里按平台流程设计器实测结构生成:
    START event -> START_HIDDEN userTask -> 图上的审批节点/结束节点。
    图中 source=START 的边在 BPMN 中 sourceRef=START_HIDDEN。
    """
    process_rule = process_rule or {}
    id_by_cell = _node_bpmn_id_by_cell(nodes)
    parts: list[str] = []
    parts.append('<?xml version="1.0" encoding="UTF-8"?>')
    parts.append(
        '<definitions xmlns:bpmndi="http://www.omg.org/spec/BPMN/20100524/DI" '
        'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" '
        'xmlns:di="http://www.omg.org/spec/DD/20100524/DI" '
        'xmlns:dc="http://www.omg.org/spec/DD/20100524/DC" '
        'xmlns="http://www.omg.org/spec/BPMN/20100524/MODEL" '
        'xmlns:activiti="http://activiti.org/bpmn" '
        'id="Definitions_Process" targetNamespace="http://bpmn.io/schema/bpmn" '
        'exporter="ai-builder" exporterVersion="1.0">'
    )
    parts.append('<process id="Process_Process_" isExecutable="true">')
    parts.append('<startEvent id="START" name="开始"/>')

    start_default = _default_edge_sequence_id(edges, "START")
    start_default_attr = f' default="{start_default}"' if start_default else ""
    parts.append(
        f'<userTask id="START_HIDDEN" name="开始" activiti:assignee="${{assignee}}"{start_default_attr}>'
        '<extensionElements>'
        '<activiti:executionListener xmlns:activiti="http://activiti.org/bpmn" event="start" delegateExpression="${executionListener}"/>'
        '<activiti:executionListener xmlns:activiti="http://activiti.org/bpmn" event="end" delegateExpression="${executionListener}"/>'
        '</extensionElements>'
        '<multiInstanceLoopCharacteristics isSequential="false" xmlns:activiti="http://activiti.org/bpmn" '
        'activiti:collection="${procPersonHandle.processUsers(processId,&apos;START&apos;,documentId,submitter)}" '
        'activiti:elementVariable="assignee">'
        '<completionCondition>${nrOfCompletedInstances &gt; 0 and multiIsComplete}</completionCondition>'
        '</multiInstanceLoopCharacteristics>'
        '</userTask>'
    )

    for node in nodes or []:
        data = node.get("data") if isinstance(node.get("data"), dict) else {}
        node_type = str(data.get("type") or "")
        if node_type in {"START", "END"}:
            continue
        bpmn_id = str(data.get("nodeId") or node.get("nodeId") or node.get("id") or "")
        if not bpmn_id:
            continue
        title = _escape_xml_text(data.get("title") or node.get("label") or "审批")
        default_sequence = _default_edge_sequence_id(edges, str(node.get("id") or ""))
        default_attr = f' default="{default_sequence}"' if default_sequence else ""
        parts.append(
            f'<userTask id="{_escape_xml_text(bpmn_id)}" name="{title}"{default_attr} activiti:assignee="${{assignee}}">'
            '<extensionElements>'
            '<activiti:executionListener xmlns:activiti="http://activiti.org/bpmn" event="start" delegateExpression="${executionListener}"/>'
            '<activiti:executionListener xmlns:activiti="http://activiti.org/bpmn" event="end" delegateExpression="${executionListener}"/>'
            '</extensionElements>'
            '<multiInstanceLoopCharacteristics isSequential="false" xmlns:activiti="http://activiti.org/bpmn" '
            f'activiti:collection="${{procPersonHandle.processUsers(processId,&apos;{_escape_xml_text(bpmn_id)}&apos;,documentId,submitter)}}" '
            'activiti:elementVariable="assignee">'
            '<completionCondition>${nrOfCompletedInstances &gt; 0 and multiIsComplete}</completionCondition>'
            '</multiInstanceLoopCharacteristics>'
            '</userTask>'
        )

    parts.append(
        '<endEvent id="END" name="结束">'
        '<extensionElements>'
        '<activiti:executionListener xmlns:activiti="http://activiti.org/bpmn" event="start" delegateExpression="${executionListener}"/>'
        '<activiti:executionListener xmlns:activiti="http://activiti.org/bpmn" event="end" delegateExpression="${executionListener}"/>'
        '</extensionElements>'
        '</endEvent>'
    )

    for edge in edges or []:
        data = edge.get("data") if isinstance(edge.get("data"), dict) else {}
        edge_data_id = str(data.get("id") or edge.get("id") or "")
        if not edge_data_id:
            continue
        source_cell = str(edge.get("source") or "")
        target_cell = str(edge.get("target") or "")
        source_ref = "START_HIDDEN" if source_cell == "START" else id_by_cell.get(source_cell, source_cell)
        target_ref = id_by_cell.get(target_cell, target_cell)
        rule = process_rule.get(edge_data_id) if isinstance(process_rule, dict) else None
        simple_rule_id = ""
        if isinstance(rule, dict):
            simple_rule_id = str(
                rule.get("simpleRuleId")
                or (rule.get("simpleRuleConfig") or {}).get("id")
                or ""
            )
        if simple_rule_id and data.get("defaultFlow") is not True:
            parts.append(
                f'<sequenceFlow id="SequenceFlow_{_escape_xml_text(edge_data_id)}" '
                f'sourceRef="{_escape_xml_text(source_ref)}" targetRef="{_escape_xml_text(target_ref)}">'
                '<conditionExpression xsi:type="tFormalExpression">'
                f"<![CDATA[${{procRuleHandle.executeSimpleProcRule(processId, documentId, '{simple_rule_id}', outcome)}}]]>"
                '</conditionExpression>'
                '</sequenceFlow>'
            )
        else:
            parts.append(
                f'<sequenceFlow id="SequenceFlow_{_escape_xml_text(edge_data_id)}" '
                f'sourceRef="{_escape_xml_text(source_ref)}" targetRef="{_escape_xml_text(target_ref)}"/>'
            )

    parts.append('<sequenceFlow id="SequenceFlow_START_HIDDEN" sourceRef="START" targetRef="START_HIDDEN"/>')
    parts.append('</process>')
    parts.append('</definitions>')
    return "\n".join(parts)



def _auto_layout_if_degenerate(
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
) -> None:
    """节点坐标退化(缺省全挤在同一点/重叠)时按流程层级重排成 上→下 布局, 原地改 x/y。

    AI 生成流程常常不带坐标 → translator 默认把每个节点都放到同一点 → 平台正交连线
    交叉成一团(用户反馈"线画得好乱")。这里按最长路径分层(START 在上、END 在下,
    分支同层左右铺开)减少交叉。人工在 ProcessDesigner 摆好的(坐标各不相同)不动。
    """
    if len(nodes) < 2:
        return
    positions = [(n.get("x"), n.get("y")) for n in nodes]
    if len(set(positions)) == len(positions):
        return  # 坐标各不相同 → 视为人工布局, 尊重之

    from collections import deque

    ids = [str(n.get("id")) for n in nodes]
    id_set = set(ids)
    succ: dict[str, list[str]] = {i: [] for i in ids}
    indeg: dict[str, int] = {i: 0 for i in ids}
    for e in edges or []:
        src = str(e.get("source") or "")
        tgt = str(e.get("target") or "")
        if src in id_set and tgt in id_set and src != tgt:
            succ[src].append(tgt)
            indeg[tgt] += 1

    # 最长路径分层 (Kahn 拓扑 + 取 max 层)。
    layer: dict[str, int] = {i: 0 for i in ids}
    indeg_work = dict(indeg)
    queue = deque([i for i in ids if indeg_work[i] == 0])
    ordered: set[str] = set()
    while queue:
        cur = queue.popleft()
        ordered.add(cur)
        for nxt in succ[cur]:
            if layer[nxt] < layer[cur] + 1:
                layer[nxt] = layer[cur] + 1
            indeg_work[nxt] -= 1
            if indeg_work[nxt] == 0:
                queue.append(nxt)
    # 有环 → 没拓扑到的节点按顺序追加到末层之后, 至少不重叠。
    leftover = [i for i in ids if i not in ordered]
    if leftover:
        base = max(layer.values(), default=0) + 1
        for offset, nid in enumerate(leftover):
            layer[nid] = base + offset

    by_layer: dict[int, list[str]] = {}
    for nid in ids:
        by_layer.setdefault(layer[nid], []).append(nid)

    node_by_id = {str(n.get("id")): n for n in nodes}
    center_x, h_spacing, v_spacing, base_y = 400.0, 240.0, 140.0, 40.0
    for lyr in sorted(by_layer):
        members = by_layer[lyr]
        count = len(members)
        for idx, nid in enumerate(members):
            node = node_by_id.get(nid)
            if node is None:
                continue
            node["x"] = round(center_x + (idx - (count - 1) / 2.0) * h_spacing, 1)
            node["y"] = round(base_y + lyr * v_spacing, 1)


def _process_global_config() -> dict[str, Any]:
    return {
        "titleConfigList": [
            {"componentId": "submitter", "name": "发起人", "type": "COMPONENT"},
            {"value": "创建的", "type": "TEXT"},
            {"componentId": "formName", "name": "表单名称", "type": "COMPONENT"},
            {"value": "流程\n\n", "type": "TEXT"},
        ],
        "processDisplayFieldList": [],
    }


def translate_definition_to_apaas_schema(
    definition: dict[str, Any],
    apaas_app_id: str,
    menu_id: str,
    role_codes: Optional[dict[str, dict]] = None,
    *,
    form_id: str = "",
    process_name: str = "",
    process_code: str = "",
    form_components: Optional[list[dict[str, Any]]] = None,
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
    resolved_process_name = str(process_name or definition.get("process_name") or "审批流程")
    resolved_process_code = str(process_code or definition.get("process_code") or menu_id or "default")
    resolved_form_id = str(form_id or definition.get("form_id") or definition.get("formId") or "")

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
            "formId": resolved_form_id,
            "menuId": menu_id,
            "processName": resolved_process_name,
            "processCode": resolved_process_code,
            "bpmn": _MINIMAL_BPMN,
            "nodes": [],
            "edges": [],
            "status": "ENABLE",
            "engine": "VERSION_1.1",
        }
        if resolved_form_id:
            payload_empty["processDataSource"] = {
                "sourceType": "SOURCE_TYPE_BO",
                "objectId": f"boc_code_{resolved_form_id}",
            }
        return payload_empty, warnings

    raw_nodes, raw_edges = _flatten_condition_nodes(raw_nodes, raw_edges, warnings)

    # 第一遍扫: 收集已知节点 id + 类型 + 检查 has_start/has_end
    has_start = False
    has_end = False
    platform_nodes: list[dict[str, Any]] = []
    known_node_ids: set[str] = set()
    node_id_aliases: dict[str, str] = {}

    for raw_node in raw_nodes:
        if not isinstance(raw_node, dict):
            continue
        raw_node_type = str(raw_node.get("type") or "")
        node_type = normalize_process_node_type(raw_node_type)
        node_id = str(raw_node.get("id") or "") or uuid.uuid4().hex
        node_label = str(raw_node.get("label") or raw_node_type or node_type)
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
            node_id_aliases[node_id] = "START"
            platform_nodes.append(_make_apaas_node("START", node_label or "开始", "START", x, y))
            known_node_ids.add("START")
            continue
        if node_type == "end":
            has_end = True
            node_id_aliases[node_id] = "END"
            platform_nodes.append(_make_apaas_node("END", node_label or "结束", "END", x, y))
            known_node_ids.add("END")
            continue
        if node_type == "timer":
            platform_nodes.append(_make_apaas_node(
                node_id, node_label or "定时触发", "TIMER_START", x, y,
                extra_data=_build_entry_extra_data("timer", node_props, resolved_process_code),
            ))
            known_node_ids.add(node_id)
            continue
        if node_type == "webhook":
            platform_nodes.append(_make_apaas_node(
                node_id, node_label or "Webhook", "MESSAGE_START", x, y,
                extra_data=_build_entry_extra_data("webhook", node_props, resolved_process_code),
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
            if apaas_type == "CONDITION_EDGE":
                # 已在 _flatten_condition_nodes 阶段折叠成条件边。
                continue
            platform_nodes.append(_make_apaas_node(
                node_id, node_label, apaas_type, x, y,
                extra_data=_build_logic_extra_data(node_type, node_props),
            ))
            known_node_ids.add(node_id)
            continue

        # === 未知节点类型 → 收 warning 跳过 ===
        warnings.append({
            "id": node_id,
            "type": raw_node_type or node_type,
            "label": node_label,
            "reason": f"未知节点类型 {raw_node_type or node_type}",
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

    normalized_raw_edges: list[dict[str, Any]] = []
    for edge in raw_edges:
        if not isinstance(edge, dict):
            normalized_raw_edges.append(edge)
            continue
        normalized_edge = dict(edge)
        source = str(edge.get("source") or "").strip()
        target = str(edge.get("target") or "").strip()
        if source in node_id_aliases:
            normalized_edge["source"] = node_id_aliases[source]
        if target in node_id_aliases:
            normalized_edge["target"] = node_id_aliases[target]
        normalized_raw_edges.append(normalized_edge)

    # K2: 用 frontend definition.edges 真还原 apaas edges (替代固定串行链)
    platform_edges, process_rules = _build_apaas_edges(
        normalized_raw_edges,
        known_node_ids,
        warnings,
        menu_id=menu_id,
        form_components=form_components,
    )

    # 坐标退化(AI 没给位置 → 全挤一点)时按层级重排, 避免连线交叉成一团。
    _auto_layout_if_degenerate(platform_nodes, platform_edges)

    payload = {
        "appId": apaas_app_id,
        "formId": resolved_form_id,
        "menuId": menu_id,
        "tenantId": "",
        "processName": resolved_process_name,
        "processCode": resolved_process_code,
        "bpmn": build_apaas_bpmn_xml(platform_nodes, platform_edges, process_rules),
        "status": "ENABLE",
        "engine": "VERSION_1.1",
        "nodes": platform_nodes,
        "edges": platform_edges,
        "processRule": process_rules,
        "globalSettings": {},
        "processGlobalConfig": _process_global_config(),
        "openProcessVersion": False,
        "boExist": True,
        "boRemindExist": True,
        "predictionFlag": False,
    }
    if resolved_form_id:
        payload["processDataSource"] = {
            "sourceType": "SOURCE_TYPE_BO",
            "objectId": f"boc_code_{resolved_form_id}",
        }

    return payload, warnings
