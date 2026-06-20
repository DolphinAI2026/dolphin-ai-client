"""TDD: CodingAgent._call_llm 拆分 reasoning + content 为两个独立 agent_thinking aggregate

Task 1: 不再 `combined_thinking = reasoning_content + full_content`; 改为各发一个 publish。
"""
from app.agents.coding.agent import CodingAgent
from app.agents.types import AgentContext


def _agent():
    ctx = AgentContext(
        conversation_id=1,
        user_id=1,
        tenant_id=1,
        session_id="s",
        model="gpt-4o",
        input={},
    )
    return CodingAgent(ctx)


class _FakeLLM:
    def __init__(self, chunks):
        self._chunks = chunks

    async def chat_completion_stream(self, *a, **k):
        for c in self._chunks:
            yield c


async def _collect_thinking(agent):
    """跑 _call_llm, 收集所有 agent_thinking publish 的 (content, reasoning?) 。"""
    seen = []

    async def _spy(event_type, data):
        if event_type == "agent_thinking":
            seen.append((data.get("content"), bool(data.get("reasoning"))))

    agent._publish = _spy
    await agent._call_llm()
    return seen


async def test_reasoning_and_content_split_into_two_aggregates():
    """有 reasoning + content 时: 两个独立 aggregate, 不拼接。"""
    agent = _agent()
    agent.ctx.llm_client = _FakeLLM([
        {"choices": [{"delta": {"reasoning_content": "我先想想"}}]},
        {"choices": [{"delta": {"content": "这是答案"}}]},
        {"choices": [{"delta": {}, "finish_reason": "stop"}]},
    ])
    seen = await _collect_thinking(agent)
    # 两个独立 aggregate: content(无标志) + reasoning(带标志); 内容不拼接
    assert ("这是答案", False) in seen, f"content aggregate missing, got {seen}"
    assert ("我先想想", True) in seen, f"reasoning aggregate missing, got {seen}"
    # 绝对不能出现拼接结果
    all_contents = [c for c, _ in seen]
    assert "我先想想这是答案" not in all_contents
    assert "这是答案我先想想" not in all_contents


async def test_only_content_emits_single_aggregate_no_reasoning_flag():
    """只有 content 时: 只发一条 aggregate, 不带 reasoning 标志。"""
    agent = _agent()
    agent.ctx.llm_client = _FakeLLM([
        {"choices": [{"delta": {"content": "纯答案"}}]},
        {"choices": [{"delta": {}, "finish_reason": "stop"}]},
    ])
    seen = await _collect_thinking(agent)
    assert seen == [("纯答案", False)], f"expected single content aggregate, got {seen}"


async def test_only_reasoning_emits_single_aggregate_with_flag():
    """只有 reasoning 时: 只发一条带 reasoning=True 的 aggregate。"""
    agent = _agent()
    agent.ctx.llm_client = _FakeLLM([
        {"choices": [{"delta": {"reasoning_content": "只有思考"}}]},
        {"choices": [{"delta": {}, "finish_reason": "stop"}]},
    ])
    seen = await _collect_thinking(agent)
    assert seen == [("只有思考", True)], f"expected single reasoning aggregate, got {seen}"
