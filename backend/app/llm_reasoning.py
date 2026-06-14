"""分离 LLM content 流里内联的 reasoning(`<think>...</think>`)。

背景:MiniMax M 系列(实测 MiniMax-M3)把 reasoning **内联在 `delta.content`** 里用
`<think>...</think>` 包裹,delta 无 `reasoning_content` 字段。若按 OpenAI 习惯把 content
原样累积,`<think>` 会泄漏进消息气泡与标题。本模块做增量、跨 chunk 安全的标签切分,把
reasoning 与可见 content 分开。

OpenAI/Anthropic 自身用独立的 reasoning 字段(reasoning_content / thinking_delta),由各
传输层另行处理;本模块只解决"内联 <think>"这一种。
"""
from __future__ import annotations

DEFAULT_OPEN = "<think>"
DEFAULT_CLOSE = "</think>"


def _held_partial_len(s: str, tag: str) -> int:
    """s 末尾有多长的后缀是 ``tag`` 的真前缀(用于跨 chunk 暂留半截标签)。

    返回需要从 s 末尾**扣下不发**的长度;0 表示可全发。
    """
    max_len = min(len(s), len(tag) - 1)
    for length in range(max_len, 0, -1):
        if s[-length:] == tag[:length]:
            return length
    return 0


class ReasoningSplitter:
    """增量分离器。逐 chunk ``feed`` content 文本,返回 ``(visible, reasoning)``;

    跨 chunk 被切断的标签(``<thi`` + ``nk>``)安全暂留到下一个 chunk;流结束调 ``flush``
    取回残留(未闭合的 ``<think>`` 残文按 reasoning 处理,绝不丢)。
    """

    def __init__(self, open_tag: str = DEFAULT_OPEN, close_tag: str = DEFAULT_CLOSE):
        self._open = open_tag
        self._close = close_tag
        self._inside = False
        self._buf = ""

    def feed(self, text: str) -> tuple[str, str]:
        if text:
            self._buf += text
        visible: list[str] = []
        reasoning: list[str] = []
        while True:
            if not self._inside:
                idx = self._buf.find(self._open)
                if idx == -1:
                    hold = _held_partial_len(self._buf, self._open)
                    cut = len(self._buf) - hold
                    visible.append(self._buf[:cut])
                    self._buf = self._buf[cut:]
                    break
                visible.append(self._buf[:idx])
                self._buf = self._buf[idx + len(self._open):]
                self._inside = True
            else:
                idx = self._buf.find(self._close)
                if idx == -1:
                    hold = _held_partial_len(self._buf, self._close)
                    cut = len(self._buf) - hold
                    reasoning.append(self._buf[:cut])
                    self._buf = self._buf[cut:]
                    break
                reasoning.append(self._buf[:idx])
                self._buf = self._buf[idx + len(self._close):]
                self._inside = False
        return "".join(visible), "".join(reasoning)

    def flush(self) -> tuple[str, str]:
        """流结束:吐出残留 buf。未闭合的 think 残文当 reasoning,否则当可见。"""
        rest = self._buf
        self._buf = ""
        if self._inside:
            return "", rest
        return rest, ""


def strip_think_blocks(text: str) -> tuple[str, str]:
    """一次性剥离整段文本里的 ``<think>...</think>``,返回 ``(visible, reasoning)``。"""
    splitter = ReasoningSplitter()
    vis, rea = splitter.feed(text)
    vis_tail, rea_tail = splitter.flush()
    return vis + vis_tail, rea + rea_tail
