"""CodingProfile.run_turn cutover(flag CODING_USE_RUNAGENT)— Phase 1' Task 3。

flag 关 → 旧 coding 流水线;flag 开 → run_agent 驱动 + 事件映射 + ws 绑定。
端到端行为(模型是否遵守 ws 绑定、多轮历史、面板刷新)需真机验证;此处只验路由/映射/绑定。
"""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.harness.contracts import ThreadContext, TurnContext
from app.harness.profiles.coding import CodingProfile


class _FakeACM:
    async def __aenter__(self):
        return MagicMock()

    async def __aexit__(self, *a):
        return False


class _FakeBus:
    def __init__(self):
        self.items: list[dict] = []

    async def publish(self, event_type, turn_id, data, item_kind=None, persist=True):
        self.items.append({"event_type": event_type, "data": data, "item_kind": item_kind})


def _thread():
    return ThreadContext(thread_id=1, tenant_id=1, user_id=1, profile_name="coding",
                         conversation_id=42, metadata={"workspace_id": "ws-1"})


def _turn():
    return TurnContext(turn_id=7, thread_id=1, turn_index=0, user_input="改一下")


@pytest.mark.asyncio
async def test_flag_off_uses_old_pipeline_not_runagent(monkeypatch):
    monkeypatch.delenv("CODING_USE_RUNAGENT", raising=False)
    called = {"runagent": False}

    async def boom_run_agent(*a, **k):
        called["runagent"] = True
        if False:
            yield {}

    async def fake_entry(params, db):
        yield {"type": "done", "workspace_id": "ws-1"}

    monkeypatch.setattr("app.ai_chat.agent.run_agent", boom_run_agent)
    monkeypatch.setattr("app.coding.pipeline.run_coding_entry", fake_entry)
    monkeypatch.setattr("app.harness.profiles.coding.AsyncSessionLocal", lambda: _FakeACM())

    prof = CodingProfile()
    monkeypatch.setattr(prof, "_save_turn_artifacts", AsyncMock())
    await prof.run_turn(_thread(), _turn(), _FakeBus())

    assert called["runagent"] is False


@pytest.mark.asyncio
async def test_flag_on_drives_runagent_maps_events_and_binds_ws(monkeypatch):
    monkeypatch.setenv("CODING_USE_RUNAGENT", "1")
    captured: dict = {}

    async def fake_run_agent(db, session, message, abort_event, section=None, view_context=None):
        captured["called"] = True
        captured["view_context"] = view_context
        captured["message"] = message
        for ev, data in [
            ("tool_call_start", {"id": 1, "tool_name": "write_workspace_files", "args": {"files": []}}),
            ("tool_call_end", {"id": 1, "tool_name": "write_workspace_files", "status": "success", "result_text": "ok"}),
            ("assistant_message", {"content": "改完了"}),
            ("done", {"ok": True}),
        ]:
            yield {"event": ev, "data": json.dumps(data)}

    # 不走 run_coding_entry
    async def boom_entry(params, db):
        raise AssertionError("flag 开时不应调 run_coding_entry")
        yield {}

    monkeypatch.setattr("app.ai_chat.agent.run_agent", fake_run_agent)
    monkeypatch.setattr("app.coding.pipeline.run_coding_entry", boom_entry)
    monkeypatch.setattr("app.harness.profiles.coding.AsyncSessionLocal", lambda: _FakeACM())

    prof = CodingProfile()
    monkeypatch.setattr(prof, "_get_or_create_ai_session",
                        AsyncMock(return_value=MagicMock(id=99, app_id=None)))
    monkeypatch.setattr(prof, "_save_turn_artifacts", AsyncMock())

    bus = _FakeBus()
    result = await prof.run_turn(_thread(), _turn(), bus)

    # run_agent 被驱动
    assert captured.get("called") is True
    # 既有 ws_id 经 view_context 硬绑(禁止新建工作区)
    assert "ws-1" in (captured.get("view_context") or "")
    assert "create_dev_workspace" in (captured.get("view_context") or "")
    # 工具名翻译:write_workspace_files → write_file 工具卡
    tool_calls = [it["data"] for it in bus.items if it["data"].get("kind") == "tool_call"]
    assert any(d.get("tool") == "write_file" for d in tool_calls)
    # done 补回 workspace_id,前端面板据此自动绑定
    dones = [it["data"] for it in bus.items if it["data"].get("type") == "done"]
    assert dones and dones[0].get("workspace_id") == "ws-1"
    # 最终回复文本取自 assistant_message
    assert result == "改完了"


@pytest.mark.asyncio
async def test_ws_bind_view_context_empty_when_no_ws():
    assert CodingProfile._ws_bind_view_context("") is None
    assert "ws-9" in CodingProfile._ws_bind_view_context("ws-9")
