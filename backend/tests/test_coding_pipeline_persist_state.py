"""TDD tests for serialize_coding_state (Task 6) — sliding-window out-turn persistence."""
import json

from app.coding.pipeline import serialize_coding_state, build_resume_snapshot


def test_serialize_roundtrip():
    msgs = [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "done"}]
    s = serialize_coding_state(msgs, "摘要文本")
    data = json.loads(s)
    assert data["messages"] == msgs
    assert data["summary"] == "摘要文本"
    assert data["version"] == 1
    # 与 Task 5 的 resume 闭环: 序列化的 state 能被 build_resume_snapshot 还原
    snap = build_resume_snapshot(s)
    assert snap["messages"] == msgs


def test_serialize_handles_none_summary():
    s = serialize_coding_state([{"role": "user", "content": "x"}], None)
    assert json.loads(s)["summary"] is None


def test_serialize_empty_messages():
    s = serialize_coding_state([], "some summary")
    data = json.loads(s)
    assert data["messages"] == []
    assert data["summary"] == "some summary"
    assert data["version"] == 1


def test_serialize_none_messages():
    s = serialize_coding_state(None, None)
    data = json.loads(s)
    assert data["messages"] == []
    assert data["version"] == 1
