"""维护「当前用户在 ai-builder 中正在编辑哪个应用」的状态。

用途：dolphin agent 通过 MCP 工具调过来时，agent 可以省略 app_id 参数 ——
ai-builder MCP server 用 user_id 反查这里的状态拿到 app_id。

实现：进程内字典（同一 backend 进程下所有请求共享）。生产多实例需换 redis，但
trial 单实例够用。条目 30 分钟自动过期。
"""
from __future__ import annotations

import time
from threading import RLock
from typing import Annotated, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.deps import AuthContext, get_auth_context

router = APIRouter(prefix="/builder", tags=["current-app"])


# user_id → (app_id, app_name, ts)
_STATE: dict[int, tuple[int, str, float]] = {}
_LOCK = RLock()
_TTL_SECONDS = 30 * 60


def get_current_app_for_user(user_id: int) -> Optional[tuple[int, str]]:
    """供 mcp_server.py 调用，反查用户当前编辑的应用。"""
    with _LOCK:
        rec = _STATE.get(user_id)
        if not rec:
            return None
        app_id, app_name, ts = rec
        if time.time() - ts > _TTL_SECONDS:
            _STATE.pop(user_id, None)
            return None
        return (app_id, app_name)


def set_current_app_for_user(user_id: int, app_id: int, app_name: str) -> None:
    with _LOCK:
        _STATE[user_id] = (app_id, app_name, time.time())


def clear_current_app_for_user(user_id: int) -> None:
    with _LOCK:
        _STATE.pop(user_id, None)


class SetCurrentAppRequest(BaseModel):
    app_id: int
    app_name: str = ""


@router.post("/current-app")
async def set_current_app(
    req: SetCurrentAppRequest,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
):
    """前端 ChatPage 进来或切应用时调一次，告诉后端"我现在在编辑 app_id=X"。"""
    set_current_app_for_user(ctx.user.id, req.app_id, req.app_name)
    return {"ok": True, "user_id": ctx.user.id, "app_id": req.app_id}


@router.delete("/current-app")
async def clear_current_app(
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
):
    clear_current_app_for_user(ctx.user.id)
    return {"ok": True}


@router.get("/current-app")
async def get_current_app(
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
):
    rec = get_current_app_for_user(ctx.user.id)
    if not rec:
        return {"ok": True, "app_id": None, "app_name": ""}
    return {"ok": True, "app_id": rec[0], "app_name": rec[1]}
