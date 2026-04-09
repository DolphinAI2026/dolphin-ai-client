import os
import sys

os.environ.setdefault("LLM_API_KEY", "test-key")
os.environ.setdefault("JWT_SECRET_KEY", "test-secret")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from app.ai_doc_parser import _build_anthropic_headers, _uses_anthropic_messages_api
from app.llm_client import LLMClient


def test_ai_doc_parser_uses_anthropic_mode_for_official_provider():
    assert _uses_anthropic_messages_api({
        "provider": "anthropic",
        "base_url": "https://api.anthropic.com/v1",
    }) is True


def test_ai_doc_parser_uses_anthropic_mode_for_minimax_proxy():
    assert _uses_anthropic_messages_api({
        "provider": "minimax",
        "base_url": "https://api.minimaxi.com/anthropic",
    }) is True


def test_official_anthropic_headers_do_not_send_bearer_authorization():
    headers = _build_anthropic_headers("https://api.anthropic.com/v1", "test-key")

    assert headers["x-api-key"] == "test-key"
    assert headers["anthropic-version"] == "2023-06-01"
    assert "Authorization" not in headers


def test_proxy_headers_send_plain_authorization_without_bearer():
    client = LLMClient()
    client.anthropic_base_url = "https://api.minimaxi.com/anthropic"
    client.anthropic_api_key = "proxy-key"

    headers = client._anthropic_headers()

    assert headers["Authorization"] == "proxy-key"
    assert headers["x-api-key"] == "proxy-key"
