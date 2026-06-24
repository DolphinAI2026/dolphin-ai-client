"""run_agent→coding UI 事件映射测试 — 统一引擎 Phase 1' Task 1。

见 docs/superpowers/plans/2026-06-24-unified-agent-engine-phase1-retire-coding-pipeline.md
"""
from __future__ import annotations

from app.harness.profiles.runagent_event_map import map_runagent_event


def test_write_tool_maps_to_coding_write_file_chip():
    out = map_runagent_event(
        "tool_call_start",
        {"id": 7, "tool_name": "write_workspace_files", "args": {"files": []}},
    )
    assert out == [{"type": "agent_tool", "action": "write_file", "id": 7,
                    "args": {"files": []}, "status": "running"}]


def test_tool_end_maps_to_agent_result_with_name_translation():
    out = map_runagent_event(
        "tool_call_end",
        {"id": 7, "tool_name": "edit_workspace_files", "status": "success", "result_text": "ok"},
    )
    assert out == [{"type": "agent_result", "id": 7, "action": "edit_file",
                    "status": "success", "result": "ok"}]


def test_assistant_delta_and_message():
    assert map_runagent_event("assistant_delta", {"text": "hi"}) == \
        [{"type": "agent_thinking_delta", "text": "hi"}]
    assert map_runagent_event("assistant_message", {"content": "done"}) == \
        [{"type": "content", "content": "done"}]


def test_ask_user_maps_to_clarify():
    out = map_runagent_event(
        "ask_user", {"tool_call_id": 3, "question": "哪个端?", "options": ["A", "B"]}
    )
    assert out == [{"type": "clarify", "question": "哪个端?", "options": ["A", "B"]}]


def test_done_and_error():
    assert map_runagent_event("done", {"ok": True}) == \
        [{"type": "agent_done"}, {"type": "done", "ok": True}]
    assert map_runagent_event("error", {"error": "boom"}) == \
        [{"type": "error", "error": "boom"}]


def test_unknown_tool_name_passes_through():
    out = map_runagent_event(
        "tool_call_start", {"id": 1, "tool_name": "list_apaas_apps", "args": {}}
    )
    assert out[0]["action"] == "list_apaas_apps"


def test_noise_events_drop_to_empty():
    for ev in ("thinking", "run_started", "tool_call_delta",
               "assistant_thinking_lock", "artifact_created"):
        assert map_runagent_event(ev, {}) == []
