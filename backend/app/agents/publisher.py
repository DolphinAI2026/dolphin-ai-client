"""EventPublisher — 将 agent 事件发布到 SSE 流 + 持久化到 conversation_events。

使用 Protocol 定义接口，方便：
- 真实实现（backend/app/agents/publishers/db_publisher.py，P1.2 阶段实装）
- Mock 实现（测试用，内存 buffer）

Agent 代码统一依赖这个接口，不关心底层是 DB / Redis / 内存。
"""
from __future__ import annotations

from typing import Any, Protocol


class EventPublisher(Protocol):
    """发布 SSE 事件的抽象接口"""

    async def publish(
        self,
        *,
        conversation_id: int,
        event_type: str,           # 如 "brainstorm.ask_user"
        agent: str,                # "brainstorm" / "coding" / ...
        session_id: str | None,
        data: dict[str, Any],
    ) -> int:
        """发布一个事件。返回分配的 seq 号。

        实现必须保证同一 conversation 内 seq 单调递增。
        """
        ...


class InMemoryEventPublisher:
    """内存 Publisher — 用于单元测试 / BaseAgent 自测。

    不依赖数据库，只存到内存 buffer 便于断言。
    """

    def __init__(self) -> None:
        self._counters: dict[int, int] = {}
        self.events: list[dict[str, Any]] = []

    async def publish(
        self,
        *,
        conversation_id: int,
        event_type: str,
        agent: str,
        session_id: str | None,
        data: dict[str, Any],
    ) -> int:
        self._counters[conversation_id] = self._counters.get(conversation_id, 0) + 1
        seq = self._counters[conversation_id]
        self.events.append({
            "type": event_type,
            "agent": agent,
            "session_id": session_id,
            "conversation_id": conversation_id,
            "seq": seq,
            "data": data,
        })
        return seq

    def clear(self) -> None:
        self._counters.clear()
        self.events.clear()

    def events_of_type(self, event_type: str) -> list[dict[str, Any]]:
        return [e for e in self.events if e["type"] == event_type]
