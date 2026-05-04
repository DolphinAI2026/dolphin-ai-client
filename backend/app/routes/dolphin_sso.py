"""Dolphin Agent 平台 SSO 配置中转 endpoint。

为什么有这个 endpoint：
- HelpAssistant 浮窗 + 内嵌 dolphin chat 都需要 dolphin 的 access token 才能初始化
- 之前 token 写在 frontend/.env 的 VITE_DOLPHIN_JWT 里 → 进 build artifact，谁拿到前端代码都能看到
- 改成：ai-builder 用户登录后向后端要，token 永远不进前端 build

实现：
- 每个 ai-builder 用户在 dolphin trial 同租户下镜像出独立账号（DolphinUserLink）
- /dolphin/config 返该用户镜像账号的 access_token —— 浮窗 / iframe 看到独立身份
- 会话历史 / 项目按用户隔离，不再都挂在 dolphin admin 名下

注意：dolphin → ai-builder MCP 调用还是带固定 service_token（自定义 Body 字段
注入 user_id=1 / tenant_id=1），mcp _resolve_identity 从 current_app slot 反查。
多 ai-builder 用户并发操作不同应用时，slot 会互相覆盖（trial 限制）。
"""
from __future__ import annotations

import logging
from typing import Annotated, Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.deps import AuthContext, get_auth_context
from app.services.dolphin_user import get_user_dolphin_credentials

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/dolphin", tags=["dolphin-sso"])


@router.get("/config")
async def get_dolphin_config(
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """前端登录后调一次拿 dolphin SDK 初始化所需配置。

    返回当前 ai-builder 用户**在 dolphin 镜像账号**的 access_token —— 浮窗里
    看到的会话历史、项目都属于这个用户，不会跨用户共享。
    """
    if not settings.dolphin_service_token:
        raise HTTPException(
            status_code=503,
            detail="Dolphin SSO 未配置。请在 backend/.env 设置 DOLPHIN_SERVICE_TOKEN。",
        )

    try:
        access_token, dolphin_uid = await get_user_dolphin_credentials(db, ctx.user)
    except Exception as exc:
        logger.error("dolphin 镜像账号颁 token 失败 user=%s: %s", ctx.user.id, exc)
        raise HTTPException(status_code=502, detail=f"dolphin 镜像账号失败：{str(exc)[:200]}")

    return {
        "server_url": settings.dolphin_server_url,
        "agent_code": settings.dolphin_agent_code,
        "app_adjust_agent_code": settings.dolphin_app_adjust_agent_code,
        "tenant_id": settings.dolphin_tenant_id,
        "access_token": access_token,
        "dolphin_user_id": dolphin_uid,
    }


# (user_id, app_id) → dolphin project_id 映射，进程内缓存
# 生产多实例时换 redis；trial 单实例够用
from threading import RLock as _RLock
_PROJECT_MAP: dict[tuple[int, int], int] = {}
_PROJECT_MAP_LOCK = _RLock()
# dolphin agent code → dolphin agent db_id (用于创建项目)
# 简化：trial 只用一个 agent (a73e75cd81 → 80)，硬编码兜底
_DOLPHIN_AGENT_DB_ID_DEFAULT = 80


async def _ensure_dolphin_project(
    *,
    user_id: int,
    app_id: int,
    app_name: str,
    server_url: str,
    user_token: str,
    agent_db_id: int = _DOLPHIN_AGENT_DB_ID_DEFAULT,
) -> Optional[int]:
    """返回该 (user, app) 的 dolphin project_id；没有就用该用户的 token 创建。

    用 user_token 而非 service_token 调用 — 这样项目归属该 dolphin 用户名下，
    侧边栏看到的"项目"只属于自己。
    """
    key = (int(user_id), int(app_id))
    with _PROJECT_MAP_LOCK:
        cached = _PROJECT_MAP.get(key)
    if cached:
        return cached

    title = f"应用 #{app_id}"
    if app_name:
        title = f"{title} · {app_name}"

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                f"{server_url.rstrip('/')}/api/agents/agent/projects",
                json={"agent_id": agent_db_id, "name": title[:60]},
                headers={
                    "Authorization": f"Bearer {user_token}",
                    "Content-Type": "application/json",
                },
            )
            if resp.status_code in (200, 201):
                data = resp.json()
                pid = data.get("id") or (data.get("data") or {}).get("id")
                if pid:
                    with _PROJECT_MAP_LOCK:
                        _PROJECT_MAP[key] = int(pid)
                    return int(pid)
            else:
                logger.warning("dolphin create project HTTP %d: %s", resp.status_code, resp.text[:200])
    except Exception as exc:
        logger.warning("dolphin create project failed: %s", exc)
    return None


