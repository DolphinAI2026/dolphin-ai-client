"""Builder UI 试调 / 按钮 → MCP tool 的统一入口。

2026-05-16 起改 proxy 模式：不再调本机 mcp_server.py 工具，而是 HTTP 调
v2 svc 的 tools/call，跟 外部 agent 走同一条路径，admin /mcp 试调结果
跟 MCP 客户端实际行为一致。

身份桥接：浏览器 JWT → ctx.tenant_id / ctx.user_id 注入到 args，v2 工具签名
大多 fallback 这两个参数（admin 模式 1, 1）。
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Annotated, Any

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.deps import AuthContext, get_auth_context

# pydantic-settings 不 export 到 os.environ；显式 load .env 兜底
try:
    from dotenv import load_dotenv as _load_dotenv
    _env_path = Path(__file__).resolve().parent.parent.parent / ".env"  # backend/.env
    if _env_path.exists():
        _load_dotenv(str(_env_path), override=False)
except Exception:
    pass

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/builder", tags=["builder-mcp"])

# 跟 admin_mcp.py 共用同样的独立 MCP endpoint 配置
_V2_BASE = os.getenv(
    "MCP_V2_INTERNAL_BASE",
    "http://127.0.0.1:8004/api/mcp/mcp",
)
_V2_HOST = os.getenv("MCP_V2_HOST", "127.0.0.1:8004")


def _v2_headers() -> dict:
    raw = (os.getenv("MCP_API_KEYS") or "").strip()
    if not raw:
        raise HTTPException(
            status_code=500,
            detail="MCP_API_KEYS env 未配置，invoke-mcp 无法调 v2 MCP",
        )
    key = raw.split(",")[0].strip()
    return {
        "Host": _V2_HOST,
        "Authorization": f"Bearer {key}",
        "Accept": "application/json, text/event-stream",
        "Content-Type": "application/json",
    }


class InvokeMcpRequest(BaseModel):
    tool_name: str
    args: dict = {}


@router.post("/invoke-mcp")
async def invoke_mcp(
    body: InvokeMcpRequest,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
):
    """前端按钮 / admin /mcp 试调 → v2 MCP tools/call 的桥。

    自动塞 ctx.tenant_id / ctx.user_id 到 args（v2 工具签名 fallback 用）。

    返回结构：
      成功: {"ok": True, "tool_name": "...", "result": <parsed dict>}
      失败: {"ok": False, "tool_name": "...", "error": "..."}
    """
    args = dict(body.args or {})
    args.setdefault("tenant_id", int(ctx.tenant_id or 0))
    args.setdefault("user_id", int(ctx.user.id or 0))

    logger.info(
        "builder UI invoke-mcp → v2: user=%s tenant=%s tool=%s args_keys=%s",
        ctx.user.id, ctx.tenant_id, body.tool_name, list(args.keys()),
    )

    try:
        async with httpx.AsyncClient(timeout=180.0) as cli:
            resp = await cli.post(
                _V2_BASE,
                headers=_v2_headers(),
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "tools/call",
                    "params": {"name": body.tool_name, "arguments": args},
                },
            )
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("invoke-mcp proxy 调 v2 异常")
        raise HTTPException(status_code=502, detail=f"v2 MCP 不可达: {exc}")

    if resp.status_code != 200:
        raise HTTPException(
            status_code=502,
            detail=f"v2 MCP tools/call 失败 ({resp.status_code}): {resp.text[:300]}",
        )

    data = resp.json()
    # v2 错误（JSON-RPC error 字段）
    if "error" in data:
        err = data["error"]
        return {
            "ok": False,
            "tool_name": body.tool_name,
            "error": err.get("message") or str(err),
            "detail": err,
        }

    result_obj = data.get("result") or {}
    # MCP tools/call 返回 {content: [{type: text, text: "..."}], isError: bool}
    content_arr = result_obj.get("content") or []
    text_pieces = [c.get("text", "") for c in content_arr if c.get("type") == "text"]
    result_text = "\n".join(text_pieces) if text_pieces else json.dumps(result_obj, ensure_ascii=False)

    try:
        parsed: Any = json.loads(result_text)
    except (json.JSONDecodeError, TypeError):
        parsed = {"raw": result_text}

    is_error = bool(result_obj.get("isError"))
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
    """给前端拿 v2 可用工具清单（用于按钮 disabled 状态判断等）。"""
    try:
        async with httpx.AsyncClient(timeout=30.0) as cli:
            resp = await cli.post(
                _V2_BASE,
                headers=_v2_headers(),
                json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
            )
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("mcp-tools proxy 调 v2 异常")
        raise HTTPException(status_code=502, detail=f"v2 MCP 不可达: {exc}")

    if resp.status_code != 200:
        raise HTTPException(
            status_code=502,
            detail=f"v2 MCP tools/list 失败 ({resp.status_code}): {resp.text[:300]}",
        )

    tools = ((resp.json() or {}).get("result") or {}).get("tools") or []
    names = sorted(t.get("name", "") for t in tools)
    return {
        "ok": True,
        "available_tools": names,
        "total": len(names),
    }
