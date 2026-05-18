"""MCP Hub — server-grouped view for the v2 /mcp page.

Returns MCP servers with status, transport, tool count, official flag.
Sources: hub-config table (configured servers) + live status from v2 proxy.
"""
from __future__ import annotations

import logging
from typing import Annotated, Optional
from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.deps import get_auth_context, AuthContext

logger = logging.getLogger(__name__)

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


# For now, seed registry; later this becomes a DB-backed table.
_REGISTRY: list[McpServer] = [
    McpServer(
        id="mcp-1", name="得帆云 aPaaS Tools", code="apaas-tools",
        status="connected", transport="sse",
        endpoint="https://apaas-poc.definesys.cn/mcp/sse",
        tools=14, last_used="2 分钟前", usage=824, version="2.3.1",
        tags=["官方", "应用配置", "部署"],
        desc="官方 MCP，提供应用 / 模型 / 表单 / 权限 / 部署等 14 个工具。",
        official=True,
    ),
    McpServer(
        id="mcp-2", name="组件市场检索", code="marketplace-search",
        status="connected", transport="sse",
        endpoint="https://agent.dfy.definesys.cn/mcp/marketplace",
        tools=5, last_used="昨天 16:08", usage=312, version="1.0.4",
        tags=["官方", "组件"],
        desc="在 AI Coding 中按需检索组件市场已有产物，避免重复开发。",
        official=True,
    ),
    McpServer(
        id="mcp-3", name="需求文档检索（飞书）", code="feishu-docs",
        status="connected", transport="http",
        endpoint="https://internal-mcp.demo/feishu",
        tools=3, last_used="今天 11:30", usage=142, version="0.4.2",
        tags=["自定义", "文档"],
        desc="把租户飞书空间里的设计文档作为上下文喂给 AI。",
        official=False,
    ),
    McpServer(
        id="mcp-4", name="内部 ERP 字段映射", code="erp-fields",
        status="error", transport="stdio",
        endpoint="erp-bridge://localhost",
        tools=8, last_used="4 小时前", usage=56, version="0.2.0",
        tags=["自定义", "ERP"],
        desc="把内部 ERP 系统的字段定义映射到 aPaaS 数据模型字段。",
        official=False,
        error="连接超时（10s），请检查 erp-bridge 是否启动。",
    ),
    McpServer(
        id="mcp-5", name="生产工单 SOP 库", code="sop-library",
        status="disabled", transport="sse",
        endpoint="https://internal-mcp.demo/sop",
        tools=6, last_used="5 天前", usage=18, version="0.1.1",
        tags=["自定义", "制造"],
        desc="提供生产 SOP 检索能力，给智能搭建生成流程时引用。",
        official=False,
    ),
    McpServer(
        id="mcp-6", name="GitHub Repo 检索", code="github-search",
        status="connected", transport="http",
        endpoint="https://mcp.github.com",
        tools=4, last_used="3 天前", usage=6, version="1.2.0",
        tags=["第三方", "代码"],
        desc="为 Vibe Coding 模式提供跨仓库代码检索能力。",
        official=False,
    ),
    McpServer(
        id="mcp-7", name="钉钉审批联动", code="dingtalk-approval",
        status="connected", transport="http",
        endpoint="https://oapi.dingtalk.com/mcp",
        tools=7, last_used="昨天", usage=92, version="0.6.0",
        tags=["自定义", "审批"],
        desc="在搭建审批流程时直接挂载钉钉审批节点。",
        official=False,
    ),
    McpServer(
        id="mcp-8", name="内部知识库（私有）", code="kb-private",
        status="connected", transport="sse",
        endpoint="https://kb.internal.demo/mcp",
        tools=2, last_used="今天 09:14", usage=248, version="1.5.0",
        tags=["自定义", "知识库"],
        desc="租户私有知识库，向量检索 + 全文检索。",
        official=False,
    ),
]


@router.get("/servers", response_model=McpServerListResponse)
async def list_servers(
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
):
    """List MCP servers visible to this tenant. Today returns the registry; later filters by tenant binding."""
    servers = _REGISTRY
    connected = sum(1 for s in servers if s.status == "connected")
    errors = sum(1 for s in servers if s.status == "error")
    return McpServerListResponse(
        servers=servers, total=len(servers),
        connected=connected, errors=errors,
    )
