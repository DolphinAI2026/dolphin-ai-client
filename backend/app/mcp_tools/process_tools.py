"""MCP tools for aPaaS process discovery, transition rules, and deployment."""
from __future__ import annotations

import copy
import logging
from typing import Any

logger = logging.getLogger(__name__)


class _StaticToolMarker:
    """No-op decorator used so static registry tests can see tool functions."""

    def tool(self):
        def _decorate(fn):
            return fn

        return _decorate


mcp = _StaticToolMarker()

_resolve_identity = None
_with_client = None

# ── 进程内短 TTL 缓存: list_processes 结果供 list/detail 两个工具共享 ──
# agent 常先 list 再逐个 detail, 复用 list 的响应避免重复全量 API 调用。
_process_list_cache: dict[str, tuple[float, list]] = {}   # key → (ts, raw_list)
_PROCESS_CACHE_TTL = 30  # 秒


async def _cached_list_processes(env_id: int, apaas_app_id: str) -> list:
    """带 30s TTL 的 list_processes 封装，同一 app 短期内不重复调 apaas。"""
    import time as _t
    from app.coding.apaas_tools import call_apaas_with_relogin
    from app.database import AsyncSessionLocal

    cache_key = f"{env_id}:{apaas_app_id.strip()}"
    cached = _process_list_cache.get(cache_key)
    if cached:
        ts, raw_list = cached
        if _t.time() - ts < _PROCESS_CACHE_TTL:
            return raw_list

    async with AsyncSessionLocal() as db:
        raw_list = await call_apaas_with_relogin(
            env_id, db, lambda client: client.list_processes(apaas_app_id.strip())
        )

    _process_list_cache[cache_key] = (_t.time(), raw_list or [])
    # 防止缓存无限增长：只保留最近 50 个 key
    if len(_process_list_cache) > 50:
        oldest = min(_process_list_cache, key=lambda k: _process_list_cache[k][0])
        _process_list_cache.pop(oldest, None)
    return raw_list or []


# 2026-05-27: 列应用全部流程 — apaas GET /xdap-app/process/query/processList?appId=
# 之前 section_content.py 调这个 tool 但 tool 不存在 → fallback 走 menus 过滤 PROCESS,
# 但 trial app 流程不是 PROCESS 类型菜单 → SPEC 章节"业务流程"始终空. 用户实测 4 个
# 流程一直在 apaas 里. 实测 endpoint 工作后补这个工具.
@mcp.tool()
async def list_apaas_app_processes(env_id: int, apaas_app_id: str) -> dict:
    """列 apaas 应用的全部流程 (含 form/menu 绑定 + nodes + edges 完整 schema).

    走 apaas GET /xdap-app/process/query/processList?appId={id} (2026-05-27 实证).
    返每条流程对象保留:
      id, processName, processCode, formId, menuId, nodes_count, edges_count.
    nodes/edges 完整 schema 留给 get_apaas_process_detail 再拉, 这里 list 只给摘要.
    """
    if not apaas_app_id.strip():
        return {"ok": False, "error_code": "INVALID_PARAMS", "message": "apaas_app_id 必填"}

    try:
        raw_list = await _cached_list_processes(env_id, apaas_app_id)
    except Exception as exc:
        return {
            "ok": False,
            "error_code": "APAAS_CLIENT_ERROR",
            "message": f"调 apaas list_processes 失败: {exc}",
        }

    processes = []
    for p in raw_list or []:
        if not isinstance(p, dict):
            continue
        nodes = p.get("nodes") or []
        edges = p.get("edges") or p.get("lineList") or p.get("sequenceFlows") or []
        processes.append({
            "id": str(p.get("id") or ""),
            "process_id": str(p.get("id") or ""),  # alias for downstream callers
            "name": str(p.get("processName") or p.get("name") or ""),
            "process_name": str(p.get("processName") or p.get("name") or ""),
            "code": str(p.get("processCode") or ""),
            "process_code": str(p.get("processCode") or ""),
            "form_id": str(p.get("formId") or ""),
            "menu_id": str(p.get("menuId") or ""),
            "node_count": len(nodes) if isinstance(nodes, list) else 0,
            "edge_count": len(edges) if isinstance(edges, list) else 0,
        })

    return {
        "ok": True,
        "apaas_app_id": apaas_app_id,
        "processes": processes,
        "total": len(processes),
    }


