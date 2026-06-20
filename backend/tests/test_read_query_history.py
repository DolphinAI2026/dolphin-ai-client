"""读路径跨轮记忆 — _read_history_messages 纯函数 + run_read_query 历史注入集成测试。

背景: 读/分析路径(run_read_query)之前 messages 从空起 = 每轮完全无状态,
「分析一下」后说「可以的」不知所指。本组测试守住「读路径加载并注入最近会话历史」。
"""
import json
from unittest.mock import MagicMock

import httpx

from app.coding import read_query
from app.coding.read_query import _read_history_messages
from app.coding.pipeline import PipelineParams


# ── 纯函数: 去重 + 截断 ──────────────────────────────────────────────

def test_history_empty():
    assert _read_history_messages([], "hi") == []


def test_history_drops_trailing_current_user():
    hist = [
        {"role": "user", "content": "分析一下"},
        {"role": "assistant", "content": "分析结果"},
        {"role": "user", "content": "可以的"},  # 当前轮, 已 save_coding_message
    ]
    assert _read_history_messages(hist, "可以的") == [
        {"role": "user", "content": "分析一下"},
        {"role": "assistant", "content": "分析结果"},
    ]


def test_history_keeps_when_last_not_current():
    hist = [
        {"role": "user", "content": "分析一下"},
        {"role": "assistant", "content": "分析结果"},
    ]
    # 末尾是 assistant(不是当前轮)→ 不去重, 全保留
    assert _read_history_messages(hist, "可以的") == hist


def test_history_only_drops_one_trailing_current():
    # 历史里更早也有一句相同内容, 不应被误删, 只去末尾当前轮那一条
    hist = [
        {"role": "user", "content": "可以的"},
        {"role": "assistant", "content": "好的"},
        {"role": "user", "content": "可以的"},  # 当前轮
    ]
    assert _read_history_messages(hist, "可以的") == [
        {"role": "user", "content": "可以的"},
        {"role": "assistant", "content": "好的"},
    ]


def test_history_truncates_to_max():
    hist = [
        {"role": "user" if i % 2 == 0 else "assistant", "content": f"m{i}"}
        for i in range(40)
    ]
    out = _read_history_messages(hist, "current", max_msgs=6)
    assert len(out) == 6
    assert out == hist[-6:]


# ── 集成: run_read_query 把历史注入 LLM payload ───────────────────────

async def test_run_read_query_injects_history(monkeypatch):
    captured: dict = {}
    sse = b"".join([
        b'data: {"choices":[{"delta":{"content":"ans"}}]}\n\n',
        b"data: [DONE]\n\n",
    ])

    def handler(request: httpx.Request) -> httpx.Response:
        captured["messages"] = json.loads(request.content)["messages"]
        return httpx.Response(200, content=sse, headers={"content-type": "text/event-stream"})

    transport = httpx.MockTransport(handler)
    orig_client = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: orig_client(transport=transport, **kw))

    async def _fake_cfg(tenant_id, model):
        return ("http://gw/v1", "key", "m")
    monkeypatch.setattr("app.agents.coding.llm_config.load_coding_llm_config", _fake_cfg)

    async def _fake_env(tenant_id, db):
        return 1  # platform_env_id 有值 → 不早退(有只读工具)
    monkeypatch.setattr(read_query, "_resolve_read_platform_env_id", _fake_env)

    async def _fake_hist(db, cid):
        return [
            {"role": "user", "content": "分析这个项目"},
            {"role": "assistant", "content": "这是个 CRM"},
            {"role": "user", "content": "可以的"},  # 当前轮(调用前已 save)
        ]
    monkeypatch.setattr("app.coding.pipeline.get_conversation_history", _fake_hist)

    params = PipelineParams(message="可以的", user_id=1, tenant_id=1, conversation_id=42)
    _ = [ev async for ev in read_query.run_read_query(params, MagicMock())]

    msgs = captured["messages"]
    assert msgs[0]["role"] == "system"
    # 历史被注入(去掉了末尾当前轮)
    assert {"role": "user", "content": "分析这个项目"} in msgs
    assert {"role": "assistant", "content": "这是个 CRM"} in msgs
    # 当前 message 仍是最后一条
    assert msgs[-1] == {"role": "user", "content": "可以的"}
    # 当前轮"可以的"只出现一次(历史末尾那条被去重)
    assert sum(1 for m in msgs if m["role"] == "user" and m.get("content") == "可以的") == 1


async def test_run_read_query_first_turn_no_history(monkeypatch):
    """首轮新会话 conversation_id=None → 不加载历史, 只有 system + 当前 user。"""
    captured: dict = {}
    sse = b'data: {"choices":[{"delta":{"content":"a"}}]}\n\ndata: [DONE]\n\n'

    def handler(request: httpx.Request) -> httpx.Response:
        captured["messages"] = json.loads(request.content)["messages"]
        return httpx.Response(200, content=sse, headers={"content-type": "text/event-stream"})

    transport = httpx.MockTransport(handler)
    orig_client = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: orig_client(transport=transport, **kw))

    async def _fake_cfg(tenant_id, model):
        return ("http://gw/v1", "key", "m")
    monkeypatch.setattr("app.agents.coding.llm_config.load_coding_llm_config", _fake_cfg)

    async def _fake_env(tenant_id, db):
        return 1
    monkeypatch.setattr(read_query, "_resolve_read_platform_env_id", _fake_env)

    def _boom(db, cid):  # 不应被调用(conversation_id None)
        raise AssertionError("首轮不应加载历史")
    monkeypatch.setattr("app.coding.pipeline.get_conversation_history", _boom)

    params = PipelineParams(message="讲讲这个项目", user_id=1, tenant_id=1)  # conversation_id 默认 None
    _ = [ev async for ev in read_query.run_read_query(params, MagicMock())]

    msgs = captured["messages"]
    assert [m["role"] for m in msgs] == ["system", "user"]
    assert msgs[-1]["content"] == "讲讲这个项目"
