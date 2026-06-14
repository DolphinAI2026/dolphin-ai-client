"""MiniMax 等模型把 reasoning 内联在 content 里用 `<think>...</think>` 包裹(实测 MiniMax-M3
delta 只有 role/content, 无 reasoning_content 字段)。ReasoningSplitter 增量分离 content 流里的
think 块, 让可见 content 干净、reasoning 单独走 —— 杜绝 `<think>` 泄漏进消息/标题。

难点全在跨 chunk 的标签切分(`<thi`+`nk>`、`</thi`+`nk>`), 这些用例即对抗验证。
"""
from app.llm_reasoning import ReasoningSplitter, strip_think_blocks


def _run(splitter, chunks):
    """喂多个 chunk + flush, 返回 (合并可见, 合并 reasoning)。"""
    vis, rea = "", ""
    for c in chunks:
        v, r = splitter.feed(c)
        vis += v
        rea += r
    v, r = splitter.flush()
    vis += v
    rea += r
    return vis, rea


def test_no_think_all_visible():
    vis, rea = _run(ReasoningSplitter(), ["hello world"])
    assert vis == "hello world"
    assert rea == ""


def test_full_think_one_chunk():
    vis, rea = _run(ReasoningSplitter(), ["<think>reasoning here</think>answer"])
    assert vis == "answer"
    assert rea == "reasoning here"


def test_real_minimax_shape_split_across_chunks():
    """实测形态: <think> 开 + 推理跨多 chunk + </think>\\n\\n 真答案。"""
    chunks = [
        "",
        "<think>The user is asking a simple math ",
        "question. 1+1=2.",
        "</think>\n\n1+1=2。",
        "",
    ]
    vis, rea = _run(ReasoningSplitter(), chunks)
    assert vis == "\n\n1+1=2。"
    assert "The user is asking" in rea
    assert "<think" not in vis and "</think" not in vis


def test_open_tag_split_across_chunks():
    """开标签被切成 `<thi` + `nk>`。"""
    vis, rea = _run(ReasoningSplitter(), ["<thi", "nk>r</think>v"])
    assert vis == "v"
    assert rea == "r"


def test_close_tag_split_across_chunks():
    """闭标签被切成 `</thi` + `nk>`。"""
    vis, rea = _run(ReasoningSplitter(), ["<think>r</thi", "nk>v"])
    assert vis == "v"
    assert rea == "r"


def test_content_before_think():
    vis, rea = _run(ReasoningSplitter(), ["hello <think>r</think> world"])
    assert vis == "hello  world"
    assert rea == "r"


def test_unclosed_think_runs_to_end():
    """没有闭标签 → 全部当 reasoning, 可见为空(flush 不漏)。"""
    vis, rea = _run(ReasoningSplitter(), ["<think>still thinking, no close"])
    assert vis == ""
    assert rea == "still thinking, no close"


def test_partial_open_tag_that_is_not_a_tag():
    """以 `<` 结尾但后续不是 think 标签 → 应原样作为可见文本(不能吞掉)。"""
    vis, rea = _run(ReasoningSplitter(), ["price < ", "5 dollars"])
    assert vis == "price < 5 dollars"
    assert rea == ""


def test_multiple_think_blocks():
    vis, rea = _run(ReasoningSplitter(), ["<think>a</think>X<think>b</think>Y"])
    assert vis == "XY"
    assert rea == "ab"


def test_empty_chunks():
    vis, rea = _run(ReasoningSplitter(), ["", "", "ok", ""])
    assert vis == "ok"
    assert rea == ""


# ─────────────────── 便捷函数: 一次性剥离(非流式 / 整段) ───────────────────

def test_strip_think_blocks_whole_string():
    vis, rea = strip_think_blocks("<think>think</think>\n\nreal answer")
    assert vis == "\n\nreal answer"
    assert rea == "think"


def test_strip_think_blocks_no_think():
    vis, rea = strip_think_blocks("plain answer")
    assert vis == "plain answer"
    assert rea == ""


