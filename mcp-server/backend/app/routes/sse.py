"""SSE（Server-Sent Events）订阅路由。

架构文档 § 4.3 / § 4.4：
- GET /api/sse/conversation/{id}?last_seen_seq=N
- 前端用 EventSource 订阅
- 每条事件格式：`data: {json}\\n\\n`
- 断线重连：客户端维护 lastSeenSeq，重连时带上，后端补发历史 + 接实时流

事件消费者约定：
- seq 单调递增，客户端跳号即提示需重连
- 心跳：每 15 秒发一个 `event: heartbeat\\ndata: {}\\n\\n` 保活
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Annotated, AsyncIterator

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.db_publisher import get_db_publisher
from app.database import AsyncSessionLocal, get_db
from app.deps import AuthContext, get_auth_context, get_auth_context_from_token
from app.models import Conversation

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/sse", tags=["SSE"])


HEARTBEAT_INTERVAL_SECONDS = 15
"""无事件时每 N 秒发 heartbeat 保活（防中间代理/浏览器超时断线）"""


# ══════════════════════════════════════════════════════════════
# 辅助
# ══════════════════════════════════════════════════════════════

def _format_sse(event: dict, *, event_name: str | None = None) -> str:
    """把一个事件字典序列化为 SSE wire format。

    - 默认不带 event 名（客户端 EventSource 监听 'message' 或统一 onmessage）
    - 心跳加 event: heartbeat，客户端可过滤掉
    """
    lines: list[str] = []
    if event_name:
        lines.append(f"event: {event_name}")
    lines.append(f"id: {event.get('seq', 0)}")
    lines.append(f"data: {json.dumps(event, ensure_ascii=False)}")
    lines.append("")  # 空行分隔
    return "\n".join(lines) + "\n"


async def _assert_conversation_access(
    db: AsyncSession, conversation_id: int, ctx: AuthContext,
) -> Conversation:
    conv = await db.get(Conversation, conversation_id)
    if not conv:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"conversation {conversation_id} not found")
    if conv.tenant_id != ctx.tenant_id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "tenant mismatch")
    return conv


async def _sse_auth(request: Request) -> AuthContext:
    """SSE 专用鉴权：优先从 Authorization header 读 Bearer token，
    否则从 query 参数 `?token=...` 读。

    EventSource API 原生不支持自定义 header，所以 query 是 SSE 必需的后备通道。
    """
    # header 优先
    auth_header = request.headers.get("authorization") or request.headers.get("Authorization")
    token: str | None = None
    if auth_header and auth_header.lower().startswith("bearer "):
        token = auth_header.split(None, 1)[1].strip()
    # query fallback
    if not token:
        token = request.query_params.get("token")
    if not token:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "缺少认证 token（header 或 ?token= 均可）",
        )
    try:
        return await get_auth_context_from_token(token)
    except Exception:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "无效的 token")


# ══════════════════════════════════════════════════════════════
# GET /sse/conversation/{id}
# ══════════════════════════════════════════════════════════════

@router.get("/conversation/{conversation_id}")
async def sse_subscribe_conversation(
    conversation_id: int,
    ctx: Annotated[AuthContext, Depends(_sse_auth)],
    last_seen_seq: int = Query(0, ge=0, description="上次收到的 seq；用于断线重连补发"),
    heartbeat_seconds: int = Query(
        HEARTBEAT_INTERVAL_SECONDS, ge=5, le=120,
        description="心跳间隔（秒）",
    ),
):
    """订阅对话的事件流。

    响应格式：`text/event-stream`
    每条事件的 JSON payload 结构：
    ```
    {
      "type": "brainstorm.ask_user",
      "agent": "brainstorm",
      "session_id": "bs_xxx",
      "conversation_id": 42,
      "seq": 17,
      "data": {...}
    }
    ```

    断线重连：客户端记住最后 seq，重连时带 `?last_seen_seq=N`，
    后端先把 seq > N 的历史 **按序补发**，再接实时流。
    """
    # 鉴权：单独一个 session（不能复用 Depends(get_db) 的 session 跑长连接）
    async with AsyncSessionLocal() as check_db:
        await _assert_conversation_access(check_db, conversation_id, ctx)

    publisher = get_db_publisher()

    async def event_stream() -> AsyncIterator[bytes]:
        # 给长连接单独开一个 DB session（订阅者循环期间会用）
        async with AsyncSessionLocal() as sub_db:
            sub_iter = publisher.subscribe(
                conversation_id, last_seen_seq=last_seen_seq, db=sub_db,
            )

            # 先把补发历史全部 yield 出（subscribe 内部会先 yield 历史再订阅实时流）
            # 心跳靠一个并发 task 推送
            heartbeat_task: asyncio.Task | None = None
            queue: asyncio.Queue[dict | None] = asyncio.Queue(maxsize=256)

            async def _pump_iter():
                try:
                    async for ev in sub_iter:
                        await queue.put(ev)
                except Exception as e:
                    logger.warning("SSE pump err: %s", e)
                finally:
                    await queue.put(None)  # 终止信号

            async def _pump_heartbeat():
                while True:
                    await asyncio.sleep(heartbeat_seconds)
                    await queue.put({"__heartbeat__": True})

            pump_task = asyncio.create_task(_pump_iter())
            heartbeat_task = asyncio.create_task(_pump_heartbeat())

            try:
                while True:
                    ev = await queue.get()
                    if ev is None:
                        break
                    if ev.get("__heartbeat__"):
                        yield _format_sse({"seq": 0}, event_name="heartbeat").encode("utf-8")
                        continue
                    yield _format_sse(ev).encode("utf-8")
            finally:
                pump_task.cancel()
                if heartbeat_task:
                    heartbeat_task.cancel()
                for t in (pump_task, heartbeat_task):
                    if t is not None:
                        try:
                            await t
                        except (asyncio.CancelledError, Exception):
                            pass

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # nginx 禁用缓冲
        },
    )
