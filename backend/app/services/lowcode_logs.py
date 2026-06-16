from __future__ import annotations

import hashlib
import json
from collections import Counter
from typing import Any


_DELETE_ACTIONS = ("删除", "下线", "禁用", "关闭", "DELETE", "DISABLE", "CLOSE", "OFFLINE", "REMOVE")
_WATCH_ACTIONS = ("发布", "启用", "导入", "导出", "下载", "PUBLISH", "ENABLE", "IMPORT", "EXPORT", "DOWNLOAD")
_WATCH_MENUS = (
    "权限",
    "角色",
    "高级设置",
    "自开发",
    "数据源",
    "服务集成",
    "应用发布",
    "ROLE",
    "ACCESS",
    "PERMISSION",
    "SELF_DEVELOPMENT",
    "DATA_SOURCE",
    "INTEGRATION",
    "APPLICATION_MANAGEMENT",
)
_RESOURCE_LABELS = {
    "permission": "权限与角色",
    "self_development": "自开发资产",
    "menu": "菜单页面",
    "application": "应用发布",
    "datasource": "数据源",
    "integration": "接口集成",
    "tenant": "租户配置",
}


def _first_non_empty(raw: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = raw.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""


def _stable_log_id(raw: dict[str, Any]) -> str:
    raw_id = _first_non_empty(raw, "id", "logId", "operateLogId", "operationLogId")
    if raw_id:
        return f"lowcode-{raw_id}"
    digest = hashlib.sha1(
        json.dumps(raw, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()[:16]
    return f"lowcode-{digest}"


def _classify_risk(operation_type: str, function_menu: str, operation_object: str, description: str) -> tuple[str, str]:
    text = f"{operation_type} {function_menu} {operation_object} {description}"
    if any(token in text for token in _DELETE_ACTIONS):
        return "high", "删除/下线/禁用类操作"
    if any(token in text for token in _WATCH_ACTIONS) or any(token in text for token in _WATCH_MENUS):
        if any(token in text for token in _WATCH_MENUS):
            return "medium", "关键配置或权限相关变更"
        return "medium", "发布/启用/导入导出类操作"
    return "low", "常规操作"


def _resource_type(function_menu: str, operation_object: str) -> str:
    text = f"{function_menu} {operation_object}"
    if any(token in text for token in ("权限", "角色", "ROLE", "ACCESS", "PERMISSION")):
        return "permission"
    if "自开发" in text or "SELF_DEVELOPMENT" in text:
        return "self_development"
    if "菜单" in text or "APP_MENU" in text:
        return "menu"
    if "应用" in text or "APPLICATION" in text or "PUBLISH" in text:
        return "application"
    if "数据源" in text or "DATA_SOURCE" in text:
        return "datasource"
    if "服务" in text or "接口" in text or "INTEGRATION" in text or "API" in text:
        return "integration"
    return "tenant"


def _resource_label(resource_type: str) -> str:
    return _RESOURCE_LABELS.get(resource_type, "租户配置")


def _item_target(item: dict[str, Any]) -> str:
    return str(item.get("details", {}).get("operation_object") or item.get("summary") or "低代码操作")


def _build_recommendations(
    *,
    items: list[dict[str, Any]],
    risks: list[dict[str, Any]],
    high_risks: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    recommendations: list[dict[str, Any]] = []

    if high_risks:
        item = high_risks[0]
        recommendations.append(
            {
                "key": "review_high_risk",
                "title": "先复核高风险操作",
                "target": _item_target(item),
                "description": str(item.get("details", {}).get("risk_reason") or "高风险变更"),
                "action": "确认是否为预期操作，必要时回滚配置或补审批记录。",
                "severity": "high",
                "evidence_id": str(item.get("id") or ""),
            }
        )

    if risks:
        risky_targets = Counter(_item_target(item) for item in risks)
        target, count = risky_targets.most_common(1)[0]
        recommendations.append(
            {
                "key": "focus_risky_target",
                "title": "聚焦高频风险对象",
                "target": target,
                "description": f"当前结果中该对象出现 {count} 条需关注记录。",
                "action": "按对象过滤日志，核对同一配置是否被连续修改。",
                "severity": "medium",
                "evidence_id": "",
            }
        )

    if items:
        latest = items[0]
        recommendations.append(
            {
                "key": "trace_latest_change",
                "title": "从最新变更回溯",
                "target": _item_target(latest),
                "description": f"{latest.get('user') or '系统'} 执行了 {latest.get('type') or '操作'}。",
                "action": "结合时间线查看该操作前后的发布、权限和自开发配置变化。",
                "severity": str(latest.get("details", {}).get("risk_level") or "low"),
                "evidence_id": str(latest.get("id") or ""),
            }
        )

    if not recommendations:
        recommendations.append(
            {
                "key": "no_action_required",
                "title": "暂无处置动作",
                "target": "当前筛选条件",
                "description": "没有命中需关注或高风险操作。",
                "action": "可扩大时间范围或切换菜单继续查看。",
                "severity": "low",
                "evidence_id": "",
            }
        )

    return recommendations[:4]


def normalize_lowcode_log_record(raw: dict[str, Any]) -> dict[str, Any]:
    """Normalize aPaaS tenant operation-log records into the LogsPanel item shape."""
    operation_time = _first_non_empty(
        raw, "operationTime", "operateTime", "createTime", "createdAt", "opTime", "updateTime"
    )
    function_menu = _first_non_empty(raw, "functionMenu", "menuName", "functionName", "moduleName")
    operation_object = _first_non_empty(
        raw, "operationObject", "operateObject", "objectName", "targetName", "resourceName"
    )
    description = _first_non_empty(
        raw, "operationDescription", "operateDescription", "description", "operateDesc", "content", "remark"
    )
    operation_type = _first_non_empty(raw, "operationType", "operateType", "type", "action")
    operator = _first_non_empty(
        raw,
        "operationUserName",
        "operationUser",
        "operatorName",
        "operator",
        "userName",
        "createUserName",
    )

    summary_parts = [part for part in (function_menu, operation_object, description) if part]
    risk, risk_reason = _classify_risk(operation_type, function_menu, operation_object, description)
    resource_type = _resource_type(function_menu, operation_object)

    return {
        "id": _stable_log_id(raw),
        "timestamp": operation_time,
        "type": operation_type or "操作",
        "user": operator or "系统",
        "summary": " · ".join(summary_parts) or operation_type or "低代码操作",
        "status": f"risk_{risk}",
        "details": {
            "risk_level": risk,
            "risk_reason": risk_reason,
            "function_menu": function_menu,
            "operation_object": operation_object,
            "operation_description": description,
            "operation_type": operation_type,
            "operator": operator,
            "resource_type": resource_type,
            "resource_label": _resource_label(resource_type),
            "raw": raw,
        },
    }


def extract_lowcode_log_records(resp: Any) -> list[dict[str, Any]]:
    """Accept the known aPaaS response envelopes and return the row list."""
    if isinstance(resp, list):
        return [row for row in resp if isinstance(row, dict)]
    if not isinstance(resp, dict):
        return []

    candidates: list[Any] = [
        resp.get("table"),
        resp.get("records"),
        resp.get("list"),
        resp.get("rows"),
    ]
    data = resp.get("data")
    if isinstance(data, dict):
        candidates.extend([data.get("table"), data.get("records"), data.get("list"), data.get("rows")])
    elif isinstance(data, list):
        candidates.append(data)

    for candidate in candidates:
        if isinstance(candidate, list):
            return [row for row in candidate if isinstance(row, dict)]
    return []


def extract_lowcode_log_total(resp: Any, fallback: int) -> int:
    if isinstance(resp, dict):
        for source in (resp, resp.get("data") if isinstance(resp.get("data"), dict) else {}):
            if not isinstance(source, dict):
                continue
            for key in ("total", "totalCount", "count"):
                value = source.get(key)
                if value is None:
                    continue
                try:
                    return int(value)
                except (TypeError, ValueError):
                    continue
    return fallback


def filter_lowcode_logs_for_application(rows: list[dict[str, Any]], app: Any) -> list[dict[str, Any]]:
    """Best-effort app-level filter for tenant logs returned by the low-code platform."""
    tokens = [
        str(getattr(app, "app_name", "") or "").strip(),
        str(getattr(app, "app_code", "") or "").strip(),
        str(getattr(app, "apaas_app_id", "") or "").strip(),
    ]
    tokens = [token.lower() for token in tokens if token]
    if not tokens:
        return rows

    matched: list[dict[str, Any]] = []
    for row in rows:
        haystack = json.dumps(row, ensure_ascii=False, default=str).lower()
        if any(token in haystack for token in tokens):
            matched.append(row)
    return matched


def build_lowcode_log_analysis(items: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(items)
    risks = [item for item in items if item.get("details", {}).get("risk_level") in {"high", "medium"}]
    high_risks = [item for item in items if item.get("details", {}).get("risk_level") == "high"]
    operation_types = Counter(str(item.get("type") or "操作") for item in items)
    menus = Counter(str(item.get("details", {}).get("function_menu") or "未分类") for item in items)
    operators = Counter(str(item.get("user") or "系统") for item in items)
    resources = Counter(str(item.get("details", {}).get("resource_type") or "tenant") for item in items)

    summary = "暂无低代码变更"
    if total:
        op_text = "，".join(f"{name} {count} 次" for name, count in operation_types.most_common(3))
        high_text = f"，高风险 {len(high_risks)} 条" if high_risks else ""
        summary = f"最近 {total} 条低代码变更：{op_text}；需关注 {len(risks)} 条{high_text}。"

    timeline = [
        {
            "id": str(item.get("id") or ""),
            "time": str(item.get("timestamp") or ""),
            "title": str(item.get("details", {}).get("operation_object") or item.get("summary") or "低代码操作"),
            "description": str(item.get("details", {}).get("operation_description") or item.get("summary") or ""),
            "operation_type": str(item.get("type") or "操作"),
            "operator": str(item.get("user") or "系统"),
            "risk_level": str(item.get("details", {}).get("risk_level") or "low"),
            "risk_reason": str(item.get("details", {}).get("risk_reason") or "常规操作"),
            "resource_type": str(item.get("details", {}).get("resource_type") or "tenant"),
            "resource_label": str(item.get("details", {}).get("resource_label") or "租户配置"),
        }
        for item in items[:12]
    ]

    change_domains = [
        {"key": key, "label": _resource_label(key), "count": count}
        for key, count in resources.most_common(6)
    ]
    recommendations = _build_recommendations(items=items, risks=risks, high_risks=high_risks)

    preset_reports = [
        {
            "key": "risk_board",
            "title": "风险看板",
            "summary": f"{len(risks)} 条需关注，{len(high_risks)} 条高风险",
            "metric": len(risks),
            "severity": "high" if high_risks else ("medium" if risks else "low"),
        },
        {
            "key": "change_timeline",
            "title": "变更时间线",
            "summary": f"最近 {min(total, len(timeline))} 条操作按平台顺序串联",
            "metric": len(timeline),
            "severity": "low",
        },
        {
            "key": "action_recommendations",
            "title": "处置建议",
            "summary": "基于当前日志给出下一步处理动作",
            "metric": len(recommendations),
            "severity": recommendations[0]["severity"] if recommendations else "low",
        },
    ]

    return {
        "total": total,
        "risk_total": len(risks),
        "high_risk_total": len(high_risks),
        "top_operation_types": [{"name": name, "count": count} for name, count in operation_types.most_common(5)],
        "top_menus": [{"name": name, "count": count} for name, count in menus.most_common(5)],
        "top_operators": [{"name": name, "count": count} for name, count in operators.most_common(5)],
        "summary": summary,
        "risk_items": risks[:8],
        "change_domains": change_domains,
        "timeline": timeline,
        "preset_reports": preset_reports,
        "recommendations": recommendations,
    }


def build_operate_log_filters(
    *, operation_type: str | None = None, function_menu: str | None = None, keyword: str | None = None
) -> dict[str, str]:
    operation_type = operation_type.strip() if isinstance(operation_type, str) else None
    function_menu = function_menu.strip() if isinstance(function_menu, str) else None
    keyword = keyword.strip() if isinstance(keyword, str) else None
    filters: dict[str, str] = {}
    if operation_type and operation_type != "all":
        filters["operationType"] = operation_type
    if function_menu and function_menu != "all":
        filters["functionMenu"] = function_menu
    if keyword:
        filters["operationObject"] = keyword
    return filters
