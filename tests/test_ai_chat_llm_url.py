from app.ai_chat.agent import LLMConfigSnapshot, _llm_chat_completions_url


def test_ai_chat_uses_openai_compatible_v1_chat_url_for_gateway_base():
    cfg = LLMConfigSnapshot(
        base_url="http://ai-agent.dfy.definesys.cn/omnigate/0",
        api_key="test-key",
        model="gpt-5.5",
        max_tokens=1024,
        temperature=0.3,
    )

    assert (
        _llm_chat_completions_url(cfg)
        == "http://ai-agent.dfy.definesys.cn/omnigate/0/v1/chat/completions"
    )


def test_ai_chat_preserves_full_chat_completions_url():
    cfg = LLMConfigSnapshot(
        base_url="http://ai-agent.dfy.definesys.cn/omnigate/0/v1/chat/completions",
        api_key="test-key",
        model="gpt-5.5",
        max_tokens=1024,
        temperature=0.3,
    )

    assert (
        _llm_chat_completions_url(cfg)
        == "http://ai-agent.dfy.definesys.cn/omnigate/0/v1/chat/completions"
    )
