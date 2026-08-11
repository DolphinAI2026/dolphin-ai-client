"""Pure P0 policy for choosing one useful next action from baseline facts."""

from __future__ import annotations

from typing import Any

from app.system_assistant.contracts import BaselineStatus


SYSTEM_ASSISTANT_ENFORCE_NOT_READY = "SYSTEM_ASSISTANT_ENFORCE_NOT_READY"
SUPPORTED_GOVERNANCE_POLICIES = frozenset({"legacy", "shadow"})


def validate_governance_policy(
    value: str | None,
    *,
    policy_revision: int = 1,
    min_policy_revision: int = 1,
    projection_cache_seconds: int = 300,
) -> str:
    """Validate the B0 rollout mode without introducing an enforce fallback."""
    policy = str(value or "legacy").strip().lower()
    if policy == "enforce":
        raise RuntimeError(SYSTEM_ASSISTANT_ENFORCE_NOT_READY)
    if policy not in SUPPORTED_GOVERNANCE_POLICIES:
        raise ValueError(f"SYSTEM_ASSISTANT_GOVERNANCE_POLICY_UNSUPPORTED: {policy}")
    if (
        isinstance(policy_revision, bool)
        or isinstance(min_policy_revision, bool)
        or not isinstance(policy_revision, int)
        or not isinstance(min_policy_revision, int)
        or policy_revision <= 0
        or min_policy_revision <= 0
        or min_policy_revision > policy_revision
        or isinstance(projection_cache_seconds, bool)
        or not isinstance(projection_cache_seconds, int)
        or projection_cache_seconds <= 0
    ):
        raise RuntimeError("SYSTEM_ASSISTANT_POLICY_REVISION_INVALID")
    return policy


def _action(action_id: str, status: BaselineStatus, title: str, reason: str) -> dict[str, str]:
    return {"id": action_id, "status": status, "title": title, "reason": reason}


def choose_recommended_action(nodes: dict[str, dict[str, Any]]) -> dict[str, str]:
    """Choose the highest-value safe action, without creating a plan or writing state."""

    workspace = nodes.get("workspace", {})
    environment = nodes.get("environment", {})
    governance_items = nodes.get("governance", {}).get("items") or []
    role = str(governance_items[0].get("id", "member")) if governance_items else "member"
    can_manage_environment = role in {"platform_admin", "tenant_admin"}
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
        if can_manage_environment:
            return _action("configure_environment", "missing", "配置开发环境", "工作区可见，但没有可用的 PlatformEnv。")
        return _action("request_environment_access", "partial", "联系管理员配置环境", "当前账号不能维护租户环境。")
    if environment.get("status") == "unavailable":
        if environment.get("metadata", {}).get("reason") == "tenant_admin_required":
            return _action("request_environment_access", "partial", "联系管理员配置环境", "当前账号不能查看或维护租户环境。")
        return _action("inspect_environment_source", "partial", "检查环境来源", "PlatformEnv 来源暂不可用，未将其当作空数据。")
    if any(
        node.get("status") in {"missing", "stale", "partial", "unavailable"}
        or node.get("source_status") in {"partial", "unavailable"}
        for node in nodes.values()
    ):
        return _action("inspect_baseline", "partial", "检查基线缺口", "基线仍有需要人工确认的缺口。")
    return _action("no_action", "not_needed", "无需操作", "当前可见基线已经满足 P0 诊断条件。")


def available_actions(action: dict[str, str]) -> list[str]:
    """Expose only the selected safe route draft in P0."""

    return [] if action["status"] == "not_needed" else [action["id"]]
