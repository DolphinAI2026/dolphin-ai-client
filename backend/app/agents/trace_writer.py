"""TraceWriter — agent 内部调试 trace 的持久化接口。

和 Publisher 区别：
- Publisher：面向用户的 SSE 事件（conversation_events）
- TraceWriter：内部调试（agent_traces），不推送给前端

Agent 代码通过本接口记录 LLM 请求/响应、tool call、thinking、error 等内部事件。
"""
from __future__ import annotations

from typing import Any, Optional, Protocol


class TraceWriter(Protocol):
    """写 agent_traces 的抽象接口"""

    async def write(
        self,
        *,
        session_type: str,         # "brainstorm" / "coding" / "verification"
        session_id: str,
        turn: int,
        event_type: str,           # TraceEventType
        payload: dict[str, Any],
        tokens_input: Optional[int] = None,
        tokens_output: Optional[int] = None,
        duration_ms: Optional[int] = None,
        model: Optional[str] = None,
    ) -> str:
        """写入一条 trace，返回 trace id。

        实现必须保证 (session_type, session_id, seq) 单调递增。
        """
        ...


class InMemoryTraceWriter:
    """内存 TraceWriter — 用于测试。"""

    def __init__(self) -> None:
        self._counters: dict[tuple[str, str], int] = {}
        self.traces: list[dict[str, Any]] = []

    async def write(
        self,
        *,
        session_type: str,
        session_id: str,
        turn: int,
        event_type: str,
        payload: dict[str, Any],
        tokens_input: Optional[int] = None,
        tokens_output: Optional[int] = None,
        duration_ms: Optional[int] = None,
        model: Optional[str] = None,
    ) -> str:
        key = (session_type, session_id)
        self._counters[key] = self._counters.get(key, 0) + 1
        seq = self._counters[key]
        trace_id = f"trace_{session_type}_{session_id}_{seq}"
        self.traces.append({
            "id": trace_id,
            "session_type": session_type,
            "session_id": session_id,
            "seq": seq,
            "turn": turn,
            "event_type": event_type,
            "payload": payload,
            "tokens_input": tokens_input,
            "tokens_output": tokens_output,
            "duration_ms": duration_ms,
            "model": model,
        })
        return trace_id

    def clear(self) -> None:
        self._counters.clear()
        self.traces.clear()

    def traces_of_type(self, event_type: str) -> list[dict[str, Any]]:
        return [t for t in self.traces if t["event_type"] == event_type]
