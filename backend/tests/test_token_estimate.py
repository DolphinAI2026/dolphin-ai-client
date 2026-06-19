from app.agents.token_estimate import estimate_tokens


def test_empty_is_zero():
    assert estimate_tokens([]) == 0


def test_counts_string_content():
    # 纯 ASCII: ~ 字符数/3.5
    msgs = [{"role": "user", "content": "x" * 350}]
    n = estimate_tokens(msgs)
    assert 80 <= n <= 130


def test_counts_tool_calls_and_blocks():
    msgs = [
        {"role": "assistant", "content": "", "tool_calls": [{"function": {"name": "read_file", "arguments": "{\"path\":\"a.vue\"}"}}]},
        {"role": "tool", "content": "file body " * 100},
        {"role": "user", "content": [{"type": "text", "text": "hello"}]},  # 多模态块
    ]
    assert estimate_tokens(msgs) > 0
