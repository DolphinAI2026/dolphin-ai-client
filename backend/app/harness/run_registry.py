"""进程级在跑 run 注册表 —— 让 agent run 脱离 SSE 连接(切会话不丢)。

强引用后台 task(否则 asyncio 只弱引用、客户端断开后闭包被 GC → task 被取消)。
按 conversation_id 持有(一会话单 run),重连时据此接回同一条在跑 EventBus。
进程内：后端重启后不保留运行状态。
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any


@dataclass
class RunHandle:
    task: asyncio.Task
    event_bus: Any
    run_id: str | None
    thread_id: int


class RunRegistry:
    def __init__(self) -> None:
        self._runs: dict[int, RunHandle] = {}

    def register(self, conversation_id: int, handle: RunHandle) -> None:
        self._runs[conversation_id] = handle

    def get(self, conversation_id: int) -> RunHandle | None:
        return self._runs.get(conversation_id)

    def unregister(self, conversation_id: int) -> None:
        self._runs.pop(conversation_id, None)

    def is_running(self, conversation_id: int) -> bool:
        h = self._runs.get(conversation_id)
        return bool(h and not h.task.done())


run_registry = RunRegistry()
