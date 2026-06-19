"""harness coding profile: run_workspace_preview / C5 的 run_result / autofix_round 必须透传到前端。

根因(2026-06-19 live SSE 抓包挖出): CodingProfile.run_turn 的 pipeline 事件→EventBus 桥接
elif 链里没有 run_result / autofix_round 分支(且链尾无 else 兜底)→ 这俩事件在 profile 层被
静默丢弃 → 前端 sseHandlers 永远收不到 → 预览不自动开(用户报「还不如自动打开预览」)。

实测 SSE 流当时只有 agent_thinking_delta / step / agent_tool / agent_result / done,无 run_result。

锁两段契约:
1. CodingProfile 把 run_result / autofix_round 以 kind=system 发到 EventBus。
2. CodingSSEAdapter 把 system+type 的事件原样透传(前端按 parsed.type 派发到 run_result handler)。
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


@pytest.mark.asyncio
@pytest.mark.parametrize("ev_type", ["run_result", "autofix_round"])
async def test_profile_forwards_preview_event_as_system(monkeypatch, ev_type):
    async def _fake_pipeline(params, db):
        yield {"type": ev_type, "dev_url": "http://127.0.0.1:8081/", "status": "ok",
               "errors": [], "capture_available": False}
        yield {"type": "done", "workspace_id": "1_x"}

    monkeypatch.setattr(coding_profile_mod, "AsyncSessionLocal", lambda: _DummyDb())
    import app.coding.pipeline as pipeline_mod
    monkeypatch.setattr(pipeline_mod, "run_coding_pipeline", _fake_pipeline)

    profile = get_profile("coding")

    async def _noop_artifacts(*a, **k):
        return None

    monkeypatch.setattr(profile, "_save_turn_artifacts", _noop_artifacts)

    thread_ctx = ThreadContext(thread_id=1, tenant_id=2, user_id=1, profile_name="coding",
                               conversation_id=29, metadata={"workspace_id": "1_x"})
    turn_ctx = TurnContext(turn_id=1, thread_id=1, turn_index=0, user_input="再启动一下预览")
    bus = _RecordingBus()

    await profile.run_turn(thread_ctx, turn_ctx, bus)

    hits = [p for p in bus.published if p["data"].get("type") == ev_type]
    assert hits, f"{ev_type} 被 profile 静默丢了(根因回归 — pipeline 事件→EventBus 缺该分支)"
    p = hits[0]
    assert p["item_kind"] == "system"           # 必须 system kind 才会被 CodingSSEAdapter 透传
    assert p["data"].get("kind") == "system"
    assert p["data"]["dev_url"] == "http://127.0.0.1:8081/"


def test_sse_adapter_passes_through_system_run_result():
    """system+type 的预览事件 → CodingSSEAdapter 原样透传(剥掉 kind), 前端据 type 派发。"""
    out = CodingSSEAdapter().translate({
        "event_type": ITEM_DELTA,
        "data": {"kind": "system", "type": "run_result", "dev_url": "http://127.0.0.1:8081/",
                 "status": "ok", "errors": [], "capture_available": False},
    })
    assert out.get("type") == "run_result"
    assert out.get("dev_url") == "http://127.0.0.1:8081/"
    assert "kind" not in out
