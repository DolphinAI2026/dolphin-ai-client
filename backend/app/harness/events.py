"""Harness Core — 事件系统（事件类型 + EventBus）"""
import asyncio
import json
import logging
from datetime import datetime
from typing import Optional

from app.harness.contracts import HarnessEvent

logger = logging.getLogger(__name__)

# ── 事件类型常量 ──────────────────────────────────

# Thread 生命周期
THREAD_STARTED = "thread.started"
THREAD_COMPLETED = "thread.completed"

# Turn 生命周期
TURN_STARTED = "turn.started"
TURN_COMPLETED = "turn.completed"
TURN_FAILED = "turn.failed"

# Item 生命周期（turn 内的原子单元）
ITEM_STARTED = "item.started"
ITEM_DELTA = "item.delta"
ITEM_COMPLETED = "item.completed"

# 审批
APPROVAL_REQUESTED = "approval.requested"
APPROVAL_RESOLVED = "approval.resolved"

# 终止信号（内部用，不持久化）
_SENTINEL = "__sentinel__"


class EventBus:
    """per-thread 事件总线。混合模式：内存实时广播 + DB 持久化 replay。"""

    def __init__(self, thread_id: int, db_session_factory):
        self._thread_id = thread_id
        self._db_factory = db_session_factory
        self._subscribers: list[asyncio.Queue] = []
        self._seq = 0
        self._history: list[HarnessEvent] = []

    async def init_from_db(self, last_seq: int):
        """从 DB 恢复序号。"""
        self._seq = last_seq

    @property
    def current_seq(self) -> int:
        return self._seq

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=500)
        self._subscribers.append(q)
        return q

    def unsubscribe(self, q: asyncio.Queue):
        try:
            self._subscribers.remove(q)
        except ValueError:
            pass

    async def publish(
        self,
        event_type: str,
        turn_id: Optional[int],
        data: dict,
        *,
        item_kind: str = "system",
        persist: bool = True,
    ):
        """发布事件 → 广播给订阅者 + 持久化到 DB。"""
        self._seq += 1
        event = HarnessEvent(
            seq=self._seq,
            event_type=event_type,
            thread_id=self._thread_id,
            turn_id=turn_id,
            data=data,
            timestamp=datetime.utcnow(),
        )
        self._history.append(event)

        # 实时广播
        event_dict = event.model_dump(mode="json")
        for q in self._subscribers:
            try:
                q.put_nowait(event_dict)
            except asyncio.QueueFull:
                logger.warning(f"EventBus subscriber queue full, dropping event seq={self._seq}")

        # 持久化到 harness_items
        if persist:
            try:
                await self._persist_item(event, item_kind)
            except Exception:
                logger.exception(f"Failed to persist harness item seq={self._seq}")

    async def _persist_item(self, event: HarnessEvent, item_kind: str):
        from app.harness.models import HarnessItem
        async with self._db_factory() as session:
            item = HarnessItem(
                thread_id=event.thread_id,
                turn_id=event.turn_id or 0,
                seq=event.seq,
                event_type=event.event_type,
                item_kind=item_kind,
                payload_json=json.dumps(event.model_dump(mode="json"), ensure_ascii=False),
            )
            session.add(item)
            await session.commit()

    async def send_sentinel(self):
        """发送终止信号，通知消费者停止读取。"""
        for q in self._subscribers:
            try:
                q.put_nowait({"event_type": _SENTINEL})
            except asyncio.QueueFull:
                pass

    async def replay_after(self, after_seq: int) -> list[dict]:
        """回放 after_seq 之后的事件。先查内存缓冲，再查 DB。"""
        # 内存快速路径
        events = [e.model_dump(mode="json") for e in self._history if e.seq > after_seq]
        if events or after_seq >= self._seq:
            return events

        # DB 查询
        from sqlalchemy import select
        from app.harness.models import HarnessItem
        async with self._db_factory() as session:
            result = await session.execute(
                select(HarnessItem)
                .where(
                    HarnessItem.thread_id == self._thread_id,
                    HarnessItem.seq > after_seq,
                )
                .order_by(HarnessItem.seq)
            )
            rows = result.scalars().all()
            return [json.loads(r.payload_json) for r in rows]
