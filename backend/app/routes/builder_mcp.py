"""Builder UI 试调 / 按钮 → 同进程 MCP tool 的统一入口。

本地平台管理和 Builder 工具试调用当前 backend 进程内 FastMCP 注册表，不再要求
独立 8004 MCP 服务存在。AI Chat agent 仍有自己的 bridge/fallback 逻辑。
"""
from __future__ import annotations

import json
import logging
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.deps import AuthContext, get_auth_context
from app.mcp_inprocess import call_inprocess_tool, list_inprocess_tools

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/builder", tags=["builder-mcp"])


class InvokeMcpRequest(BaseModel):
    tool_name: str
    args: dict = Field(default_factory=dict)


@router.post("/invoke-mcp")
async def invoke_mcp(
    body: InvokeMcpRequest,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
):
    """前端按钮 / admin /mcp 试调 → 同进程 MCP tool。

    自动塞 ctx.tenant_id / ctx.user_id 到 args（工具签名 fallback 用）。

    返回结构：
      成功: {"ok": True, "tool_name": "...", "result": <parsed dict>}
      失败: {"ok": False, "tool_name": "...", "error": "..."}
    """
    args = dict(body.args or {})
    args["tenant_id"] = int(ctx.tenant_id or 0)
    args["user_id"] = int(ctx.user.id or 0)

    logger.info(
        "builder UI invoke-mcp → inprocess: user=%s tenant=%s tool=%s args_keys=%s",
        ctx.user.id, ctx.tenant_id, body.tool_name, list(args.keys()),
    )

    result_obj = await call_inprocess_tool(body.tool_name, args)

    try:
        parsed: Any = json.loads(result_obj) if isinstance(result_obj, str) else result_obj
    except (json.JSONDecodeError, TypeError):
        parsed = {"raw": result_obj}

    is_error = isinstance(parsed, dict) and (
        parsed.get("ok") is False or parsed.get("error_code") or parsed.get("isError")
    )
    if is_error or (isinstance(parsed, dict) and parsed.get("ok") is False):
        return {
            "ok": False,
            "tool_name": body.tool_name,
            "error": (parsed.get("message") if isinstance(parsed, dict) else None)
                or (parsed.get("error_code") if isinstance(parsed, dict) else None)
                or "工具执行失败",
            "detail": parsed,
        }

    return {
        "ok": True,
        "tool_name": body.tool_name,
        "result": parsed,
    }


@router.get("/mcp-tools")
async def list_available_tools(
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
):
    """给前端拿同进程可用工具清单（用于按钮 disabled 状态判断等）。"""
    try:
        tools = list_inprocess_tools()
    except Exception as exc:
        logger.exception("mcp-tools 读取同进程 MCP 工具失败")
        raise HTTPException(status_code=500, detail=f"同进程 MCP 工具不可用: {exc}")
    names = sorted(t.get("name", "") for t in tools)
    return {
        "ok": True,
        "available_tools": names,
        "total": len(names),
    }
