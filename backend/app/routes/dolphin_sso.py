"""Dolphin Agent 平台 SSO 配置中转 endpoint。

为什么有这个 endpoint：
- HelpAssistant 浮窗 + 内嵌 dolphin chat 都需要 dolphin 的 access token 才能初始化
- 之前 token 写在 frontend/.env 的 VITE_DOLPHIN_JWT 里 → 进 build artifact，谁拿到前端代码都能看到
- 改成：ai-builder 用户登录后向后端要，token 永远不进前端 build

当前实现（trial 限制）：
- 所有 ai-builder 用户共用一个 dolphin service token（settings.dolphin_service_token）
- dolphin 那边看到的是同一个 admin 身份；会话历史/quota 不分用户
- TODO（待 dolphin 提供 user-impersonate / token-exchange API）：
  按 ai-builder 用户颁发独立的 dolphin 短期 token

未来扩展点已经预留：返回结构里只有 access_token，前端不假设它怎么生成的。
"""
from __future__ import annotations

import logging
from typing import Annotated, Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.config import settings
from app.deps import AuthContext, get_auth_context

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/dolphin", tags=["dolphin-sso"])


@router.get("/config")
async def get_dolphin_config(
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
):
    """前端登录后调一次拿 dolphin SDK 初始化所需配置。

    需要 ai-builder 登录态。返回：
    - server_url：dolphin 平台公网地址
    - agent_code：默认嵌入的 agent code
    - tenant_id：dolphin 租户 ID
    - access_token：dolphin 用户身份 token（当前阶段是 service token）
    """
    if not settings.dolphin_service_token:
        raise HTTPException(
            status_code=503,
            detail="Dolphin SSO 未配置。请在 backend/.env 设置 DOLPHIN_SERVICE_TOKEN。",
        )

    # TODO: 当 dolphin 提供 token-exchange API 时改为：
    # access_token = await exchange_dolphin_user_token(
    #     service_token=settings.dolphin_service_token,
    #     external_user_id=ctx.user.id,
    #     external_username=ctx.user.username,
    # )
    access_token = settings.dolphin_service_token

    return {
        "server_url": settings.dolphin_server_url,
        "agent_code": settings.dolphin_agent_code,
        "app_adjust_agent_code": settings.dolphin_app_adjust_agent_code,
        "tenant_id": settings.dolphin_tenant_id,
        "access_token": access_token,
    }


class InitContextRequest(BaseModel):
    app_id: int
    app_name: str = ""
    agent_code: Optional[str] = None  # 默认用 app_adjust_agent_code


@router.post("/init-app-context")
async def init_app_context_session(
    req: InitContextRequest,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
):
    """前端进 ChatPage 时调一次：用 dolphin service token 在 dolphin agent
    里发一条隐藏 [系统] ctx 消息，让 dolphin user 的"最近 session"是含
    上下文的新 session。然后 iframe 加载时 dolphin embed resume 这个
    session，agent 已经知道当前应用，不会再问"哪个应用"。

    dolphin chat send 不带 sessionid header 时会创建新 session，所以
    每次进 ChatPage 都开新 session（注入新 ctx），不会污染老对话。
    """
    if not settings.dolphin_service_token:
        raise HTTPException(status_code=503, detail="DOLPHIN_SERVICE_TOKEN 未配置")
    agent_code = req.agent_code or settings.dolphin_app_adjust_agent_code
    if not agent_code:
        raise HTTPException(status_code=503, detail="dolphin app_adjust_agent_code 未配置")

    # 构造 ctx 消息 — agent prompt 里教过看到 [SYSTEM CTX] 开头就简短确认不展开
    ctx_msg = (
        f"[SYSTEM CTX] 用户当前在 ai-builder 编辑应用 #{req.app_id}"
        + (f"（{req.app_name}）" if req.app_name else "")
        + "。后续对话中调任何 MCP 工具时不必显式传 app_id，后端会自动用这个应用。"
        + "请用一句话简短确认上下文已锁定到这个应用。"
    )

    url = f"{settings.dolphin_server_url.rstrip('/')}/api/agentChat/agent/run/chat/{agent_code}"
    session_id = ""
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            # dolphin chat send 是流式响应，我们只关心 sessionid header（响应一开始就发）
            async with client.stream(
                "POST",
                url,
                json={"input": ctx_msg, "budget_preset": "complex"},
                headers={
                    "Authorization": f"Bearer {settings.dolphin_service_token}",
                    "Content-Type": "application/json",
                    "X-Tenant-Id": settings.dolphin_tenant_id or "default",
                },
            ) as resp:
                session_id = resp.headers.get("sessionid", "")
                # 消费一段流让 dolphin 真正写 session 历史，但不等完整回复
                # （限 5s 否则放弃）
                import asyncio as _asyncio
                async def _consume():
                    async for _ in resp.aiter_bytes():
                        pass
                try:
                    await _asyncio.wait_for(_consume(), timeout=5.0)
                except _asyncio.TimeoutError:
                    pass
    except Exception as exc:
        logger.warning("init-app-context failed: %s", exc)
        # 不阻塞前端 — 即使 ctx 注入失败 iframe 仍可正常使用
        return {"ok": False, "error": str(exc)[:200]}

    return {"ok": True, "session_id": session_id, "agent_code": agent_code}
