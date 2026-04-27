"""DbEventPublisher — 把 agent 事件写入 conversation_events 表 + 推送给 SSE 订阅者。

架构：
- write 路径：单例内存 seq counter（首次从 DB 查最大值）+ 每事件写 conversation_events
- 推送路径：asyncio Queue pub/sub，订阅者从 Queue 消费

单实例部署用内存 counter；多实例未来需要换成 Redis pub/sub + 分布式 seq。
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Any, AsyncIterator

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent_models import ConversationEvent

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════
# Ephemeral 事件类型：不落 DB，只走实时 fan-out
# ══════════════════════════════════════════════════════════════
#
# 这些事件在生成过程中高频（每个 LLM token 一条），如果每条都 commit 一次 DB，
# 远端 MySQL 的 fsync + network RTT 会把实时打字机效果拖到几秒后。
#
# 策略：不持久化 delta，但 agent 在流式结束时会另发一条 `agent_thinking`
# （带 full content）落 DB —— 刷新回放时用整条思考文本重建条目，不需要 delta。
EPHEMERAL_EVENT_TYPES: frozenset[str] = frozenset({
    "coding.agent_thinking_delta",
    "agent_thinking_delta",
})


# ══════════════════════════════════════════════════════════════
# 全局 seq counter + SSE 订阅管理（单实例）
# ══════════════════════════════════════════════════════════════

class _ConversationState:
    """每个 conversation 的 publisher 状态（seq counter + 订阅者队列）"""
    __slots__ = ("seq_counter", "subscribers", "lock")

    def __init__(self) -> None:
        self.seq_counter: int = 0
        self.seq_loaded: bool = False  # type: ignore[assignment]
        self.subscribers: set[asyncio.Queue[dict[str, Any]]] = set()
        self.lock: asyncio.Lock = asyncio.Lock()

    # 用 __init__ 无法声明两个不同类型字段时，补充赋值
    def __init_subclass__(cls) -> None:  # pragma: no cover
        pass


# 因 __slots__ 要包含所有字段，单独定义一个扩展版
class _ConvState:
    def __init__(self) -> None:
        self.seq_counter: int = 0
        self.seq_loaded: bool = False
        self.subscribers: set[asyncio.Queue] = set()
        self.lock: asyncio.Lock = asyncio.Lock()


class DbEventPublisher:
    """基于数据库的 EventPublisher 实现。

    生命周期：
    - publisher 本身是进程级单例
    - 每个 conversation 有自己的 _ConvState（内存）
    - 事件同时写 DB + 推送到内存队列（pub/sub）
    """

    def __init__(self) -> None:
        self._conv_states: dict[int, _ConvState] = {}

    def _state(self, conversation_id: int) -> _ConvState:
        state = self._conv_states.get(conversation_id)
        if state is None:
            state = _ConvState()
            self._conv_states[conversation_id] = state
        return state

    async def _ensure_seq_loaded(
        self, state: _ConvState, conversation_id: int, db: AsyncSession,
    ) -> None:
        if state.seq_loaded:
            return
        result = await db.execute(
            select(func.max(ConversationEvent.seq)).where(
                ConversationEvent.conversation_id == conversation_id
            )
        )
        max_seq = result.scalar() or 0
        state.seq_counter = max_seq
        state.seq_loaded = True

    async def publish(
        self,
        *,
        conversation_id: int,
        event_type: str,
        agent: str,
        session_id: str | None,
        data: dict[str, Any],
        db: AsyncSession,
    ) -> int:
        """发布事件。

        参数 db 是 publisher 接口的扩展（Protocol 里没有，但 DB 实现需要）。
        Agent 代码应通过 ctx.publisher.publish(... db=ctx.db) 调用。
        """
        state = self._state(conversation_id)
        is_ephemeral = event_type in EPHEMERAL_EVENT_TYPES
        async with state.lock:
            await self._ensure_seq_loaded(state, conversation_id, db)
            state.seq_counter += 1
            seq = state.seq_counter

            # 非 ephemeral 事件才持久化；ephemeral（高频 thinking delta）只 fan-out 给
            # 实时订阅者，跳过 DB commit 以避免 MySQL fsync 拖慢打字机。
            # 代价：刷新后 delta 不会回放——但 agent 在流式结束会另发
            # agent_thinking（full_content）落 DB，重建条目用整条聚合内容。
            if not is_ephemeral:
                event_id = uuid.uuid4().hex
                event_row = ConversationEvent(
                    id=event_id,
                    conversation_id=conversation_id,
                    seq=seq,
                    event_type=event_type,
                    agent=agent,
                    session_id=session_id,
                    payload=data or {},
                )
                db.add(event_row)
                try:
                    await db.commit()
                except Exception as e:
                    logger.error("Failed to persist conversation_event: %s", e)
                    await db.rollback()
                    # 退回 seq（避免 seq 跳跃）
                    state.seq_counter -= 1
                    raise

            # 构造 SSE envelope
            event = {
                "type": event_type,
                "agent": agent,
                "session_id": session_id,
                "conversation_id": conversation_id,
                "seq": seq,
                "data": data,
            }

            # 推送到所有订阅者（非阻塞，队列满了就丢弃）
            dead: list[asyncio.Queue] = []
            for q in state.subscribers:
                try:
                    q.put_nowait(event)
                except asyncio.QueueFull:
                    logger.warning("SSE subscriber queue full, dropping event seq=%d", seq)
                except Exception as e:
                    logger.warning("SSE subscriber push failed: %s", e)
                    dead.append(q)
            for q in dead:
                state.subscribers.discard(q)

            return seq

    # ══════════════════════════════════════════════════════════════
    # SSE 订阅：给 route 层用
    # ══════════════════════════════════════════════════════════════

    async def subscribe(
        self,
        conversation_id: int,
        *,
        last_seen_seq: int = 0,
        db: AsyncSession,
        queue_size: int = 100,
    ) -> AsyncIterator[dict[str, Any]]:
        """订阅 conversation 的事件流。

        先补发 seq > last_seen_seq 的历史事件，再订阅实时流。

        调用方（FastAPI route）应包装成 StreamingResponse。
        """
        state = self._state(conversation_id)

        # 1. 补发历史事件
        result = await db.execute(
            select(ConversationEvent)
            .where(
                ConversationEvent.conversation_id == conversation_id,
                ConversationEvent.seq > last_seen_seq,
            )
            .order_by(ConversationEvent.seq.asc())
        )
        rows = result.scalars().all()
        for row in rows:
            yield {
                "type": row.event_type,
                "agent": row.agent,
                "session_id": row.session_id,
                "conversation_id": row.conversation_id,
                "seq": row.seq,
                "data": row.payload or {},
            }

        # 2. 订阅实时流
        queue: asyncio.Queue = asyncio.Queue(maxsize=queue_size)
        state.subscribers.add(queue)
        try:
            while True:
                event = await queue.get()
                # 客户端可能还没收到第 N 条，但 subscribe 时已补发过；
                # 下游收到的 seq 不保证紧随 last_seen_seq（中间可能有补发间隙），
                # 客户端要基于实际 seq 做判断。
                yield event
        finally:
            state.subscribers.discard(queue)


class ScopedDbEventPublisher:
    """满足 EventPublisher Protocol 的 adapter — 绑定一个 DB session。

    Agent 代码通过 ctx.publisher.publish(...) 调用，不感知底层 db 参数。
    Orchestrator 创建 AgentContext 时用 `db_publisher.scoped(db)` 构造。
    """

    def __init__(self, publisher: "DbEventPublisher", db: AsyncSession) -> None:
        self._publisher = publisher
        self._db = db

    async def publish(
        self,
        *,
        conversation_id: int,
        event_type: str,
        agent: str,
        session_id: str | None,
        data: dict[str, Any],
    ) -> int:
        return await self._publisher.publish(
            conversation_id=conversation_id,
            event_type=event_type,
            agent=agent,
            session_id=session_id,
            data=data,
            db=self._db,
        )


def _make_scoped_publisher(publisher: "DbEventPublisher", db: AsyncSession) -> ScopedDbEventPublisher:
    return ScopedDbEventPublisher(publisher, db)


# 绑定方法到类
DbEventPublisher.scoped = _make_scoped_publisher  # type: ignore[attr-defined]


# 进程级单例
_publisher_instance: DbEventPublisher | None = None


def get_db_publisher() -> DbEventPublisher:
    global _publisher_instance
    if _publisher_instance is None:
        _publisher_instance = DbEventPublisher()
    return _publisher_instance