class InitContextRequest(BaseModel):
    app_id: int
    app_name: str = ""
    agent_code: Optional[str] = None  # 默认用 app_adjust_agent_code


@router.post("/init-app-context")
async def init_app_context_session(
    req: InitContextRequest,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """前端进 ChatPage 时调一次：用**当前 ai-builder 用户的 dolphin 镜像账号 token**
    在 dolphin agent 里发一条隐藏 [SYSTEM CTX] 消息 → dolphin 该用户最近 session
    就是含上下文的新 session。iframe 加载时 dolphin embed resume 这个 session，
    agent 已经知道当前应用，不会再问"哪个应用"。

    每个 ai-builder 用户在 dolphin 是独立账号，session / project 都按用户隔离。
    """
    agent_code = req.agent_code or settings.dolphin_app_adjust_agent_code
    if not agent_code:
        raise HTTPException(status_code=503, detail="dolphin app_adjust_agent_code 未配置")

    # 拿当前用户在 dolphin 镜像账号的 token（没有就创建）
    try:
        user_token, _dolphin_uid = await get_user_dolphin_credentials(db, ctx.user)
    except Exception as exc:
        logger.error("init-app-context 颁 dolphin token 失败 user=%s: %s", ctx.user.id, exc)
        raise HTTPException(status_code=502, detail=f"dolphin 镜像账号失败：{str(exc)[:200]}")

    # 构造 ctx 消息 — agent prompt 里教过看到 [SYSTEM CTX] 开头就简短确认不展开
    ctx_msg = (
        f"[SYSTEM CTX] 用户当前在 ai-builder 编辑应用 #{req.app_id}"
        + (f"（{req.app_name}）" if req.app_name else "")
        + "。后续对话中调任何 MCP 工具时不必显式传 app_id，后端会自动用这个应用。"
        + "请用一句话简短确认上下文已锁定到这个应用。"
    )

    # ★ 关键：先把 current_app state 写好（用本请求的 app_id），保证 mcp 工具调用
    # 反查时一定拿到当前 app，不依赖前端 ChatPage syncCurrentAppToBackend 的时序。
    # 否则切 app 时 sync 还在路上，agent 调 mcp 拿到的是上一个 app 的 state，
    # 跨应用污染（agent 把 A 应用的内容上传到 B 应用）。
    from app.routes.current_app import set_current_app as _set_current_app
    _set_current_app(ctx.user.id, ctx.tenant_id, req.app_id, req.app_name)

    # 给当前 (user, app) 拿/创 dolphin 项目（用用户 token，project 归该用户）
    project_id = await _ensure_dolphin_project(
        user_id=ctx.user.id,
        app_id=req.app_id,
        app_name=req.app_name,
        server_url=settings.dolphin_server_url,
        user_token=user_token,
    )

    url = f"{settings.dolphin_server_url.rstrip('/')}/api/agentChat/agent/run/chat/{agent_code}"
    session_id = ""
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            # dolphin chat send 是流式响应，我们只关心 sessionid header（响应一开始就发）
            chat_body: dict = {"input": ctx_msg, "budget_preset": "complex"}
            if project_id:
                chat_body["project_id"] = project_id
            async with client.stream(
                "POST",
                url,
                json=chat_body,
                headers={
                    "Authorization": f"Bearer {user_token}",
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

    return {"ok": True, "session_id": session_id, "agent_code": agent_code, "project_id": project_id}
