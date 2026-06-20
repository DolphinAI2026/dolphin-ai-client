from app.agents.coding.agent import CodingAgent
from app.agents.types import AgentContext


def _make_agent():
    ctx = AgentContext(
        conversation_id=1,
        user_id=1,
        tenant_id=1,
        session_id="s",
        model="gpt-4o",   # required field
        input={},
    )
    return CodingAgent(ctx)


def test_token_usage_snapshot_shape_and_values():
    agent = _make_agent()
    agent._messages = [
        {"role": "system", "content": "x" * 100},
        {"role": "user", "content": "帮我加个字段" * 50},
    ]
    agent._tokens_input = 1234
    agent._tokens_output = 567

    snap = agent.token_usage_snapshot()

    assert set(snap) == {"tokens_input", "tokens_output", "context_tokens", "context_budget"}
    assert snap["tokens_input"] == 1234
    assert snap["tokens_output"] == 567
    assert snap["context_budget"] == 90000  # CODING_CONTEXT_TOKEN_BUDGET
    assert snap["context_tokens"] > 0       # estimate_tokens(_messages) 非空


def test_token_usage_snapshot_empty_messages():
    agent = _make_agent()
    agent._messages = []
    agent._tokens_input = 0
    agent._tokens_output = 0
    snap = agent.token_usage_snapshot()
    assert snap["context_tokens"] == 0
    assert snap["context_budget"] == 90000
