"""Builder UI thin wrapper: 把 UI 按钮的"创建应用 / 发布"等动作走 MCP tool。

为啥要这一层：让前端按钮和 cowork agent 走的是**同一条路径**（都到 mcp_server），
所有动作都是 tool_call，可观测、可审计、未来 mcp_server 拆独立 service 时 UI
不用改。

跟 cowork 区别：
- cowork: LLM 推理决定调哪个工具
- builder UI: 用户点按钮，前端已经知道调哪个工具（如 publish_application），
  这里 backend 透传给本机 MCP

身份桥接：浏览器 JWT → ctx → 给 MCP args 塞 tenant_id / user_id（MCP 工具签名
都隐式接受这两参，fallback admin (1,1)）

只有登录用户能调，登录态依赖 get_auth_context。
"""
from __future__ import annotations

import logging
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.deps import AuthContext, get_auth_context

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/builder", tags=["builder-mcp"])


class InvokeMcpRequest(BaseModel):
    tool_name: str
    args: dict = {}


@router.post("/invoke-mcp")
async def invoke_mcp(
    body: InvokeMcpRequest,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
):
    """前端按钮调本机 MCP tool 的统一入口。

    自动塞 ctx.tenant_id / ctx.user_id 到 args（让 MCP 工具按真实身份执行，
    不是 admin fallback）。

    返回结构：
      成功: {"ok": True, "tool_name": "...", "result": <parsed dict>}
      失败: {"ok": False, "tool_name": "...", "error": "..."}
    """
    from app.ai_chat.mcp_bridge import call_tool, list_mcp_tool_names_cached, ensure_loaded
    import json

    # 触发一次 lazy load（保证 cache）
    await ensure_loaded()

    available = list_mcp_tool_names_cached()
    if body.tool_name not in available:
        # 注意：available 不含 stub 工具
        raise HTTPException(
            status_code=400,
            detail=f"工具 '{body.tool_name}' 不存在或未启用。可用工具数：{len(available)}",
        )

    logger.info(
        "builder UI invoke-mcp: user=%s tenant=%s tool=%s args=%s",
        ctx.user.id, ctx.tenant_id, body.tool_name, list(body.args.keys()),
    )

    result_text = await call_tool(
        body.tool_name,
        body.args,
        tenant_id=ctx.tenant_id,
        user_id=ctx.user.id,
    )

    # call_tool 返回字符串（通常是 JSON）。尝试 parse
    try:
        parsed = json.loads(result_text)
    except (json.JSONDecodeError, TypeError):
        parsed = {"raw": result_text}

    # 看是否是失败结果（约定 ok=False 或 isError）
    if isinstance(parsed, dict) and parsed.get("ok") is False:
        return {
            "ok": False,
            "tool_name": body.tool_name,
            "error": parsed.get("message") or parsed.get("error_code") or "工具执行失败",
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
    """给前端拿可用工具清单（用于按钮 disabled 状态判断等）。"""
    from app.ai_chat.mcp_bridge import ensure_loaded, list_mcp_tool_names_cached
    await ensure_loaded()
    return {
        "ok": True,
        "available_tools": sorted(list_mcp_tool_names_cached()),
        "total": len(list_mcp_tool_names_cached()),
    }
