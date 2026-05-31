"""通过 HTTP 调 MCP server，把工具桥接给 ai_chat agent 用。

为什么走 HTTP 而不是 in-process import：
- 跟外部 agent（dolphin / Claude / Cursor）的调法完全一致，方便排查
- mcp_server 未来如果拆独立 service，cowork 端不用改
- 同 process 内 loopback HTTP 几乎零开销
- 所有调用都进 MCP 调用日志，统一可观测

启动时拉 tools/list 是 lazy 的（第一次 get_tool_schemas_openai 时拉），之后用 cache。
支持配置多个 MCP endpoint，把拆分后的工具在 AI Chat 里合并成一套工具池。

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


def _split_csv_env(value: str) -> list[str]:
    return [item.strip() for item in (value or "").split(",") if item.strip()]


def _default_mcp_bridge_base_url() -> str:
    from app.config import settings
    return f"http://127.0.0.1:{settings.port}/api/mcp/mcp"


# `MCP_BRIDGE_BASE_URLS` 是多 endpoint 配置；旧的 MCP_BRIDGE_BASE_URL 继续兼容。
def _configured_base_urls() -> list[str]:
    urls: list[str] = []
    urls.extend(_split_csv_env(os.getenv("MCP_BRIDGE_BASE_URLS", "")))
    urls.extend(_split_csv_env(os.getenv("MCP_BRIDGE_BASE_URL", "")))
    urls.extend(_split_csv_env(os.getenv("MCP_BRIDGE_EXTRA_BASE_URLS", "")))
    if not urls:
        urls.append(_default_mcp_bridge_base_url())

    seen: set[str] = set()
    deduped: list[str] = []
    for url in urls:
        normalized = url.rstrip("/")
        if normalized and normalized not in seen:
            seen.add(normalized)
            deduped.append(normalized)
    return deduped


_BASE_URLS = _configured_base_urls()

# 黑名单：这里曾用于隐藏旧生命周期工具；当前 AIChat 需要完整工具池，保持为空。
_STUB_TOOLS: set[str] = set()


def _get_api_key() -> Optional[str]:
    # MCP_BRIDGE_AUTH_KEY 单独配置 outbound 鉴权，跟 ming 自己 mcp_server 的入站
    # 鉴权 MCP_API_KEYS 解耦 — 切 v2 时 BASE 指 v2 svc，AUTH_KEY 必须配 v2 的 key
    # 而不能复用本机的 MCP_API_KEYS（否则两边 secret 体系串了）。
    raw = (os.getenv("MCP_BRIDGE_AUTH_KEY", "").strip()
           or os.getenv("MCP_API_KEYS", "").strip())
    if raw:
        return raw.split(",")[0].strip()
    return None


async def _fetch_tools_from(base_url: str, headers: dict, body: dict) -> list[dict]:
    async with httpx.AsyncClient(timeout=10.0) as client:
        r = await client.post(base_url, headers=headers, json=body)
        r.raise_for_status()
        data = r.json()
    return data.get("result", {}).get("tools", []) or []


async def _fetch_mcp_tools() -> tuple[list[dict], dict[str, str], Optional[str]]:
    """HTTP 调 MCP server 拉 tools/list。返回 (tools, tool_url_map, error_message)。"""
    key = _get_api_key()
    if not key:
        return [], {}, "MCP_API_KEYS 未配置 — 在 backend/.env 加一行 MCP_API_KEYS=<key>"
    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
    }
    body = {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}
    merged: list[dict] = []
    tool_url_map: dict[str, str] = {}
    errors: list[str] = []

    for base_url in _BASE_URLS:
        try:
            tools = await _fetch_tools_from(base_url, headers, body)
        except Exception as e:
            logger.warning("MCP bridge tools/list 失败 url=%s: %s", base_url, e)
            errors.append(f"{base_url}: {e}")
            continue
        for tool in tools:
            name = tool.get("name")
            if not name or name in tool_url_map:
                continue
            merged.append(tool)
            tool_url_map[name] = base_url

    if merged:
        if errors:
            logger.warning("MCP bridge 部分 endpoint 加载失败：%s", " | ".join(errors))
        return merged, tool_url_map, None
    return [], {}, "MCP tools/list 全部失败: " + " | ".join(errors)


async def ensure_loaded(force: bool = False) -> dict:
    """lazy 拉本机 MCP server 工具列表。返回 {tools, error}。"""
    global _LOADED
    if _LOADED is not None and not force:
        return _LOADED
    tools, tool_url_map, error = await _fetch_mcp_tools()
    _LOADED = {"tools": tools, "tool_url_map": tool_url_map, "error": error}
    if error:
        logger.warning("MCP bridge 加载失败：%s（cowork agent 只能用原生 4 工具）", error)
    else:
        logger.info(
            "MCP bridge 加载成功：%d 个 endpoint, %d 个工具（去 stub 后 %d 个可用）",
            len(_BASE_URLS),
            len(tools),
            len([t for t in tools if t.get("name") not in _STUB_TOOLS]),
        )
    return _LOADED


async def get_tool_schemas_openai() -> list[dict]:
    """把 MCP 的工具元信息转成 OpenAI tool calling 格式 schema 数组。

    过滤掉 stub 工具，避免 LLM 误调拿到 NOT_IMPLEMENTED。

    剥掉 tenant_id / user_id 字段不暴露给 LLM — 这俩是后端身份字段，由
    ai_chat dispatcher 从 session 注入；让 LLM 看到反而会自作主张填 0
    导致工具内部身份解析失败（2026-05-14 修）。
    """
    loaded = await ensure_loaded()
    out = []
    for t in loaded["tools"]:
        name = t.get("name")
        if not name or name in _STUB_TOOLS:
            continue
        input_schema = t.get("inputSchema") or {"type": "object", "properties": {}}
        cleaned_schema = _strip_identity_params(input_schema)
        out.append({
            "type": "function",
            "function": {
                "name": name,
                "description": (t.get("description") or "")[:1024],
                "parameters": cleaned_schema,
            },
        })
    return out


def _strip_identity_params(schema: dict) -> dict:
    """从 JSON Schema 里剥掉 tenant_id / user_id 字段，让 LLM 看不到。

    properties 字段必须保留（即使是空 {}）— 某些 LLM API 严格校验 type=object
    必须带 properties 键，否则 400 Bad Request（2026-05-14 实测 omnigate 这条）。
    """
    if not isinstance(schema, dict):
        return schema
    out = {k: v for k, v in schema.items() if k != "properties" and k != "required"}
    props = (schema.get("properties") or {}).copy()
    for hidden in ("tenant_id", "user_id"):
        props.pop(hidden, None)
    out["properties"] = props  # 永远保留 properties 键，即使是空 {}
    required = schema.get("required") or []
    required = [r for r in required if r not in ("tenant_id", "user_id")]
    if required:
        out["required"] = required
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
    if not tenant_id or not user_id:
        return json.dumps({
            "ok": False,
            "error_code": "MISSING_LOCAL_IDENTITY",
            "message": "AIChat 会话缺少本地 tenant_id/user_id，无法调用需要身份的 MCP 工具",
            "tool_name": tool_name,
        }, ensure_ascii=False)

    # 自动塞身份 — 强制覆盖。
    # 2026-05-14 修：之前用 `if 'tenant_id' not in enriched` 软合并，结果 LLM 看
    # 工具 schema 里有 tenant_id/user_id 字段，自作主张填 0 → 我们这边不敢覆盖 →
    # MCP 工具内部 _resolve_identity(0, 0) 报"缺少身份信息" → agent hallucinate
    # 说"系统没注入身份"误导用户。
    # 这俩是后端身份字段，**永远不让 LLM 决定**，session 给啥就用啥。
    enriched = {**(args or {})}
    enriched["tenant_id"] = tenant_id
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
        from app.auth import create_mcp_service_token
        headers["X-AiBuilder-Token"] = create_mcp_service_token(
            user_id=int(user_id),
            tenant_id=int(tenant_id),
            ttl_minutes=15,
        )
    except Exception as exc:
        logger.exception("MCP bridge failed to mint X-AiBuilder-Token")
        return json.dumps({
            "ok": False,
            "error_code": "MCP_IDENTITY_TOKEN_FAIL",
            "message": str(exc),
            "tool_name": tool_name,
        }, ensure_ascii=False)
    loaded = await ensure_loaded()
    base_url = (loaded.get("tool_url_map") or {}).get(tool_name) or (_BASE_URLS[0] if _BASE_URLS else "")
    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            r = await client.post(base_url, headers=headers, json=body)
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
