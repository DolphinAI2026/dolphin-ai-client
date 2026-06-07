"""Dedicated standard MCP service for external support triage agents."""
from __future__ import annotations

import os

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

from app.support_triage_records import write_support_triage_record


_allowed_hosts = [h.strip() for h in (os.getenv("MCP_ALLOWED_HOSTS") or "").split(",") if h.strip()]
if _allowed_hosts:
    _security = TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=_allowed_hosts,
    )
else:
    _security = TransportSecuritySettings(enable_dns_rebinding_protection=False)

mcp = FastMCP(
    "support-triage",
    instructions=(
        "问题分诊记录 MCP。外部问题助手先判断用户问题属于操作问题、Bug、需求或待确认，"
        "再调用 record_support_triage 记录分类、原因、优先级和准备回复给用户的话。"
    ),
    transport_security=_security,
    stateless_http=True,
    json_response=True,
)


@mcp.tool()
async def record_support_triage(
    user_question: str,
    category: str,
    summary: str,
    reason: str,
    user_reply: str,
    confidence: str = "中",
    missing_info: str = "",
    priority: str = "P2",
    status: str = "新建",
    source: str = "external_agent",
    tenant_id: int = 0,
    user_id: int = 0,
) -> dict:
    """记录用户问题分诊结果。

    category 取值：操作问题 / Bug / 需求 / 待确认。
    本工具只记录分类、判断原因和给用户的回复，不会创建工单、改代码或部署。
    """
    return write_support_triage_record(
        user_question=user_question,
        category=category,
        summary=summary,
        reason=reason,
        user_reply=user_reply,
        confidence=confidence,
        missing_info=missing_info,
        priority=priority,
        status=status,
        source=source,
        tenant_id=tenant_id,
        user_id=user_id,
    )
