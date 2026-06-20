"""harness coding profile: agent_thinking_delta / agent_thinking 必须透传 reasoning 标志。

根因: CodingProfile.run_turn 桥接 pipeline 事件 → EventBus 时只提取 content,
不带 reasoning 字段 → 前端无法把推理思维链路由到单独可折叠卡片。

Task 2 断言:
1. profile 处理带 reasoning:True 的 agent_thinking_delta 时, publish payload 含 reasoning=True。
2. 不带 reasoning 字段的事件 → payload reasoning=False(bool 化)。
3. CodingSSEAdapter 把 thinking payload 的 reasoning 字段透传给前端(不被字段白名单过滤)。
"""
from __future__ import annotations

import pytest

import app.harness.profiles.coding as coding_profile_mod
from app.harness.profiles import get_profile
from app.harness.contracts import ThreadContext, TurnContext
from app.harness.events import ITEM_DELTA
from app.harness.sse_adapter import CodingSSEAdapter


class _RecordingBus:
    def __init__(self):
        self.published = []

    async def publish(self, event_type, turn_id, data, *, item_kind="system", persist=True):
        self.published.append({"event_type": event_type, "data": data, "item_kind": item_kind})


class _DummyDb:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False


# ── Profile 层测试 ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_profile_thinking_delta_with_reasoning_true(monkeypatch):
    """agent_thinking_delta + reasoning:True → publish payload 含 reasoning=True。"""
    async def _fake_pipeline(params, db):
        yield {"type": "agent_thinking_delta", "content": "正在推理...", "reasoning": True}
        yield {"type": "done", "workspace_id": "1_x"}

    monkeypatch.setattr(coding_profile_mod, "AsyncSessionLocal", lambda: _DummyDb())
    import app.coding.pipeline as pipeline_mod
    monkeypatch.setattr(pipeline_mod, "run_coding_pipeline", _fake_pipeline)

    profile = get_profile("coding")
    monkeypatch.setattr(profile, "_save_turn_artifacts", _noop_artifacts)

    bus = _RecordingBus()
    thread_ctx = _make_thread_ctx()
    turn_ctx = _make_turn_ctx()
    await profile.run_turn(thread_ctx, turn_ctx, bus)

    hits = [p for p in bus.published if p["data"].get("kind") == "thinking"]
    assert hits, "agent_thinking_delta 未被 publish 到 EventBus"
    payload = hits[0]["data"]
    assert "reasoning" in payload, "publish payload 缺 reasoning 字段"
    assert payload["reasoning"] is True, f"期望 reasoning=True, 实得 {payload['reasoning']!r}"


@pytest.mark.asyncio
async def test_profile_thinking_delta_without_reasoning_flag(monkeypatch):
    """agent_thinking_delta 不带 reasoning → publish payload 含 reasoning=False。"""
    async def _fake_pipeline(params, db):
        yield {"type": "agent_thinking_delta", "content": "普通思考"}
        yield {"type": "done", "workspace_id": "1_x"}

    monkeypatch.setattr(coding_profile_mod, "AsyncSessionLocal", lambda: _DummyDb())
    import app.coding.pipeline as pipeline_mod
    monkeypatch.setattr(pipeline_mod, "run_coding_pipeline", _fake_pipeline)

    profile = get_profile("coding")
    monkeypatch.setattr(profile, "_save_turn_artifacts", _noop_artifacts)

    bus = _RecordingBus()
    await profile.run_turn(_make_thread_ctx(), _make_turn_ctx(), bus)

    hits = [p for p in bus.published if p["data"].get("kind") == "thinking"]
    assert hits
    payload = hits[0]["data"]
    assert "reasoning" in payload, "publish payload 缺 reasoning 字段"
    assert payload["reasoning"] is False, f"期望 reasoning=False, 实得 {payload['reasoning']!r}"


@pytest.mark.asyncio
async def test_profile_agent_thinking_completed_with_reasoning(monkeypatch):
    """agent_thinking(completed) + reasoning:True → publish payload 含 reasoning=True。"""
    async def _fake_pipeline(params, db):
        yield {"type": "agent_thinking", "content": "推理完毕", "reasoning": True}
        yield {"type": "done", "workspace_id": "1_x"}

    monkeypatch.setattr(coding_profile_mod, "AsyncSessionLocal", lambda: _DummyDb())
    import app.coding.pipeline as pipeline_mod
    monkeypatch.setattr(pipeline_mod, "run_coding_pipeline", _fake_pipeline)

    profile = get_profile("coding")
    monkeypatch.setattr(profile, "_save_turn_artifacts", _noop_artifacts)

    bus = _RecordingBus()
    await profile.run_turn(_make_thread_ctx(), _make_turn_ctx(), bus)

    hits = [p for p in bus.published if p["data"].get("kind") == "thinking"]
    assert hits, "agent_thinking 未被 publish 到 EventBus"
    payload = hits[0]["data"]
    assert "reasoning" in payload, "publish payload 缺 reasoning 字段"
    assert payload["reasoning"] is True, f"期望 reasoning=True, 实得 {payload['reasoning']!r}"


# ── SSEAdapter 透传层测试 ──────────────────────────────────────────────────


def test_sse_adapter_passes_reasoning_flag_through():
    """CodingSSEAdapter: thinking payload 含 reasoning=True → 前端事件含 reasoning=True。"""
    out = CodingSSEAdapter().translate({
        "event_type": ITEM_DELTA,
        "data": {"kind": "thinking", "text": "推理中...", "reasoning": True},
    })
    assert out.get("type") == "agent_thinking_delta"
    assert "reasoning" in out, "CodingSSEAdapter 过滤掉了 reasoning 字段"
    assert out["reasoning"] is True


def test_sse_adapter_passes_reasoning_false():
    """CodingSSEAdapter: reasoning=False 也透传(不是 True 的才不渲染折叠)。"""
    out = CodingSSEAdapter().translate({
        "event_type": ITEM_DELTA,
        "data": {"kind": "thinking", "text": "普通思考", "reasoning": False},
    })
    assert out.get("type") == "agent_thinking_delta"
    assert out.get("reasoning") is False


# ── 辅助 ─────────────────────────────────────────────────────────────────


async def _noop_artifacts(*a, **k):
    return None


def _make_thread_ctx():
    return ThreadContext(
        thread_id=1, tenant_id=2, user_id=1,
        profile_name="coding", conversation_id=29,
        metadata={"workspace_id": "1_x"},
    )


def _make_turn_ctx():
    return TurnContext(turn_id=1, thread_id=1, turn_index=0, user_input="测试")
