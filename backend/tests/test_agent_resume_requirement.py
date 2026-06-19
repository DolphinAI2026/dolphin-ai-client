"""CRITICAL 1 — 验证 resume 时新 turn 的用户消息不丢失"""
import asyncio
import pytest
from app.agents.base import BaseAgent
from app.agents.types import (
    AgentContext,
    AgentResult,
    AgentStatus,
    AgentType,
    LLMResponse,
    ProductT,
    StopReason,
    Tool,
)

MARKER = "NEW_TURN_REQUIREMENT_MARKER"


class _MinimalAgent(BaseAgent[str]):
    agent_type = AgentType.SYSTEM

    def get_system_prompt(self) -> str:
        return "system"

    def get_tools(self) -> list[Tool]:
        return []

    def get_max_turns(self) -> int:
        return 5

    def build_initial_user_message(self) -> str:
        return self.ctx.input.get("requirement", MARKER)

    def should_terminate(self) -> tuple[bool, str]:
        return True, "done"

    async def finalize(self) -> str:
        return "product"

    async def _call_llm(self, messages, tools, stream=False):
        """Stub: 直接返回 no-tool-call 的 LLM 响应"""
        return LLMResponse(
            content="ok",
            tool_calls=[],
            stop_reason="stop",
            input_tokens=0,
            output_tokens=0,
        )


def _make_ctx() -> AgentContext:
    return AgentContext(
        session_id="s1",
        conversation_id=1,
        user_id=1,
        tenant_id=1,
        model="gpt-4",
        input={"requirement": MARKER},
    )


@pytest.mark.asyncio
async def test_resume_appends_new_user_message():
    """
    resume 场景（_messages 非空）下 run() 应把当前 turn 的用户消息追加进去。
    Bug: is_resume=True 时 build_initial_user_message() 被完全跳过。
    """
    agent = _MinimalAgent(_make_ctx())

    # 模拟 from_snapshot 恢复了历史消息（非空，触发 is_resume=True）
    agent._messages = [
        {"role": "system", "content": "system"},
        {"role": "user", "content": "old requirement from previous turn"},
        {"role": "assistant", "content": "old response"},
    ]

    await agent.run()

    roles = [m["role"] for m in agent._messages]
    contents = [m.get("content", "") for m in agent._messages]

    # 新 turn 的用户消息必须出现在 _messages 中
    assert any(MARKER in c for c in contents), (
        f"新 turn 用户消息 ({MARKER!r}) 未追加到 _messages。实际 messages: {agent._messages}"
    )
    # 最新用户消息应在末尾（assistant 回复之前或之后，但 user 消息必须存在）
    user_msgs_with_marker = [c for c in contents if MARKER in c]
    assert len(user_msgs_with_marker) >= 1
