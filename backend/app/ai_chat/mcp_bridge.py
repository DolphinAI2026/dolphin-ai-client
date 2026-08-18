"""通过 HTTP 调 MCP server，把工具桥接给 ai_chat agent 用。

为什么走 HTTP 而不是 in-process import：
- 跟外部 agent（外部 agent / Claude / Cursor）的调法完全一致，方便排查
- mcp_server 未来如果拆独立 service，cowork 端不用改
- 同 process 内 loopback HTTP 几乎零开销
- 所有调用都进 MCP 调用日志，统一可观测

启动时拉 tools/list 是 lazy 的（第一次 get_tool_schemas_openai 时拉），之后用 cache。
支持配置多个 MCP endpoint，把拆分后的工具在 AI Chat 里合并成一套工具池。

注：MCP key 优先使用平台管理页配置；未配置时兼容读取 backend/.env 的 MCP_API_KEYS。
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


def _configured_base_urls() -> list[str]:
    """Return MCP endpoints in priority order.

    `MCP_BRIDGE_BASE_URLS` is the preferred multi-endpoint setting. The older
    `MCP_BRIDGE_BASE_URL` remains supported for single-endpoint deployments.
    """
    urls: list[str] = []
    urls.extend(_split_csv_env(os.getenv("MCP_BRIDGE_BASE_URLS", "")))
    urls.extend(_split_csv_env(os.getenv("MCP_BRIDGE_BASE_URL", "")))
    urls.extend(_split_csv_env(os.getenv("MCP_BRIDGE_EXTRA_BASE_URLS", "")))
    if not urls:
        legacy = os.getenv("MCP_INTERNAL_BASE", "").strip()
        urls.append(legacy or "http://127.0.0.1:8004/api/mcp/mcp")

    seen: set[str] = set()
    deduped: list[str] = []
    for url in urls:
        normalized = url.rstrip("/")
        if normalized and normalized not in seen:
            seen.add(normalized)
            deduped.append(normalized)
    return deduped


_BASE_URLS = _configured_base_urls()
_INPROCESS_TOOL_URL = "__inprocess_mcp__"
_CRITICAL_BUILDER_TOOLS = {
    "generate_app_from_doc",
    "validate_builder_doc",
    "submit_design_doc",
    "deploy_application",
    "publish_application",
    "get_application",
}

# 黑名单：这里曾有 4 个 stub 工具被屏蔽，现在全部已 ship 真实现，清空
_STUB_TOOLS: set[str] = set()


async def _get_api_key() -> Optional[str]:
    # MCP_BRIDGE_AUTH_KEY 单独配置 outbound 鉴权，跟 ming 自己 mcp_server 的入站
    # 鉴权 MCP_API_KEYS 解耦 — 切 v2 时 BASE 指 v2 svc，AUTH_KEY 必须配 v2 的 key
    # 而不能复用本机的 MCP_API_KEYS（否则两边 secret 体系串了）。
    raw = os.getenv("MCP_BRIDGE_AUTH_KEY", "").strip()
    if raw:
        return raw.split(",")[0].strip()
    try:
        from app.mcp_keys import get_mcp_api_keys

        keys = await get_mcp_api_keys()
        if keys:
            return keys[0]
    except Exception as exc:  # noqa: BLE001
        logger.warning("MCP bridge 读取页面配置 key 失败，降级读取环境变量: %s", exc)
    raw = os.getenv("MCP_API_KEYS", "").strip()
    if raw:
        return raw.split(",")[0].strip()
    return None


async def _fetch_tools_from(base_url: str, headers: dict, body: dict) -> list[dict]:
    async with httpx.AsyncClient(timeout=10.0) as client:
        r = await client.post(base_url, headers=headers, json=body)
        r.raise_for_status()
        data = r.json()
    return data.get("result", {}).get("tools", []) or []


async def _fetch_inprocess_tools() -> tuple[list[dict], dict[str, str], Optional[str]]:
    """兜底从同进程 FastMCP 实例读取工具。

    AIChat 正常走 HTTP bridge，方便观测和未来拆服务。但本地/单进程启动时
    8004 MCP 服务可能没起来；这时 Builder 核心工具不应该从模型 schema 里消失。
    """
    try:
        from app import mcp_server

        manager = getattr(getattr(mcp_server, "mcp", None), "_tool_manager", None)
        registered = getattr(manager, "_tools", None) or {}
        tools: list[dict] = []
        tool_url_map: dict[str, str] = {}
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
            tool_url_map[name] = _INPROCESS_TOOL_URL
        if tools:
            return tools, tool_url_map, None
        return [], {}, "同进程 MCP 未注册任何工具"
    except Exception as exc:  # noqa: BLE001
        return [], {}, f"同进程 MCP 加载失败: {exc}"


async def _fetch_mcp_tools() -> tuple[list[dict], dict[str, str], Optional[str]]:
    """HTTP 调 MCP server 拉 tools/list。返回 (tools, tool_url_map, error_message)。"""
    key = await _get_api_key()
    if not key:
        tools, tool_url_map, fallback_error = await _fetch_inprocess_tools()
        if tools:
            logger.warning("MCP_API_KEYS 未配置，AIChat bridge 使用同进程 MCP 工具兜底")
            return tools, tool_url_map, None
        return [], {}, (
            "MCP key 未配置 — 请在平台管理页 MCP 接入里配置 key；"
            f"{fallback_error}"
        )
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
        present = set(tool_url_map)
        # System-asset administration exists only in the Builder backend.  The
        # external v2 MCP cluster deliberately does not get a user's Control
        # Plane session, so always supplement those names from the in-process
        # registry instead of silently making them disappear in desktop mode.
        from app.mcp_tools.system_assets import SYSTEM_ASSET_TOOL_NAMES
        missing_critical = (_CRITICAL_BUILDER_TOOLS | set(SYSTEM_ASSET_TOOL_NAMES)) - present
        if missing_critical:
            fallback_tools, fallback_map, fallback_error = await _fetch_inprocess_tools()
            by_name = {t.get("name"): t for t in fallback_tools}
            patched: list[str] = []
            for name in sorted(missing_critical):
                tool = by_name.get(name)
                if not tool:
                    continue
                merged.append(tool)
                tool_url_map[name] = fallback_map.get(name, _INPROCESS_TOOL_URL)
                patched.append(name)
            if patched:
                logger.warning(
                    "MCP bridge HTTP tools/list 缺少 Builder 核心工具，已同进程补齐：%s",
                    ", ".join(patched),
                )
            elif fallback_error:
                logger.warning(
                    "MCP bridge HTTP tools/list 缺少 Builder 核心工具且补齐失败：%s",
                    fallback_error,
                )
        if errors:
            logger.warning("MCP bridge 部分 endpoint 加载失败：%s", " | ".join(errors))
        return merged, tool_url_map, None
    tools, inprocess_map, fallback_error = await _fetch_inprocess_tools()
    if tools:
        logger.warning(
            "MCP bridge HTTP tools/list 全部失败，AIChat bridge 使用同进程 MCP 工具兜底：%s",
            " | ".join(errors),
        )
        return tools, inprocess_map, None
    return [], {}, "MCP tools/list 全部失败: " + " | ".join(errors + [fallback_error or ""])


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


async def _call_inprocess_tool(
    tool_name: str,
    args: dict,
    *,
    control_plane_tenant_id: str | None = None,
) -> str:
    try:
        from app import mcp_server

        manager = getattr(getattr(mcp_server, "mcp", None), "_tool_manager", None)
        tool = (getattr(manager, "_tools", None) or {}).get(tool_name)
        if not tool:
            return json.dumps({
                "ok": False,
                "error_code": "INPROCESS_TOOL_NOT_FOUND",
                "message": f"同进程 MCP 未注册工具 {tool_name}",
            }, ensure_ascii=False)
        # 进程内调用 = 可信身份（args 里的 tenant_id/user_id 由 call_tool 从已鉴权
        # 会话强制注入）。标记可信，让工具内 _resolve_identity 采信传入租户、不被进程内
        # current_app slot 覆盖（修 unified ai-chat 串租户 bug）。
        args = args or {}
        from app.mcp_tools.system_assets import trusted_control_plane_tenant
        with (
            mcp_server.trusted_identity(args.get("tenant_id"), args.get("user_id")),
            trusted_control_plane_tenant(control_plane_tenant_id),
        ):
            result = await tool.run(args, convert_result=False)
        if isinstance(result, str):
            return result
        return json.dumps(result, ensure_ascii=False)
    except Exception as exc:  # noqa: BLE001
        logger.exception("同进程 MCP 工具调用失败 tool=%s", tool_name)
        return json.dumps({
            "ok": False,
            "error_code": "INPROCESS_TOOL_ERROR",
            "message": str(exc),
            "tool_name": tool_name,
        }, ensure_ascii=False)


async def call_tool(
    tool_name: str,
    args: dict,
    tenant_id: int = 0,
    user_id: int = 0,
    *,
    allow_zero_tenant: bool = False,
    control_plane_tenant_id: str | None = None,
) -> str:
    """调本机 MCP server 的某个工具，自动塞 tenant_id/user_id 到 args。

    返回 result 的第一个 content 块的 text（通常是 JSON 字符串，调用方自己 parse）。
    错误情况返回 {"ok": false, "error_code": ..., "message": ...} 的 JSON 串。
    """
    if (not tenant_id and not allow_zero_tenant) or not user_id:
        return json.dumps({
            "ok": False,
            "error_code": "MISSING_LOCAL_IDENTITY",
            "message": "AIChat 会话缺少当前 tenant_id/user_id，无法调用需要身份的 MCP 工具",
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

    loaded = await ensure_loaded()
    tool_url = (loaded.get("tool_url_map") or {}).get(tool_name)
    if tool_url == _INPROCESS_TOOL_URL:
        return await _call_inprocess_tool(
            tool_name,
            enriched,
            control_plane_tenant_id=control_plane_tenant_id,
        )

    key = await _get_api_key()
    if not key:
        return json.dumps({
            "ok": False, "error_code": "NO_MCP_KEY",
            "message": "MCP_API_KEYS 未配置",
        })

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
    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            loaded = await ensure_loaded()
            base_url = (loaded.get("tool_url_map") or {}).get(tool_name) or (_BASE_URLS[0] if _BASE_URLS else "")
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

    # ── 截断超长工具返回，避免单条 tool_result 吃掉大量上下文窗口 ──
    MCP_TOOL_RESULT_MAX_CHARS = 20_000
    if len(text) > MCP_TOOL_RESULT_MAX_CHARS:
        truncated = text[:MCP_TOOL_RESULT_MAX_CHARS]
        text = (
            f"{truncated}\n\n"
            f"[工具返回已截断：原文 {len(text)} 字符，已保留前 {MCP_TOOL_RESULT_MAX_CHARS} 字符。"
            f"如需更多细节请缩小查询范围或分多次调用。]"
        )
    return text
