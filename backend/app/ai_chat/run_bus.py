"""ai-chat run 进程内总线 + 注册表(切会话不丢 run Phase2)。

ai-chat 走 session_id(非 conversation_id),且没有现成事件总线 → 自建轻量内存总线:
- 承载原始 SSE 事件 dict(run_agent 直接 yield 的 {"event":..,"data":..})+ 单调 seq;
- replay_after(after_seq) 补缺口,subscribe()/unsubscribe() 实时,send_sentinel() 收尾;
- 进程内,不落库(历史由 loadSession REST 覆盖);run 后台任务 + RunRegistry 强引用防 GC。
"""
from __future__ import annotations

import asyncio

from app.harness.run_registry import RunRegistry

_SENTINEL_SEQ = -1


class AiChatRunBus:
    def __init__(self) -> None:
        self._seq = 0
        self._history: list[tuple[int, dict]] = []
        self._subscribers: list[asyncio.Queue] = []

    @property
    def current_seq(self) -> int:
        return self._seq

    async def publish(self, event: dict) -> int:
        self._seq += 1
        self._history.append((self._seq, event))
        for q in self._subscribers:
            try:
                q.put_nowait((self._seq, event))
            except asyncio.QueueFull:
                pass
        return self._seq

    def replay_after(self, after_seq: int) -> list[tuple[int, dict]]:
        return [(s, e) for (s, e) in self._history if s > after_seq]

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=1000)
        self._subscribers.append(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        try:
            self._subscribers.remove(q)
        except ValueError:
            pass

    async def send_sentinel(self) -> None:
        for q in self._subscribers:
            try:
                q.put_nowait((_SENTINEL_SEQ, {"__sentinel__": True}))
            except asyncio.QueueFull:
                pass


def is_sentinel(item: tuple[int, dict]) -> bool:
    return item[0] == _SENTINEL_SEQ


async def subscribe_run_events(bus: "AiChatRunBus", after_seq: int = 0):
    """订阅一个在跑 run 的事件流:先补 seq>after_seq 的缺口,再跟实时到 sentinel。

    yield 原始 SSE 事件 dict(run_agent 直接产出的 {"event":..,"data":..})。send 与 attach 共用。
    客户端断开 → 生成器被取消 → finally 只 unsubscribe,后台 run task 不受影响。
    """
    q = bus.subscribe()
    try:
        seen = after_seq
        for s, ev in bus.replay_after(after_seq):
            yield ev
            if s > seen:
                seen = s
        while True:
            try:
                s, ev = await asyncio.wait_for(q.get(), timeout=15.0)
            except asyncio.TimeoutError:
                yield {"event": "ping", "data": ""}
                continue
            if s == _SENTINEL_SEQ:
                break
            if s <= seen:
                continue  # 缺口已补发过
            seen = s
            yield ev
    finally:
        bus.unsubscribe(q)


# 按 session_id 持有在跑 ai-chat run(与 coding 的 run_registry 分开,避免键冲突)
ai_chat_run_registry = RunRegistry()
