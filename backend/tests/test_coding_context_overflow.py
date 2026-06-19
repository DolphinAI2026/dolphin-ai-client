"""TDD: CodingAgent.on_context_overflow 按 token 预算本地压缩

Task 3: 先 clean_tool_results; 若仍超预算则本地 compact, 轮内不调 LLM。

NOTE: AgentContext.model 是必填字段 (non-optional), brief 的 scaffold 缺了它。
"""
import pytest
from app.agents.coding.agent import CodingAgent
from app.agents.types import AgentContext


def _agent():
    ctx = AgentContext(
        conversation_id=1,
        user_id=1,
        tenant_id=1,
        session_id="s",
        model="gpt-4o",   # required field — brief scaffold missed this
        input={},
    )
    return CodingAgent(ctx)


@pytest.mark.asyncio
async def test_overflow_under_budget_only_cleans_tool_results():
    a = _agent()
    a._context_token_budget = 10_000_000  # 永不超预算
    msgs = [{"role": "tool", "content": "x" * 500} for _ in range(10)]
    out = await a.on_context_overflow(msgs)
    # clean_tool_results 压缩了旧 tool(保留最近 4 完整), 但没做 compact 丢消息
    assert len(out) == len(msgs)


@pytest.mark.asyncio
async def test_overflow_over_budget_compacts():
    a = _agent()
    a._context_token_budget = 50  # 极低预算 → 触发本地 compact
    rounds = []
    for i in range(12):
        rounds.append({"role": "user", "content": f"req {i} " * 50})
        rounds.append({"role": "assistant", "content": f"```js\ncode {i}\n``` done {i}"})
    out = await a.on_context_overflow(rounds)
    # 本地 compact 会去代码块 + 只保留最近若干轮 → 总量明显变小
    assert len(out) < len(rounds)
