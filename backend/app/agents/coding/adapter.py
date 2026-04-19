"""CodingAgentStreamAdapter — 让 CodingAgent 对外呈现为 VibeCodingAgent 兼容的 async generator 接口。

目的：pipeline.py 等上游代码原本用法：
    async for event in agent.run(requirement=..., max_turns=30):
        yield event
期望事件是 dict（type/content/tool/... 等 VibeCodingAgent 格式）。

Adapter 通过 QueuePublisher 拦截 CodingAgent 的 publish 事件，做两件事：
1. 把 BaseAgent publisher event（{type: "coding.xxx", data: {...}}）翻译成 VibeCodingAgent 兼容
   事件（{type: "agent_xxx", ...data flat}）
2. async 迭代 yield 给 pipeline.py，行为与 VibeCodingAgent.run() 一致
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, AsyncIterator

from app.agents.coding.agent import CodingAgent
from app.agents.types import AgentStatus

logger = logging.getLogger(__name__)


# 事件类型过滤：BaseAgent 发的通用 tool_call / tool_result 被 CodingAgent 的
# agent_tool / agent_result 覆盖了更详细版本，adapter 忽略通用版避免重复
_IGNORED_ACTIONS = {
    "tool_call",     # BaseAgent 通用（被 CodingAgent.before_tool_call 发 agent_tool 覆盖）
    "tool_result",   # BaseAgent 通用（被 CodingAgent.after_tool_call 发 agent_result 覆盖）
    "start",         # pipeline 已经发 step:generate:running
    "paused",
    "aborted",       # failed / done 等显式事件已覆盖
}


def translate_event(raw: dict[str, Any]) -> dict[str, Any] | None:
    """把 BaseAgent publisher event 翻译成 VibeCodingAgent 兼容事件。

    返回 None 表示此事件应被丢弃（如重复的通用事件）。
    """
    event_type = raw.get("type", "") or ""
    data = raw.get("data") or {}

    # 只处理 coding.* 命名空间
    if not event_type.startswith("coding."):
        return None
    action = event_type.split(".", 1)[1]

    if action in _IGNORED_ACTIONS:
        return None

    if action == "done":
        return {"type": "agent_done", "result": data.get("result") or "completed"}
    if action == "failed":
        return {"type": "agent_error", "message": data.get("error") or "unknown error"}
    if action == "tool_progress":
        # VibeCodingAgent 用 agent_command_output
        out = {"type": "agent_command_output"}
        out.update(data)
        return out

    # agent_tool / agent_result / agent_thinking / agent_thinking_delta
    # 格式：VibeCodingAgent 的这些事件 data 是 flat 到顶层的（无 "data" 包装）
    out = {"type": action}
    out.update(data)
    return out


class _QueuePublisher:
    """把事件塞 asyncio.Queue 的 Publisher（满足 EventPublisher Protocol）。

    用于 adapter 拦截 CodingAgent 的事件流。不写 DB、不保证 seq。
    """

    def __init__(self) -> None:
        self.queue: asyncio.Queue = asyncio.Queue()

    async def publish(
        self,
        *,
        conversation_id: int,
        event_type: str,
        agent: str,
        session_id: str | None,
        data: dict[str, Any],
    ) -> int:
        await self.queue.put({
            "type": event_type,
            "agent": agent,
            "session_id": session_id,
            "data": data,
        })
        return 0  # seq 在 adapter 模式下无意义

    async def close(self) -> None:
        """推入 sentinel，告诉 adapter 停止 iterate"""
        await self.queue.put(None)


class CodingAgentStreamAdapter:
    """把 CodingAgent 包装成 VibeCodingAgent 兼容接口。

    用法（与 pipeline.py 现有 `async for event in VibeCodingAgent(ws_id).run(...)` 一致）：

        agent = CodingAgent(ctx)
        adapter = CodingAgentStreamAdapter(agent)
        async for event in adapter.run(requirement=..., max_turns=30):
            yield event
    """

    def __init__(self, agent: CodingAgent) -> None:
        self._agent = agent

    async def run(
        self,
        *,
        requirement: str,
        conversation_summary: str = "",
        max_turns: int = 30,
        model: str | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        """执行 agent 并流式 yield VibeCodingAgent 兼容事件。"""
        # 把 pipeline 传进来的参数注入到 agent.ctx.input（CodingAgent 从这里取）
        current_input = dict(self._agent.ctx.input or {})
        current_input.update({
            "requirement": requirement,
            "conversation_summary": conversation_summary,
            "max_turns": max_turns,
        })
        self._agent.ctx.input = current_input
        if model:
            self._agent.ctx.model = model

        # 替换 publisher 为 queue 版
        orig_publisher = self._agent.ctx.publisher
        queue_pub = _QueuePublisher()
        self._agent.ctx.publisher = queue_pub

        # 在后台跑 agent，完成后往 queue 塞 sentinel
        async def _run_agent_and_close():
            try:
                return await self._agent.run()
            finally:
                await queue_pub.close()

        agent_task = asyncio.create_task(_run_agent_and_close())

        try:
            while True:
                raw = await queue_pub.queue.get()
                if raw is None:  # sentinel
                    break
                translated = translate_event(raw)
                if translated is not None:
                    yield translated

            # agent task 已完成（close() 一定在 agent.run 后调用）
            result = await agent_task

            # 若期间没 yield 过 done / error（极端情况），补一个
            if result.status == AgentStatus.COMPLETED:
                # CodingAgent 的 final_result 是 dict，取 final_text 作为完成注解
                final_text = ""
                if isinstance(result.product, dict):
                    final_text = str(result.product.get("final_text") or "").strip()
                # 只有 LLM 主动结束时才发（流程中 coding.done 已经翻译成 agent_done，
                # 但 Stage 2.2 里 LLM 无 tool_call 会路由到 BaseAgent 的 done 事件，已被翻译）
                # 这里主要为安全兜底：已经 yield 过的情况下，上游看到的是第二个 agent_done，
                # VibeCodingAgent 原行为也允许（pipeline 用 str result，取最后一个）
                if final_text and result.turns_used > 0:
                    yield {"type": "agent_done", "result": final_text}
            elif result.status == AgentStatus.FAILED and result.error_message:
                # 同样的安全兜底
                logger.debug("agent failed after stream closed: %s", result.error_message)
        finally:
            # 恢复原 publisher；确保 task 已 await 过
            self._agent.ctx.publisher = orig_publisher
            if not agent_task.done():
                agent_task.cancel()
                try:
                    await agent_task
                except (asyncio.CancelledError, Exception):
                    pass
