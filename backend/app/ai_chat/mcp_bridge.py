"""通过 HTTP 调本机 MCP server，把 44 个工具桥接给 ai_chat agent 用。

为什么走 HTTP 而不是 in-process import：
- 跟外部 agent（dolphin / Claude / Cursor）的调法完全一致，方便排查
- mcp_server 未来如果拆独立 service，cowork 端不用改
- 同 process 内 loopback HTTP 几乎零开销
- 所有调用都进 MCP 调用日志，统一可观测

启动时拉 tools/list 是 lazy 的（第一次 get_tool_schemas_openai 时拉），之后用 cache。

注：MCP_API_KEYS 必须在 backend/.env 配，否则桥接不可用（cowork agent 只剩原 4 个工具）。
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any, Optional

import httpx

# 跟 mcp_server.py 同款 dotenv 兜底：pydantic-settings 不写 os.environ，
# 但 mcp_bridge / mcp_server 都用 os.getenv 读 MCP_API_KEYS，必须显式加载 .env
try:
    from dotenv import load_dotenv as _load_dotenv
    _backend_dir = Path(__file__).resolve().parent.parent.parent  # backend/
    _env_path = _backend_dir / ".env"
    if _env_path.exists():
        _load_dotenv(str(_env_path), override=False)
except Exception:
    pass

logger = logging.getLogger(__name__)


_LOADED: Optional[dict] = None
_BASE_URL = "http://127.0.0.1:8000/api/mcp/mcp"

# 黑名单：这里曾有 4 个 stub 工具被屏蔽，现在全部已 ship 真实现，清空
_STUB_TOOLS: set[str] = set()


def _get_api_key() -> Optional[str]:
    raw = os.getenv("MCP_API_KEYS", "").strip()
    if raw:
        return raw.split(",")[0].strip()
    return None


async def _fetch_mcp_tools() -> tuple[list[dict], Optional[str]]:
    """HTTP 调本机 MCP server 拉 tools/list。返回 (tools, error_message)。"""
    key = _get_api_key()
    if not key:
        return [], "MCP_API_KEYS 未配置 — 在 backend/.env 加一行 MCP_API_KEYS=<key>"
    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
    }
    body = {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.post(_BASE_URL, headers=headers, json=body)
            r.raise_for_status()
            data = r.json()
    except Exception as e:
        logger.warning("MCP bridge tools/list 失败: %s", e)
        return [], f"MCP tools/list 失败: {e}"
    tools = data.get("result", {}).get("tools", []) or []
    return tools, None


async def ensure_loaded(force: bool = False) -> dict:
    """lazy 拉本机 MCP server 工具列表。返回 {tools, error}。"""
    global _LOADED
    if _LOADED is not None and not force:
        return _LOADED
    tools, error = await _fetch_mcp_tools()
    _LOADED = {"tools": tools, "error": error}
    if error:
        logger.warning("MCP bridge 加载失败：%s（cowork agent 只能用原生 4 工具）", error)
    else:
        logger.info("MCP bridge 加载成功：%d 个工具（去 stub 后 %d 个可用）",
                    len(tools), len([t for t in tools if t.get("name") not in _STUB_TOOLS]))
    return _LOADED


async def get_tool_schemas_openai() -> list[dict]:
    """把 MCP 的工具元信息转成 OpenAI tool calling 格式 schema 数组。

    过滤掉 stub 工具，避免 LLM 误调拿到 NOT_IMPLEMENTED。
    """
    loaded = await ensure_loaded()
    out = []
    for t in loaded["tools"]:
        name = t.get("name")
        if not name or name in _STUB_TOOLS:
            continue
        out.append({
            "type": "function",
            "function": {
                "name": name,
                "description": (t.get("description") or "")[:1024],
                "parameters": t.get("inputSchema") or {"type": "object", "properties": {}},
            },
        })
    return out


def list_mcp_tool_names_cached() -> set[str]:
    """同步：从 cache 拿可用 MCP 工具名列表（不包括 stub）。未加载返回空集。"""
    if _LOADED is None:
        return set()
    return {
        t.get("name") for t in _LOADED["tools"]
        if t.get("name") and t.get("name") not in _STUB_TOOLS
    }


async def call_tool(tool_name: str, args: dict, tenant_id: int = 0, user_id: int = 0) -> str:
    """调本机 MCP server 的某个工具，自动塞 tenant_id/user_id 到 args。

    返回 result 的第一个 content 块的 text（通常是 JSON 字符串，调用方自己 parse）。
    错误情况返回 {"ok": false, "error_code": ..., "message": ...} 的 JSON 串。
    """
    key = _get_api_key()
    if not key:
        return json.dumps({
            "ok": False, "error_code": "NO_MCP_KEY",
            "message": "MCP_API_KEYS 未配置",
        })

    # 自动塞身份（很多工具都有 tenant_id / user_id 隐式参数，默认 0 会 fallback admin）
    enriched = {**(args or {})}
    if "tenant_id" not in enriched:
        enriched["tenant_id"] = tenant_id
    if "user_id" not in enriched:
        enriched["user_id"] = user_id

    body = {
        "jsonrpc": "2.0", "id": 1,
        "method": "tools/call",
        "params": {"name": tool_name, "arguments": enriched},
    }
    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
    }
    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            r = await client.post(_BASE_URL, headers=headers, json=body)
            r.raise_for_status()
            data = r.json()
    except Exception as e:
        logger.exception("MCP bridge call_tool %s failed", tool_name)
        return json.dumps({
            "ok": False, "error_code": "MCP_HTTP_FAIL",
            "message": str(e), "tool_name": tool_name,
        }, ensure_ascii=False)

    if data.get("error"):
        return json.dumps({
            "ok": False, "error_code": "JSONRPC_ERROR",
            "message": data["error"].get("message", "未知 JSONRPC 错误"),
            "raw": data["error"],
        }, ensure_ascii=False)

    result = data.get("result", {})
    if result.get("isError"):
        return json.dumps({
            "ok": False, "error_code": "TOOL_RUNTIME_ERROR",
            "raw": result,
        }, ensure_ascii=False)

    content = result.get("content") or []
    if not content:
        return json.dumps({"ok": False, "error_code": "EMPTY_RESULT", "raw": result})

    # 取第一块 text 内容（FastMCP 用 TextContent 包装）
    block = content[0]
    text = block.get("text") if isinstance(block, dict) else None
    if text is None:
        return json.dumps({"ok": True, "raw": result}, ensure_ascii=False)
    return text
