"""维护「ai-builder 用户 → 当前编辑应用 + 真实身份」的状态。

用途
====
外部 agent 通过 MCP 工具调过来时，agent 可以省略 app_id 参数 —— ai-builder
MCP server 反查这里的状态拿到真实 app_id。同时 _resolve_identity 用此 slot
把外部 agent 传过来的 user_id 反查成 (tenant_id, app_id, app_name)。

设计变更（2026-05-09 v2 · stop bleed）
======================================
**之前（v1）**：slot 是全局单 key（GLOBAL_USER_SLOT=1），所有 ai-builder 用户的
set_current_app 都覆盖到这个 key。外部 agent 传 user_id=0 时 _resolve_identity 默
认查 user 1 的 slot —— 实际效果：所有 MCP 客户端 chat 调用都拿 admin 的 slot 数据，
跨租户数据泄漏（截图实证：宝洁 li.l.77 通过 外部 agent 调 list_platform_envs
拿到 admin 租户 18 个环境）。

**现在（v2）**：slot 按 ai-builder real_user_id 严格分 key。每个 user 自己一格，
互不污染。agent 调 MCP 工具时**必须**明确传 user_id（依赖 外部 agent prompt
从 [SYSTEM CTX 用户身份锚点] 读取并传过来），否则 _resolve_identity 直接 raise
拒绝调用。

实现
====
进程内字典（同一 backend 进程下所有请求共享）。多进程 / 多实例需换 redis。
"""
from __future__ import annotations

import time
from threading import RLock
from typing import Annotated, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.deps import AuthContext, get_auth_context

router = APIRouter(prefix="/builder", tags=["current-app"])


# real_user_id → (real_tenant_id, app_id, app_name, ts)
# 注意：之前 v1 是全局单 key (GLOBAL_USER_SLOT=1)，现在按 real_user_id 分 key
_STATE: dict[int, tuple[int, int, str, float]] = {}
_LOCK = RLock()
_TTL_SECONDS = 30 * 60


# 2026-05-10：aPaaS user_id → ai-builder 本地 (User.id, default tenant_id) 反查缓存。
# 背景：MCP 客户端 chat MCP 调用时 caller 透传的 user_id 是 aPaaS 大整数（21 位 bigint），
# 而 ai-builder 本地 User.id 是小整数自增。slot _STATE 是按本地 User.id 分 key 写入的
# （登录 _prime_slot 那条），agent 用 aPaaS user_id 做查询永远 miss → fallback 用
# aPaaS 大整数签 JWT → 本地 backend get_auth_context 查不到 User → 401。
# alias 缓存 + DB 反查解决这条断链：apaas_uid → local (uid, tid)。
_APAAS_USER_CACHE: dict[int, tuple[int, int, float]] = {}


def get_current_app_for_user(real_user_id: int) -> Optional[tuple[int, int, int, str]]:
    """取某 ai-builder 用户当前编辑的应用 + 真实 (user_id, tenant_id) 元组。

    返回 (real_user_id, real_tenant_id, app_id, app_name) 或 None。
    返回元组保留 v1 接口（4 元素），方便 mcp_server.py 那边代码不动。
    """
    if not real_user_id or real_user_id <= 0:
        return None
    with _LOCK:
        rec = _STATE.get(int(real_user_id))
        if not rec:
            return None
        real_tid, app_id, app_name, ts = rec
        if time.time() - ts > _TTL_SECONDS:
            _STATE.pop(int(real_user_id), None)
            return None
        return (int(real_user_id), int(real_tid), int(app_id), app_name)


def set_current_app(real_user_id: int, real_tenant_id: int, app_id: int, app_name: str) -> None:
    """登录或切应用时调一次写入 slot。app_id=0 表示用户已登录但未打开具体应用 ——
    仍然写入 slot 是为了让 MCP 客户端 chat 调 MCP 工具时能用 user_id 反查 tenant_id。"""
    if not real_user_id or real_user_id <= 0:
        return
    with _LOCK:
        _STATE[int(real_user_id)] = (int(real_tenant_id), int(app_id or 0), app_name or "", time.time())


def clear_current_app(real_user_id: int) -> None:
    if not real_user_id or real_user_id <= 0:
        return
    with _LOCK:
        _STATE.pop(int(real_user_id), None)


# ── apaas_uid → local (uid, tid) 反查 alias ────────────────────────────────
def set_apaas_user_alias(apaas_uid: int | str, local_uid: int, local_tid: int) -> None:
    """登录或 DB 反查命中后写入 alias，下次 MCP 调用走 cache 不打 DB。"""
    try:
        au = int(apaas_uid) if apaas_uid else 0
    except Exception:
        return
    if au <= 0 or not local_uid or local_uid <= 0:
        return
    with _LOCK:
        _APAAS_USER_CACHE[au] = (int(local_uid), int(local_tid or 0), time.time())


def resolve_apaas_user_alias(apaas_uid: int) -> Optional[tuple[int, int]]:
    """apaas_uid → (local_uid, local_tid) 或 None（未缓存 / 已过期）。"""
    if not apaas_uid or apaas_uid <= 0:
        return None
    with _LOCK:
        rec = _APAAS_USER_CACHE.get(int(apaas_uid))
        if not rec:
            return None
        local_uid, local_tid, ts = rec
        if time.time() - ts > _TTL_SECONDS:
            _APAAS_USER_CACHE.pop(int(apaas_uid), None)
            return None
        return (int(local_uid), int(local_tid))


class SetCurrentAppRequest(BaseModel):
    app_id: int
    app_name: str = ""


@router.post("/current-app")
async def set_current_app_endpoint(
    req: SetCurrentAppRequest,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
):
    """前端进入应用编辑页时调一次，告诉后端"我现在在编辑 app_id=X"。
    state 里同时记录用户真实 (user_id, tenant_id)，给外部 agent 调 mcp 时反查用。"""
    set_current_app(ctx.user.id, ctx.tenant_id, req.app_id, req.app_name)
    return {"ok": True, "user_id": ctx.user.id, "tenant_id": ctx.tenant_id, "app_id": req.app_id}


@router.delete("/current-app")
async def clear_current_app_endpoint(
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
):
    clear_current_app(ctx.user.id)
    return {"ok": True}


@router.get("/current-app")
async def get_current_app_endpoint(
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
):
    rec = get_current_app_for_user(ctx.user.id)
    if not rec:
        return {"ok": True, "app_id": None, "app_name": ""}
    real_uid, real_tid, app_id, app_name = rec
    return {"ok": True, "app_id": app_id, "app_name": app_name, "real_user_id": real_uid, "real_tenant_id": real_tid}
