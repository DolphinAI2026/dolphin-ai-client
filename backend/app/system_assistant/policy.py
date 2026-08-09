"""Pure P0 policy for choosing one useful next action from baseline facts."""

from __future__ import annotations

from typing import Any

from app.system_assistant.contracts import BaselineStatus


def _action(action_id: str, status: BaselineStatus, title: str, reason: str) -> dict[str, str]:
    return {"id": action_id, "status": status, "title": title, "reason": reason}


def choose_recommended_action(nodes: dict[str, dict[str, Any]]) -> dict[str, str]:
    """Choose the highest-value safe action, without creating a plan or writing state."""

    workspace = nodes.get("workspace", {})
    environment = nodes.get("environment", {})
    validation_status = workspace.get("metadata", {}).get(
        "validation_status", workspace.get("validation_status", "not_needed")
    )
    if workspace.get("status") == "missing":
        if nodes.get("templates", {}).get("status") == "ready":
            return _action("select_template", "partial", "选择可选模板", "当前没有可见工作区，但存在可选模板来源。")
        return _action("connect_workspace", "missing", "连接已有工程", "当前租户没有可见的 Code 工作区。")
    if validation_status == "stale" or workspace.get("status") == "stale":
        return _action("validate_workspace", "stale", "验证当前工程", "工作区已有事实，但验证结果已过期。")
    if environment.get("status") == "missing":
        return _action("configure_environment", "missing", "配置开发环境", "工作区可见，但没有可用的 PlatformEnv。")
    if environment.get("status") == "unavailable":
        return _action("inspect_environment_source", "partial", "检查环境来源", "PlatformEnv 来源暂不可用，未将其当作空数据。")
    if any(node.get("status") in {"missing", "stale"} for node in nodes.values()):
        return _action("inspect_baseline", "partial", "检查基线缺口", "基线仍有需要人工确认的缺口。")
    return _action("no_action", "not_needed", "无需操作", "当前可见基线已经满足 P0 诊断条件。")


def available_actions(action: dict[str, str]) -> list[str]:
    """Expose only the selected safe route draft in P0."""

    return [] if action["status"] == "not_needed" else [action["id"]]
