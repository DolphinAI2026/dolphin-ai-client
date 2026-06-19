"""Tests for build_resume_snapshot in coding pipeline."""
import json

import pytest

from app.coding.pipeline import build_resume_snapshot


def test_none_or_garbage_returns_none():
    assert build_resume_snapshot(None) is None
    assert build_resume_snapshot("not json") is None
    assert build_resume_snapshot(json.dumps({"summary": "x"})) is None  # 无 messages


def test_empty_messages_returns_none():
    state = json.dumps({"messages": [], "version": 1})
    assert build_resume_snapshot(state) is None


def test_parses_messages_into_snapshot():
    state = json.dumps({
        "messages": [
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "ok"},
        ],
        "summary": "s",
        "version": 1,
    })
    snap = build_resume_snapshot(state)
    assert snap is not None
    assert snap["messages"] == [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "ok"},
    ]
    # from_snapshot 需要的最小字段
    assert snap.get("status") in ("idle", None) or "status" in snap


def test_snapshot_has_required_fields():
    state = json.dumps({
        "messages": [{"role": "user", "content": "hello"}],
    })
    snap = build_resume_snapshot(state)
    assert snap is not None
    assert "messages" in snap
    assert "status" in snap
    assert snap["status"] == "idle"
    assert "turn" in snap
    assert snap["turn"] == 0


def test_non_list_messages_returns_none():
    state = json.dumps({"messages": "not a list"})
    assert build_resume_snapshot(state) is None


def test_messages_with_invalid_json_returns_none():
    assert build_resume_snapshot("{invalid json") is None
