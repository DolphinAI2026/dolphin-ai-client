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
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

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
