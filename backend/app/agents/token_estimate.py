"""粗估 chat messages 的 token 数 —— 用于上下文预算判断 + token 用量显示。

不追求精确(gpt-5.5 经 dolphin 网关, 无官方 tokenizer): 按字符/3.5 估(中英文混合的
保守经验值)。tiktoken 若已装则用 cl100k_base 更准, 否则回退字符估算。"""
from __future__ import annotations

from typing import Any

_CHARS_PER_TOKEN = 3.5


def _message_text(m: dict[str, Any]) -> str:
    parts: list[str] = []
    c = m.get("content")
    if isinstance(c, str):
        parts.append(c)
    elif isinstance(c, list):  # 多模态 content blocks
        for b in c:
            if isinstance(b, dict):
                parts.append(str(b.get("text") or ""))
    for tc in (m.get("tool_calls") or []):
        parts.append(str(tc))
    return "".join(parts)


def estimate_tokens(messages: list[dict[str, Any]]) -> int:
    text = "".join(_message_text(m) for m in (messages or []))
    if not text:
        return 0
    try:
        import tiktoken
        return len(tiktoken.get_encoding("cl100k_base").encode(text))
    except Exception:
        return int(len(text) / _CHARS_PER_TOKEN)
