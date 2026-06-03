"""MCP Hub — server-grouped view for the v2 /mcp page.

Returns MCP servers with status, transport, tool count, official flag.

2026-05-18: replaced hardcoded 8-server seed with REAL data sourced from
`_V2_TOOL_PATHS` in admin_mcp + live `tools/list` proxy. Now shows actual
v2 MCP cluster servers (main + design) with live tool counts and status.

If v2 cluster is unreachable, falls back to status=error gracefully (the
page handles the response shape unchanged).
"""
from __future__ import annotations

import logging
import re
from typing import Annotated, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.ai_chat import mcp_bridge
from app.deps import get_auth_context, AuthContext
from app.routes.admin_mcp import _V2_TOOL_PATHS, _fetch_tools_from

logger = logging.getLogger(__name__)


# 独立 MCP server 作为第 1 条 server 暴露给 /mcp 管理页。
_LOCAL_SERVER_META: dict = {
    "id": "standalone-mcp-server",
    "name": "独立 MCP Server",
    "code": "standalone-mcp-server",
    "transport": "http",
    "endpoint": "http://127.0.0.1:8004/api/mcp/mcp",
    "version": "local-dev",
    "official": False,
    "tags": ["本地", "独立服务"],
    "desc": "独立 MCP 服务（apaas-builder-mcp-server 仓库 / k8s）的 FastMCP — ai_chat / cowork agent 默认调用的工具集。",
}


async def _build_local_server() -> McpServer:
    """从 mcp_bridge.ensure_loaded() 拉真实工具数构建本地 server 条目。

    失败时降级为 status=error 但不抛 — 整个 /servers 不能因为本地探活挂掉。
    """
    try:
        loaded = await mcp_bridge.ensure_loaded()
        tools = loaded.get("tools") or []
        error = loaded.get("error")
        tool_count = len(tools)
        if error or tool_count == 0:
            status = "error"
            err = error or "本地 MCP 工具数为 0"
        else:
            status = "connected"
            err = None
    except Exception as e:  # noqa: BLE001
        err_text = _clean_error_message(e)
        logger.warning("mcp-hub: local mcp_bridge ensure_loaded failed: %s", err_text)
        tool_count = 0
        status = "error"
        err = err_text

    meta = _LOCAL_SERVER_META
    return McpServer(
        id=meta["id"],
        name=meta["name"],
        code=meta["code"],
        status=status,
        transport=meta["transport"],
        endpoint=meta["endpoint"],
        tools=tool_count,
        last_used=None,
        usage=0,
        version=meta["version"],
        tags=meta["tags"],
        desc=meta["desc"],
        official=meta["official"],
        error=err,
    )


def _clean_error_message(err: str | Exception) -> str:
    """Strip HTML tags + collapse whitespace from raw exception strings.

    Backend may receive nginx 404 HTML when the cluster route is missing;
    we never want that leaking into UI error fields.
    """
    text = str(err)[:300]
    # Strip HTML tags
    text = re.sub(r"<[^>]+>", " ", text)
    # Collapse whitespace
    text = re.sub(r"\s+", " ", text).strip()
    return text[:200]


def _looks_like_cluster_unreachable(err: Exception, err_text: str) -> bool:
    """Heuristic: is this error a 'cluster not reachable / not configured' (dev mode)
    rather than a real per-server fault?

    Indicators: connect-refused / DNS / nginx 404 default page / generic Not Found.
    """
    s = err_text.lower()
    raw = str(err).lower()
    if "connection" in s or "name resolution" in s or "dns" in s:
        return True
    if "unreachable" in s or "name or service not known" in s:
        return True
    if "404" in s and "nginx" in s:
        return True
    if "not found" in s and ("html" in s or "<" in raw):
        return True
    return False

router = APIRouter(prefix="/api/mcp-hub", tags=["mcp-hub"])


class McpServer(BaseModel):
    id: str
    name: str
    code: str
    status: str  # connected / error / disabled
    transport: str  # sse / http / stdio
    endpoint: str
    tools: int
    last_used: Optional[str] = None
    usage: int = 0
    version: str = ""
    tags: list[str] = []
    desc: str = ""
    official: bool = False
    error: Optional[str] = None


