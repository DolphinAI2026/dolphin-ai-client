"""Helpers for testing the in-process FastMCP tool registry.

These helpers are used by the admin/tooling UI when local development does not
run the standalone 8004 MCP service.
"""
from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)


def _tool_manager():
    from app import mcp_server

    manager = getattr(getattr(mcp_server, "mcp", None), "_tool_manager", None)
    if manager is None:
        raise RuntimeError("同进程 MCP tool manager 不可用")
    return manager


def list_inprocess_tools() -> list[dict]:
    """Return FastMCP tools registered in the current backend process."""
    registered = getattr(_tool_manager(), "_tools", None) or {}
    tools: list[dict] = []
    for name, tool in registered.items():
        if not name:
            continue
        tools.append({
            "name": name,
            "description": getattr(tool, "description", "") or "",
            "inputSchema": getattr(tool, "parameters", None) or {
                "type": "object",
                "properties": {},
            },
        })
    return sorted(tools, key=lambda item: item.get("name") or "")


async def call_inprocess_tool(tool_name: str, args: dict | None) -> Any:
    """Run a registered FastMCP tool and return its native result."""
    registered = getattr(_tool_manager(), "_tools", None) or {}
    tool = registered.get(tool_name)
    if not tool:
        return {
            "ok": False,
            "error_code": "INPROCESS_TOOL_NOT_FOUND",
            "message": f"同进程 MCP 未注册工具 {tool_name}",
        }

    from app import mcp_server

    args = args or {}
    try:
        # 进程内可信入口（admin 测试台传平台管理员 JWT 的 tenant_id/user_id）：标记可信，
        # 让工具内 _resolve_identity 采信传入租户、不被 current_app slot 覆盖。
        with mcp_server.trusted_identity(args.get("tenant_id"), args.get("user_id")):
            result = await tool.run(args, convert_result=False)
    except Exception as exc:  # noqa: BLE001
        logger.exception("同进程 MCP 工具调用失败 tool=%s", tool_name)
        return {
            "ok": False,
            "error_code": "INPROCESS_TOOL_ERROR",
            "message": str(exc),
            "tool_name": tool_name,
        }

    if isinstance(result, str):
        try:
            return json.loads(result)
        except Exception:
            return {"raw": result}
    return result
