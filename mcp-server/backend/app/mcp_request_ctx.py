"""MCP 请求级上下文 —— 由 _McpAuthMiddleware 装填，工具读取。

Phase 3 / 2026-05-10 设计：MCP 工具不再依赖 caller-trusted `user_id` / `tenant_id`
参数（dolphin agent 可篡改）。新路径：HTTP middleware 从 Authorization 头解
ai-builder JWT，把双 ID 装到 ContextVar；工具内通过 get_mcp_ctx() 拿，零参数依赖。

兼容：老 caller-trusted 参数路径仍走 _resolve_identity 兜底（dolphin SDK 当前
透传 user_id 参数的老 prompt 还在跑），但每次命中打 deprecation INFO log。
"""
from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass
from typing import Optional


@dataclass
class McpRequestCtx:
    """从 ai-builder JWT 解出来的请求级身份（已经过 JWT 验签 + DB 校验）。"""
    local_user_id: int
    local_tenant_id: int
    apaas_token: Optional[str] = None
    apaas_user_id: Optional[str] = None
    apaas_tenant_id: Optional[str] = None
    username: Optional[str] = None
    auth_source: str = "ai_builder_jwt"
    # auth_source: "ai_builder_jwt" | "apaas_token_exchange" | "apaas_user_token" | "platform_api_key"


_current_ctx: ContextVar[Optional[McpRequestCtx]] = ContextVar("mcp_request_ctx", default=None)


def set_mcp_ctx(ctx: Optional[McpRequestCtx]):
    """装 ctx，返回 token 用于 reset（FastAPI 用 contextvars.copy_context 隔离请求间）"""
    return _current_ctx.set(ctx)


def reset_mcp_ctx(token):
    _current_ctx.reset(token)


def get_mcp_ctx() -> Optional[McpRequestCtx]:
    return _current_ctx.get()