class McpServerListResponse(BaseModel):
    servers: list[McpServer]
    total: int
    connected: int
    errors: int


# Per-path metadata not available in the tool response itself (status / version /
# desc / endpoint pretty form). Server id/code/name are inferred from the path.
# Keys are substrings to match against the v2 path.
_BASE_SERVER_META: dict[str, dict] = {
    "main": {
        "id": "mcp-v2-main",
        "name": "得帆云 aPaaS MCP v2 (main)",
        "code": "apaas-v2-main",
        "transport": "http",
        "version": "2.3.1",
        "official": True,
        "tags": ["官方", "应用配置", "自开发"],
        "desc": "v2 主 FastMCP — 应用生命周期 / workspace / 自开发 / 内省。外部 agent 实际在调的版本。",
    },
    "design": {
        "id": "mcp-v2-design",
        "name": "设计文档 MCP",
        "code": "apaas-v2-design",
        "transport": "http",
        "version": "2.3.1",
        "official": True,
        "tags": ["官方", "设计文档"],
        "desc": "独立 design FastMCP — design system / principle 等设计资源 4 工具。",
    },
}


def _meta_for_path(path: str) -> dict:
    """Match path to BASE_SERVER_META key. Falls back to a generic shell."""
    if "mcp-design" in path or "design" in path:
        return _BASE_SERVER_META["design"]
    if "mcp/mcp" in path or "main" in path or path.endswith("/mcp"):
        return _BASE_SERVER_META["main"]
    # Unknown path — synthesize a minimal meta entry
    slug = path.strip("/").replace("/", "-") or "unknown"
    return {
        "id": f"mcp-v2-{slug}",
        "name": f"MCP ({path})",
        "code": slug,
        "transport": "http",
        "version": "?",
        "official": False,
        "tags": [],
        "desc": f"MCP server at {path}",
    }


@router.get("/servers", response_model=McpServerListResponse)
async def list_servers(
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
):
    """List real MCP servers visible to this tenant.

    Derives the list from `_V2_TOOL_PATHS` (the same endpoints admin_mcp
    proxies to) and probes each with `tools/list` to get a live tool count
    + connection status. Errors are surfaced per-server, not as a 5xx.
    """
    servers: list[McpServer] = []
    connected = 0
    errors = 0

    # 独立 MCP server 永远是 servers[0]，保留 v2 placeholder 在后作为 catalog
    # （v2 cluster 不可达时显示 disabled，可达时显示真工具数）。
    local_server = await _build_local_server()
    servers.append(local_server)
    if local_server.status == "connected":
        connected += 1
    elif local_server.status == "error":
        errors += 1

    for path in _V2_TOOL_PATHS:
        meta = _meta_for_path(path)
        try:
            tools = await _fetch_tools_from(path)
            tool_count = len(tools)
            status = "connected"
            err: Optional[str] = None
            connected += 1
        except Exception as e:  # noqa: BLE001 - we want to surface any failure as per-server error
            err_text = _clean_error_message(e)
            logger.warning("mcp-hub: fetch tools failed for %s: %s", path, err_text)
            tool_count = 0
            if _looks_like_cluster_unreachable(e, err_text):
                # Local dev / cluster not configured — treat as "disabled" not "error".
                status = "disabled"
                err = "本地未接入 v2 MCP cluster (dev 模式)"
            else:
                status = "error"
                err = err_text
                errors += 1

        servers.append(
            McpServer(
                id=meta["id"],
                name=meta["name"],
                code=meta["code"],
                status=status,
                transport=meta["transport"],
                endpoint=path,
                tools=tool_count,
                last_used=None,
                usage=0,
                version=meta["version"],
                tags=meta["tags"],
                desc=meta["desc"],
                official=meta["official"],
                error=err,
            )
        )

    return McpServerListResponse(
        servers=servers,
        total=len(servers),
        connected=connected,
        errors=errors,
    )
