from __future__ import annotations

import hashlib
import json
from collections import Counter
from typing import Any


_DELETE_ACTIONS = ("删除", "下线", "禁用", "关闭")
_WATCH_ACTIONS = ("发布", "启用", "导入", "导出", "下载")
_WATCH_MENUS = ("权限", "高级设置", "自开发", "数据源", "服务集成", "应用发布")


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


def _classify_risk(operation_type: str, function_menu: str, operation_object: str, description: str) -> str:
    text = f"{operation_type} {function_menu} {operation_object} {description}"
    if any(token in text for token in _DELETE_ACTIONS):
        return "high"
    if any(token in text for token in _WATCH_ACTIONS) or any(token in text for token in _WATCH_MENUS):
        return "medium"
    return "low"


def _resource_type(function_menu: str, operation_object: str) -> str:
    text = f"{function_menu} {operation_object}"
    if "权限" in text or "角色" in text:
        return "permission"
    if "自开发" in text:
        return "self_development"
    if "菜单" in text:
        return "menu"
    if "应用" in text:
        return "application"
    if "数据源" in text:
        return "datasource"
    if "服务" in text or "接口" in text:
        return "integration"
    return "tenant"


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
    risk = _classify_risk(operation_type, function_menu, operation_object, description)

    return {
        "id": _stable_log_id(raw),
        "timestamp": operation_time,
        "type": operation_type or "操作",
        "user": operator or "系统",
        "summary": " · ".join(summary_parts) or operation_type or "低代码操作",
        "status": f"risk_{risk}",
        "details": {
            "risk_level": risk,
            "function_menu": function_menu,
            "operation_object": operation_object,
            "operation_description": description,
            "operation_type": operation_type,
            "operator": operator,
            "resource_type": _resource_type(function_menu, operation_object),
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

    summary = "暂无低代码变更"
    if total:
        op_text = "，".join(f"{name} {count} 次" for name, count in operation_types.most_common(3))
        summary = f"最近 {total} 条低代码变更：{op_text}；需关注 {len(risks)} 条。"

    return {
        "total": total,
        "risk_total": len(risks),
        "high_risk_total": len(high_risks),
        "top_operation_types": [{"name": name, "count": count} for name, count in operation_types.most_common(5)],
        "top_menus": [{"name": name, "count": count} for name, count in menus.most_common(5)],
        "top_operators": [{"name": name, "count": count} for name, count in operators.most_common(5)],
        "summary": summary,
        "risk_items": risks[:5],
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
