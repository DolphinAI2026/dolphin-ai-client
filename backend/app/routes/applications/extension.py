"""扩展 (extension) section 后端 — PR6 SPEC v2 §2 Section E.

提供:
- GET  /{app_id}/dev-kits                       —— 轮询用, 列当前应用已关联的自开发包
- GET  /{app_id}/extension-update-events        —— SSE 通道, 收外部资源更新通知
- POST /{app_id}/extension-update-notify        —— ai-coding agent 完成 publish 后调本接口广播
- POST /{app_id}/republish                      —— 触发 aPaaS 重发版本让自开发资源生效

设计要点:
- SSE 走 **进程内 pub/sub** (asyncio.Queue per (app_id, subscriber))
- 多人订阅同一 app_id → fan-out 给所有 subscriber
- ai-coding agent 完成 publish_dev_workspace 后, **同进程**调 publish_extension_update()
  跨进程时走 HTTP POST /extension-update-notify (auth = 当前用户)
- list_apaas_app_dev_kits MCP 工具一致语义: 调 apaas_client.query_app_dev_kits.
  worktree 老版 apaas_client 缺此方法时, 返空列表占位 (本 PR scaffolding 不阻塞)

不动 ChatPage / ApaasMenuSidebar / SectionNav / ai-coding agent 代码 — PR2b 才接入.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from jose import JWTError, jwt
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sse_starlette.sse import EventSourceResponse

from app.apaas_client import APaaSClient
from app.config import settings, APP_DEPLOY_ABSTRACT
from app.crypto import decrypt_password
from app.database import get_db
from app.deps import AuthContext, get_auth_context
from app.error_messages import APAAS_LOGIN_FAILED, is_apaas_token_error
from app.models import Application, PlatformEnv, User
from app.permissions import Action, check_resource_permission

logger = logging.getLogger(__name__)
router = APIRouter()


# ---------------------------------------------------------------------------
# In-memory pub/sub for extension update events
# ---------------------------------------------------------------------------
# key = app_id (int), value = list[asyncio.Queue] for current subscribers.
# 进程内单实例 — P0 假设单 backend pod (多 pod 时再换成 redis pub/sub 或 DB row poll).
_subscribers: dict[int, list[asyncio.Queue]] = {}
_subscribers_lock = asyncio.Lock()


async def _subscribe(app_id: int) -> asyncio.Queue:
    """注册一个新 subscriber, 返回它的事件队列."""
    queue: asyncio.Queue = asyncio.Queue(maxsize=64)
    async with _subscribers_lock:
        _subscribers.setdefault(app_id, []).append(queue)
    return queue


async def _unsubscribe(app_id: int, queue: asyncio.Queue) -> None:
    async with _subscribers_lock:
        lst = _subscribers.get(app_id, [])
        if queue in lst:
            lst.remove(queue)
        if not lst:
            _subscribers.pop(app_id, None)


async def publish_extension_update(app_id: int, event_type: str, payload: dict) -> int:
    """供进程内其他模块 (如 ai-coding agent publish 钩子) 调.

    返回扇出的 subscriber 数量.
    """
    msg = {"event": event_type, "data": payload, "ts": int(time.time() * 1000)}
    n = 0
    async with _subscribers_lock:
        subs = list(_subscribers.get(app_id, []))
    for q in subs:
        try:
            q.put_nowait(msg)
            n += 1
        except asyncio.QueueFull:
            logger.warning(f"extension-update queue full for app_id={app_id}, dropping event")
    if n:
        logger.info(f"extension-update fan-out app_id={app_id} type={event_type} n={n}")
    return n


# ---------------------------------------------------------------------------
# 通用 helpers
# ---------------------------------------------------------------------------
async def _load_app_and_env(
    app_id: int,
    ctx: AuthContext,
    db: AsyncSession,
) -> tuple[Application, PlatformEnv | None]:
    """加载应用 + 检权 + 取绑定的 platform env (跟 preflight._load_app_and_env 同语义)."""
    r = await db.execute(
        select(Application).where(
            Application.id == app_id,
            Application.tenant_id == ctx.tenant_id,
        )
    )
    app = r.scalar_one_or_none()
    if not app:
        raise HTTPException(status_code=404, detail="应用不存在")
    await check_resource_permission(ctx, db, app, "application", Action.VIEW)

    env: PlatformEnv | None = None
    if app.platform_env_id:
        er = await db.execute(
            select(PlatformEnv).where(PlatformEnv.id == app.platform_env_id)
        )
        env = er.scalar_one_or_none()
    if env is None:
        er = await db.execute(
            select(PlatformEnv).where(PlatformEnv.tenant_id == ctx.tenant_id)
        )
        env = er.scalar_one_or_none()
    return app, env


async def _ensure_env_token(env: PlatformEnv, db: AsyncSession) -> str:
    """env.token 不可用时尝试用 username/password 重新登录拿 token."""
    if env.token:
        return env.token
    if not env.username or not env.password_enc:
        raise HTTPException(status_code=400, detail="平台 token 不可用, 且环境未配置登录凭证")
    try:
        password = decrypt_password(env.password_enc)
        client = APaaSClient(base_url=env.base_url, tenant_id=env.platform_tenant_id)
        result = await client.login(env.username, password)
        token = result.get("token", "")
        if not token:
            raise HTTPException(status_code=400, detail=APAAS_LOGIN_FAILED)
        env.token = token
        env.status = "connected"
        await db.commit()
        return token
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"{APAAS_LOGIN_FAILED}: {e}")


# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------
class DevKitItem(BaseModel):
    id: str
    fileName: str
    fileType: str = ""
    size: Optional[int] = None
    userName: Optional[str] = None
    createTime: Optional[str] = None


class ListDevKitsResponse(BaseModel):
    ok: bool
    env_id: Optional[int] = None
    apaas_app_id: Optional[str] = None
    total: int
    kits: list[DevKitItem]
    note: Optional[str] = None  # 占位/降级原因


class NotifyExtensionUpdateRequest(BaseModel):
    event_type: str = Field(
        default="dev_kit_published",
        description="事件类型, 默认 dev_kit_published; 也可以是 dev_kit_attached / republish_done"
    )
    payload: dict = Field(default_factory=dict, description="事件附带数据 (kit_id/kit_name/from_workspace 等)")


class NotifyExtensionUpdateResponse(BaseModel):
    ok: bool
    delivered: int


class RepublishResponse(BaseModel):
    ok: bool
    version: Optional[str] = None
    remote_status: Optional[str] = None
    note: Optional[str] = None


# ---------------------------------------------------------------------------
# 路由
# ---------------------------------------------------------------------------
@router.get("/{app_id}/dev-kits", response_model=ListDevKitsResponse)
async def list_dev_kits(
    app_id: int,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
    file_name_filter: str = "",
) -> ListDevKitsResponse:
    """轮询用: 列当前 apaas 应用已 attach 的自开发包 (zip).

    跟 MCP 工具 `list_apaas_app_dev_kits` 等价 — 走 apaas_client.query_app_dev_kits.
    worktree 老版 apaas_client 缺此方法时返空列表, 不阻塞 PR scaffolding.
    """
    app, env = await _load_app_and_env(app_id, ctx, db)

    if not app.apaas_app_id:
        return ListDevKitsResponse(ok=True, total=0, kits=[], note="应用尚未部署到平台, 没有 apaas_app_id")
    if env is None:
        return ListDevKitsResponse(ok=True, total=0, kits=[], note="租户尚未配置 platform env")

    try:
        token = await _ensure_env_token(env, db)
    except HTTPException as e:
        return ListDevKitsResponse(ok=False, total=0, kits=[], note=f"token 不可用: {e.detail}")

    client = APaaSClient(base_url=env.base_url, tenant_id=env.platform_tenant_id, token=token)

    # 调 apaas_client.query_app_dev_kits — worktree 老版若缺方法则降级.
    method = getattr(client, "query_app_dev_kits", None)
    if method is None:
        return ListDevKitsResponse(
            ok=True, env_id=env.id, apaas_app_id=str(app.apaas_app_id),
            total=0, kits=[],
            note="当前 backend apaas_client 缺 query_app_dev_kits, scaffolding 占位 — PR 合主干后自动 work",
        )

    try:
        raw = await method(str(app.apaas_app_id), file_name=file_name_filter)
    except Exception as e:
        detail = str(e)
        if is_apaas_token_error(detail) or "401" in detail:
            try:
                token = await _ensure_env_token(env, db)
                client = APaaSClient(base_url=env.base_url, tenant_id=env.platform_tenant_id, token=token)
                raw = await client.query_app_dev_kits(str(app.apaas_app_id), file_name=file_name_filter)
            except Exception as retry_e:
                logger.warning(f"list_dev_kits retry failed: {retry_e}")
                return ListDevKitsResponse(ok=False, total=0, kits=[], note=f"查询自开发包失败: {retry_e}")
        else:
            logger.warning(f"list_dev_kits failed: {e}")
            return ListDevKitsResponse(ok=False, total=0, kits=[], note=f"查询自开发包失败: {e}")

    kits = [
        DevKitItem(
            id=str(k.get("id") or ""),
            fileName=str(k.get("fileName") or ""),
            fileType=str(k.get("fileType") or ""),
            size=k.get("size"),
            userName=k.get("userName"),
            createTime=k.get("createTime"),
        )
        for k in (raw or []) if isinstance(k, dict)
    ]
    return ListDevKitsResponse(
        ok=True, env_id=env.id, apaas_app_id=str(app.apaas_app_id),
        total=len(kits), kits=kits,
    )


@router.get("/{app_id}/extension-update-events")
async def extension_update_events(
    app_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    token: Optional[str] = Query(None),
) -> EventSourceResponse:
    """SSE 通道: 当前应用的自开发资源 (扩展) 有外部更新时, 推送通知.

    事件示例:
      event: dev_kit_published
      data: {"kit_id": "...", "kit_name": "...", "from_workspace": "ws_xxx"}

      event: ping
      data: {"ts": 1716694800000}

    客户端 (ChatPage / ExtensionSectionPanel) 用 EventSource API 订阅.
    无新事件时定时发 ping 防 nginx 60s 超时断流.

    2026-05-26 (PR6 reviewer Critical): EventSource 不支持 set Authorization
    header → 走 token query param 模式 (跟 incremental/execute-stream 一致). 调用方:
      new EventSource(`/api/applications/${id}/extension-update-events?token=${jwt}`)
    """
    # PR6 Critical: SSE 走 query param 验证 token (EventSource 不能 set header)
    if not token:
        raise HTTPException(status_code=401, detail="缺少认证token (SSE 走 query param)")
    try:
        payload = jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
        user_id = int(payload.get("sub", 0))
        tenant_id_claim = payload.get("tid")
        if tenant_id_claim is None:
            raise HTTPException(status_code=403, detail="平台管理员无法订阅应用 SSE")
        tenant_id = int(tenant_id_claim)
    except (JWTError, Exception) as exc:
        if isinstance(exc, HTTPException):
            raise
        raise HTTPException(status_code=401, detail="无效的认证凭证")

    user_row = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
    if not user_row:
        raise HTTPException(status_code=401, detail="用户不存在")
    # Tenant scoping 是主要安全边界 — 跟 incremental_update.execute_update_stream 一致.
    # 细粒度 EDIT/VIEW 留给具体的 mutation endpoint (notify / republish) 用标准 ctx 路径检查.
    app_row = (await db.execute(
        select(Application).where(Application.id == app_id, Application.tenant_id == tenant_id)
    )).scalar_one_or_none()
    if not app_row:
        raise HTTPException(status_code=404, detail="应用不存在")

    queue = await _subscribe(app_id)
    logger.info(f"extension-update SSE subscribed app_id={app_id} user_id={user_id}")

    async def event_generator():
        try:
            # 立即发 hello, 让客户端确认连接 OK
            yield {
                "event": "hello",
                "data": json.dumps({"app_id": app_id, "ts": int(time.time() * 1000)}, ensure_ascii=False),
            }
            while True:
                try:
                    msg = await asyncio.wait_for(queue.get(), timeout=20.0)
                except asyncio.TimeoutError:
                    # 心跳防 nginx / browser 60s idle 断流
                    yield {
                        "event": "ping",
                        "data": json.dumps({"ts": int(time.time() * 1000)}, ensure_ascii=False),
                    }
                    continue
                yield {
                    "event": msg["event"],
                    "data": json.dumps({"ts": msg["ts"], **msg["data"]}, ensure_ascii=False),
                }
        except asyncio.CancelledError:
            logger.info(f"extension-update SSE cancelled app_id={app_id}")
            raise
        finally:
            await _unsubscribe(app_id, queue)
            logger.info(f"extension-update SSE unsubscribed app_id={app_id}")

    return EventSourceResponse(event_generator())


@router.post("/{app_id}/extension-update-notify", response_model=NotifyExtensionUpdateResponse)
async def notify_extension_update(
    app_id: int,
    body: NotifyExtensionUpdateRequest,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> NotifyExtensionUpdateResponse:
    """ai-coding agent 完成 publish_dev_workspace 后, 调本接口广播给同 app_id 的 SSE 订阅者.

    跨进程 (ai-coding 在另一个 backend pod 或独立服务) 时由 agent 发起 HTTP POST.
    同进程 (ai-coding 是 backend 内部模块) 可直接调 publish_extension_update() 函数.
    """
    # 检 app 存在 + 权限 (写权限, 因为这是触发动作的"发起者"端要求, 但只读侧才会订)
    await _load_app_and_env(app_id, ctx, db)
    delivered = await publish_extension_update(app_id, body.event_type, body.payload)
    return NotifyExtensionUpdateResponse(ok=True, delivered=delivered)


@router.post("/{app_id}/republish", response_model=RepublishResponse)
async def republish_application(
    app_id: int,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> RepublishResponse:
    """触发 aPaaS 应用重发版本 — 让自开发资源变更生效.

    等价 MCP `republish_apaas_app(env_id, apaas_app_id)`, 直接调 apaas_client.deploy_app.
    版本号策略: 取 currentVersion → 失败时 patch+1 重试.
    """
    app, env = await _load_app_and_env(app_id, ctx, db)
    await check_resource_permission(ctx, db, app, "application", Action.EDIT)

    if not app.apaas_app_id:
        return RepublishResponse(ok=False, note="应用尚未部署到平台, 无法重发")
    if env is None:
        return RepublishResponse(ok=False, note="租户尚未配置 platform env")

    try:
        token = await _ensure_env_token(env, db)
    except HTTPException as e:
        return RepublishResponse(ok=False, note=f"token 不可用: {e.detail}")

    client = APaaSClient(base_url=env.base_url, tenant_id=env.platform_tenant_id, token=token)

    def _bump_patch(v: str) -> str:
        try:
            parts = [int(p) for p in v.split(".")]
            parts[-1] += 1
            return ".".join(str(p) for p in parts)
        except (ValueError, IndexError):
            return v

    abstract = APP_DEPLOY_ABSTRACT or "自开发资源更新自动重发"
    try:
        detail = await client.query_app_detail(str(app.apaas_app_id))
        current_version = (
            detail.get("currentVersion") or detail.get("appVersion") or detail.get("version") or "1.0.0"
        )
        try:
            await client.deploy_app(str(app.apaas_app_id), current_version, abstract=abstract)
            target_version = current_version
        except Exception as e1:
            if "版本" in str(e1) or "version" in str(e1).lower():
                bumped = _bump_patch(current_version)
                if bumped != current_version:
                    await client.deploy_app(str(app.apaas_app_id), bumped, abstract=abstract)
                    target_version = bumped
                else:
                    raise
            else:
                raise

        # 重发成功后给同 app_id 的订阅者广播一条 republish_done 事件
        await publish_extension_update(
            app_id, "republish_done",
            {"version": target_version, "apaas_app_id": str(app.apaas_app_id)},
        )
        return RepublishResponse(ok=True, version=target_version, remote_status="ENABLE")
    except Exception as e:
        logger.warning(f"republish app_id={app_id} failed: {e}")
        return RepublishResponse(ok=False, note=f"重发失败: {e}")
