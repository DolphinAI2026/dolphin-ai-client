"""TDD: context-length/413 errors trigger compact-then-retry-once in _call_llm_with_retry."""
import pytest
from app.agents.base import BaseAgent
from app.agents.types import AgentContext, AgentType, LLMResponse


class _CtxLenError(Exception):
    pass


class _ProbeAgent(BaseAgent):
    agent_type = AgentType.CODING

    def __init__(self, ctx):
        super().__init__(ctx)
        self._calls = 0
        self.overflow_called = 0

    # Required abstract method stubs
    def get_system_prompt(self): return ""
    def get_tools(self): return []
    def get_max_turns(self): return 1
    async def build_initial_user_message(self): return ""
    async def should_terminate(self, resp): return True
    async def finalize(self): pass

    async def on_context_overflow(self, messages):
        self.overflow_called += 1
        return messages[-1:]  # 强压成一条

    async def _call_llm(self):
        self._calls += 1
        if self._calls == 1:
            raise _CtxLenError("This model's maximum context length is 128000 tokens")
        return LLMResponse(content="ok", tool_calls=[], tokens_input=1, tokens_output=1)


@pytest.mark.asyncio
async def test_context_length_triggers_compact_then_retry():
    ctx = AgentContext(
        conversation_id=1,
        user_id=1,
        tenant_id=1,
        session_id="s",
        model="gpt-test",
        input={},
    )
    a = _ProbeAgent(ctx)
    a._messages = [{"role": "user", "content": "a"}, {"role": "user", "content": "b"}]
    resp = await a._call_llm_with_retry()
    assert resp.content == "ok"
    assert a.overflow_called == 1          # 压了一次
    assert a._calls == 2                   # 重试了一次
    assert a._messages == [{"role": "user", "content": "b"}]  # 用压缩后的 messages 重试


@pytest.mark.asyncio
async def test_context_length_compact_only_once():
    """第二次还是 context-length 错误时，不再重压，直接抛出。"""

    class _AlwaysCtxLen(_ProbeAgent):
        async def _call_llm(self):
            self._calls += 1
            raise _CtxLenError("maximum context length exceeded")

    ctx = AgentContext(
        conversation_id=1,
        user_id=1,
        tenant_id=1,
        session_id="s",
        model="gpt-test",
        input={},
    )
    a = _AlwaysCtxLen(ctx)
    a._messages = [{"role": "user", "content": "x"}]
    with pytest.raises(_CtxLenError):
        await a._call_llm_with_retry()
    assert a.overflow_called == 1   # 只压一次
    assert a._calls == 2            # 首次失败 + 重试后再失败