# ─────────────────── transport 接线: _stream_chunks_once 对 MiniMax 流 ───────────────────

import json as _json

import pytest

from app import llm_transport


class _FakeStreamResp:
    status_code = 200

    def __init__(self, lines):
        self._lines = lines

    async def aread(self):
        return b""

    def raise_for_status(self):
        return None

    async def aiter_lines(self):
        for ln in self._lines:
            yield ln


class _FakeStreamCtx:
    def __init__(self, lines):
        self._resp = _FakeStreamResp(lines)

    async def __aenter__(self):
        return self._resp

    async def __aexit__(self, *a):
        return False


class _FakeStreamClient:
    def __init__(self, lines):
        self._lines = lines

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    def stream(self, *a, **k):
        return _FakeStreamCtx(self._lines)


@pytest.mark.asyncio
async def test_stream_chunks_strips_minimax_inline_think(monkeypatch):
    """MiniMax 形态: content 内联 <think>…</think>。断言 content_delta / done.content 干净,
    reasoning 单独走 reasoning_delta, usage 仍采到。"""
    lines = [
        'data: ' + _json.dumps({"choices": [{"delta": {"role": "assistant", "content": ""}}]}),
        'data: ' + _json.dumps({"choices": [{"delta": {"content": "<think>reasoning A "}}]}),
        'data: ' + _json.dumps({"choices": [{"delta": {"content": "more thinking</think>\n\nReal answer."}}]}),
        'data: ' + _json.dumps({"usage": {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30}, "choices": []}),
        'data: [DONE]',
    ]
    monkeypatch.setattr(llm_transport.httpx, "AsyncClient", lambda *a, **k: _FakeStreamClient(lines))

    content_deltas, reasoning_deltas, done = [], [], None
    async for ev in llm_transport.stream_chunks(
        base_url="https://api.minimax.chat/v1",
        api_key="k",
        payload={"model": "MiniMax-M3", "messages": [], "stream": True},
        timeout=30,
    ):
        if ev["type"] == "content_delta":
            content_deltas.append(ev["text"])
        elif ev["type"] == "reasoning_delta":
            reasoning_deltas.append(ev["text"])
        elif ev["type"] == "done":
            done = ev

    visible = "".join(content_deltas)
    reasoning = "".join(reasoning_deltas)
    assert visible == "\n\nReal answer.", f"content 应干净, 实际 {visible!r}"
    assert "<think" not in visible and "</think" not in visible
    assert "reasoning A" in reasoning and "more thinking" in reasoning
    assert done is not None
    assert done["message"]["content"] == "\n\nReal answer.", "done.content 应干净"
    assert done["usage"]["total_tokens"] == 30, "usage 仍应采到"


@pytest.mark.asyncio
async def test_stream_chunks_passthrough_when_no_think(monkeypatch):
    """无 <think> 的普通 OpenAI 流 → content 原样,无 reasoning_delta。"""
    lines = [
        'data: ' + _json.dumps({"choices": [{"delta": {"content": "Hello "}}]}),
        'data: ' + _json.dumps({"choices": [{"delta": {"content": "world"}}]}),
        'data: [DONE]',
    ]
    monkeypatch.setattr(llm_transport.httpx, "AsyncClient", lambda *a, **k: _FakeStreamClient(lines))

    content, reasoning_seen, done = "", False, None
    async for ev in llm_transport.stream_chunks(
        base_url="https://api.openai.com/v1", api_key="k",
        payload={"model": "gpt-x", "messages": [], "stream": True}, timeout=30,
    ):
        if ev["type"] == "content_delta":
            content += ev["text"]
        elif ev["type"] == "reasoning_delta":
            reasoning_seen = True
        elif ev["type"] == "done":
            done = ev
    assert content == "Hello world"
    assert reasoning_seen is False
    assert done["message"]["content"] == "Hello world"
