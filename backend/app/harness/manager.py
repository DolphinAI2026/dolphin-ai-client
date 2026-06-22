"""Harness Core — HarnessManager 编排器

核心职责：
- 创建 / 加载 thread
- 启动 turn（后台执行 profile.run_turn + 实时 SSE 输出）
- 支持事件回放（replay）
"""
import asyncio
import json
import logging
from datetime import datetime
from typing import AsyncIterator, Optional

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import AsyncSessionLocal
from app.harness.models import HarnessThread as HarnessThreadModel, HarnessTurn as HarnessTurnModel
from app.harness.contracts import ThreadContext, TurnContext, ThreadInfo
from app.harness.events import EventBus, TURN_STARTED, TURN_COMPLETED, TURN_FAILED, _SENTINEL
from app.harness.run_registry import RunHandle, run_registry
from app.harness.profiles import get_profile
from app.harness.sse_adapter import get_sse_adapter

logger = logging.getLogger(__name__)


class HarnessManager:
    """Harness 核心编排器。一个实例对应一次 API 请求。"""

    def __init__(self, db: AsyncSession):
        self._db = db

    # ── Thread CRUD ──────────────────────────────────

    async def create_thread(
        self,
        *,
        tenant_id: int,
        user_id: int,
        profile_name: str,
        conversation_id: Optional[int] = None,
        metadata: Optional[dict] = None,
    ) -> ThreadContext:
        """创建新的 harness thread。"""
        # 校验 profile 存在
        get_profile(profile_name)

        thread = HarnessThreadModel(
            tenant_id=tenant_id,
            user_id=user_id,
            profile_name=profile_name,
            conversation_id=conversation_id,
            metadata_json=json.dumps(metadata or {}, ensure_ascii=False),
        )
        self._db.add(thread)
        await self._db.flush()

        return ThreadContext(
            thread_id=thread.id,
            tenant_id=tenant_id,
            user_id=user_id,
            profile_name=profile_name,
            conversation_id=conversation_id,
            metadata=metadata or {},
        )

    async def load_thread(self, thread_id: int, *, tenant_id: int) -> ThreadContext:
        """加载已有 thread（含租户隔离）。"""
        result = await self._db.execute(
            select(HarnessThreadModel).where(
                HarnessThreadModel.id == thread_id,
                HarnessThreadModel.tenant_id == tenant_id,
            )
        )
        thread = result.scalar_one_or_none()
        if not thread:
            raise ValueError(f"Thread {thread_id} not found or access denied")

        return ThreadContext(
            thread_id=thread.id,
            tenant_id=thread.tenant_id,
            user_id=thread.user_id,
            profile_name=thread.profile_name,
            conversation_id=thread.conversation_id,
            metadata=json.loads(thread.metadata_json) if thread.metadata_json else {},
        )

    async def get_thread_info(self, thread_id: int, *, tenant_id: int) -> ThreadInfo:
        """获取 thread 详情（API 响应用）。"""
        result = await self._db.execute(
            select(HarnessThreadModel).where(
                HarnessThreadModel.id == thread_id,
                HarnessThreadModel.tenant_id == tenant_id,
            )
        )
        thread = result.scalar_one_or_none()
        if not thread:
            raise ValueError(f"Thread {thread_id} not found")

        return ThreadInfo(
            id=thread.id,
            tenant_id=thread.tenant_id,
            user_id=thread.user_id,
            profile_name=thread.profile_name,
            status=thread.status,
            conversation_id=thread.conversation_id,
            metadata=json.loads(thread.metadata_json) if thread.metadata_json else {},
            last_seq=thread.last_seq,
            created_at=thread.created_at,
            updated_at=thread.updated_at,
        )

    # ── Turn 执行 ──────────────────────────────────

    async def start_turn(
        self, thread_ctx: ThreadContext, user_input: str
    ) -> AsyncIterator[dict]:
        """启动新一轮执行。返回 SSE 事件异步迭代器。"""
        profile = get_profile(thread_ctx.profile_name)

        # 计算 turn_index
        result = await self._db.execute(
            select(func.count()).where(HarnessTurnModel.thread_id == thread_ctx.thread_id)
        )
        turn_index = result.scalar() or 0

        # 创建 turn 行
        turn = HarnessTurnModel(
            thread_id=thread_ctx.thread_id,
            turn_index=turn_index,
            user_input=user_input,
        )
        self._db.add(turn)
        await self._db.flush()
        turn_id = turn.id
        await self._db.commit()

        turn_ctx = TurnContext(
            turn_id=turn_id,
            thread_id=thread_ctx.thread_id,
            turn_index=turn_index,
            user_input=user_input,
        )

        # 创建 EventBus
        event_bus = EventBus(thread_ctx.thread_id, AsyncSessionLocal)
        # 从 DB 恢复 seq
        result = await self._db.execute(
            select(HarnessThreadModel.last_seq).where(
                HarnessThreadModel.id == thread_ctx.thread_id
            )
        )
        last_seq = result.scalar() or 0
        await event_bus.init_from_db(last_seq)

        # SSE 订阅
        subscriber_queue = event_bus.subscribe()

        # SSE 适配器
        adapter = get_sse_adapter(profile.get_sse_adapter_name())

        # 后台执行 turn
        async def _run_turn_background():
            try:
                await event_bus.publish(
                    TURN_STARTED, turn_id,
                    {"turn_index": turn_index, "user_input": user_input},
                )

                result_summary = await profile.run_turn(thread_ctx, turn_ctx, event_bus)

                # 标记完成
                async with AsyncSessionLocal() as session:
                    turn_row = await session.get(HarnessTurnModel, turn_id)
                    if turn_row:
                        turn_row.status = "completed"
                        turn_row.result_summary = result_summary
                        turn_row.completed_at = datetime.utcnow()
                    thread_row = await session.get(HarnessThreadModel, thread_ctx.thread_id)
                    if thread_row:
                        thread_row.conversation_id = thread_ctx.conversation_id
                        thread_row.metadata_json = json.dumps(thread_ctx.metadata, ensure_ascii=False)
                    await session.commit()

                await event_bus.publish(
                    TURN_COMPLETED, turn_id,
                    {"result_summary": result_summary},
                )
            except Exception as e:
                logger.exception(f"Turn {turn_id} failed")
                async with AsyncSessionLocal() as session:
                    turn_row = await session.get(HarnessTurnModel, turn_id)
                    if turn_row:
                        turn_row.status = "failed"
                        turn_row.error_message = str(e)
                        turn_row.completed_at = datetime.utcnow()
                    thread_row = await session.get(HarnessThreadModel, thread_ctx.thread_id)
                    if thread_row:
                        thread_row.conversation_id = thread_ctx.conversation_id
                        thread_row.metadata_json = json.dumps(thread_ctx.metadata, ensure_ascii=False)
                    await session.commit()

                await event_bus.publish(
                    TURN_FAILED, turn_id,
                    {"error": str(e)},
                )
            finally:
                # 更新 thread.last_seq
                async with AsyncSessionLocal() as session:
                    thread_row = await session.get(HarnessThreadModel, thread_ctx.thread_id)
                    if thread_row:
                        thread_row.last_seq = event_bus.current_seq
                        await session.commit()

                await event_bus.send_sentinel()
                # 摘除注册表(切会话不丢 run:run 完成/失败才解绑)
                if thread_ctx.conversation_id is not None:
                    run_registry.unregister(thread_ctx.conversation_id)

        # 启动后台任务
        task = asyncio.create_task(_run_turn_background())
        # 注册到进程级 RunRegistry:强引用 task(防 GC)+ 持有在跑 EventBus(供切回重连)
        if thread_ctx.conversation_id is not None:
            run_registry.register(
                thread_ctx.conversation_id,
                RunHandle(
                    task=task,
                    event_bus=event_bus,
                    run_id=str(turn_id),
                    thread_id=thread_ctx.thread_id,
                ),
            )

        # SSE 事件流生成器
        async def _event_stream() -> AsyncIterator[dict]:
            try:
                while True:
                    try:
                        event = await asyncio.wait_for(subscriber_queue.get(), timeout=1.0)
                        if event.get("event_type") == _SENTINEL:
                            break
                        translated = adapter.translate(event)
                        if translated:
                            # 附加 seq 供前端 replay 用
                            translated["_seq"] = event.get("seq", 0)
                            yield translated
                        if event.get("event_type") in (TURN_COMPLETED, TURN_FAILED):
                            break
                    except asyncio.TimeoutError:
                        if task.done():
                            break
                        # 心跳
                        yield {"type": "heartbeat"}
            finally:
                event_bus.unsubscribe(subscriber_queue)

        return _event_stream()

    # ── Replay ──────────────────────────────────

    async def replay_events(
        self, thread_id: int, *, after_seq: int = 0, tenant_id: int
    ) -> list[dict]:
        """回放 thread 的历史事件。"""
        # 租户隔离
        await self.load_thread(thread_id, tenant_id=tenant_id)

        from app.harness.models import HarnessItem
        result = await self._db.execute(
            select(HarnessItem)
            .where(
                HarnessItem.thread_id == thread_id,
                HarnessItem.seq > after_seq,
            )
            .order_by(HarnessItem.seq)
        )
        items = result.scalars().all()
        return [json.loads(item.payload_json) for item in items]
