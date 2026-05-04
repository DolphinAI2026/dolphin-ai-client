"""维护「当前用户在 ai-builder 中正在编辑哪个应用」的状态。

用途：dolphin agent 通过 MCP 工具调过来时，agent 可以省略 app_id 参数 ——
ai-builder MCP server 反查这里的状态拿到真实 app_id + 用户身份。

注意：dolphin 自定义 Body 字段硬编码 tenant_id=1, user_id=1（dolphin 平台只有
admin 一个用户），但 ai-builder 这边用户多租户多账号，每个用户在自己租户下有
应用。所以 mcp 工具不能直接用 dolphin 传的 (1, 1) — 必须从这里的 state 反查
出 ai-builder **真实**的 (user_id, tenant_id)，否则就操作错租户的应用了。

实现：进程内字典（同一 backend 进程下所有请求共享）。trial 单实例 + 单管理员
场景下用 dolphin user_id (1) 当固定 key（state 全局只有一条），任何 ai-builder
用户调 set 都覆盖这个 slot。多用户并发会互相覆盖，trial 不考虑。生产多实例
需换 redis + 改 dolphin 端按用户注入 user_id。
"""
from __future__ import annotations

import time
from threading import RLock
from typing import Annotated, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.deps import AuthContext, get_auth_context

router = APIRouter(prefix="/builder", tags=["current-app"])


# 固定 slot key — dolphin 自定义 Body 字段永远注入 user_id=1
DOLPHIN_USER_SLOT = 1

# slot → (real_user_id, real_tenant_id, app_id, app_name, ts)
_STATE: dict[int, tuple[int, int, int, str, float]] = {}
_LOCK = RLock()
_TTL_SECONDS = 30 * 60


def get_current_app_for_user(dolphin_user_id: int) -> Optional[tuple[int, int, int, str]]:
    """供 mcp_server.py 调用：dolphin 传过来的 user_id（恒为 1）→
    返回 (real_user_id, real_tenant_id, app_id, app_name)。"""
    with _LOCK:
        rec = _STATE.get(DOLPHIN_USER_SLOT)
        if not rec:
            return None
        real_uid, real_tid, app_id, app_name, ts = rec
        if time.time() - ts > _TTL_SECONDS:
            _STATE.pop(DOLPHIN_USER_SLOT, None)
            return None
        return (real_uid, real_tid, app_id, app_name)


def set_current_app(real_user_id: int, real_tenant_id: int, app_id: int, app_name: str) -> None:
    with _LOCK:
        _STATE[DOLPHIN_USER_SLOT] = (real_user_id, real_tenant_id, app_id, app_name, time.time())


def clear_current_app() -> None:
    with _LOCK:
        _STATE.pop(DOLPHIN_USER_SLOT, None)


class SetCurrentAppRequest(BaseModel):
    app_id: int
    app_name: str = ""


@router.post("/current-app")
async def set_current_app_endpoint(
    req: SetCurrentAppRequest,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
):
    """前端 ChatPage 进来或切应用时调一次，告诉后端"我现在在编辑 app_id=X"。
    state 里同时记录用户真实 (user_id, tenant_id)，给 dolphin 调 mcp 时反查用。"""
    set_current_app(ctx.user.id, ctx.tenant_id, req.app_id, req.app_name)
    return {"ok": True, "user_id": ctx.user.id, "tenant_id": ctx.tenant_id, "app_id": req.app_id}


@router.delete("/current-app")
async def clear_current_app_endpoint(
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
):
    clear_current_app()
    return {"ok": True}


@router.get("/current-app")
async def get_current_app_endpoint(
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
):
    rec = get_current_app_for_user(DOLPHIN_USER_SLOT)
    if not rec:
        return {"ok": True, "app_id": None, "app_name": ""}
    real_uid, real_tid, app_id, app_name = rec
    return {"ok": True, "app_id": app_id, "app_name": app_name, "real_user_id": real_uid, "real_tenant_id": real_tid}