def _as_nonempty_str(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    return text


def _role_label_map(raw_roles: list | None) -> dict[str, str]:
    labels: dict[str, str] = {}
    for role in raw_roles or []:
        if not isinstance(role, dict):
            continue
        role_id = _as_nonempty_str(role.get("id") or role.get("roleId"))
        role_code = _as_nonempty_str(role.get("roleCode") or role.get("code"))
        role_name = _as_nonempty_str(role.get("roleName") or role.get("name") or role_code or role_id)
        if not role_name:
            continue
        for key in (role_id, role_code):
            if key:
                labels[key] = role_name
    return labels


async def _load_process_role_labels(env_id: int, apaas_app_id: str) -> dict[str, str]:
    try:
        from app.coding.apaas_tools import call_apaas_with_relogin
        from app.database import AsyncSessionLocal

        async with AsyncSessionLocal() as db:
            raw_roles = await call_apaas_with_relogin(
                env_id, db, lambda client: client.query_roles(apaas_app_id.strip())
            )
        return _role_label_map(raw_roles if isinstance(raw_roles, list) else [])
    except Exception as exc:
        logger.warning("load process role labels failed env=%s app=%s: %s", env_id, apaas_app_id, exc)
        return {}


def _append_unique_str(target: list[str], value: Any) -> None:
    text = _as_nonempty_str(value)
    if text and text not in target:
        target.append(text)


def _normalize_process_approver_labels(approvers: Any, role_labels: dict[str, str]) -> list[str]:
    labels: list[str] = []
    items = approvers if isinstance(approvers, list) else ([approvers] if approvers else [])
    for item in items:
        if isinstance(item, dict):
            approver_type = _as_nonempty_str(item.get("type") or item.get("approverType")).upper()
            raw_value = _as_nonempty_str(
                item.get("value")
                or item.get("roleId")
                or item.get("roleCode")
                or item.get("userId")
                or item.get("id")
            )
            explicit_label = (
                item.get("label")
                or item.get("name")
                or item.get("roleName")
                or item.get("userName")
                or item.get("displayName")
                or item.get("subjectName")
            )
            if approver_type == "SUBMITTER":
                _append_unique_str(labels, explicit_label or "申请人")
                continue
            mapped = role_labels.get(raw_value) if raw_value else ""
            _append_unique_str(labels, explicit_label or mapped)
        else:
            raw_value = _as_nonempty_str(item)
            _append_unique_str(labels, role_labels.get(raw_value) or raw_value)
    return labels


def _resolve_process_binding_from_raw(raw_list: list | None, process_ref: str) -> dict[str, str]:
    ref = str(process_ref or "").strip()
    for p in raw_list or []:
        if not isinstance(p, dict):
            continue
        process_id = _as_nonempty_str(p.get("id"))
        menu_id = _as_nonempty_str(p.get("menuId"))
        form_id = _as_nonempty_str(p.get("formId"))
        process_code = _as_nonempty_str(p.get("processCode"))
        if ref and ref not in (process_id, menu_id, process_code):
            continue
        return {
            "process_id": process_id or ref,
            "menu_id": menu_id or ref,
            "form_id": form_id,
            "process_name": _as_nonempty_str(p.get("processName") or p.get("name")),
            "process_code": process_code or ref,
        }
    return {
        "process_id": ref,
        "menu_id": ref,
        "form_id": "",
        "process_name": "",
        "process_code": ref,
    }


def _normalize_apaas_process_edge(edge: dict[str, Any]) -> dict[str, Any]:
    data = edge.get("data") if isinstance(edge.get("data"), dict) else {}
    label = (
        edge.get("name")
        or edge.get("label")
        or edge.get("lineName")
        or data.get("title")
        or ""
    )
    label_text = str(label or "").strip()
    if label_text and all(ch == "\\" for ch in label_text):
        label_text = ""
    condition = (
        edge.get("conditionExpression")
        or edge.get("condition")
        or data.get("conditionExpression")
        or data.get("condition")
        or ""
    )
    return {
        "id": str(edge.get("id") or edge.get("flowId") or edge.get("lineId") or ""),
        "source": str(
            edge.get("sourceRef")
            or edge.get("from")
            or edge.get("source")
            or edge.get("sourceNodeKey")
            or edge.get("sourceNodeId")
            or ""
        ),
        "target": str(
            edge.get("targetRef")
            or edge.get("to")
            or edge.get("target")
            or edge.get("targetNodeKey")
            or edge.get("targetNodeId")
            or ""
        ),
        "label": label_text,
        "condition": str(condition or "") or None,
    }


def _apaas_node_title(node: dict[str, Any]) -> str:
    data = node.get("data") if isinstance(node.get("data"), dict) else {}
    return _as_nonempty_str(
        data.get("title")
        or node.get("nodeName")
        or node.get("name")
        or node.get("label")
    )


def _apaas_edge_data_id(edge: dict[str, Any]) -> str:
    data = edge.get("data") if isinstance(edge.get("data"), dict) else {}
    return _as_nonempty_str(
        data.get("id")
        or edge.get("dataId")
        or edge.get("flowRefUUID")
        or edge.get("lineId")
        or edge.get("id")
    )


def _apaas_edge_title(edge: dict[str, Any]) -> str:
    data = edge.get("data") if isinstance(edge.get("data"), dict) else {}
    title = _as_nonempty_str(
        edge.get("lineName")
        or edge.get("name")
        or edge.get("label")
        or data.get("title")
    )
    return "" if title and all(ch == "\\" for ch in title) else title


def _apaas_edge_endpoint(edge: dict[str, Any], key: str) -> str:
    if key == "source":
        candidates = ("source", "sourceNodeKey", "sourceNodeId", "sourceRef", "from")
    else:
        candidates = ("target", "targetNodeKey", "targetNodeId", "targetRef", "to")
    for candidate in candidates:
        text = _as_nonempty_str(edge.get(candidate))
        if text:
            return text
    return ""


def _find_process_transition_edge(
    edges: list[dict[str, Any]],
    rule_spec: dict[str, Any],
    nodes: list[dict[str, Any]],
) -> dict[str, Any] | None:
    """Find an aPaaS process edge by stable ids, endpoint ids/titles, or line name."""
    edge_id = _as_nonempty_str(
        rule_spec.get("edge_id")
        or rule_spec.get("edgeId")
        or rule_spec.get("line_id")
        or rule_spec.get("lineId")
    )
    line_name = _as_nonempty_str(
        rule_spec.get("line_name")
        or rule_spec.get("lineName")
        or rule_spec.get("transition_name")
        or rule_spec.get("transitionName")
    )
    source_ref = _as_nonempty_str(
        rule_spec.get("source")
        or rule_spec.get("source_node_id")
        or rule_spec.get("sourceNodeId")
    )
    target_ref = _as_nonempty_str(
        rule_spec.get("target")
        or rule_spec.get("target_node_id")
        or rule_spec.get("targetNodeId")
    )
    source_title = _as_nonempty_str(
        rule_spec.get("source_node_title")
        or rule_spec.get("sourceNodeTitle")
    )
    target_title = _as_nonempty_str(
        rule_spec.get("target_node_title")
        or rule_spec.get("targetNodeTitle")
    )

    node_titles = {
        _as_nonempty_str(node.get("id") or node.get("nodeId") or node.get("nodeKey")): _apaas_node_title(node)
        for node in nodes or []
        if isinstance(node, dict)
    }

    for edge in edges or []:
        if not isinstance(edge, dict):
            continue
        candidates = {
            _as_nonempty_str(edge.get("id")),
            _as_nonempty_str(edge.get("lineId")),
            _apaas_edge_data_id(edge),
        }
        if edge_id and edge_id in candidates:
            return edge

    for edge in edges or []:
        if not isinstance(edge, dict):
            continue
        source_id = _apaas_edge_endpoint(edge, "source")
        target_id = _apaas_edge_endpoint(edge, "target")
        if source_ref and source_ref != source_id:
            continue
        if target_ref and target_ref != target_id:
            continue
        if source_title and source_title != node_titles.get(source_id, ""):
            continue
        if target_title and target_title != node_titles.get(target_id, ""):
            continue
        if line_name and line_name != _apaas_edge_title(edge):
            continue
        if any([source_ref, target_ref, source_title, target_title, line_name]):
            return edge
    return None


def _process_transition_edge_summary(edge: dict[str, Any], nodes: list[dict[str, Any]]) -> dict[str, str]:
    node_titles = {
        _as_nonempty_str(node.get("id") or node.get("nodeId") or node.get("nodeKey")): _apaas_node_title(node)
        for node in nodes or []
        if isinstance(node, dict)
    }
    source = _apaas_edge_endpoint(edge, "source")
    target = _apaas_edge_endpoint(edge, "target")
    return {
        "edge_id": _as_nonempty_str(edge.get("id")),
        "edge_data_id": _apaas_edge_data_id(edge),
        "line_name": _apaas_edge_title(edge),
        "source": source,
        "source_title": node_titles.get(source, ""),
        "target": target,
        "target_title": node_titles.get(target, ""),
    }


# design-v4 J1: 拉 apaas 平台已有流程详情 (反向, 给 ProcessDesigner 渲染 canvas)
@mcp.tool()
async def get_apaas_process_detail(env_id: int, apaas_app_id: str, process_id: str) -> dict:
    """拉 apaas 平台某流程的详情 (nodes + edges + bpmn).

    先用 processList 定位流程绑定, 再走 apaas_client.query_process_config 拉完整
    processConfigDetail。详情接口失败时回退到 processList 里的节点/边数据。

    成功时翻译 apaas raw → ProcessDefinition shape:
      {nodes: [{id, type, label, position, props}], edges: [{id, source, target, label, condition}]}

    apaas → frontend type 反向映射 (跟 process_translator.py 正向对应):
      START → start, END → end, APPROVE → assignee_approval (默认), 其他 → action 兜底.
    """
    if not (apaas_app_id.strip() and process_id.strip()):
        return {"ok": False, "error_code": "INVALID_PARAMS", "message": "apaas_app_id+process_id 都必填"}

    try:
        # 复用 _cached_list_processes: agent 同一轮 list→detail 不重复调 apaas 列表。
        raw_list = await _cached_list_processes(env_id, apaas_app_id)
    except Exception as exc:
        return {"ok": False, "error_code": "APAAS_CLIENT_ERROR", "message": f"调 apaas list_processes 失败: {exc}"}

    pid = process_id.strip()
    raw = None
    for p in raw_list or []:
        if not isinstance(p, dict):
            continue
        if pid in (str(p.get("id") or ""), str(p.get("processCode") or ""), str(p.get("menuId") or "")):
            raw = p
            break
    if raw is None:
        return {
            "ok": False,
            "error_code": "PROCESS_NOT_FOUND",
            "message": f"apaas 应用 {apaas_app_id} 下找不到流程 {pid} (该应用共 {len(raw_list or [])} 个流程)",
        }
    detail_process_id = _as_nonempty_str(raw.get("id")) or pid
    ok_detail, detail_result = await _with_client(
        env_id,
        "查流程详情",
        lambda c: c.query_process_config(apaas_app_id.strip(), detail_process_id),
    )
    if ok_detail and isinstance(detail_result, dict):
        detail_raw = detail_result.get("data") if detail_result.get("ok") else detail_result
        if isinstance(detail_raw, dict) and (detail_raw.get("nodes") or detail_raw.get("edges")):
            raw = detail_raw
    elif not ok_detail:
        logger.warning(
            "get_apaas_process_detail: query_process_config failed env=%s app=%s process=%s: %s",
            env_id,
            apaas_app_id,
            detail_process_id,
            detail_result,
        )

    # apaas raw 结构推测: { nodes: [{nodeKey, nodeType, nodeName, x, y, approverType, ...}], edges: [...] }
    nodes_out = []
    edges_out = []
    apaas_nodes = raw.get("nodes") or raw.get("nodeList") or []
    apaas_edges = raw.get("edges") or raw.get("lineList") or raw.get("sequenceFlows") or []
    role_labels = await _load_process_role_labels(env_id, apaas_app_id)

    APAAS_TO_FRONTEND = {
        "START": "start",
        "END": "end",
        "APPROVE": "assignee_approval",
        "USERTASK": "assignee_approval",
        "GATEWAY": "condition",
        "EXCLUSIVE_GATEWAY": "condition",
        "PARALLEL_GATEWAY": "parallel_gateway",
        "TIMER": "timer",
        "WEBHOOK": "webhook",
        "FORM": "fill_form",
    }
    for n in apaas_nodes:
        if not isinstance(n, dict):
            continue
        # 2026-05-28 实测 apaas list_processes 节点真实结构: type/title 嵌在 data 里,
        # 不是顶层 nodeType/nodeName (旧代码读顶层 → 全落 fill_form 兜底 + label 空).
        d = n.get("data") if isinstance(n.get("data"), dict) else {}
        apaas_type = str(d.get("type") or n.get("nodeType") or n.get("type") or "").upper()
        ft = APAAS_TO_FRONTEND.get(apaas_type, "fill_form")
        approvers = d.get("approvers") or n.get("approvers") or []
        nodes_out.append({
            "id": str(n.get("id") or n.get("nodeId") or n.get("nodeKey") or n.get("key") or ""),
            "type": ft,
            "label": str(d.get("title") or n.get("nodeName") or n.get("name") or n.get("label") or ""),
            "position": {"x": float(n.get("x") or 0), "y": float(n.get("y") or 0)},
            "props": {
                "approverType": str(d.get("approverType") or n.get("approverType") or ""),
                "approveType": str(d.get("approveType") or n.get("approveType") or ""),
                "approvers": approvers,
                "approverLabels": _normalize_process_approver_labels(approvers, role_labels),
                "_apaas_raw_type": apaas_type,
            },
        })
    for e in apaas_edges:
        if not isinstance(e, dict):
            continue
        normalized_edge = _normalize_apaas_process_edge(e)
        if normalized_edge["source"] and normalized_edge["target"]:
            edges_out.append(normalized_edge)

    # 2026-05-28: apaas list_processes 不返显式连线 (edges 字段缺失). 对线性审批流,
    # 按 y 坐标 (再 x) 排序推断顺序连线 START→审批→…→END, 让业务视角画布能连起来.
    # (有显式 edges 时上面已建, 不覆盖; 仅在缺连线且 ≥2 节点时补.)
    if not edges_out and len(nodes_out) >= 2:
        ordered = sorted(nodes_out, key=lambda x: (x["position"]["y"], x["position"]["x"]))
        for a, b in zip(ordered, ordered[1:]):
            edges_out.append({
                "id": f"{a['id']}->{b['id']}",
                "source": a["id"],
                "target": b["id"],
                "label": "",
                "condition": None,
                "_inferred": True,
            })

    return {
        "ok": True,
        "process_id": process_id,
        "process_name": str(raw.get("processName") or raw.get("name") or ""),
        "nodes": nodes_out,
        "edges": edges_out,
        "node_count": len(nodes_out),
        "edge_count": len(edges_out),
        "_apaas_raw_keys": list(raw.keys())[:20],
    }


@mcp.tool()
async def set_apaas_process_transition_rules(
    env_id: int,
    apaas_app_id: str,
    process_id: str,
    rules: list,
) -> dict:
    """给已有 aPaaS 流程连线设置流转规则，不重建整条流程。

    使用场景：用户说“规则判断没设置 / 给某条流转设置条件 / 项目类型=客户交付走交付负责人”。
    流程：
      1. 先用 list_apaas_app_processes / get_apaas_process_detail 找到 process_id 和连线；
      2. rules 每项用 edge_id（优先）或 line_name + target_node_title 定位一条现有连线；
      3. condition 可传自然语言/表达式，也可传结构化字段：
         {"fieldCode":"project_type", "operator":"eq", "value":"custom_delivery"}；
      4. 工具会先保存 simpleRule，再把 simpleRuleId 挂回 processRule[edge.data.id]，最后保存流程配置。

    rules 示例：
      [
        {
          "line_name": "客户交付",
          "target_node_title": "交付负责人审批",
          "condition": {"fieldCode": "project_type", "operator": "eq", "value": "custom_delivery"}
        }
      ]
    """
    if not (apaas_app_id.strip() and process_id.strip()):
        return {"ok": False, "error_code": "INVALID_PARAMS", "message": "apaas_app_id + process_id 必填"}
    if not isinstance(rules, list) or not rules:
        return {"ok": False, "error_code": "INVALID_RULES", "message": "rules 必须是非空数组"}

    try:
        raw_list = await _cached_list_processes(env_id, apaas_app_id)
    except Exception as exc:
        return {"ok": False, "error_code": "APAAS_CLIENT_ERROR", "message": f"调 apaas list_processes 失败: {exc}"}

    binding = _resolve_process_binding_from_raw(raw_list, process_id.strip())
    detail_process_id = binding.get("process_id") or process_id.strip()
    ok_detail, detail_result = await _with_client(
        env_id,
        "查流程详情",
        lambda c: c.query_process_config(apaas_app_id.strip(), detail_process_id),
    )
    if not ok_detail:
        return detail_result

    raw = detail_result.get("data") if isinstance(detail_result, dict) and detail_result.get("ok") else detail_result
    if not isinstance(raw, dict):
        return {"ok": False, "error_code": "PROCESS_DETAIL_INVALID", "message": "流程详情返回不是对象"}

    nodes = raw.get("nodes") or raw.get("nodeList") or []
    edges = raw.get("edges") or raw.get("lineList") or raw.get("sequenceFlows") or []
    if not isinstance(nodes, list):
        nodes = []
    if not isinstance(edges, list) or not edges:
        return {
            "ok": False,
            "error_code": "PROCESS_EDGES_EMPTY",
            "message": "流程详情中没有可设置规则的连线",
            "process_id": detail_process_id,
        }

    menu_id = _as_nonempty_str(raw.get("menuId") or binding.get("menu_id"))
    form_id = _as_nonempty_str(raw.get("formId") or binding.get("form_id"))
    if not menu_id or not form_id:
        return {
            "ok": False,
            "error_code": "PROCESS_BINDING_MISSING",
            "message": "流程详情缺少 menuId/formId，无法保存流转规则",
            "process_id": detail_process_id,
        }

    ok_components, components_raw = await _with_client(
        env_id,
        "查表单组件",
        lambda c: c.query_form_components(apaas_app_id.strip(), form_id),
    )
    form_components = components_raw if ok_components and isinstance(components_raw, list) else []

    from app.process_translator import _build_simple_process_rule, _component_lookup, build_apaas_bpmn_xml

    lookup = _component_lookup(form_components)
    process_rule = copy.deepcopy(raw.get("processRule") if isinstance(raw.get("processRule"), dict) else {})
    updated: list[dict[str, str]] = []

    for idx, spec in enumerate(rules, start=1):
        if not isinstance(spec, dict):
            return {"ok": False, "error_code": "INVALID_RULE_ITEM", "message": f"rules[{idx}] 必须是对象"}
        edge = _find_process_transition_edge(edges, spec, nodes)
        if edge is None:
            return {
                "ok": False,
                "error_code": "EDGE_NOT_FOUND",
                "message": f"未找到 rules[{idx}] 指定的流程连线；请用 available_edges 里的 edge_data_id 或 line_name+target_title 重试",
                "rule": spec,
                "available_edges": [_process_transition_edge_summary(e, nodes) for e in edges if isinstance(e, dict)],
            }

        data = edge.setdefault("data", {})
        if not isinstance(data, dict):
            data = {}
            edge["data"] = data
        edge_rule_key = _apaas_edge_data_id(edge)
        if not edge_rule_key:
            edge_rule_key = _as_nonempty_str(edge.get("id") or edge.get("lineId"))
            if edge_rule_key:
                data["id"] = edge_rule_key
        if not edge_rule_key:
            return {
                "ok": False,
                "error_code": "EDGE_RULE_KEY_MISSING",
                "message": f"rules[{idx}] 匹配到的连线缺少 edge.data.id，无法挂 processRule",
                "edge": _process_transition_edge_summary(edge, nodes),
            }

        line_name = _as_nonempty_str(
            spec.get("line_name")
            or spec.get("lineName")
            or spec.get("transition_name")
            or spec.get("transitionName")
            or _apaas_edge_title(edge)
        )
        if line_name:
            edge["lineName"] = line_name
            edge["label"] = line_name
            data["title"] = line_name

        is_default = bool(spec.get("default_flow") or spec.get("defaultFlow"))
        if is_default:
            data["defaultFlow"] = True
            data["conditionExpression"] = ""
            edge["conditionExpression"] = ""
            process_rule.pop(edge_rule_key, None)
            updated.append({**_process_transition_edge_summary(edge, nodes), "rule_type": "default"})
            continue

        condition = spec.get("condition")
        if condition is None:
            condition = {
                "boCode": spec.get("bo_code") or spec.get("boCode"),
                "fieldCode": spec.get("field_code") or spec.get("fieldCode"),
                "field": spec.get("field"),
                "operator": spec.get("operator") or spec.get("op") or "eq",
                "value": spec.get("value"),
                "valueLabel": spec.get("value_label") or spec.get("valueLabel"),
            }
        rule = _build_simple_process_rule(condition, menu_id, lookup)
        if not rule:
            return {
                "ok": False,
                "error_code": "RULE_TRANSLATE_FAILED",
                "message": f"rules[{idx}] 的条件无法转换成平台 simpleRule；请确认字段 code/label 与表单组件一致",
                "rule": spec,
                "available_components": [
                    {
                        "uuid": _as_nonempty_str(c.get("uuid") or c.get("id")),
                        "label": _as_nonempty_str(c.get("label") or c.get("name")),
                        "bo_code": _as_nonempty_str(c.get("boCode") or c.get("bo_code") or c.get("modelField")),
                        "field_code": _as_nonempty_str(c.get("fieldCode") or c.get("code")),
                    }
                    for c in form_components
                    if isinstance(c, dict)
                ],
            }

        simple_rule_config = rule.get("simpleRuleConfig")
        ok_rule, saved_rule = await _with_client(
            env_id,
            "存流程条件规则",
            lambda c, cfg=simple_rule_config: c.save_simple_rule(
                apaas_app_id.strip(),
                menu_id,
                cfg,
            ),
        )
        if not ok_rule:
            return saved_rule
        if not isinstance(saved_rule, dict) or not _as_nonempty_str(saved_rule.get("id")):
            return {
                "ok": False,
                "error_code": "PROCESS_RULE_SAVE_FAILED",
                "message": f"rules[{idx}] 条件规则保存后未返回 id",
                "platform_response": saved_rule,
            }

        rule["simpleRuleId"] = _as_nonempty_str(saved_rule.get("id"))
        rule["simpleRuleConfig"] = saved_rule
        process_rule[edge_rule_key] = rule
        data["defaultFlow"] = False
        data["conditionExpression"] = condition
        edge["conditionExpression"] = condition
        updated.append({
            **_process_transition_edge_summary(edge, nodes),
            "rule_type": "simple",
            "simple_rule_id": rule["simpleRuleId"],
        })

    payload = copy.deepcopy(raw)
    payload["appId"] = _as_nonempty_str(payload.get("appId") or apaas_app_id)
    payload["formId"] = form_id
    payload["menuId"] = menu_id
    payload["nodes"] = nodes
    payload["edges"] = edges
    payload["processRule"] = process_rule
    payload["bpmn"] = build_apaas_bpmn_xml(nodes, edges, process_rule)
    payload.setdefault("status", raw.get("status") or "ENABLE")
    payload.setdefault("engine", raw.get("engine") or "VERSION_1.1")
    payload.setdefault("globalSettings", raw.get("globalSettings") or {})
    payload.setdefault("processGlobalConfig", raw.get("processGlobalConfig") or {})
    payload.setdefault("openProcessVersion", raw.get("openProcessVersion", False))
    payload.setdefault("boExist", raw.get("boExist", True))
    payload.setdefault("boRemindExist", raw.get("boRemindExist", True))
    payload.setdefault("predictionFlag", raw.get("predictionFlag", False))
    payload.setdefault(
        "processDataSource",
        raw.get("processDataSource") or {"sourceType": "SOURCE_TYPE_BO", "objectId": f"boc_code_{form_id}"},
    )

    ok_save, save_result = await _with_client(
        env_id,
        "存流程流转规则",
        lambda c: c.save_process_config(apaas_app_id.strip(), payload),
    )
    if not ok_save:
        return save_result

    _process_list_cache.pop(f"{env_id}:{apaas_app_id.strip()}", None)
    return {
        "ok": True,
        "apaas_app_id": apaas_app_id,
        "process_id": detail_process_id,
        "menu_id": menu_id,
        "form_id": form_id,
        "updated_rules": updated,
        "updated_count": len(updated),
        "process_rule_count": len(process_rule),
        "platform_response": save_result if isinstance(save_result, dict) else {"raw": save_result},
        "message": f"已为流程 {detail_process_id} 更新 {len(updated)} 条流转规则（仅保存流程配置，发布应用需另行执行）",
    }


# design-v4 I4: ProcessDefinition 真同步到 apaas 平台 (basic 翻译, P6 完整)
@mcp.tool()
async def deploy_process_to_apaas(
    app_id: int,
    process_id: str,
    tenant_id: int = 0,
    user_id: int = 0,
) -> dict:
    """把 backend `process_definitions` 表里的本地 definition 真同步到 apaas 平台.

    流程:
      1) 加载 ai-builder Application 拿 platform_env_id + apaas_app_id
      2) 从 `process_definitions` 读 (application_id, process_id) 行
      3) 从 aPaaS processList 把 process_id 解析成 menuId/formId
      4) 调 process_translator.translate_definition_to_apaas_schema 翻译 24→17 节点
      5) 调 apaas_client.save_process_config(apaas_app_id, payload) 真存平台
      6) 成功 → 更新 process_definitions.last_deployed_version + last_deployed_at

    入参:
      - app_id: ai-builder 应用 ID (Application.id, 不是 apaas_app_id)
      - process_id: 流程 ID (来自前端 process list; 工具会反查对应 menuId/formId)

    返回:
      - {ok, deployed_version, apaas_app_id, menu_id, unsupported_nodes, message}
      - unsupported_nodes: 未知节点 / 孤儿边 / 自动补 start/end 等 warning
    """
    from app.database import AsyncSessionLocal
    from app.models.process_definition import ProcessDefinition
    from app.models import Application
    from app.coding.apaas_tools import _get_apaas_client
    from app.process_translator import build_apaas_bpmn_xml, translate_definition_to_apaas_schema
    from sqlalchemy import select
    from datetime import datetime as _dt
    import json as _json

    tid, uid = _resolve_identity(tenant_id, user_id)
    if not app_id or app_id <= 0:
        return {"ok": False, "error_code": "INVALID_APP_ID", "message": "app_id 必填"}
    if not process_id or not process_id.strip():
        return {"ok": False, "error_code": "INVALID_PROCESS_ID", "message": "process_id 必填"}
    process_id = process_id.strip()

    async with AsyncSessionLocal() as db:
        # 1) 加载 Application
        r = await db.execute(select(Application).where(Application.id == app_id, Application.tenant_id == tid))
        app = r.scalar_one_or_none()
        if not app:
            return {"ok": False, "error_code": "APP_NOT_FOUND", "message": f"应用 {app_id} 不存在或无权访问"}
        if not app.platform_env_id:
            return {
                "ok": False, "error_code": "APP_NOT_DEPLOYED",
                "message": "应用未绑定平台环境 — 先 deploy_application 把应用部署到 apaas",
            }
        if not app.apaas_app_id:
            return {
                "ok": False, "error_code": "APP_NOT_DEPLOYED",
                "message": "应用 apaas_app_id 为空 — 先 deploy_application 把应用真部署到 apaas 平台",
            }

        # 2) 读本地 ProcessDefinition
        def_q = await db.execute(
            select(ProcessDefinition).where(
                ProcessDefinition.application_id == app_id,
                ProcessDefinition.process_id == process_id,
            )
        )
        row = def_q.scalar_one_or_none()
        if not row:
            return {
                "ok": False, "error_code": "PROCESS_DEFINITION_NOT_FOUND",
                "message": f"流程 {process_id} 在本地无 definition — 先在前端保存 (H2 onSave) 再部署",
            }
        try:
            definition = _json.loads(row.definition_json or "{}")
        except (ValueError, TypeError) as exc:
            return {
                "ok": False, "error_code": "INVALID_DEFINITION_JSON",
                "message": f"definition_json 解析失败: {exc}",
            }

        try:
            raw_processes = await _cached_list_processes(app.platform_env_id, str(app.apaas_app_id))
        except Exception:
            raw_processes = []
        binding = _resolve_process_binding_from_raw(raw_processes, process_id)
        menu_id = binding["menu_id"]
        form_id = binding["form_id"]
        process_name = row.process_name or definition.get("process_name") or binding["process_name"] or "审批流程"
        process_code = definition.get("process_code") or binding["process_code"] or process_id

        from app.coding.apaas_tools import call_apaas_with_relogin

        role_codes: dict[str, dict] = {}
        try:
            roles = await call_apaas_with_relogin(
                app.platform_env_id, db,
                lambda client: client.query_roles(str(app.apaas_app_id)),
            )
            for role in roles or []:
                if not isinstance(role, dict):
                    continue
                code = str(role.get("roleCode") or "").strip()
                rid = str(role.get("id") or role.get("roleId") or "").strip()
                if code:
                    role_codes[code] = role
                if rid:
                    role_codes[rid] = role
        except Exception as exc:
            logger.warning("deploy_process_to_apaas: query roles failed app_id=%s: %s", app_id, exc)

        form_components: list[dict[str, Any]] = []
        if form_id:
            try:
                components_raw = await call_apaas_with_relogin(
                    app.platform_env_id, db,
                    lambda client: client.query_form_components(str(app.apaas_app_id), form_id),
                )
                if isinstance(components_raw, list):
                    form_components = components_raw
            except Exception as exc:
                logger.warning("deploy_process_to_apaas: query form components failed app_id=%s form_id=%s: %s", app_id, form_id, exc)

        # 3) 翻译 — 24 → apaas schema; edges 按本地 definition 保真, 支持条件/并行分支。
        try:
            payload, unsupported = translate_definition_to_apaas_schema(
                definition,
                apaas_app_id=str(app.apaas_app_id),
                menu_id=menu_id,
                role_codes=role_codes,
                form_id=form_id,
                process_name=str(process_name),
                process_code=str(process_code),
                form_components=form_components,
            )
        except Exception as exc:
            logger.exception("translate_definition_to_apaas_schema failed app_id=%s process_id=%s", app_id, process_id)
            return {
                "ok": False, "error_code": "TRANSLATE_FAILED",
                "message": f"翻译 ProcessDefinition 失败: {exc}",
            }

        process_rule = payload.get("processRule") if isinstance(payload.get("processRule"), dict) else {}
        for edge_rule_key, rule in list(process_rule.items()):
            if not isinstance(rule, dict) or rule.get("ruleType") != "simple":
                continue
            if rule.get("simpleRuleId"):
                continue
            simple_rule_config = rule.get("simpleRuleConfig")
            if not isinstance(simple_rule_config, dict):
                continue
            try:
                saved_rule = await call_apaas_with_relogin(
                    app.platform_env_id, db,
                    lambda client, cfg=simple_rule_config: client.save_simple_rule(str(app.apaas_app_id), menu_id, cfg),
                )
            except Exception as exc:
                logger.exception("save_simple_rule failed app_id=%s process_id=%s edge_rule_key=%s", app_id, process_id, edge_rule_key)
                return {
                    "ok": False,
                    "error_code": "PROCESS_RULE_SAVE_FAILED",
                    "message": f"apaas 平台保存流程条件规则失败: {exc}",
                    "unsupported_nodes": unsupported,
                }
            if not isinstance(saved_rule, dict) or not str(saved_rule.get("id") or "").strip():
                return {
                    "ok": False,
                    "error_code": "PROCESS_RULE_SAVE_FAILED",
                    "message": f"条件规则保存后未返回 id，edge_rule_key={edge_rule_key}",
                    "platform_response": saved_rule,
                    "unsupported_nodes": unsupported,
                }
            rule["simpleRuleId"] = str(saved_rule.get("id"))
            rule["simpleRuleConfig"] = saved_rule
        if process_rule:
            payload["bpmn"] = build_apaas_bpmn_xml(
                payload.get("nodes") or [],
                payload.get("edges") or [],
                process_rule,
            )

        # 4) 调 apaas_client 真同步
        # 2026-05-29: 套 call_apaas_with_relogin — token 过期(401)自动重登重试。
        # save_process_config 是写接口, 但 401 发生在认证层(请求没到业务), 重试无重复副作用, 安全。
        try:
            apaas_resp = await call_apaas_with_relogin(
                app.platform_env_id, db,
                lambda client: client.save_process_config(str(app.apaas_app_id), payload),
            )
        except Exception as exc:
            logger.exception("save_process_config failed app_id=%s process_id=%s", app_id, process_id)
            return {
                "ok": False, "error_code": "APAAS_SAVE_FAILED",
                "message": f"apaas 平台保存流程失败: {exc}",
                "unsupported_nodes": unsupported,
            }

        # 5) 更新 last_deployed_*
        now = _dt.utcnow()
        deployed_version = row.version or 1
        row.last_deployed_version = deployed_version
        row.last_deployed_at = now
        await db.flush()
        await db.commit()

        return {
            "ok": True,
            "app_id": app_id,
            "process_id": process_id,
            "deployed_version": deployed_version,
            "deployed_at": now.isoformat(),
            "apaas_app_id": str(app.apaas_app_id),
            "menu_id": menu_id,
            "form_id": form_id,
            "node_count": len(payload.get("nodes") or []),
            "edge_count": len(payload.get("edges") or []),
            "unsupported_nodes": unsupported,
            "apaas_response_code": (apaas_resp or {}).get("code"),
            "message": (
                f"已同步到 apaas 平台 (v{deployed_version}, {len(payload.get('nodes') or [])} 节点)"
                + (f", {len(unsupported)} 类节点 P6 待支持" if unsupported else "")
            ),
        }



def register(
    mcp,
    resolve_identity,
    with_client,
    cached_list_processes,
    load_process_role_labels,
):
    global _resolve_identity, _with_client, _cached_list_processes, _load_process_role_labels
    _resolve_identity = resolve_identity
    _with_client = with_client
    _cached_list_processes = cached_list_processes
    _load_process_role_labels = load_process_role_labels
    tools = [
        list_apaas_app_processes,
        get_apaas_process_detail,
        set_apaas_process_transition_rules,
        deploy_process_to_apaas,
    ]
    for tool in tools:
        mcp.tool()(tool)
    return {tool.__name__: tool for tool in tools}
